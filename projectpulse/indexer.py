"""Полная и инкрементальная индексация репозитория."""
import json
import logging
import time

from . import gitio, graph, pyparse

log = logging.getLogger("projectpulse.indexer")


class Cancelled(Exception):
    pass


class Indexer:
    def __init__(self, db, path, name=None, progress=None, cancel=None, snapshots=5,
                 use_cache=True, fast_blobs=True, max_file_bytes=500_000, max_files=5000):
        self.db, self.path = db, path
        self.name = name or path.rstrip("/\\").split("/")[-1].split("\\")[-1]
        self.progress, self.cancel = progress, cancel
        self.snapshots, self.use_cache, self.fast_blobs = snapshots, use_cache, fast_blobs
        self.max_file_bytes, self.max_files = max_file_bytes, max_files
        self.mem, self.reader = {}, None

    def _tick(self, stage, done=0, total=0):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()
        if self.progress:
            self.progress(stage, done, total)

    # ---- публичный API ----
    def run(self, rebuild=False):
        t0 = time.perf_counter()
        started = time.time()
        try:
            res = self._run(rebuild)
            self.db.commit()
        except BaseException as e:
            self.db.rollback()
            log.warning("индексация %s прервана: %r", self.name, e)
            raise
        finally:
            if self.reader:
                self.reader.close()
                self.reader = None
        res["duration"] = time.perf_counter() - t0
        self.db.execute("INSERT INTO analysis_events(repo,kind,mode,started,duration,n_commits,head) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (self.name, "index", res["mode"], started, res["duration"], res["n_commits"], res["head"]))
        self.db.commit()
        log.info("индексация %s: %s", self.name, res)
        return res

    # ---- внутреннее ----
    def _wipe(self, blobs=False):
        for t in ("commits", "file_changes", "files"):
            self.db.execute(f"DELETE FROM {t} WHERE repo=?", (self.name,))
        ids = "(SELECT id FROM graph_versions WHERE repo=?)"
        for t in ("graph_nodes", "graph_edges"):
            self.db.execute(f"DELETE FROM {t} WHERE version_id IN {ids}", (self.name,))
        self.db.execute("DELETE FROM graph_versions WHERE repo=?", (self.name,))
        self.db.execute("DELETE FROM repos WHERE name=?", (self.name,))
        if blobs:
            self.db.execute("DELETE FROM blobs")
        self.mem.clear()

    def _run(self, rebuild):
        if not gitio.is_repo(self.path):
            raise gitio.GitError(f"{self.path}: не git-репозиторий")
        self._tick("проверка репозитория")
        head = gitio.head(self.path)           # GitError для пустого/битого репозитория
        row = self.db.execute("SELECT head FROM repos WHERE name=?", (self.name,)).fetchone()
        last = row[0] if row else None
        if rebuild:
            self._wipe(blobs=True)
            last = None
        if last == head:
            return {"mode": "noop", "n_commits": 0, "head": head}
        if last and gitio.is_ancestor(self.path, last, head):
            mode = "incremental"
        else:
            mode = "full"
            if last:                           # история переписана
                self._wipe()
                last = None
        self._tick("чтение истории")
        commits = gitio.log(self.path, since=last)
        self._save_commits(commits)
        self.reader = gitio.BlobReader(self.path, batch=self.fast_blobs)
        head_infos = self._tree_infos(head, "состояние HEAD")
        self.db.execute("DELETE FROM files WHERE repo=?", (self.name,))
        self.db.executemany("INSERT INTO files VALUES(?,?,?,?,?,?)", [
            (self.name, p, sha, i["loc"], i["cc"], i["max_cc"]) for p, (sha, i) in head_infos.items()])
        infos_head = {p: i for p, (_, i) in head_infos.items()}
        head_ts = int(gitio._run(self.path, "log", "-1", "--format=%at", head).stdout.decode().strip() or 0)
        graph.store_snapshot(self.db, self.name, head, head_ts, graph.build_graph(infos_head))
        if mode == "full":
            for k, c in enumerate(self._sample(commits)):
                infos = {p: i for p, (_, i) in self._tree_infos(c["hash"], f"срез графа {k + 1}").items()}
                graph.store_snapshot(self.db, self.name, c["hash"], c["ts"], graph.build_graph(infos))
        self.db.execute("INSERT OR REPLACE INTO repos VALUES(?,?,?)", (self.name, self.path, head))
        return {"mode": mode, "n_commits": len(commits), "head": head}

    def _sample(self, commits):
        k = self.snapshots - 1                 # последний срез — HEAD — уже сохранён
        if k <= 0 or len(commits) < 2:
            return []
        n = len(commits) - 1
        idx = sorted({round(i * (n - 1) / max(k - 1, 1)) if k > 1 else 0 for i in range(k)})
        return [commits[i] for i in idx if commits[i]["hash"] != commits[-1]["hash"]]

    def _save_commits(self, commits):
        self.db.executemany("INSERT OR IGNORE INTO commits VALUES(?,?,?,?,?,?)",
                            [(self.name, c["hash"], c["author"], c["ts"], c["message"], c["is_fix"]) for c in commits])
        self.db.executemany("INSERT INTO file_changes VALUES(?,?,?,?,?)",
                            [(self.name, c["hash"], p, a, d) for c in commits for p, a, d in c["files"]])
        self._tick("сохранение коммитов", len(commits), len(commits))

    def _tree_infos(self, rev, stage):
        tree = gitio.ls_tree_py(self.path, rev)
        if len(tree) > self.max_files:
            log.warning("%s: %d .py файлов, берём первые %d", self.name, len(tree), self.max_files)
            tree = dict(sorted(tree.items())[:self.max_files])
        out = {}
        for k, (p, sha) in enumerate(sorted(tree.items())):
            if k % 50 == 0:
                self._tick(stage, k, len(tree))
            out[p] = (sha, self._info(sha))
        return out

    def _info(self, sha):
        if self.use_cache:                     # оптимизация №1: кэш по sha блоба (контент-адресация)
            if sha in self.mem:
                return self.mem[sha]
            r = self.db.execute("SELECT info FROM blobs WHERE sha=?", (sha,)).fetchone()
            if r:
                self.mem[sha] = json.loads(r[0])
                return self.mem[sha]
        data = self.reader.read(sha)
        info = pyparse.parse(data.decode("utf-8", "replace")) if len(data) <= self.max_file_bytes \
            else dict(pyparse.EMPTY)
        if self.use_cache:
            self.mem[sha] = info
            self.db.execute("INSERT OR REPLACE INTO blobs VALUES(?,?)", (sha, json.dumps(info)))
        return info
