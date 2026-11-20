import os
import subprocess
import threading

import pytest

from projectpulse.db import open_db
from projectpulse.demo import _commit, _git, _write, make_repo


@pytest.fixture(scope="session")
def demo_repos(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo")
    make_repo(str(root / "healthy"), "healthy")
    make_repo(str(root / "problem"), "problem")
    return str(root / "healthy"), str(root / "problem")


@pytest.fixture
def db():
    conn = open_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def small_repo(tmp_path):
    r = str(tmp_path / "r")
    os.makedirs(r)
    _git(r, "init", "-q")
    _write(r, "a.py", "import b\n\nclass A(b.B):\n    pass\n")
    _write(r, "b.py", "class B:\n    pass\n")
    _commit(r, "alice", 1_700_000_000, "init")
    return r


def add_commit(repo, name, text, msg="feat", ts=1_700_100_000, author="bob"):
    _write(repo, name, text)
    _commit(repo, author, ts, msg)
