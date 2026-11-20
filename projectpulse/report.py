"""Экспорт отчёта одним HTML-файлом: Сводка / Риски / Динамика / Граф / Рекомендации."""
import html
from string import Template

from . import graph
from .analysis import timings

PAGE = Template("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ProjectPulse: $repo</title>
<style>body{font-family:sans-serif;max-width:900px;margin:2em auto;padding:0 1em}
.score{font-size:3em;font-weight:bold}.high{color:#c0392b}.medium{color:#d68910}.low{color:#2874a6}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}svg{background:#fafafa;border:1px solid #ddd}</style>
</head><body><h1>ProjectPulse: $repo</h1>
<h2>Сводка</h2><p class="score">$health / 100</p>$summary
<h2>Риски</h2>$risks
<h2>Динамика</h2>$dynamics
<h2>Граф</h2>$graph
<h2>Рекомендации</h2>$recs
</body></html>""")


def _spark(values, title, w=600, h=100):
    if not values:
        return ""
    mx = max(values) or 1
    step = w / max(len(values) - 1, 1)
    pts = " ".join(f"{i * step:.1f},{h - 5 - v / mx * (h - 10):.1f}" for i, v in enumerate(values))
    return f"<p>{html.escape(title)} (макс. {mx:.2f})</p><svg width='{w}' height='{h}'><polyline fill='none' stroke='#2874a6' points='{pts}'/></svg>"


def build_html(db, res):
    mv, e = res.mv, html.escape
    summ = [("Коммитов", mv.project("commits_total")), ("Авторов", mv.project("authors")),
            ("Файлов .py", mv.project("files_total")), ("LOC", mv.project("loc_total")),
            ("Bus factor", mv.project("bus_factor")), ("Доля багфиксов", f"{mv.project('fix_ratio', 0):.0%}")]
    t = timings(db, res.repo)
    for mode, label in (("full", "Полная индексация"), ("incremental", "Инкрементальная")):
        if t[mode]:
            summ.append((label, f"{t[mode][0]:.2f} с ({t[mode][1]} коммитов)"))
    summary = "<table>" + "".join(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>" for k, v in summ) + "</table>"
    risks = "<ul>" + "".join(f"<li class='{f.severity}'><b>[{f.severity}] {e(f.rule)}</b>: {e(f.message)}</li>"
                             for f in res.findings) + "</ul>" if res.findings else "<p>Рисков не выявлено.</p>"
    dyn = "".join(_spark([v for _, v in mv.series(n)], n) for n in ("weekly_commits", "weekly_churn", "weekly_fix_ratio"))
    vs = graph.versions(db, res.repo)
    g = ""
    if vs:
        rows = "".join(f"<tr><td>{e(h[:8])}</td><td>{n}</td><td>{m}</td></tr>" for _, h, _, n, m in vs)
        g = f"<p>Версии графа (срезы по коммитам):</p><table><tr><th>commit</th><th>узлов</th><th>рёбер</th></tr>{rows}</table>"
        edges = graph.load_edges(db, vs[-1][0], "file")
        deg = {}
        for s, d, _ in edges:
            deg[d] = deg.get(d, 0) + 1
        top = sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        g += "<p>Самые зависимые модули (входящие связи): " + e(", ".join(f"{k} ({v})" for k, v in top)) + "</p>"
        g += f"<p>Циклов импорта: {mv.project('cycle_count', 0):.0f}</p>"
    recs = "<ol>" + "".join(f"<li>{e(f.recommendation)}</li>" for f in res.findings) + "</ol>"
    return PAGE.substitute(repo=e(res.repo), health=res.health, summary=summary, risks=risks,
                           dynamics=dyn, graph=g, recs=recs)
