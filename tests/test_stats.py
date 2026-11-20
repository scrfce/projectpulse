import math

from hypothesis import given, strategies as st

from projectpulse.stats import ols_slope, pearson, percentile_ranks, ranks, spearman

lists = st.lists(st.integers(-1000, 1000), min_size=3, max_size=40)


def test_pearson_perfect():
    assert pearson([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert pearson([1, 2, 3], [3, 2, 1]) == -1.0


def test_pearson_constant_is_nan():
    assert math.isnan(pearson([1, 1, 1], [1, 2, 3]))


def test_ranks_ties():
    assert ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_monotone_nonlinear():
    xs = [1, 2, 3, 4, 5]
    assert abs(spearman(xs, [x ** 3 for x in xs]) - 1.0) < 1e-12


def test_ols_slope():
    assert abs(ols_slope([1, 3, 5, 7]) - 2.0) < 1e-12
    assert ols_slope([5]) == 0.0


def test_percentile_ranks_bounds():
    r = percentile_ranks([5, 1, 9])
    assert r == [0.5, 0.0, 1.0]


@given(lists, lists)
def test_prop_correlation_in_range(xs, ys):
    n = min(len(xs), len(ys))
    for f in (pearson, spearman):
        v = f(xs[:n], ys[:n])
        assert math.isnan(v) or -1.0 <= v <= 1.0


@given(lists, lists)
def test_prop_symmetry(xs, ys):
    n = min(len(xs), len(ys))
    a, b = spearman(xs[:n], ys[:n]), spearman(ys[:n], xs[:n])
    assert (math.isnan(a) and math.isnan(b)) or abs(a - b) < 1e-9


@given(lists, lists)
def test_prop_spearman_invariant_to_monotone_transform(xs, ys):
    n = min(len(xs), len(ys))
    a = spearman(xs[:n], ys[:n])
    b = spearman([x ** 3 + 7 * x for x in xs[:n]], ys[:n])     # x^3+7x строго возрастает
    assert (math.isnan(a) and math.isnan(b)) or abs(a - b) < 1e-9
