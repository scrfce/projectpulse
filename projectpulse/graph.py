"""Графы зависимостей (файл→файл, класс→класс), Тарьян, топосорт, версии графа."""
import heapq


# ---------- построение ----------
def module_of(path):
    parts = (path[:-3] if path.endswith(".py") else path).split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _mod_index(paths):
    full = {module_of(p): p for p in paths if module_of(p)}
    suf = {}
    for m, p in full.items():
        parts = m.split(".")
        for i in range(1, len(parts)):
            suf.setdefault(".".join(parts[i:]), set()).add(p)
    idx = dict(full)
    for s, ps in suf.items():           # суффиксы нужны для src-layout; неоднозначные отбрасываем
        if s not in idx and len(ps) == 1:
            idx[s] = next(iter(ps))
    return idx


def resolve_imports(path, info, idx):
    out = set()
    pkg = path.split("/")[:-1]
    for mod, level, names in info["imports"]:
        if level:
            base = pkg[:max(0, len(pkg) - (level - 1))] + (mod.split(".") if mod else [])
        else:
            base = mod.split(".") if mod else []
        b = ".".join(base)
        hit = False
        for n in names:
            t = idx.get(f"{b}.{n}" if b else n)
            if t:
                out.add(t)
                hit = True
        if not hit and b in idx:
            out.add(idx[b])
    out.discard(path)
    return out


def build_graph(infos):
    """infos: {path: info}. Возвращает две проекции графа."""
    idx = _mod_index(list(infos))
    file_edges = set()
    for p, info in infos.items():
        for t in resolve_imports(p, info, idx):
            file_edges.add((p, t, "import"))
    by_name = {}
    for p, info in infos.items():
        for c in info["classes"]:
            by_name.setdefault(c["name"], []).append(f"{p}::{c['name']}")
    class_nodes, class_edges = set(), set()
    for p, info in infos.items():
        for c in info["classes"]:
            src = f"{p}::{c['name']}"
            class_nodes.add(src)
            for rel, names in (("inherit", c["bases"]), ("compose", c["compose"]), ("call", c["calls"])):
                for n in names:
                    cands = by_name.get(n, [])
                    same = [x for x in cands if x.startswith(p + "::")]
                    tgt = same[0] if same else (cands[0] if len(cands) == 1 else None)
                    if tgt and tgt != src:
                        class_edges.add((src, tgt, rel))
    return {"file_nodes": sorted(infos), "class_nodes": sorted(class_nodes),
            "file_edges": sorted(file_edges), "class_edges": sorted(class_edges)}


# ---------- алгоритмы (самостоятельно, без networkx) ----------
def adjacency(edges, nodes=()):
    adj = {n: set() for n in nodes}
    for s, d, *_ in edges:
        adj.setdefault(s, set()).add(d)
        adj.setdefault(d, set())
    return adj


def tarjan_scc(adj):
    """Итеративный алгоритм Тарьяна. Возвращает список компонент сильной связности."""
    index, low, onstack, stack, res, counter = {}, {}, set(), [], [], 0
    nodes = set(adj) | {w for ws in adj.values() for w in ws}
    for root in sorted(nodes):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        work = [(root, iter(sorted(adj.get(root, ()))))]
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    break
                elif w in onstack:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        onstack.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    res.append(sorted(comp))
    return res


def cycle_components(adj):
    return [c for c in tarjan_scc(adj) if len(c) > 1 or c[0] in adj.get(c[0], ())]


def toposort(adj):
    """Топосорт (Кана) по конденсации графа; цикл схлопывается в одну компоненту.
    Порядок: зависимые раньше зависимостей, детерминированно."""
    comps = tarjan_scc(adj)
    comp_of = {n: i for i, c in enumerate(comps) for n in c}
    out_edges = {i: set() for i in range(len(comps))}
    indeg = {i: 0 for i in range(len(comps))}
    for v, ws in adj.items():
        for w in ws:
            a, b = comp_of[v], comp_of[w]
            if a != b and b not in out_edges[a]:
                out_edges[a].add(b)
                indeg[b] += 1
    heap = [(comps[i][0], i) for i, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        _, i = heapq.heappop(heap)
        order.append(comps[i])
        for j in sorted(out_edges[i]):
            indeg[j] -= 1
            if indeg[j] == 0:
                heapq.heappush(heap, (comps[j][0], j))
    return order


def bfs(adj_both, start, depth):
    """{узел: расстояние} до глубины depth."""
    seen = {start: 0}
    frontier = [start]
    for d in range(1, depth + 1):
        nxt = []
        for v in frontier:
            for w in sorted(adj_both.get(v, ())):
                if w not in seen:
                    seen[w] = d
                    nxt.append(w)
        frontier = nxt
    return seen


# ---------- версионирование ----------
def store_snapshot(db, repo, commit_hash, ts, g):
    n_nodes = len(g["file_nodes"]) + len(g["class_nodes"])
    n_edges = len(g["file_edges"]) + len(g["class_edges"])
    cur = db.execute("INSERT INTO graph_versions(repo,commit_hash,ts,n_nodes,n_edges) VALUES(?,?,?,?,?)",
                     (repo, commit_hash, ts, n_nodes, n_edges))
    vid = cur.lastrowid
    db.executemany("INSERT INTO graph_nodes VALUES(?,?,?)",
                   [(vid, "file", n) for n in g["file_nodes"]] + [(vid, "class", n) for n in g["class_nodes"]])
    db.executemany("INSERT INTO graph_edges VALUES(?,?,?,?,?)",
                   [(vid, "file", r, s, d) for s, d, r in g["file_edges"]] +
                   [(vid, "class", r, s, d) for s, d, r in g["class_edges"]])
    return vid


def versions(db, repo):
    return db.execute("SELECT id,commit_hash,ts,n_nodes,n_edges FROM graph_versions "
                      "WHERE repo=? ORDER BY ts,id", (repo,)).fetchall()


def load_edges(db, vid, projection):
    return db.execute("SELECT src,dst,rel FROM graph_edges WHERE version_id=? AND projection=? "
                      "ORDER BY src,dst,rel", (vid, projection)).fetchall()


def load_nodes(db, vid, projection):
    return [r[0] for r in db.execute("SELECT node FROM graph_nodes WHERE version_id=? AND projection=? "
                                     "ORDER BY node", (vid, projection))]


def diff_versions(db, v1, v2, projection="file"):
    a, b = set(load_edges(db, v1, projection)), set(load_edges(db, v2, projection))
    return {"added": sorted(b - a), "removed": sorted(a - b)}
