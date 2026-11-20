"""Движок правил риска: 9 правил (3 на трендах). Каждое объясняет, почему сработало."""
from dataclasses import dataclass, field

from .plugins import rule
from .stats import mean, ols_slope

HIGH, MEDIUM, LOW = "high", "medium", "low"
SEV_RANK = {HIGH: 3, MEDIUM: 2, LOW: 1}
PENALTY = {HIGH: 20, MEDIUM: 10, LOW: 4}

DEFAULT_TH = {
    "bus_factor_high": 1,
    "hotspot_max": 80.0, "hotspot_min_files": 8,
    "cc_func_medium": 20, "cc_func_high": 40,
    "cycle_ratio_medium": 0.05,
    "ownership_decay": 0.4,
    "coupling": 0.5,
    "jump_ratio": 3.0, "jump_min_lines": 100,
    "fix_slope": 0.02, "fix_level": 0.25,
    "break_slope": 0.1,
}


@dataclass
class Finding:
    rule: str
    severity: str
    message: str            # почему сработало: значения метрик и пороги
    recommendation: str
    details: dict = field(default_factory=dict)


class MetricView:
    def __init__(self, rows):
        self.rows = rows

    def project(self, name, default=None):
        for n, s, _, v in self.rows:
            if n == name and s == "project":
                return v
        return default

    def files(self, name):
        return {k: v for n, s, k, v in self.rows if n == name and s == "file"}

    def series(self, name):
        return sorted((k, v) for n, s, k, v in self.rows if n == name and s == "series")

    def pairs(self, name="coupling_pair"):
        return [(k, v) for n, s, k, v in self.rows if n == name and s == "pair"]


def _worst(d):
    return max(d.items(), key=lambda kv: (kv[1], kv[0])) if d else ("", 0)


@rule("low_bus_factor")
def r_bus(mv, th):
    b = mv.project("bus_factor")
    if b and b <= th["bus_factor_high"]:
        return Finding("low_bus_factor", HIGH,
                       f"bus factor = {b} (порог ≤ {th['bus_factor_high']}): 50% изменений кода делает {b} чел.",
                       "Распределить знания: парное программирование, ревью, ротация владельцев модулей.",
                       {"bus_factor": b})


@rule("hotspot")
def r_hot(mv, th):
    h, n = mv.project("hotspot_max", 0), mv.project("files_total", 0)
    if n >= th["hotspot_min_files"] and h >= th["hotspot_max"]:
        f, v = _worst(mv.files("hotspot"))
        return Finding("hotspot", MEDIUM, f"hotspot_max = {h:.0f} (порог ≥ {th['hotspot_max']}), файл {f} ({v:.0f}).",
                       f"Приоритетно покрыть тестами и отрефакторить {f}.", {"file": f})


@rule("complex_function")
def r_cc(mv, th):
    c = mv.project("cc_max_func", 0)
    sev = HIGH if c > th["cc_func_high"] else MEDIUM if c > th["cc_func_medium"] else None
    if sev:
        f, _ = _worst(mv.files("cc_max_func"))
        return Finding("complex_function", sev,
                       f"макс. цикломатическая сложность функции = {c} (порог > {th['cc_func_medium']}), файл {f}.",
                       "Разбить функцию на меньшие, убрать вложенные ветвления.", {"file": f})


@rule("import_cycles")
def r_cycles(mv, th):
    r, k = mv.project("cycle_files_ratio", 0), mv.project("cycle_count", 0)
    if k:
        sev = MEDIUM if r >= th["cycle_ratio_medium"] else LOW
        return Finding("import_cycles", sev,
                       f"циклов импорта: {k}, файлов в циклах {r:.0%} (порог для medium ≥ {th['cycle_ratio_medium']:.0%}).",
                       "Разорвать циклы: вынести общий код в отдельный модуль или инвертировать зависимость.",
                       {"cycles": k})


@rule("ownership_decay")
def r_decay(mv, th):
    d = mv.project("ownership_decay", 0)
    if d >= th["ownership_decay"]:
        return Finding("ownership_decay", MEDIUM, f"ownership_decay = {d:.2f} (порог ≥ {th['ownership_decay']}): "
                       "у значительной доли файлов недавно сменился основной автор.",
                       "Провести передачу знаний по затронутым модулям, обновить документацию.", {"value": d})


@rule("change_coupling")
def r_coupling(mv, th):
    c = mv.project("change_coupling", 0)
    if c >= th["coupling"]:
        pairs = mv.pairs()
        return Finding("change_coupling", MEDIUM, f"change_coupling = {c:.2f} (порог ≥ {th['coupling']}), "
                       f"пример пары: {pairs[0][0] if pairs else '-'}.",
                       "Скрытая связность: объединить или явно описать зависимость между файлами.", {"value": c})


# ----- трендовые правила -----
@rule("trend_churn_jump")
def r_jump(mv, th):
    v = [x for _, x in mv.series("weekly_churn")]
    if len(v) < 12:
        return None
    recent, prev = mean(v[-4:]), mean(v[-12:-4])
    if recent >= th["jump_min_lines"] and recent >= th["jump_ratio"] * max(prev, 1):
        return Finding("trend_churn_jump", MEDIUM,
                       f"скачок churn: среднее за 4 последние недели {recent:.0f} строк против {prev:.0f} "
                       f"за предыдущие 8 (порог ×{th['jump_ratio']}, мин. {th['jump_min_lines']}).",
                       "Проверить крупные изменения: ревью, разбиение на небольшие PR.", {"recent": recent, "prev": prev})


@rule("trend_fix_growth")
def r_fix(mv, th):
    v = [x for _, x in mv.series("weekly_fix_ratio")]
    if len(v) < 8:
        return None
    s, lvl = ols_slope(v[-8:]), mean(v[-4:])
    if s >= th["fix_slope"] and lvl >= th["fix_level"]:
        return Finding("trend_fix_growth", HIGH,
                       f"рост доли багфиксов: наклон {s:.3f}/нед (порог ≥ {th['fix_slope']}), "
                       f"уровень за 4 нед {lvl:.0%} (порог ≥ {th['fix_level']:.0%}).",
                       "Усилить тестирование и CI, провести разбор причин дефектов.", {"slope": s, "level": lvl})


@rule("trend_activity_break")
def r_break(mv, th):
    v = [x for _, x in mv.series("weekly_commits")]
    if len(v) < 16:
        return None
    s1, s2 = ols_slope(v[-16:-8]), ols_slope(v[-8:])
    if s1 >= th["break_slope"] and s2 <= -th["break_slope"]:
        return Finding("trend_activity_break", MEDIUM,
                       f"перелом тренда активности: наклон {s1:+.2f} → {s2:+.2f} коммитов/нед (порог ±{th['break_slope']}).",
                       "Выяснить причину спада: выгорание, смена приоритетов, блокеры.", {"s1": s1, "s2": s2})
