import sqlite3
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta
import pydeck as pdk
from database import (
    init_schema, get_history, get_forecasts, get_tariffs,
    get_stations_info, update_station_load_from_sessions, get_user_by_id,
    init_logs_table, get_logs, get_system_stats, add_log,
    get_ev_models, add_custom_ev_model, set_station_active,
    init_accounts_table, get_user_balance, update_user_balance,
    get_user_transactions, get_user_connector_type, retrain_forecasts_for_stations
)
from data_generator import generate_synthetic_data
from ml_forecast import train_and_predict_station
from optimizer import optimize_load, get_expected_peak_load, get_current_station_loads
from session_store import save_session_to_disk, load_session_from_disk, clear_session_from_disk
from auth import (
    init_users_table, login_user, register_user,
    get_user_sessions, get_favorite_stations, toggle_favorite,
    update_user_profile, get_all_users,
    start_charging_session, finish_charging_session,
    get_user_active_session, get_active_sessions
)
from config import (
    SUBSTATION_LIMIT_KW, BASE_TARIFF_RUB, DB_PATH,
    MAP_CENTER_LAT, MAP_CENTER_LON, MAP_ZOOM
)

EV_PLACEHOLDER = "— Выбрать из списка —"
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


def restore_session():
    if st.session_state.get("logged_in"):
        return
    data = load_session_from_disk()
    if not data:
        return
    try:
        role = data.get("role", "user")
        if role == "admin":
            st.session_state.logged_in = True
            st.session_state.current_user = {
                "id": 0, "username": "admin", "role": "admin"
            }
        else:
            user = get_user_by_id(int(data["id"]))
            if user:
                st.session_state.logged_in = True
                st.session_state.current_user = user
            else:
                clear_session_from_disk()
    except Exception:
        clear_session_from_disk()


def save_session(user: dict):
    save_session_to_disk(user)


def clear_session():
    clear_session_from_disk()
    st.session_state.logged_in = False
    st.session_state.current_user = None


restore_session()


def get_status_color(ratio, is_active=True):
    if not is_active:
        return [128, 128, 128]
    if ratio < 0.4:
        return [40, 167, 69]
    elif ratio < 0.7:
        return [255, 193, 7]
    else:
        return [220, 53, 69]


def get_current_load_data():
    stations_df = get_stations_info()
    hist = get_history()
    tariffs = get_tariffs()

    if not hist.empty:
        hist["timestamp"] = pd.to_datetime(hist["timestamp"])
        hist_latest = hist.sort_values("timestamp").groupby("station_id").last().reset_index()
        hist_data = hist_latest[["station_id", "load_kw"]].copy()
    else:
        hist_data = pd.DataFrame(columns=["station_id", "load_kw"])

    if not tariffs.empty:
        tariffs["timestamp"] = pd.to_datetime(tariffs["timestamp"])
        tariff_latest = tariffs.sort_values("timestamp").groupby("station_id").last().reset_index()
        tariff_data = tariff_latest[["station_id", "tariff_multiplier", "new_price"]].copy()
        source = "optimization"
    else:
        tariff_data = pd.DataFrame(columns=["station_id", "tariff_multiplier", "new_price"])
        source = "history"

    merged = stations_df.merge(hist_data, left_on="id", right_on="station_id", how="left")

    if not tariff_data.empty:
        merged = merged.merge(tariff_data, left_on="id", right_on="station_id", how="left", suffixes=('', '_t'))

    merged['load_kw'] = merged['load_kw'].fillna(0)
    merged['multiplier'] = merged.get('tariff_multiplier', pd.Series([1.0] * len(merged))).fillna(1.0)
    merged['price'] = merged.get('new_price', pd.Series([BASE_TARIFF_RUB] * len(merged))).fillna(BASE_TARIFF_RUB)

    if 'tariff_multiplier' in merged.columns:
        merged['multiplier'] = merged['tariff_multiplier'].fillna(1.0)
    if 'new_price' in merged.columns:
        merged['price'] = merged['new_price'].fillna(BASE_TARIFF_RUB)

    return merged, stations_df, source


def get_best_station(load_data: pd.DataFrame, active_counts: dict, user_connector: str = None) -> dict | None:
    if load_data is None or load_data.empty:
        return None
    candidates = []
    max_price = load_data['price'].max() or BASE_TARIFF_RUB

    for _, row in load_data.iterrows():
        sid = int(row['id'])
        if not row.get('is_active', True):
            continue
        station_connector = row.get('connector_type', 'CCS')
        if user_connector and station_connector and user_connector != station_connector:
            continue
        slots_left = 5 - active_counts.get(sid, 0)
        if slots_left <= 0:
            continue
        ratio = row['load_kw'] / row['max_power_kw'] if row['max_power_kw'] > 0 else 0
        price_norm = row['price'] / max_price if max_price > 0 else 1.0
        score = (1 - ratio) * 0.5 + (1 - price_norm) * 0.3 + (slots_left / 5) * 0.2
        candidates.append({
            "id": sid,
            "name": row['name'],
            "location": row['location'],
            "price": row['price'],
            "ratio": ratio,
            "slots_left": slots_left,
            "score": score
        })

    if not candidates:
        return None
    return max(candidates, key=lambda x: x['score'])


def render_map(load_data):
    if load_data is None:
        st.info("Нет данных для отображения")
        return

    load_data = load_data.copy()
    load_data['ratio'] = load_data.apply(
        lambda row: row['load_kw'] / row['max_power_kw'] if row['max_power_kw'] > 0 else 0, axis=1
    )
    load_data['load_kw_str'] = load_data['load_kw'].apply(lambda x: f"{x:.1f}")
    load_data['ratio_str'] = load_data['ratio'].apply(lambda x: f"{x:.0%}")
    load_data['multiplier_str'] = load_data['multiplier'].apply(lambda x: f"{x:.2f}")
    load_data['price_str'] = load_data['price'].apply(lambda x: f"{x:.1f}")
    load_data['color'] = load_data.apply(
        lambda row: get_status_color(row['ratio'], row.get('is_active', True)), axis=1
    )

    tooltip = {
        "html": """
        <div style="padding:10px;background:white;border-radius:5px;min-width:250px;color:black;">
            <b>{name}</b><br/>
            <small>Адрес: {location}</small><br/>
            <hr style="margin:8px 0;"/>
            <small>Нагрузка: {load_kw_str} кВт / {max_power_kw} кВт</small><br/>
            <small>Загрузка: {ratio_str}</small><br/>
            <small>Тариф: {multiplier_str}x ({price_str} руб/кВт·ч)</small><br/>
            <small>Статус: {status_text}</small><br/>
            <small>Разъём: {connector_type}</small>
        </div>""",
        "style": {"backgroundColor": "transparent", "color": "black"}
    }

    load_data['status_text'] = load_data.apply(
        lambda row: "Отключена" if not row.get('is_active', True) else "Активна", axis=1
    )
    load_data['connector_type'] = load_data.get('connector_type', pd.Series(['CCS'] * len(load_data))).fillna('CCS')

    scatter_layer = pdk.Layer(
        "ScatterplotLayer", data=load_data,
        get_position="[lon, lat]", get_radius=200,
        get_fill_color="color", get_line_color=[255, 255, 255],
        get_line_width=2, pickable=True, auto_highlight=True,
        radius_min_pixels=15, radius_max_pixels=50,
    )

    deck_map = pdk.Deck(
        layers=[scatter_layer],
        initial_view_state=pdk.ViewState(latitude=MAP_CENTER_LAT, longitude=MAP_CENTER_LON, zoom=MAP_ZOOM, pitch=0),
        tooltip=tooltip,
        map_style="mapbox://styles/mapbox/satellite-streets-v12",
        map_provider="mapbox"
    )
    st.pydeck_chart(deck_map)


