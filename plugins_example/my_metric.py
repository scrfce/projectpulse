"""Пример файлового плагина: python -m projectpulse analyze NAME --plugins plugins_example"""
from projectpulse.plugins import metric, rule
from projectpulse.rules import MEDIUM, Finding


@metric("avg_loc")
def avg_loc(ctx):
    n = len(ctx.files) or 1
    return [("avg_loc", "project", "", sum(f["loc"] for f in ctx.files.values()) / n)]


@rule("big_files")
def big_files(mv, th):
    v = mv.project("avg_loc", 0)
    if v > 400:
        return Finding("big_files", MEDIUM, f"средний размер файла {v:.0f} LOC (порог > 400)",
                       "Разбить крупные модули.", {"avg_loc": v})
