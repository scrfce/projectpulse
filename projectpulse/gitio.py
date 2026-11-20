"""Работа с git через git CLI (subprocess). Только локально, без сети."""
import os
import re
import subprocess

FIX_RE = re.compile(r"\b(fix|bug|hotfix|patch)|исправ|баг|ошибк", re.I)


class GitError(RuntimeError):
    pass


def _run(path, *args, check=True):
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=false", "-C", path, *args],
                           capture_output=True)
    except FileNotFoundError as e:
        raise GitError("git не найден в PATH") from e
    if check and p.returncode != 0:
        raise GitError(p.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return p


def is_repo(path):
    return os.path.isdir(path) and _run(path, "rev-parse", "--git-dir", check=False).returncode == 0


def head(path):
    return _run(path, "rev-parse", "--verify", "HEAD").stdout.decode().strip()


def is_ancestor(path, a, b):
    return _run(path, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def is_fix(message):
    return bool(FIX_RE.search(message or ""))


def log(path, since=None):
    """Коммиты в хронологическом порядке: dict(hash, author, ts, message, is_fix, files)."""
    rng = f"{since}..HEAD" if since else "HEAD"
    out = _run(path, "log", rng, "--no-merges", "--no-renames", "--numstat",
               "--format=%x01%H%x02%an%x02%at%x02%s").stdout.decode("utf-8", "replace")
    commits = []
    for chunk in out.split("\x01")[1:]:
        lines = chunk.split("\n")
        parts = lines[0].split("\x02")
        if len(parts) < 4:
            continue
        files = []
        for ln in lines[1:]:
            t = ln.split("\t")
            if len(t) == 3:
                a = int(t[0]) if t[0].isdigit() else 0   # бинарные файлы: '-'
                d = int(t[1]) if t[1].isdigit() else 0
                files.append((t[2], a, d))
        commits.append(dict(hash=parts[0], author=parts[1], ts=int(parts[2]),
                            message=parts[3], is_fix=int(is_fix(parts[3])), files=files))
    commits.reverse()
    return commits


def ls_tree_py(path, rev):
    """{путь: sha блоба} для .py файлов ревизии."""
    out = _run(path, "ls-tree", "-r", "-z", rev).stdout.decode("utf-8", "replace")
    res = {}
    for ent in out.split("\0"):
        if not ent:
            continue
        meta, _, p = ent.partition("\t")
        m = meta.split()
        if len(m) == 3 and m[1] == "blob" and p.endswith(".py"):
            res[p] = m[2]
    return res


class BlobReader:
    """Чтение блобов. batch=True — один долгоживущий `git cat-file --batch` (оптимизация №2)."""

    def __init__(self, path, batch=True):
        self.path, self.batch, self.proc = path, batch, None
        if batch:
            self.proc = subprocess.Popen(["git", "-C", path, "cat-file", "--batch"],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL)

    def read(self, sha):
        if not self.batch:
            return _run(self.path, "cat-file", "blob", sha).stdout
        self.proc.stdin.write(sha.encode() + b"\n")
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        if len(header) < 3 or header[1] != b"blob":
            raise GitError(f"битый объект {sha}")
        data = self.proc.stdout.read(int(header[2]))
        self.proc.stdout.read(1)
        return data

    def close(self):
        if self.proc:
            self.proc.stdin.close()
            self.proc.wait()
            self.proc = None
