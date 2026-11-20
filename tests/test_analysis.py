import os

from projectpulse import analysis, plugins, report
from projectpulse.indexer import Indexer


def _prep(db, demo_repos):
    h, p = demo_repos
    Indexer(db, h, "healthy").run()
    Indexer(db, p, "problem").run()


def test_health_ordering(db, demo_repos):
    _prep(db, demo_repos)
    h, p = analysis.analyze(db, "healthy"), analysis.analyze(db, "problem")
    assert h.health > p.health
    assert h.health >= 80 and p.health <= 40


def test_problem_triggers_expected_rules(db, demo_repos):
    _prep(db, demo_repos)
    rules = {f.rule for f in analysis.analyze(db, "problem").findings}
    assert {"low_bus_factor", "import_cycles", "trend_fix_growth", "trend_churn_jump", "trend_activity_break"} <= rules


def test_findings_explain_values(db, demo_repos):
    _prep(db, demo_repos)
    for f in analysis.analyze(db, "problem").findings:
        assert "порог" in f.message and f.recommendation


def test_determinism(db, demo_repos):
    _prep(db, demo_repos)
    a, b = analysis.analyze(db, "problem"), analysis.analyze(db, "problem")
    assert a.mv.rows == b.mv.rows and [f.message for f in a.findings] == [f.message for f in b.findings]


def test_at_least_10_metrics_and_8_rules(db, demo_repos):
    _prep(db, demo_repos)
    r = analysis.analyze(db, "healthy")
    names = {row[0] for row in r.mv.rows}
    assert len(names) >= 10 and len(plugins.RULES) >= 8


def test_metric_values_sane(db, demo_repos):
    _prep(db, demo_repos)
    mv = analysis.analyze(db, "healthy").mv
    assert mv.project("bus_factor") >= 2
    assert 0 <= mv.project("ownership_decay") <= 1 and 0 <= mv.project("change_coupling") <= 1
    assert all(0 <= v <= 100 for v in mv.files("hotspot").values())


def test_time_series_cover_all_weeks(db, demo_repos):
    _prep(db, demo_repos)
    mv = analysis.analyze(db, "healthy").mv
    assert len(mv.series("weekly_churn")) == len(mv.series("weekly_fix_ratio")) >= 19


def test_compare_five_indicators(db, demo_repos):
    _prep(db, demo_repos)
    rows = analysis.compare(db, "healthy", "problem")
    assert len(rows) == 5 and rows[0][1] > rows[0][2]


def test_research_returns_correlations(db, demo_repos):
    _prep(db, demo_repos)
    r = analysis.research(analysis.analyze(db, "problem").mv)
    assert r["n"] > 5 and -1 <= r["spearman"] <= 1


def test_file_plugin_and_broken_plugin(db, demo_repos, tmp_path):
    _prep(db, demo_repos)
    (tmp_path / "good.py").write_text(
        "from projectpulse.plugins import metric\n@metric('x_files')\ndef m(ctx):\n    return [('x_files','project','',len(ctx.files))]\n")
    (tmp_path / "bad.py").write_text("raise RuntimeError('boom')\n")
    r = analysis.analyze(db, "healthy", plugin_dirs=[str(tmp_path)])
    assert r.mv.project("x_files") == 11


def test_custom_threshold_changes_findings(db, demo_repos):
    _prep(db, demo_repos)
    r = analysis.analyze(db, "healthy", thresholds={"coupling": 0.0, "ownership_decay": 0.0})
    assert {"change_coupling"} <= {f.rule for f in r.findings}


def test_timings_recorded(db, demo_repos):
    _prep(db, demo_repos)
    assert analysis.timings(db, "healthy")["full"] is not None


def test_html_report_sections(db, demo_repos):
    _prep(db, demo_repos)
    html = report.build_html(db, analysis.analyze(db, "problem"))
    for s in ("Сводка", "Риски", "Динамика", "Граф", "Рекомендации"):
        assert f"<h2>{s}</h2>" in html
    assert "<svg" in html
