import sqlite3
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta
from database import (
    init_schema, get_history, get_forecasts, get_tariffs,
    get_stations_info, update_station_load_from_sessions, init_logs_table, get_logs, get_system_stats, add_log,
    get_ev_models, add_custom_ev_model, set_station_active,
    init_accounts_table
)
from data_generator import generate_synthetic_data
from ml_forecast import train_and_predict_station
from optimizer import optimize_load, get_expected_peak_load
from auth import (
    init_users_table, get_all_users,
    get_active_sessions
)
from config import (
    SUBSTATION_LIMIT_KW, DB_PATH
)
from ui.auth_screen import render_auth_screen
from ui.helpers import get_current_load_data, calculate_total_load, restore_session, clear_session
from ui.legacy.user_cabinet import render_user_cabinet
from ui.map_view import render_map

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