from projectpulse.pyparse import count_loc, parse


def test_loc_ignores_comments_and_blank():
    assert count_loc("# c\n\nx = 1\n\ny = 2  # t\n") == 2


def test_cyclomatic_counts_branches():
    src = "def f(a, b):\n    if a and b:\n        return 1\n    for i in range(3):\n        pass\n    return 0\n"
    i = parse(src)
    assert i["max_cc"] == 1 + 1 + 1 + 1       # if, and, for
    assert i["cc"] == i["max_cc"]


def test_imports_extracted():
    i = parse("import os.path\nfrom . import x\nfrom a.b import c, d\n")
    assert ["os.path", 0, []] in i["imports"]
    assert ["", 1, ["x"]] in i["imports"]
    assert ["a.b", 0, ["c", "d"]] in i["imports"]


def test_class_relations():
    i = parse("class A(B):\n    def __init__(self):\n        self.p = P()\n    def m(self):\n        return Q()\n")
    c = i["classes"][0]
    assert c["bases"] == ["B"] and c["compose"] == ["P"] and c["calls"] == ["Q"]


def test_syntax_error_is_tolerated():
    i = parse("def broken(:\n  x = \n")
    assert i["error"] == 1 and i["cc"] == 0
