import pytest

from ui.scenarios import available_scenarios, load_by_name


def test_lists_known_scenarios():
    names = set(available_scenarios())
    assert {"default", "evening_peak", "reduced_limit", "many_ev"} <= names


def test_models_file_is_not_a_scenario():
    assert "ev_models" not in available_scenarios()


def test_load_by_name_returns_config():
    assert load_by_name("default").days >= 1


def test_unknown_name_raises():
    with pytest.raises(KeyError):
        load_by_name("нет_такого")