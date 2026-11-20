"""Плагины: метрики и правила риска. Реестр + entry points + загрузка из файлов."""
import importlib.metadata
import importlib.util
import logging
import os

log = logging.getLogger("projectpulse.plugins")
METRICS, RULES = {}, {}
EP_METRICS, EP_RULES = "projectpulse.metrics", "projectpulse.rules"


def metric(name):
    """Декоратор. fn(ctx) -> [(metric_name, scope, key, value)], scope: file|project|series|pair."""
    def deco(fn):
        METRICS[name] = fn
        return fn
    return deco


def rule(name):
    """Декоратор. fn(metric_view, thresholds) -> Finding | [Finding] | None."""
    def deco(fn):
        RULES[name] = fn
        return fn
    return deco


def load_all(plugin_dirs=()):
    """Подгружает внешние плагины; сломанный плагин не валит анализ."""
    try:
        eps = importlib.metadata.entry_points()
        for group in (EP_METRICS, EP_RULES):
            for ep in eps.select(group=group):
                try:
                    ep.load()
                except Exception:
                    log.exception("плагин %s не загрузился", ep.name)
    except Exception:
        log.exception("entry points недоступны")
    for d in plugin_dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".py") and not fn.startswith("_"):
                try:
                    spec = importlib.util.spec_from_file_location(f"pp_plugin_{fn[:-3]}", os.path.join(d, fn))
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                except Exception:
                    log.exception("плагин-файл %s не загрузился", fn)
