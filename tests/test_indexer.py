import threading

import pytest

from conftest import add_commit
from projectpulse import graph
from projectpulse.gitio import GitError
from projectpulse.indexer import Cancelled, Indexer


def test_full_import(db, small_repo):
    r = Indexer(db, small_repo, "r").run()
    assert r["mode"] == "full" and r["n_commits"] == 1
    assert db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2
    assert len(graph.versions(db, "r")) == 1


def test_noop_when_unchanged(db, small_repo):
    Indexer(db, small_repo, "r").run()
    assert Indexer(db, small_repo, "r").run()["mode"] == "noop"


def test_incremental_picks_only_new_commits(db, small_repo):
    Indexer(db, small_repo, "r").run()
    add_commit(small_repo, "c.py", "import a\n", ts=1_700_200_000)
    r = Indexer(db, small_repo, "r").run()
    assert r["mode"] == "incremental" and r["n_commits"] == 1
    assert db.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 3
    assert len(graph.versions(db, "r")) == 2


def test_incremental_equals_full(small_repo, db):
    from projectpulse.db import open_db
    Indexer(db, small_repo, "r").run()
    add_commit(small_repo, "c.py", "import a\n", ts=1_700_200_000)
    Indexer(db, small_repo, "r").run()
    db2 = open_db(":memory:")
    Indexer(db2, small_repo, "r").run()
    q = "SELECT path,loc,cc FROM files ORDER BY path"
    assert db.execute(q).fetchall() == db2.execute(q).fetchall()
    assert db.execute("SELECT hash FROM commits ORDER BY hash").fetchall() == \
        db2.execute("SELECT hash FROM commits ORDER BY hash").fetchall()


def test_rebuild_resets(db, small_repo):
    Indexer(db, small_repo, "r").run()
    r = Indexer(db, small_repo, "r").run(rebuild=True)
    assert r["mode"] == "full"
    assert db.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 1


def test_blob_cache_reused(db, small_repo):
    Indexer(db, small_repo, "r").run()
    assert db.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 2


def test_cancel_rolls_back(db, small_repo):
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        Indexer(db, small_repo, "r", cancel=ev).run()
    assert db.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 0


def test_not_a_repo(db, tmp_path):
    with pytest.raises(GitError):
        Indexer(db, str(tmp_path), "x").run()


def test_empty_repo(db, tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    with pytest.raises(GitError):
        Indexer(db, str(tmp_path), "x").run()


def test_broken_python_file_does_not_crash(db, small_repo):
    add_commit(small_repo, "bad.py", "def x(:\n", ts=1_700_300_000)
    Indexer(db, small_repo, "r").run()
    assert db.execute("SELECT cc FROM files WHERE path='bad.py'").fetchone()[0] == 0


def test_progress_callback(db, small_repo):
    calls = []
    Indexer(db, small_repo, "r", progress=lambda s, d, t: calls.append(s)).run()
    assert calls


def test_baseline_and_optimized_give_same_result(small_repo):
    from projectpulse.db import open_db
    out = []
    for kw in (dict(use_cache=False, fast_blobs=False), dict(use_cache=True, fast_blobs=True)):
        d = open_db(":memory:")
        Indexer(d, small_repo, "r", **kw).run()
        out.append(d.execute("SELECT path,loc,cc,max_cc FROM files ORDER BY path").fetchall())
    assert out[0] == out[1]
