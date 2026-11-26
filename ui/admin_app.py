"""Интерфейс администратора: симуляция и прежняя панель сети."""

import streamlit as st

from ui.helpers import clear_session
from ui.legacy.admin_panel import render_admin_interface
from ui.navigation import SECTION_SIMULATION, choose_admin_section
from ui.simulation_page import render_simulation_page


def render_admin_app() -> None:
    section = choose_admin_section()
    st.divider()
    if section == SECTION_SIMULATION:
        if st.button("Выйти", key="sim_logout"):
            clear_session()
            st.rerun()
        render_simulation_page()
    else:
        render_admin_interface()