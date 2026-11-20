"""Статистика вручную (без scipy/numpy)."""
import math


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def pearson(xs, ys):
    n = len(xs)
    if n != len(ys) or n < 2:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def ranks(xs):
    """Средние ранги (учёт связок)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    return pearson(ranks(xs), ranks(ys))


def ols_slope(ys):
    """Наклон МНК по равноотстоящим точкам."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = mean(ys)
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (y - my) for i, y in enumerate(ys)) / den


def percentile_ranks(values):
    """Ранг в [0,1] для каждого значения (0 — минимум, 1 — максимум)."""
    if len(values) < 2:
        return [1.0] * len(values)
    r = ranks(values)
    return [(x - 1) / (len(values) - 1) for x in r]