def calculate_total_load():
    load_df = get_current_station_loads()
    if load_df is None or load_df.empty:
        return 0.0, "none"
    active_load = load_df[load_df.get('is_active', True) == True]['current_load'].sum()
    return active_load, "optimization"


def do_optimize():
    try:
        optimize_load()
        from database import get_stations_info, retrain_forecasts_for_stations
        stations = get_stations_info()
        retrained = retrain_forecasts_for_stations(stations['id'].tolist(), min_hours_since_retrain=12)
        if retrained:
            add_log("SYSTEM", f"Переобучены прогнозы для {len(retrained)} станций",
                   f"Станции: {retrained}")
    except Exception as e:
        print(f"[optimize] {e}")


def render_auth_screen():
    st.markdown("""
    <div style="text-align:center; padding: 40px 0 20px 0;">
        <h2>Система управления сетью зарядных станций</h2>
        <p style="color:gray;">Оптимизация сети зарядных станций для электротранспорта</p>
    </div>
    """, unsafe_allow_html=True)

    col_left, col_center, col_right = st.columns([1, 1.2, 1])
    with col_center:
        tab_login, tab_register = st.tabs(["Вход", "Регистрация"])

        with tab_login:
            username = st.text_input("Логин", key="login_username", placeholder="Введите логин")
            password = st.text_input("Пароль", type="password", key="login_password", placeholder="Введите пароль")

            if st.button("Войти", type="primary", use_container_width=True, key="btn_login"):
                if not username or not password:
                    st.error("Заполните все поля")
                else:
                    ok, msg, user = login_user(username, password)
                    if ok:
                        st.session_state.logged_in = True
                        st.session_state.current_user = user
                        save_session(user)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_register:
            reg_username = st.text_input("Логин", key="reg_username", placeholder="Придумайте логин")
            reg_password = st.text_input("Пароль", type="password", key="reg_password", placeholder="Минимум 4 символа")
            reg_password2 = st.text_input("Повторите пароль", type="password", key="reg_password2")
            reg_email = st.text_input("Email", key="reg_email", placeholder="Необязательно")

            ev_df = get_ev_models()
            ev_options = [EV_PLACEHOLDER] + [
                f"{r['brand']} {r['model']} ({r['battery_kwh']} кВт·ч, {r['connector_type']})" for _, r in ev_df.iterrows()
            ] + ["Добавить свой автомобиль"]

            reg_ev = st.selectbox("Электромобиль", options=ev_options, key="reg_ev")

            custom_ev_data = None
            ev_model_id_to_save = None

            if reg_ev == "Добавить свой автомобиль":
                st.markdown("**Данные вашего автомобиля:**")
                c1, c2 = st.columns(2)
                custom_brand = c1.text_input("Марка", key="custom_brand")
                custom_model = c2.text_input("Модель", key="custom_model")
                c3, c4 = st.columns(2)
                custom_battery = c3.number_input("Ёмкость батареи (кВт·ч)", 10.0, 200.0, 60.0, key="custom_battery")
                custom_power = c4.number_input("Макс. зарядка (кВт)", 3.0, 350.0, 50.0, key="custom_power")
                custom_connector = st.selectbox("Тип разъёма", ["CCS", "CHAdeMO", "Type2", "GB/T"], key="custom_conn")
                custom_ev_data = {
                    "brand": custom_brand, "model": custom_model,
                    "battery_kwh": custom_battery, "max_charge_kw": custom_power,
                    "connector_type": custom_connector
                }
            else:
                if reg_ev != EV_PLACEHOLDER:
                    selected_row = ev_df[ev_df.apply(lambda r: f"{r['brand']} {r['model']} ({r['battery_kwh']} кВт·ч, {r['connector_type']})",
                                                     axis=1) == reg_ev]
                    if not selected_row.empty:
                        ev_model_id_to_save = int(selected_row.iloc[0]['id'])

            if st.button("Зарегистрироваться", type="primary", use_container_width=True, key="btn_register"):
                if not reg_username or not reg_password:
                    st.error("Логин и пароль обязательны")
                elif len(reg_password) < 4:
                    st.error("Пароль слишком короткий (минимум 4 символа)")
                elif reg_password != reg_password2:
                    st.error("Пароли не совпадают")
                elif reg_ev == EV_PLACEHOLDER and custom_ev_data is None:
                    st.error("Пожалуйста, выберите электромобиль из списка или добавьте свой.")
                else:
                    final_ev_model_id = ev_model_id_to_save
                    if custom_ev_data is not None:
                        if not custom_ev_data['brand'] or not custom_ev_data['model']:
                            st.error("Укажите марку и модель автомобиля.")
                        else:
                            final_ev_model_id = add_custom_ev_model(
                                custom_ev_data['brand'], custom_ev_data['model'],
                                custom_ev_data['battery_kwh'],
                                custom_ev_data['max_charge_kw'], custom_ev_data['connector_type']
                            )

                    if final_ev_model_id and final_ev_model_id > 0:
                        ok, msg = register_user(reg_username, reg_password, reg_email, ev_model_id=final_ev_model_id)
                        if ok:
                            st.success(msg + " Теперь войдите в систему.")
                        else:
                            st.error(msg)
                    else:
                        st.error("Не удалось сохранить автомобиль. Проверьте данные.")


