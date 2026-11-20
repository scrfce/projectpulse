"""Анализ исходников Python: ast + tokenize (без radon и пр.)."""
import ast
import io
import tokenize

_SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
         tokenize.DEDENT, tokenize.ENDMARKER, tokenize.ENCODING}
_BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.Assert)
EMPTY = {"loc": 0, "cc": 0, "max_cc": 0, "imports": [], "classes": []}


def count_loc(src):
    """Число физических строк, содержащих код (комментарии и пустые не считаются)."""
    lines = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in _SKIP:
                lines.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return sum(1 for l in src.splitlines() if l.strip() and not l.strip().startswith("#"))
    return len(lines)


def _branches(node):
    n = 0
    for x in ast.walk(node):
        if isinstance(x, _BRANCH):
            n += 1
        elif isinstance(x, ast.BoolOp):
            n += len(x.values) - 1
        elif isinstance(x, ast.comprehension):
            n += 1 + len(x.ifs)
    return n


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _classes(tree):
    out = []
    for c in ast.walk(tree):
        if not isinstance(c, ast.ClassDef):
            continue
        bases = sorted({n for b in c.bases if (n := _name(b))})
        comp, calls = set(), set()
        for x in ast.walk(c):
            if isinstance(x, ast.Assign) and isinstance(x.value, ast.Call):
                n = _name(x.value.func)
                if n and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                             and t.value.id == "self" for t in x.targets):
                    comp.add(n)
            elif isinstance(x, ast.AnnAssign):
                n = _name(x.annotation)
                if n:
                    comp.add(n)
            elif isinstance(x, ast.Call):
                n = _name(x.func)
                if n:
                    calls.add(n)
        calls -= comp
        calls.discard(c.name)
        comp.discard(c.name)
        out.append({"name": c.name, "bases": bases, "compose": sorted(comp), "calls": sorted(calls)})
    return out


def parse(src):
    loc = count_loc(src)
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return {**EMPTY, "loc": loc, "error": 1}
    imports = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports += [[a.name, 0, []] for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            imports.append([n.module or "", n.level, [a.name for a in n.names]])
    funcs = [1 + _branches(f) for f in ast.walk(tree)
             if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return {"loc": loc, "cc": 1 + _branches(tree), "max_cc": max(funcs, default=1),
            "imports": imports, "classes": _classes(tree)}
