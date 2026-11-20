from hypothesis import given, strategies as st

from projectpulse import graph
from projectpulse.pyparse import parse


def test_tarjan_simple_cycle():
    comps = graph.tarjan_scc({"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}})
    assert ["a", "b", "c"] in comps and ["d"] in comps


def test_tarjan_deep_chain_no_recursion_error():
    adj = {i: {i + 1} for i in range(5000)}
    assert len(graph.tarjan_scc(adj)) == 5001


def test_cycle_components_selfloop():
    assert graph.cycle_components({"a": {"a"}, "b": set()}) == [["a"]]


def test_toposort_dag():
    order = graph.toposort({"app": {"lib", "util"}, "lib": {"util"}, "util": set()})
    flat = [c[0] for c in order]
    assert flat.index("app") < flat.index("lib") < flat.index("util")


def test_toposort_collapses_cycle():
    order = graph.toposort({"a": {"b"}, "b": {"a"}, "c": {"a"}})
    assert ["a", "b"] in order and order[0] == ["c"]


def test_resolve_imports_relative_and_absolute():
    infos = {"pkg/__init__.py": parse(""), "pkg/a.py": parse("from . import b\nimport pkg.c\n"),
             "pkg/b.py": parse(""), "pkg/c.py": parse("")}
    g = graph.build_graph(infos)
    assert ("pkg/a.py", "pkg/b.py", "import") in g["file_edges"]
    assert ("pkg/a.py", "pkg/c.py", "import") in g["file_edges"]


def test_class_graph_relations():
    infos = {"m.py": parse("class B: pass\nclass A(B):\n    def __init__(self):\n        self.b = B()\n")}
    g = graph.build_graph(infos)
    assert ("m.py::A", "m.py::B", "inherit") in g["class_edges"]
    assert ("m.py::A", "m.py::B", "compose") in g["class_edges"]


def test_snapshot_store_and_diff(db):
    g1 = {"file_nodes": ["a", "b"], "class_nodes": [], "file_edges": [("a", "b", "import")], "class_edges": []}
    g2 = {"file_nodes": ["a", "b", "c"], "class_nodes": [], "file_edges": [("a", "b", "import"), ("b", "c", "import")], "class_edges": []}
    v1 = graph.store_snapshot(db, "r", "h1", 1, g1)
    v2 = graph.store_snapshot(db, "r", "h2", 2, g2)
    assert graph.diff_versions(db, v1, v2) == {"added": [("b", "c", "import")], "removed": []}


def test_bfs_depth():
    assert graph.bfs({"a": {"b"}, "b": {"a", "c"}, "c": {"b"}}, "a", 1) == {"a": 0, "b": 1}


@given(st.dictionaries(st.integers(0, 15), st.sets(st.integers(0, 15), max_size=5), max_size=16))
def test_prop_scc_is_partition(adj):
    comps = graph.tarjan_scc(adj)
    nodes = set(adj) | {w for ws in adj.values() for w in ws}
    flat = [n for c in comps for n in c]
    assert sorted(flat) == sorted(nodes)          # каждый узел ровно в одной компоненте
    comp_of = {n: i for i, c in enumerate(comps) for n in c}
    order = graph.toposort(adj)
    pos = {n: i for i, c in enumerate(order) for n in c}
    for v, ws in adj.items():
        for w in ws:
            assert pos[v] <= pos[w]                # рёбра идут «вперёд» в топопорядке