def render_user_cabinet():
    user = st.session_state.current_user

    balance = get_user_balance(user['id'])
    user_connector = get_user_connector_type(user['id'])

    col_title, col_balance, col_logout = st.columns([3, 2, 1])
    with col_title:
        st.title("Система управления сетью ЭЗС")
    with col_balance:
        if balance < 100:
            st.error(f"Баланс: {balance:.2f} руб (недостаточно)")
        elif balance < 500:
            st.warning(f"Баланс: {balance:.2f} руб")
        else:
            st.success(f"Баланс: {balance:.2f} руб")

        if st.button("Пополнить счёт", key="topup_btn", use_container_width=True):
            st.session_state.show_topup = True

    with col_logout:
        st.write(f"**{user['username']}**")
        if user_connector:
            st.caption(f"Разъём: {user_connector}")
        if st.button("Выйти", key="user_logout", use_container_width=True):
            clear_session()
            st.rerun()

    if st.session_state.get("show_topup"):
        with st.form("topup_form"):
            st.subheader("Пополнение счёта")
            amount = st.number_input("Сумма (руб)", min_value=100, max_value=10000,
                                     value=500, step=100)
            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Пополнить", type="primary",
                                         use_container_width=True):
                    msg = ""
                    success = False
                    try:
                        success, msg = update_user_balance(
                            user['id'], amount, "topup",
                            f"Пополнение счёта на {amount} руб"
                        )
                    except Exception as e:
                        msg = f"Ошибка при пополнении: {e}"
                        success = False

                    if success:
                        st.success(msg)
                        st.session_state.show_topup = False
                        st.rerun()
                    else:
                        st.error(msg)
            with col2:
                if st.form_submit_button("Отмена", use_container_width=True):
                    st.session_state.show_topup = False
                    st.rerun()
        st.divider()

    st.divider()

    section = st.radio(
        "Навигация",
        ["Карта и станции", "Избранное", "История зарядок", "Профиль"],
        horizontal=True,
        label_visibility="collapsed"
    )

    st.divider()

    if section == "Карта и станции":
        load_data, stations_df, source = get_current_load_data()
        active_session = get_user_active_session(user['id'])
        active_all = get_active_sessions()
        active_counts = {}
        if not active_all.empty:
            active_counts = active_all.groupby('station_id').size().to_dict()

        ev_battery_default = 60.0
        ev_max_charge_default = 50.0
        ev_model_id = user.get('ev_model_id')
        if not ev_model_id:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute("SELECT ev_model_id FROM users WHERE id=?", (user['id'],)).fetchone()
                if row and row[0]:
                    ev_model_id = row[0]

        if ev_model_id:
            ev_df_user = get_ev_models()
            ev_row = ev_df_user[ev_df_user['id'] == ev_model_id]
            if not ev_row.empty:
                ev_battery_default = float(ev_row.iloc[0]['battery_kwh'])
                ev_max_charge_default = float(ev_row.iloc[0]['max_charge_kw'])
                st.caption(
                    f"Ваш автомобиль: {ev_row.iloc[0]['brand']} {ev_row.iloc[0]['model']} · {ev_battery_default} кВт·ч · макс. {ev_max_charge_default} кВт · разъём {ev_row.iloc[0]['connector_type']}")

        if active_session:
            st.warning(
                f"Активная сессия: станция {active_session['station_name']} (начало: {active_session['start_time']})")

        if not active_session and load_data is not None:
            best = get_best_station(load_data, active_counts, user_connector)
            if best:
                st.info(
                    f"Рекомендуется: {best['name']} — {best['price']:.2f} руб/кВт·ч, свободно {best['slots_left']}/5 мест, загрузка {best['ratio']:.0%}")
            elif user_connector:
                st.info(f"Станции с разъёмом {user_connector} сейчас недоступны. Попробуйте позже.")

        total_load, _ = calculate_total_load()
        if total_load > SUBSTATION_LIMIT_KW * 0.85:
            st.error(
                f"Высокая нагрузка на сеть: {total_load:.0f} кВт из {SUBSTATION_LIMIT_KW:.0f} кВт. Скорость зарядки может быть снижена.")

        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("Карта станций")
            render_map(load_data)

        with col2:
            st.subheader("Текущие тарифы")
            tariffs = get_tariffs()
            if tariffs.empty:
                st.write(f"Базовый тариф: {BASE_TARIFF_RUB} руб/кВт·ч")
            else:
                tariffs["timestamp"] = pd.to_datetime(tariffs["timestamp"])
                latest = tariffs.sort_values("timestamp").groupby("station_id").last().reset_index()
                sdf = get_stations_info()
                display_df = latest.merge(sdf[['id', 'name']], left_on="station_id", right_on="id")
                for _, row in display_df.iterrows():
                    st.write(f"**{row['name']}** — {row['new_price']:.2f} руб/кВт·ч")

        st.divider()
        st.subheader("Станции зарядки")

        if load_data is not None:
            load_data = load_data.copy()
            load_data['ratio'] = load_data.apply(
                lambda row: row['load_kw'] / row['max_power_kw'] if row['max_power_kw'] > 0 else 0, axis=1)
            favs = get_favorite_stations(user['id'])
            fav_ids = set(favs['id'].tolist()) if not favs.empty else set()

            tariffs_df = get_tariffs()
            planned_loads = {}
            if not tariffs_df.empty:
                tariffs_df["timestamp"] = pd.to_datetime(tariffs_df["timestamp"])
                latest_t = tariffs_df.sort_values("timestamp").groupby("station_id").last()
                planned_loads = latest_t['planned_load_kw'].to_dict()

            def sort_key(row):
                sid = int(row['id'])
                if active_session and active_session['station_id'] == sid:
                    return 0
                if sid in fav_ids:
                    return 1
                return 2

            load_data['_sort'] = load_data.apply(sort_key, axis=1)
            load_data = load_data.sort_values('_sort').drop(columns='_sort')

            for _, row in load_data.iterrows():
                sid = int(row['id'])
                is_active = row.get('is_active', True)
                active_count = active_counts.get(sid, 0)
                slots_left = 5 - active_count if is_active else 0
                is_full = slots_left <= 0
                is_active_station = active_session and active_session['station_id'] == sid
                is_fav = sid in fav_ids
                ratio = row['ratio']
                station_connector = row.get('connector_type', 'CCS')

                is_compatible = True
                connector_warning = ""
                if user_connector and station_connector:
                    if user_connector != station_connector:
                        is_compatible = False
                        connector_warning = f"Несовместимый разъём (ваш: {user_connector}, станция: {station_connector})"

                if not is_active:
                    status_icon = "X"
                    slots_label = "Станция отключена"
                elif not is_compatible:
                    status_icon = "!"
                    slots_label = "Несовместимый разъём"
                elif is_active_station:
                    status_icon = ">>"
                    slots_label = "Активная зарядка"
                elif is_fav:
                    status_icon = "*"
                    slots_label = f"{slots_left}/5 мест свободно"
                elif is_full:
                    status_icon = "X"
                    slots_label = "Заполнена"
                elif ratio > 0.7:
                    status_icon = "~"
                    slots_label = f"{slots_left}/5 мест свободно"
                else:
                    status_icon = "✓"
                    slots_label = f"{slots_left}/5 мест свободно"

                expander_label = f"[{status_icon}] {row['name']}  ·  {row['price']:.2f} руб/кВт·ч  ·  {slots_label}"

                with st.expander(expander_label, expanded=bool(is_active_station)):
                    info_cols = st.columns([2, 1, 1, 1])
                    info_cols[0].caption(f"Адрес: {row['location']} · Разъём: {station_connector}")
                    info_cols[1].metric("Макс. мощность", f"{row['max_power_kw']:.0f} кВт")
                    info_cols[2].metric("Тариф", f"{row['price']:.2f} руб")
                    info_cols[3].metric("Свободно", f"{slots_left}/5" if is_active else "—")

                    if is_active:
                        st.progress(min(ratio, 1.0), text=f"Нагрузка: {ratio:.0%}")
                    else:
                        st.error("Станция временно отключена администратором")

                    if not is_active:
                        st.warning("На этой станции нельзя начать зарядку")
                    elif not is_compatible:
                        st.warning(connector_warning)
                        st.info("Выберите станцию с совместимым разъёмом")
                    elif is_full:
                        st.error("Станция заполнена — все 5 мест заняты.")
                    elif ratio > 0.8:
                        st.warning("Высокая загрузка. Скорость зарядки может быть снижена.")

                    fc_df = get_forecasts(sid)
                    peak_hours_info = ""
                    if not fc_df.empty and is_active:
                        fc_df["timestamp"] = pd.to_datetime(fc_df["timestamp"])
                        latest_fc = fc_df.sort_values("created_at").iloc[-1]
                        fc_subset = fc_df[fc_df["created_at"] == latest_fc["created_at"]]
                        avg_load = fc_subset["predicted_load_kw"].mean()
                        peak_hours = fc_subset[fc_subset["predicted_load_kw"] > avg_load * 1.3][
                            "timestamp"].dt.hour.tolist()
                        if peak_hours:
                            peak_hours_info = f"Ожидаемый пик: {', '.join(f'{h}:00' for h in sorted(set(peak_hours))[:3])}"
                            st.caption(peak_hours_info)

                    if sid in planned_loads and row['load_kw'] > planned_loads[sid] * 1.1 and is_active:
                        st.warning(
                            f"Текущая нагрузка ({row['load_kw']:.1f} кВт) превышает план ({planned_loads[sid]:.1f} кВт).")

                    if is_active and is_compatible:
                        st.markdown("**Калькулятор стоимости зарядки**")
                        calc_col1, calc_col2, calc_col3 = st.columns(3)

                        calc_col1.metric("Ёмкость батареи", f"{ev_battery_default:.0f} кВт·ч")
                        current_soc = calc_col2.number_input("Текущий заряд (%)", min_value=0, max_value=99, value=20,
                                                             step=5, key=f"calc_soc_{sid}")
                        target_soc = calc_col3.number_input("Необходимый заряд (%)", min_value=1, max_value=100, value=80,
                                                            step=5, key=f"calc_target_{sid}")

                        needed_kwh = ev_battery_default * (target_soc - current_soc) / 100
                        if needed_kwh > 0:
                            est_cost = needed_kwh * row['price']
                            station_share = row['max_power_kw'] / max(active_count + 1, 1)
                            charge_power = min(station_share, ev_max_charge_default)
                            est_minutes = (needed_kwh / charge_power * 60) if charge_power > 0 else 0
                            st.info(
                                f"Нужно: {needed_kwh:.1f} кВт·ч · Стоимость: {est_cost:.2f} руб · Время: {est_minutes:.0f} мин")

                        col_fav, col_charge = st.columns(2)
                        with col_fav:
                            fav_label = "Убрать из избранного" if sid in fav_ids else "В избранное"
                            if st.button(fav_label, key=f"fav_{sid}", use_container_width=True):
                                toggle_favorite(user['id'], sid)
                                st.rerun()

                        with col_charge:
                            if active_session and active_session['station_id'] == sid:
                                if st.button("Завершить зарядку", key=f"stop_{sid}", type="primary", use_container_width=True):
                                    st.session_state[f"show_finish_{sid}"] = True

                                if st.session_state.get(f"show_finish_{sid}"):
                                    with st.form(key=f"finish_form_{sid}"):
                                        energy = st.number_input("Заряжено (кВт·ч)", min_value=0.1, max_value=200.0,
                                                                 value=20.0, step=0.5)
                                        if st.form_submit_button("Подтвердить", type="primary"):
                                            msg = ""
                                            ok = False
                                            try:
                                                ok, msg = finish_charging_session(active_session['id'], energy)
                                            except Exception as e:
                                                msg = f"Ошибка при завершении зарядки: {e}"
                                                ok = False

                                            if ok:
                                                update_station_load_from_sessions()
                                                do_optimize()
                                                st.session_state[f"show_finish_{sid}"] = False
                                                st.success(msg)
                                                st.rerun()
                                            else:
                                                st.error(msg)
                            elif active_session:
                                st.button("Начать зарядку", key=f"charge_{sid}", disabled=True, use_container_width=True)
                            elif not is_full:
                                if st.button("Начать зарядку", key=f"charge_{sid}", type="primary", use_container_width=True):
                                    ok, msg, session_id = start_charging_session(user['id'], sid, row['price'])
                                    if ok:
                                        update_station_load_from_sessions()
                                        retrained = retrain_forecasts_for_stations([sid], min_hours_since_retrain=3)
                                        if retrained:
                                            add_log("SYSTEM", f"Переобучен прогноз для станции после начала зарядки",
                                                    f"Станция ID: {sid}")
                                        do_optimize()
                                        st.success(msg)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                            else:
                                st.button("Начать зарядку", key=f"charge_{sid}", disabled=True, use_container_width=True)
                    else:
                        st.button("Начать зарядку", key=f"charge_{sid}", disabled=True, use_container_width=True)
                        if not is_active:
                            st.caption("Станция отключена — зарядка недоступна")
                        elif not is_compatible:
                            st.caption(connector_warning)

    elif section == "Избранное":
        st.subheader("Избранные станции")
        favs = get_favorite_stations(user['id'])
        if favs.empty:
            st.info("У вас пока нет избранных станций.")
        else:
            tariffs = get_tariffs()
            active_all = get_active_sessions()
            active_counts_fav = active_all.groupby('station_id').size().to_dict() if not active_all.empty else {}

            for _, fav in favs.iterrows():
                price = BASE_TARIFF_RUB
                if not tariffs.empty:
                    tariffs["timestamp"] = pd.to_datetime(tariffs["timestamp"])
                    t_latest = tariffs[tariffs['station_id'] == fav['id']].sort_values("timestamp")
                    if not t_latest.empty:
                        price = t_latest.iloc[-1]['new_price']

                slots = 5 - active_counts_fav.get(fav['id'], 0)
                is_active = fav.get('is_active', True)
                station_connector = fav.get('connector_type', 'CCS')
                status = "Отключена" if not is_active else (
                    "Доступна" if slots > 2 else ("Мало мест" if slots > 0 else "Заполнена"))

                col_info, col_del = st.columns([4, 1])
                with col_info:
                    st.markdown(
                        f"**{fav['name']}**\n{fav['location']}\n{price:.2f} руб/кВт·ч | Разъём: {station_connector} | {slots}/5 мест | {status}")
                with col_del:
                    if st.button("Убрать", key=f"del_fav_{fav['id']}"):
                        toggle_favorite(user['id'], int(fav['id']))
                        st.rerun()
                st.divider()

    elif section == "История зарядок":
        st.subheader("История зарядок")
        sessions = get_user_sessions(user['id'])
        if sessions.empty:
            st.info("Нет завершённых сессий зарядки.")
        else:
            completed = sessions[sessions['end_time'].notna()].copy()
            if completed.empty:
                st.info("Нет завершённых сессий.")
            else:
                m1, m2, m3 = st.columns(3)
                m1.metric("Всего сессий", len(completed))
                m2.metric("Суммарно заряжено", f"{completed['energy_kwh'].sum():.1f} кВт·ч")
                m3.metric("Потрачено", f"{completed['total_cost'].sum():.2f} руб")
                st.divider()

                completed['start_time'] = pd.to_datetime(completed['start_time'])
                completed['date'] = completed['start_time'].dt.date
                daily = completed.groupby('date').agg({'energy_kwh': 'sum', 'total_cost': 'sum'}).reset_index()

                if len(daily) > 1:
                    fig = go.Figure()
                    fig.add_trace(
                        go.Bar(x=daily['date'], y=daily['total_cost'], name='Расходы', marker_color='#636EFA'))
                    fig.update_layout(title="Расходы на зарядку по дням", xaxis_title="Дата", yaxis_title="Сумма (руб)",
                                      height=300)
                    st.plotly_chart(fig, use_container_width=True)

                st.subheader("Все сессии")
                display = completed[['station_name', 'start_time', 'energy_kwh', 'total_cost']].copy()
                display.columns = ['Станция', 'Время начала', 'Энергия (кВт·ч)', 'Стоимость (руб)']
                st.dataframe(display, hide_index=True, use_container_width=True)

    elif section == "Профиль":
        st.subheader("Профиль пользователя")

        if st.button("История операций", key="show_transactions"):
            transactions = get_user_transactions(user['id'])

            if not transactions.empty:
                def format_type(t):
                    if t == 'topup':
                        return 'Пополнение'
                    elif t == 'charge':
                        return 'Списание за зарядку'
                    elif t == 'refund':
                        return 'Возврат'
                    return t

                display_tx = transactions.copy()
                display_tx['transaction_type'] = display_tx['transaction_type'].apply(format_type)
                display_tx.columns = ['ID', 'Сумма', 'Тип', 'Описание', 'Дата']
                st.dataframe(display_tx, hide_index=True, use_container_width=True)
            else:
                st.info("Нет транзакций")

        col_prof, col_stat = st.columns(2)

        with col_prof:
            with st.form("profile_form"):
                st.markdown(f"**Логин:** `{user['username']}`")
                new_email = st.text_input("Email", value=user.get('email') or "")
                if st.form_submit_button("Сохранить изменения", type="primary"):
                    update_user_profile(user['id'], new_email)
                    st.session_state.current_user['email'] = new_email
                    st.success("Профиль обновлён")

        with col_stat:
            sessions = get_user_sessions(user['id'])
            completed = sessions[sessions['end_time'].notna()] if not sessions.empty else sessions
            st.markdown("**Статистика**")
            if completed.empty:
                st.info("Нет данных о зарядках")
            else:
                st.metric("Зарядок выполнено", len(completed))
                st.metric("Заряжено энергии", f"{completed['energy_kwh'].sum():.1f} кВт·ч")
                st.metric("Потрачено", f"{completed['total_cost'].sum():.2f} руб")
                fav_station = completed.groupby('station_name')['energy_kwh'].sum().idxmax()
                st.metric("Любимая станция", fav_station)


