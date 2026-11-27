"""Страница «Симуляция» мультиагентной системы."""

import streamlit as st

from mas.cli import apply_overrides
from mas.scenario import ScenarioConfig
from ui.scenarios import available_scenarios, load_by_name

def render_simulation_page() -> None:
    st.subheader("Симуляция мультиагентной системы")
    config = scenario_form()


def scenario_form() -> ScenarioConfig | None:
    """Форма параметров прогона; None, если параметры не прошли проверку."""
    names = list(available_scenarios())
    name = st.selectbox(
        "Сценарий", names,
        index=names.index("default") if "default" in names else 0,
        key="sim_scenario",
    )
    base = load_by_name(name)
    col1, col2, col3, col4 = st.columns(4)
    seed = col1.number_input("Seed", min_value=0, value=int(base.seed), step=1, key=f"sim_seed_{name}")
    days = col2.number_input("Суток", min_value=1, max_value=14, value=int(base.days), step=1, key=f"sim_days_{name}")
    ev_per_day = col3.number_input("Автомобилей в сутки", min_value=0, max_value=500, value=int(base.ev_per_day), step=5, key=f"sim_ev_{name}")
    limit_kw = col4.number_input("Лимит подстанции, кВт", min_value=10.0, value=float(base.substation_limit_kw), step=10.0, key=f"sim_limit_{name}")
    no_storage = st.checkbox(
        "Без накопителя", value=base.storage is None,
        disabled=base.storage is None, key=f"sim_nostorage_{name}",
    )
    try:
        return apply_overrides(
            base, days=int(days), seed=int(seed), ev_per_day=int(ev_per_day),
            limit_kw=float(limit_kw), no_storage=bool(no_storage),
        )
    except ValueError as error:
        st.error(str(error))
        return None