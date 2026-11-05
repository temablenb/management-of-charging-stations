import pytest

from mas.allocation import AllocationInfeasible, allocate_power

LIMIT = 100.0


def alloc(demands, limit=LIMIT, max_powers=None, **kwargs):
    max_powers = max_powers or {station: 100.0 for station in demands}
    return allocate_power(demands, max_powers, limit, **kwargs)


def test_no_deficit_everyone_gets_demand():
    result = alloc({"a": 30.0, "b": 40.0})
    assert result.allocated_kw == {"a": 30.0, "b": 40.0}
    assert not result.deficit


def test_demand_is_capped_by_station_power():
    result = alloc({"a": 150.0}, max_powers={"a": 80.0}, limit=200.0)
    assert result.allocated_kw["a"] == 80.0


def test_deficit_total_equals_limit():
    result = alloc({"a": 80.0, "b": 80.0})
    assert result.deficit
    assert result.total_kw == pytest.approx(LIMIT)


def test_deficit_respects_caps_and_floors():
    demands = {"a": 60.0, "b": 50.0, "c": 40.0}
    result = alloc(demands)
    for station, power in result.allocated_kw.items():
        assert 0.6 * demands[station] - 1e-6 <= power <= demands[station] + 1e-6
    assert result.total_kw == pytest.approx(LIMIT)


def test_infeasible_when_floors_exceed_limit():
    with pytest.raises(AllocationInfeasible):
        alloc({"a": 100.0, "b": 100.0}, limit=100.0)


def test_weights_prefer_heavier_station():
    result = alloc({"a": 80.0, "b": 80.0}, weights={"a": 2.0, "b": 1.0})
    assert result.allocated_kw["a"] == pytest.approx(52.0)
    assert result.allocated_kw["b"] == pytest.approx(48.0)


def test_zero_demand_station_gets_zero():
    result = alloc({"a": 0.0, "b": 150.0}, max_powers={"a": 100.0, "b": 200.0})
    assert result.allocated_kw["a"] == 0.0
    assert result.allocated_kw["b"] == pytest.approx(100.0)


def test_empty_input_gives_empty_result():
    result = allocate_power({}, {}, 100.0)
    assert result.allocated_kw == {}
    assert not result.deficit


def test_mismatched_station_sets_rejected():
    with pytest.raises(ValueError):
        allocate_power({"a": 10.0}, {"b": 100.0}, 100.0)


def test_negative_demand_rejected():
    with pytest.raises(ValueError):
        alloc({"a": -1.0})


def test_negative_limit_rejected():
    with pytest.raises(ValueError):
        alloc({"a": 10.0}, limit=-5.0)


def test_min_share_out_of_range_rejected():
    with pytest.raises(ValueError):
        alloc({"a": 10.0}, min_share=1.5)


def test_non_positive_weight_rejected():
    with pytest.raises(ValueError):
        alloc({"a": 10.0}, weights={"a": 0.0})


def test_non_positive_max_power_rejected():
    with pytest.raises(ValueError):
        allocate_power({"a": 10.0}, {"a": 0.0}, 100.0)