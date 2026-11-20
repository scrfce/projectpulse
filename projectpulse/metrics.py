"""Метрики. 5 классических + 3 собственные + временные ряды (см. docs/architecture.md)."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations

from . import graph
from .plugins import metric
from .stats import mean, percentile_ranks


class Ctx:
    """Данные для метрик, загруженные из БД."""

    def __init__(self, commits, changes, files, file_edges):
        self.commits = commits                       # [dict(hash, author, ts, is_fix)] по времени
        self.changes = changes                       # [(hash, author, ts, path, added, deleted)]
        self.files = files                           # {path: dict(loc, cc, max_cc)} на HEAD
        self.file_edges = file_edges
        self.py_changes = [c for c in changes if c[3] in files]
        self.file_churn = Counter()
        self.file_history = defaultdict(list)        # path -> [(ts, author)]
        self.file_author_lines = defaultdict(Counter)
        seen = set()
        for h, a, ts, p, ad, de in self.py_changes:
            self.file_churn[p] += ad + de
            self.file_author_lines[p][a] += ad + de
            if (h, p) not in seen:
                seen.add((h, p))
                self.file_history[p].append((ts, a))

    @classmethod
    def load(cls, db, repo):
        commits = [dict(hash=h, author=a, ts=t, is_fix=f) for h, a, t, f in db.execute(
            "SELECT hash,author,ts,is_fix FROM commits WHERE repo=? ORDER BY ts,hash", (repo,))]
        changes = db.execute(
            "SELECT c.hash,c.author,c.ts,f.path,f.added,f.deleted FROM file_changes f "
            "JOIN commits c ON c.repo=f.repo AND c.hash=f.hash WHERE f.repo=? "
            "ORDER BY c.ts,c.hash,f.path", (repo,)).fetchall()
        files = {p: dict(loc=l, cc=c, max_cc=m) for p, l, c, m in db.execute(
            "SELECT path,loc,cc,max_cc FROM files WHERE repo=?", (repo,))}
        vs = graph.versions(db, repo)
        edges = graph.load_edges(db, vs[-1][0], "file") if vs else []
        return cls(commits, changes, files, edges)


def _top(counter):
    return max(counter.items(), key=lambda kv: (kv[1], kv[0]))


# ---------------- 5 классических ----------------
@metric("loc")
def m_loc(ctx):
    rows = [("loc", "file", p, f["loc"]) for p, f in ctx.files.items()]
    return rows + [("loc_total", "project", "", sum(f["loc"] for f in ctx.files.values()))]


@metric("cyclomatic")
def m_cc(ctx):
    rows = [("cc", "file", p, f["cc"]) for p, f in ctx.files.items()]
    rows += [("cc_max_func", "file", p, f["max_cc"]) for p, f in ctx.files.items()]
    return rows + [("cc_max_func", "project", "", max((f["max_cc"] for f in ctx.files.values()), default=0))]


@metric("churn")
def m_churn(ctx):
    rows = [("churn", "file", p, ctx.file_churn[p]) for p in ctx.files]
    return rows + [("churn_total", "project", "", sum(ctx.file_churn.values()))]


@metric("ownership")
def m_own(ctx):
    vals = {}
    for p in ctx.files:
        c = ctx.file_author_lines[p]
        tot = sum(c.values())
        vals[p] = _top(c)[1] / tot if tot else 1.0
    return [("ownership", "file", p, v) for p, v in vals.items()] + \
           [("ownership_mean", "project", "", mean(vals.values()))]


@metric("bus_factor")
def m_bus(ctx):
    lines = Counter()
    for _, a, _, _, ad, de in ctx.py_changes:
        lines[a] += ad + de
    total = sum(lines.values())
    if not total:
        return [("bus_factor", "project", "", 0)]
    acc, n = 0, 0
    for _, v in sorted(lines.items(), key=lambda kv: (-kv[1], kv[0])):
        acc += v
        n += 1
        if acc >= 0.5 * total:
            break
    return [("bus_factor", "project", "", n)]


# ---------------- 3 собственные ----------------
@metric("hotspot")
def m_hotspot(ctx):
    """Hotspot(f) = 100 * P_churn(f) * P_cc(f), P — перцентильный ранг среди файлов проекта."""
    paths = sorted(ctx.files)
    if not paths:
        return []
    pc = percentile_ranks([ctx.file_churn[p] for p in paths])
    px = percentile_ranks([ctx.files[p]["cc"] for p in paths])
    h = {p: 100 * a * b for p, a, b in zip(paths, pc, px)}
    top5 = sorted(h.values(), reverse=True)[:5]
    return [("hotspot", "file", p, v) for p, v in h.items()] + [
        ("hotspot_max", "project", "", max(h.values())),
        ("hotspot_top5_mean", "project", "", mean(top5))]


@metric("ownership_decay")
def m_decay(ctx):
    """Доля файлов (≥4 правок), у которых главный автор последних 30% правок ≠ главному автору за всё время."""
    elig = diff = 0
    for p, hist in ctx.file_history.items():
        if len(hist) < 4:
            continue
        hist = sorted(hist)
        recent = hist[-max(1, round(len(hist) * 0.3)):]
        overall = _top(Counter(a for _, a in hist))[0]
        now = _top(Counter(a for _, a in recent))[0]
        elig += 1
        diff += overall != now
    return [("ownership_decay", "project", "", diff / elig if elig else 0.0)]


@metric("change_coupling")
def m_coupling(ctx):
    """Средний Жаккар топ-10 пар файлов, меняющихся вместе (коммиты из 2..30 файлов, ≥3 совместных)."""
    by_commit = defaultdict(set)
    for h, _, _, p, _, _ in ctx.py_changes:
        by_commit[h].add(p)
    n_f, pair = Counter(), Counter()
    for files in by_commit.values():
        n_f.update(files)
        if 2 <= len(files) <= 30:
            pair.update(combinations(sorted(files), 2))
    scored = sorted(((c / (n_f[a] + n_f[b] - c), a, b) for (a, b), c in pair.items() if c >= 3),
                    key=lambda t: (-t[0], t[1], t[2]))[:10]
    rows = [("coupling_pair", "pair", f"{a} | {b}", j) for j, a, b in scored]
    return rows + [("change_coupling", "project", "", mean(j for j, _, _ in scored))]


# ---------------- временные ряды ----------------
def _week(ts):
    d = datetime.fromtimestamp(ts, timezone.utc).date()
    return d - timedelta(days=d.weekday())


def _weeks(ctx):
    if not ctx.commits:
        return []
    a, b = _week(ctx.commits[0]["ts"]), _week(ctx.commits[-1]["ts"])
    return [a + timedelta(weeks=i) for i in range((b - a).days // 7 + 1)]


@metric("series")
def m_series(ctx):
    weeks = _weeks(ctx)
    commits, fixes, churn = Counter(), Counter(), Counter()
    ch_by_hash = defaultdict(int)
    for h, _, _, _, ad, de in ctx.changes:
        ch_by_hash[h] += ad + de
    for c in ctx.commits:
        w = _week(c["ts"])
        commits[w] += 1
        fixes[w] += c["is_fix"]
        churn[w] += ch_by_hash[c["hash"]]
    rows = []
    for w in weeks:
        k = w.isoformat()
        rows += [("weekly_commits", "series", k, commits[w]),
                 ("weekly_churn", "series", k, churn[w]),
                 ("weekly_fixes", "series", k, fixes[w]),
                 ("weekly_fix_ratio", "series", k, fixes[w] / commits[w] if commits[w] else 0.0)]
    return rows


# ---------------- сводные ----------------
@metric("summary")
def m_summary(ctx):
    n = len(ctx.commits)
    return [("commits_total", "project", "", n),
            ("authors", "project", "", len({c["author"] for c in ctx.commits})),
            ("fix_ratio", "project", "", sum(c["is_fix"] for c in ctx.commits) / n if n else 0.0),
            ("files_total", "project", "", len(ctx.files))]


@metric("cycles")
def m_cycles(ctx):
    adj = graph.adjacency(ctx.file_edges, ctx.files)
    comps = graph.cycle_components(adj)
    in_cycle = sum(len(c) for c in comps)
    return [("cycle_count", "project", "", len(comps)),
            ("cycle_files_ratio", "project", "", in_cycle / len(ctx.files) if ctx.files else 0.0)]
