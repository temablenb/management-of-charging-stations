import sqlite3
import streamlit as st
from database import (
    init_schema, init_logs_table, init_accounts_table
)
from data_generator import generate_synthetic_data
from auth import (
    init_users_table
)
from ui.auth_screen import render_auth_screen
from ui.helpers import restore_session
from ui.legacy.admin_panel import render_admin_interface
from ui.legacy.user_cabinet import render_user_cabinet

_original_connect = sqlite3.connect


def _patched_connect(*args, **kwargs):
    kwargs.setdefault('timeout', 15)
    kwargs.setdefault('isolation_level', None)
    conn = _original_connect(*args, **kwargs)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
    except:
        pass
    return conn


sqlite3.connect = _patched_connect

st.set_page_config(
    page_title="Система оптимизации сети ЭЗС",
    layout="wide",
    page_icon=""
)

init_schema()
init_users_table()
init_logs_table()
init_accounts_table()
generate_synthetic_data()

for key, default in [
    ("logged_in", False),
    ("current_user", None),
    ("selected_station", 1),
]:
    if key not in st.session_state:
        st.session_state[key] = default

restore_session()

if not st.session_state.logged_in:
    render_auth_screen()
else:
    user = st.session_state.current_user
    if user and user.get('role') == 'admin':
        render_admin_interface()
    else:
        render_user_cabinet()