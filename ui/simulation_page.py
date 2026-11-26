"""Страница «Симуляция» мультиагентной системы."""

import streamlit as st


def render_simulation_page() -> None:
    st.subheader("Симуляция мультиагентной системы")
    st.info("Здесь появятся запуск сценариев и сравнение с базовым.")