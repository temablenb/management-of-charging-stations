"""Навигация панели администратора."""

import streamlit as st

SECTION_SIMULATION = "Симуляция"
SECTION_NETWORK = "Сеть ЭЗС"
ADMIN_SECTIONS = (SECTION_SIMULATION, SECTION_NETWORK)


def choose_admin_section() -> str:
    """Верхний переключатель разделов администратора."""
    return st.radio(
        "Раздел", ADMIN_SECTIONS, horizontal=True,
        key="admin_section", label_visibility="collapsed",
    )