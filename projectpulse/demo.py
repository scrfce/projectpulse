"""Генератор детерминированных демо-репозиториев («здоровый» и «проблемный») для тестов и проверки."""
import os
import random
import subprocess
from datetime import datetime, timezone

START = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())   # понедельник
WEEK = 7 * 86400


def _git(cwd, *args, env=None):
    e = {**os.environ, **(env or {})}
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, env=e)


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _commit(root, author, ts, msg):
    env = {"GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author}@x.io", "GIT_COMMITTER_NAME": author,
           "GIT_COMMITTER_EMAIL": f"{author}@x.io", "GIT_AUTHOR_DATE": f"{ts} +0000", "GIT_COMMITTER_DATE": f"{ts} +0000"}
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg, env=env)


def make_repo(root, style="healthy", weeks=20, seed=1):
    """style: 'healthy' | 'problem'. Возвращает число коммитов."""
    rnd = random.Random(seed)
    os.makedirs(root, exist_ok=True)
    _git(root, "init", "-q")
    n_mod = 10
    src = {}
    for i in range(n_mod):
        imp = f"from pkg.m{i - 1} import C{i - 1}\n" if i else ""
        base = f"(C{i - 1})" if i else ""
        src[f"pkg/m{i}.py"] = f"{imp}\nclass C{i}{base}:\n    def __init__(self):\n        self.x = 0\n"
    src["pkg/__init__.py"] = ""
    if style == "problem":
        src["pkg/core.py"] = "import pkg.util\nfrom pkg.m0 import C0\n\nclass Core:\n    def __init__(self):\n        self.c = C0()\n\ndef big(x):\n    r = 0\n"
        src["pkg/util.py"] = "import pkg.core\n\ndef helper():\n    return pkg.core.Core()\n"
    for p, t in src.items():
        _write(root, p, t)
    _commit(root, "alice", START, "initial import")
    authors = ["alice", "bob", "carol", "dave"]
    total, fn = 1, 0
    for w in range(weeks):
        if style == "healthy":
            n = 3 + (w % 2)
        else:   # рост активности, затем спад
            n = 1 + w // 2 if w < 12 else max(1, 6 - (w - 12))
        for k in range(n):
            ts = START + w * WEEK + (k + 1) * 3600 * 20
            if style == "healthy":
                k_mod = rnd.randrange(n_mod)
                author = authors[k_mod % 4] if rnd.random() < 0.9 else authors[rnd.randrange(4)]
                p_fix = 0.1
                files = [f"pkg/m{k_mod}.py"]
                lines = rnd.randint(2, 6)
            else:
                late = w >= weeks * 0.7
                author = "bob" if late and rnd.random() < 0.7 else ("alice" if rnd.random() < 0.9 else "carol")
                p_fix = 0.05 + 0.6 * w / weeks
                files = ["pkg/core.py"] + ([f"pkg/m{rnd.randrange(3)}.py"] if rnd.random() < 0.7 else [])
                lines = 200 if w >= weeks - 4 else rnd.randint(2, 6)
            for f in files:
                fn += 1
                body = "".join(f"\n\ndef f{fn}_{j}(x):\n    return x + {j}" for j in range(lines // 4 + 1)) \
                    if style == "healthy" else ""
                with open(os.path.join(root, f), "a", encoding="utf-8") as fh:
                    if f == "pkg/core.py":
                        for j in range(max(1, lines // 4)):
                            fh.write(f"    if x > {fn}{j} and x % 2 or x < {j}:\n        r += {j}\n")
                    else:
                        fh.write(body or f"\ndef g{fn}(x):\n    return x * {fn}\n")
            fixmsg = rnd.random() < p_fix
            _commit(root, author, ts, ("fix: bug in module" if fixmsg else "feat: add functionality") + f" #{total}")
            total += 1
    return total