def render_admin_interface():
    col_title, col_logout = st.columns([4, 1])
    with col_title:
        st.title("Администрирование сети ЭЗС")
    with col_logout:
        st.write("**Администратор**")
        if st.button("Выйти", key="admin_logout", use_container_width=True):
            clear_session()
            st.rerun()

    st.divider()

    section = st.radio(
        "Навигация",
        ["Мониторинг", "Прогнозирование", "Оптимизация и тарифы", "Пользователи", "Электромобили", "Журнал",
         "Управление станциями"],
        horizontal=True,
        label_visibility="collapsed"
    )
    st.divider()

    stations_df = get_stations_info()
    total_load, source = calculate_total_load()

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Суммарная нагрузка", f"{total_load:.1f} кВт",
                  f"{(total_load / SUBSTATION_LIMIT_KW * 100):.1f}% от лимита",
                  delta_color="inverse" if total_load > SUBSTATION_LIMIT_KW else "normal")
    col_m2.metric("Лимит подстанции", f"{SUBSTATION_LIMIT_KW:.0f} кВт")
    col_m3.metric("Запас", f"{SUBSTATION_LIMIT_KW - total_load:.1f} кВт")

    if total_load > SUBSTATION_LIMIT_KW:
        st.error(f"ПЕРЕГРУЗКА: {total_load:.1f} кВт превышает лимит {SUBSTATION_LIMIT_KW} кВт")

    if section == "Мониторинг":
        st.subheader("Статус станций")
        active_all = get_active_sessions()
        active_counts = active_all.groupby('station_id').size().to_dict() if not active_all.empty else {}

        load_data, _, _ = get_current_load_data()
        if load_data is not None:
            load_data = load_data.copy()
            load_data['active_sessions'] = load_data['id'].apply(lambda x: active_counts.get(int(x), 0))
            load_data['slots_left'] = load_data.apply(
                lambda r: 5 - r['active_sessions'] if r.get('is_active', True) else 0, axis=1)
            load_data['ratio'] = load_data.apply(
                lambda r: r['load_kw'] / r['max_power_kw'] if r['max_power_kw'] > 0 else 0, axis=1)

            display = load_data[
                ['name', 'load_kw', 'max_power_kw', 'active_sessions', 'slots_left', 'price', 'connector_type']].copy()
            display['Загрузка'] = load_data['ratio'].apply(lambda x: f"{x:.0%}")
            display['Статус'] = load_data['is_active'].apply(lambda x: "Активна" if x else "Отключена")
            display.columns = ['Станция', 'Нагрузка (кВт)', 'Макс. (кВт)', 'Активных зарядок', 'Свободно мест',
                               'Тариф (руб/кВт·ч)', 'Разъём', 'Загрузка', 'Статус']
            st.dataframe(display, hide_index=True, use_container_width=True)

        render_map(load_data)

        st.divider()
        st.subheader("Динамика нагрузки (24 часа)")
        hist = get_history()
        if not hist.empty:
            hist["timestamp"] = pd.to_datetime(hist["timestamp"])
            max_ts = hist["timestamp"].max()
            recent = hist[hist["timestamp"] >= max_ts - timedelta(hours=24)]
            fig = go.Figure()
            for _, station in stations_df.iterrows():
                s_data = recent[recent["station_id"] == station['id']].sort_values("timestamp")
                if not s_data.empty:
                    fig.add_trace(
                        go.Scatter(x=s_data["timestamp"], y=s_data["load_kw"], name=station['name'], mode='lines'))
            fig.add_hline(y=SUBSTATION_LIMIT_KW, line_dash="dash", line_color="red", annotation_text="Лимит подстанции")
            fig.update_layout(xaxis_title="Время", yaxis_title="Нагрузка (кВт)", height=400)
            st.plotly_chart(fig, use_container_width=True)

    elif section == "Прогнозирование":
        st.subheader("Прогнозирование спроса")
        forecasts_ready = sum(1 for _, s in stations_df.iterrows() if not get_forecasts(s['id']).empty)
        st.write(f"Прогнозы рассчитаны для {forecasts_ready} из {len(stations_df)} станций")

        if st.button("Рассчитать прогнозы для всех станций", type="primary", key="bulk_forecast_btn"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            success_count = 0
            errors = []
            for idx, (_, station) in enumerate(stations_df.iterrows()):
                try:
                    status_text.text(f"Прогноз: {station['name']}...")
                    train_and_predict_station(station['id'])
                    success_count += 1
                except Exception as e:
                    errors.append(f"{station['name']}: {str(e)[:60]}")
                progress_bar.progress((idx + 1) / len(stations_df))
            status_text.text(f"Готово: {success_count}/{len(stations_df)}")
            if errors:
                with st.expander(f"Ошибки ({len(errors)})"):
                    for err in errors:
                        st.text(err)
            st.cache_data.clear()
            st.rerun()

        st.divider()
        st.subheader("Прогноз для отдельной станции")
        col1, col2 = st.columns([1, 2])
        with col1:
            station_options = {row['name']: row['id'] for _, row in stations_df.iterrows()}
            selected_name_fc = st.selectbox("Станция", options=list(station_options.keys()),
                                            key="station_select_forecast")
            selected_id_fc = station_options[selected_name_fc]
            if st.button("Рассчитать прогноз", key="single_forecast_btn"):
                try:
                    with st.spinner("Выполняется прогноз..."):
                        forecast_df, mae, sse, peak_info = train_and_predict_station(selected_id_fc)
                    msg = f"MAE: {mae:.2f} кВт"
                    if peak_info.get("is_peak_expected"):
                        hours_str = ", ".join(f"{h}:00" for h in peak_info["peak_hours"][:3])
                        msg += f" | Ожидается пик: макс. {peak_info['predicted_max_kw']:.1f} кВт, часы: {hours_str}"
                    st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Ошибка: {e}")

        with col2:
            fc = get_forecasts(selected_id_fc)
            if not fc.empty:
                hist = get_history(selected_id_fc)
                hist["timestamp"] = pd.to_datetime(hist["timestamp"])
                latest_fc = fc.sort_values("created_at").iloc[-1]
                fc_subset = fc[fc["created_at"] == latest_fc["created_at"]].copy()
                fc_subset["timestamp"] = pd.to_datetime(fc_subset["timestamp"])

                st.caption("Исторические данные (последние 7 дней)")
                hist_display = hist.tail(168)
                fig_hist = go.Figure()
                fig_hist.add_trace(
                    go.Scatter(x=hist_display["timestamp"], y=hist_display["load_kw"], name="Нагрузка", mode='lines',
                               line=dict(color="gray", width=2), fill='tozeroy', fillcolor='rgba(128,128,128,0.1)'))
                fig_hist.add_hline(y=SUBSTATION_LIMIT_KW / len(stations_df), line_dash="dash", line_color="red",
                                   annotation_text=f"Средний лимит ({SUBSTATION_LIMIT_KW / len(stations_df):.0f} кВт)")
                fig_hist.update_layout(xaxis_title="Время", yaxis_title="Нагрузка (кВт)", height=250,
                                       margin=dict(l=50, r=20, t=30, b=50), showlegend=False)
                st.plotly_chart(fig_hist, use_container_width=True)

                st.caption("Прогноз на 24 часа")
                hist_recent = hist.tail(6)
                fig_forecast = go.Figure()
                fig_forecast.add_trace(
                    go.Scatter(x=hist_recent["timestamp"], y=hist_recent["load_kw"], name="История (контекст)",
                               mode='lines+markers', line=dict(color="gray", width=2, dash='dot'), marker=dict(size=6)))
                fig_forecast.add_trace(
                    go.Scatter(x=fc_subset["timestamp"].tolist(), y=fc_subset["predicted_load_kw"].tolist(),
                               name="Прогноз", mode='lines+markers', line=dict(color="blue", width=3),
                               marker=dict(size=8, symbol='diamond')))

                avg_fc = fc_subset["predicted_load_kw"].mean()
                max_fc = fc_subset["predicted_load_kw"].max()
                fig_forecast.add_hline(y=avg_fc, line_dash="dot", line_color="orange",
                                       annotation_text=f"Среднее: {avg_fc:.1f} кВт")
                fig_forecast.add_hline(y=max_fc, line_dash="dash", line_color="red",
                                       annotation_text=f"Пик: {max_fc:.1f} кВт")
                fig_forecast.update_layout(xaxis_title="Время", yaxis_title="Нагрузка (кВт)", height=250,
                                           margin=dict(l=50, r=20, t=30, b=50),
                                           legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig_forecast, use_container_width=True)

                peak_hours = fc_subset[fc_subset["predicted_load_kw"] > avg_fc * 1.3]["timestamp"].dt.hour.tolist()
                c_fc1, c_fc2, c_fc3 = st.columns(3)
                c_fc1.metric("MAE модели", f"{latest_fc['mae']:.2f} кВт")
                c_fc2.metric("Ожидаемый пик", f"{max_fc:.1f} кВт")
                c_fc3.metric("Пиковых часов", len(peak_hours))

                if peak_hours:
                    st.info(
                        f"Ожидаются пиковые часы: {', '.join(f'{h}:00' for h in sorted(set(peak_hours)))}.")

    elif section == "Оптимизация и тарифы":
        st.subheader("Оптимизация распределения мощности")
        load_df, _, _ = get_current_load_data()

        if load_df is not None:
            total = load_df['load_kw'].sum()
            expected_peak = sum(get_expected_peak_load(int(sid))['max_kw'] or 0 for sid in load_df['id'])

            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            col_m1.metric("Текущая нагрузка", f"{total:.1f} кВт")
            col_m2.metric("Лимит подстанции", f"{SUBSTATION_LIMIT_KW:.0f} кВт")
            col_m3.metric("Запас", f"{SUBSTATION_LIMIT_KW - total:.1f} кВт")
            col_m4.metric("Ожидаемый пик (24ч)", f"{expected_peak:.1f} кВт",
                          delta=f"{(expected_peak / SUBSTATION_LIMIT_KW * 100 - total / SUBSTATION_LIMIT_KW * 100):+.1f}%",
                          delta_color="inverse" if expected_peak > SUBSTATION_LIMIT_KW else "normal")

            if expected_peak > SUBSTATION_LIMIT_KW:
                st.warning(
                    f"Прогноз показывает будущую перегрузку ({expected_peak:.0f} кВт > {SUBSTATION_LIMIT_KW:.0f} кВт лимита).")

        col_opt1, col_opt2 = st.columns(2)
        with col_opt1:
            if st.button("Запустить оптимизацию", type="primary", key="run_pred_opt"):
                with st.spinner("Учёт прогноза и пересчёт тарифов..."):
                    result = optimize_load()
                st.success(f"Готово. Обработано {len(result)} станций")
                st.cache_data.clear()
                st.rerun()

        tariffs = get_tariffs()
        if not tariffs.empty:
            st.divider()
            st.subheader("Результаты последней оптимизации")
            tariffs["timestamp"] = pd.to_datetime(tariffs["timestamp"])
            latest = tariffs.sort_values("timestamp").groupby("station_id").last().reset_index()
            sdf = get_stations_info()
            display_df = latest.merge(sdf[['id', 'name']], left_on="station_id", right_on="id")
            st.dataframe(display_df[['name', 'planned_load_kw', 'tariff_multiplier', 'new_price']].rename(columns={
                'name': 'Станция', 'planned_load_kw': 'Выделено (кВт)', 'tariff_multiplier': 'Множитель',
                'new_price': 'Тариф (руб/кВт·ч)'
            }), hide_index=True, use_container_width=True)

    elif section == "Пользователи":
        st.subheader("Список пользователей")
        users_df = get_all_users()
        active_all = get_active_sessions()

        col_u1, col_u2, col_u3 = st.columns(3)
        col_u1.metric("Зарегистрировано", len(users_df) if not users_df.empty else 0)
        col_u2.metric("Сейчас заряжаются", len(active_all) if not active_all.empty else 0)
        with sqlite3.connect(DB_PATH) as conn:
            total_sessions = \
                conn.execute("SELECT COUNT(*) FROM charging_sessions WHERE end_time IS NOT NULL").fetchone()[0]
        col_u3.metric("Всего завершённых зарядок", total_sessions)

        st.divider()
        if not users_df.empty:
            st.dataframe(users_df.rename(
                columns={'id': 'ID', 'username': 'Логин', 'email': 'Email', 'car_model': 'Авто',
                         'created_at': 'Дата регистрации'}), hide_index=True, use_container_width=True)

        if not active_all.empty:
            st.divider()
            st.subheader("Активные сессии")
            st.dataframe(active_all[['station_name', 'start_time']].rename(
                columns={'station_name': 'Станция', 'start_time': 'Начало зарядки'}), hide_index=True,
                use_container_width=True)

        st.divider()
        st.subheader("Статистика по станциям")
        with sqlite3.connect(DB_PATH) as conn:
            try:
                stats = pd.read_sql("""
                    SELECT s.name as station_name, COUNT(cs.id) as sessions,
                           ROUND(SUM(cs.energy_kwh), 1) as total_kwh, ROUND(SUM(cs.total_cost), 2) as total_revenue
                    FROM charging_sessions cs JOIN stations s ON cs.station_id = s.id
                    WHERE cs.end_time IS NOT NULL GROUP BY s.name ORDER BY total_revenue DESC
                """, conn)
                if not stats.empty:
                    st.dataframe(stats.rename(
                        columns={'station_name': 'Станция', 'sessions': 'Сессий', 'total_kwh': 'Энергия (кВт·ч)',
                                 'total_revenue': 'Выручка (руб)'}), hide_index=True, use_container_width=True)
            except Exception:
                st.info("Нет данных")

    elif section == "Управление станциями":
        st.subheader("Управление статусом станций")

        stations_df = get_stations_info()
        active_sessions = get_active_sessions()

        for _, station in stations_df.iterrows():
            sid = station['id']
            is_active = station.get('is_active', True)
            station_active_sessions = active_sessions[
                active_sessions['station_id'] == sid] if not active_sessions.empty else pd.DataFrame()
            has_active_charging = len(station_active_sessions) > 0

            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.markdown(f"**{station['name']}**")
                st.caption(f"Адрес: {station['location']} · Макс. мощность: {station['max_power_kw']:.0f} кВт · Разъём: {station.get('connector_type', 'CCS')}")
                if has_active_charging:
                    st.warning(f"Сейчас заряжается: {len(station_active_sessions)} авто")
                    for _, sess in station_active_sessions.iterrows():
                        st.caption(f"  - Начал: {sess['start_time']}")

            with col2:
                status_text = "Активна" if is_active else "Отключена"
                st.metric("Текущий статус", status_text)

            with col3:
                if is_active:
                    if st.button("Отключить", key=f"disable_{sid}", use_container_width=True):
                        if has_active_charging:
                            st.session_state[f"confirm_disable_{sid}"] = True
                        else:
                            set_station_active(sid, False)
                            add_log("SYSTEM", f"Станция '{station['name']}' отключена администратором",
                                    f"ID станции: {sid}", level="WARNING")
                            st.success(f"Станция '{station['name']}' отключена")
                            update_station_load_from_sessions()
                            st.rerun()
                else:
                    if st.button("Включить", key=f"enable_{sid}", type="primary", use_container_width=True):
                        set_station_active(sid, True)
                        add_log("SYSTEM", f"Станция '{station['name']}' включена администратором",
                                f"ID станции: {sid}", level="INFO")
                        st.success(f"Станция '{station['name']}' включена")
                        st.rerun()

            if st.session_state.get(f"confirm_disable_{sid}"):
                with st.expander("Подтверждение отключения", expanded=True):
                    st.warning(
                        f"На станции '{station['name']}' сейчас происходит зарядка {len(station_active_sessions)} авто!")
                    st.info("При отключении все активные сессии будут отменены БЕЗ списания средств.")

                    col_confirm1, col_confirm2 = st.columns(2)
                    with col_confirm1:
                        if st.button("Всё равно отключить", key=f"confirm_yes_{sid}", type="primary",
                                     use_container_width=True):
                            with sqlite3.connect(DB_PATH) as conn:
                                for _, sess in station_active_sessions.iterrows():
                                    conn.execute("""
                                        DELETE FROM charging_sessions WHERE id = ?
                                    """, (sess['id'],))
                                add_log("SYSTEM",
                                        f"Станция '{station['name']}' отключена с активными сессиями",
                                        f"Отменено сессий: {len(station_active_sessions)}. Средства НЕ списаны.",
                                        level="WARNING")
                            set_station_active(sid, False)
                            update_station_load_from_sessions()
                            st.session_state[f"confirm_disable_{sid}"] = False
                            st.success(
                                f"Станция отключена. {len(station_active_sessions)} сессий отменено без списания средств.")
                            st.rerun()
                    with col_confirm2:
                        if st.button("Отмена", key=f"confirm_no_{sid}", use_container_width=True):
                            st.session_state[f"confirm_disable_{sid}"] = False
                            st.rerun()

            st.divider()

    elif section == "Журнал":
        st.subheader("Журнал системы")
        stats = get_system_stats()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего пользователей", stats['total_users'])
        c2.metric("Всего сессий", stats['total_sessions'])
        c3.metric("Выдано энергии", f"{stats['total_energy_kwh']:.1f} кВт·ч")
        c4.metric("Общая выручка", f"{stats['total_revenue']:.2f} руб")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Активных зарядок", stats['active_sessions'])
        c6.metric("Оптимизаций сегодня", stats['optimizations_today'])
        c7.metric("Ошибок сегодня", stats['errors_today'],
                  delta_color="inverse" if stats['errors_today'] > 0 else "normal")
        c8.metric("Ср. энергия/сессия", f"{stats['avg_session_kwh']:.1f} кВт·ч")

        st.divider()
        st.subheader("Лог событий")
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            log_level = st.selectbox("Уровень", ["Все", "INFO", "WARNING", "ERROR"], key="log_level_filter")
        with col_f2:
            log_type = st.selectbox("Тип события", ["Все", "OPTIMIZATION", "CHARGING", "AUTH", "SYSTEM"],
                                    key="log_type_filter")
        with col_f3:
            log_limit = st.selectbox("Показать записей", [50, 100, 200, 500], key="log_limit_filter")

        logs_df = get_logs(limit=log_limit, level=None if log_level == "Все" else log_level)
        if not logs_df.empty:
            if log_type != "Все":
                logs_df = logs_df[logs_df['event_type'] == log_type]

            if logs_df.empty:
                st.info("Нет записей по выбранным фильтрам.")
            else:
                def highlight_level(row):
                    if row['Уровень'] == 'ERROR':
                        return ['background-color: rgba(220,53,69,0.2)'] * len(row)
                    elif row['Уровень'] == 'WARNING':
                        return ['background-color: rgba(255,193,7,0.15)'] * len(row)
                    return [''] * len(row)

                display_logs = logs_df[['created_at', 'level', 'event_type', 'message', 'details']].copy()
                display_logs.columns = ['Время', 'Уровень', 'Тип', 'Сообщение', 'Детали']
                st.dataframe(display_logs.style.apply(highlight_level, axis=1), hide_index=True,
                             use_container_width=True)
                st.caption(f"Показано {len(display_logs)} записей")
        else:
            st.info("Журнал пуст.")

        st.divider()
        if st.button("Очистить журнал", key="clear_logs_btn"):
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM system_logs")
            add_log("SYSTEM", "Журнал очищен администратором")
            st.success("Журнал очищен.")
            st.rerun()

    elif section == "Электромобили":
        st.subheader("Справочник электромобилей")
        ev_df = get_ev_models()
        if not ev_df.empty:
            col_s1, col_s2, col_s3 = st.columns(3)
            col_s1.metric("Всего моделей", len(ev_df))
            custom_count = len(ev_df[ev_df['is_custom'] == 1]) if 'is_custom' in ev_df.columns else 0
            col_s2.metric("Пользовательских", custom_count)
            col_s3.metric("Стандартных", len(ev_df) - custom_count)
            st.divider()
            display_ev = ev_df[['brand', 'model', 'battery_kwh', 'max_charge_kw', 'connector_type', 'is_custom']].copy()
            display_ev.columns = ['Марка', 'Модель', 'Батарея (кВт·ч)', 'Макс. зарядка (кВт)', 'Разъём',
                                  'Пользовательский']
            display_ev['Пользовательский'] = display_ev['Пользовательский'].apply(lambda x: 'Да' if x == 1 else 'Нет')
            st.dataframe(display_ev, hide_index=True, use_container_width=True)
        else:
            st.info("Справочник электромобилей пуст.")

        st.divider()
        st.subheader("Добавить новый электромобиль")
        with st.form("add_ev_form"):
            c1, c2 = st.columns(2)
            brand = c1.text_input("Марка", key="admin_ev_brand")
            model = c2.text_input("Модель", key="admin_ev_model")
            c3, c4, c5 = st.columns(3)
            battery = c3.number_input("Ёмкость батареи (кВт·ч)", min_value=10.0, max_value=200.0, value=60.0, step=5.0,
                                      key="admin_ev_battery")
            max_charge = c4.number_input("Макс. зарядка (кВт)", min_value=3.0, max_value=350.0, value=50.0, step=10.0,
                                         key="admin_ev_max_charge")
            connector = c5.selectbox("Тип разъёма", ["CCS", "CHAdeMO", "Type2", "GB/T"], key="admin_ev_connector")
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                submitted = st.form_submit_button("Добавить автомобиль", type="primary", use_container_width=True)
            if submitted:
                if not brand or not model:
                    st.error("Укажите марку и модель автомобиля.")
                else:
                    ev_id = add_custom_ev_model(brand, model, battery, max_charge, connector)
                    if ev_id and ev_id > 0:
                        st.success(f"Автомобиль '{brand} {model}' добавлен в справочник.")
                        add_log("SYSTEM", f"Администратор добавил электромобиль: {brand} {model}",
                                f"Батарея: {battery} кВт·ч, Разъём: {connector}", level="INFO")
                        st.rerun()
                    else:
                        st.error("Автомобиль с такой маркой и моделью уже существует в справочнике.")

if not st.session_state.logged_in:
    render_auth_screen()
else:
    user = st.session_state.current_user
    if user and user.get('role') == 'admin':
        render_admin_interface()
    else:
        render_user_cabinet()