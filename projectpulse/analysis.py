"""Запуск метрик и правил, индекс здоровья, сравнение, тайминги, мини-исследование."""
import json
import logging
import time
from dataclasses import dataclass

from . import metrics as _m, plugins, rules as _r     # noqa: F401  (регистрация встроенных плагинов)
from .metrics import Ctx
from .rules import DEFAULT_TH, PENALTY, SEV_RANK, Finding, MetricView
from .stats import pearson, spearman

log = logging.getLogger("projectpulse.analysis")


@dataclass
class Result:
    id: int
    repo: str
    health: int
    findings: list
    mv: MetricView


def analyze(db, repo, thresholds=None, plugin_dirs=()):
    t0, started = time.perf_counter(), time.time()
    plugins.load_all(plugin_dirs)
    ctx = Ctx.load(db, repo)
    rows = []
    for name in sorted(plugins.METRICS):
        try:
            rows.extend(plugins.METRICS[name](ctx))
        except Exception:
            log.exception("метрика %s упала", name)
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    mv = MetricView(rows)
    th = {**DEFAULT_TH, **(thresholds or {})}
    findings = []
    for name in sorted(plugins.RULES):
        try:
            res = plugins.RULES[name](mv, th)
        except Exception:
            log.exception("правило %s упало", name)
            continue
        findings += [res] if isinstance(res, Finding) else (res or [])
    findings.sort(key=lambda f: (-SEV_RANK[f.severity], f.rule))
    health = max(0, 100 - sum(PENALTY[f.severity] for f in findings))
    cur = db.execute("INSERT INTO analysis_events(repo,kind,mode,started,duration,n_commits,head) "
                     "VALUES(?,?,?,?,?,?,?)", (repo, "analyze", "", started, time.perf_counter() - t0,
                                                len(ctx.commits), ""))
    aid = cur.lastrowid
    db.executemany("INSERT INTO metrics VALUES(?,?,?,?,?)", [(aid, *r) for r in rows])
    db.executemany("INSERT INTO rule_results VALUES(?,?,?,?,?)", [
        (aid, f.rule, f.severity, f.message, json.dumps(f.details, ensure_ascii=False)) for f in findings])
    db.commit()
    return Result(aid, repo, health, findings, mv)


def timings(db, repo):
    """Последнее время полной и инкрементальной индексации."""
    out = {}
    for mode in ("full", "incremental"):
        r = db.execute("SELECT duration,n_commits FROM analysis_events WHERE repo=? AND kind='index' "
                       "AND mode=? ORDER BY id DESC LIMIT 1", (repo, mode)).fetchone()
        out[mode] = r
    return out


KEY_INDICATORS = [("Индекс здоровья", None), ("Bus factor", "bus_factor"), ("Ownership (среднее)", "ownership_mean"),
                  ("Доля багфиксов", "fix_ratio"), ("Hotspot (топ-5)", "hotspot_top5_mean")]


def compare(db, a, b):
    ra, rb = analyze(db, a), analyze(db, b)
    rows = []
    for label, key in KEY_INDICATORS:
        va = ra.health if key is None else ra.mv.project(key, 0)
        vb = rb.health if key is None else rb.mv.project(key, 0)
        rows.append((label, va, vb))
    return rows


def research(mv):
    """Гипотеза: churn недели t предсказывает число багфиксов недели t+1 (Спирмен/Пирсон, свои реализации)."""
    churn = [v for _, v in mv.series("weekly_churn")]
    fixes = [v for _, v in mv.series("weekly_fixes")]
    x, y = churn[:-1], fixes[1:]
    return {"n": len(x), "spearman": spearman(x, y), "pearson": pearson(x, y)}
