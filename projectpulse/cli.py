"""CLI: index / analyze / compare / report / research / fetch / bench / ui."""
import argparse
import cProfile
import json
import logging
import os
import pstats
import subprocess
import sys
import tempfile
import time

from . import analysis, gitio, report
from .db import open_db
from .indexer import Indexer


def _data_dir(a):
    d = a.data or os.path.join(os.path.expanduser("~"), ".projectpulse")
    os.makedirs(d, exist_ok=True)
    logging.basicConfig(filename=os.path.join(d, "projectpulse.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return d


def _print_result(res):
    print(f"[{res.repo}] индекс здоровья: {res.health}/100")
    for f in res.findings:
        print(f"  [{f.severity:6}] {f.rule}: {f.message}")


def cmd_index(a):
    db = open_db(os.path.join(_data_dir(a), "projectpulse.db"))
    r = Indexer(db, a.path, a.name, progress=lambda s, d, t: None).run(rebuild=a.rebuild)
    print(f"{r['mode']}: {r['n_commits']} коммитов за {r['duration']:.2f} с")


def cmd_analyze(a):
    _print_result(analysis.analyze(open_db(os.path.join(_data_dir(a), "projectpulse.db")), a.name,
                                   plugin_dirs=a.plugins or ()))


def cmd_compare(a):
    db = open_db(os.path.join(_data_dir(a), "projectpulse.db"))
    for label, x, y in analysis.compare(db, a.healthy, a.problem):
        print(f"{label:24} {x!s:>10} {y!s:>10}")


def cmd_report(a):
    db = open_db(os.path.join(_data_dir(a), "projectpulse.db"))
    html = report.build_html(db, analysis.analyze(db, a.name, plugin_dirs=a.plugins or ()))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)
    print("отчёт:", a.out)


def cmd_research(a):
    db = open_db(os.path.join(_data_dir(a), "projectpulse.db"))
    for n in a.names:
        r = analysis.research(analysis.analyze(db, n).mv)
        print(f"{n}: n={r['n']} spearman={r['spearman']:.3f} pearson={r['pearson']:.3f}")


def cmd_fetch(a):
    """Клонирует репозитории из repos.json (единственный шаг, где нужен интернет)."""
    d = _data_dir(a)
    for r in json.load(open(a.manifest, encoding="utf-8"))["repos"]:
        dest = os.path.join(d, "repos", r["name"])
        if not os.path.isdir(dest):
            subprocess.run(["git", "clone", r["url"], dest], check=True)
        if r.get("commit"):
            subprocess.run(["git", "-C", dest, "checkout", "-q", r["commit"]], check=True)
        print("готов:", dest)


def cmd_bench(a):
    """Замеры + cProfile + доказательство 2 оптимизаций (до/после)."""
    def run(label, **kw):
        db = open_db(":memory:")
        t = time.perf_counter()
        Indexer(db, a.path, "bench", **kw).run()
        dt = time.perf_counter() - t
        print(f"{label:46} {dt:7.2f} с")
        return db, dt
    print("== сравнение конфигураций (полный импорт) ==")
    run("база (без кэша, git cat-file на каждый файл)", use_cache=False, fast_blobs=False)
    run("оптимизация 1: кэш по sha блоба", use_cache=True, fast_blobs=False)
    run("оптимизация 2: + cat-file --batch", use_cache=True, fast_blobs=True)
    db, tfull = run("итог (полный)")
    t = time.perf_counter()
    Indexer(db, a.path, "bench").run()
    print(f"{'повторный запуск (noop/инкремент.)':46} {time.perf_counter() - t:7.2f} с")
    print("== cProfile: топ-10 по накопленному времени (база) ==")
    pr = cProfile.Profile()
    pr.enable()
    Indexer(open_db(":memory:"), a.path, "bench", use_cache=False, fast_blobs=False).run()
    pr.disable()
    pstats.Stats(pr).sort_stats("cumulative").print_stats(10)


def cmd_ui(a):
    from .ui import run_ui
    run_ui(_data_dir(a))


def main(argv=None):
    p = argparse.ArgumentParser(prog="projectpulse")
    p.add_argument("--data", help="папка данных (по умолчанию ~/.projectpulse)")
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("index"); s.add_argument("path"); s.add_argument("--name"); s.add_argument("--rebuild", action="store_true"); s.set_defaults(f=cmd_index)
    s = sp.add_parser("analyze"); s.add_argument("name"); s.add_argument("--plugins", nargs="*"); s.set_defaults(f=cmd_analyze)
    s = sp.add_parser("compare"); s.add_argument("healthy"); s.add_argument("problem"); s.set_defaults(f=cmd_compare)
    s = sp.add_parser("report"); s.add_argument("name"); s.add_argument("out"); s.add_argument("--plugins", nargs="*"); s.set_defaults(f=cmd_report)
    s = sp.add_parser("research"); s.add_argument("names", nargs="+"); s.set_defaults(f=cmd_research)
    s = sp.add_parser("fetch"); s.add_argument("--manifest", default="repos.json"); s.set_defaults(f=cmd_fetch)
    s = sp.add_parser("bench"); s.add_argument("path"); s.set_defaults(f=cmd_bench)
    s = sp.add_parser("demo"); s.add_argument("--dest", default=os.path.join(tempfile.gettempdir(), "pp_demo")); s.set_defaults(f=cmd_demo)
    s = sp.add_parser("ui"); s.set_defaults(f=cmd_ui)
    a = p.parse_args(argv)
    try:
        a.f(a)
    except gitio.GitError as e:
        print("Ошибка git:", e, file=sys.stderr)
        sys.exit(2)


def cmd_demo(a):
    from .demo import make_repo
    for style in ("healthy", "problem"):
        dest = os.path.join(a.dest, style)
        if not os.path.isdir(dest):
            make_repo(dest, style)
        print("демо-репозиторий:", dest)
