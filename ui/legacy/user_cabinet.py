import sqlite3

import pandas as pd
import streamlit as st
from plotly import graph_objects as go

from auth import get_user_active_session, get_active_sessions, get_favorite_stations, toggle_favorite, \
    finish_charging_session, start_charging_session, get_user_sessions, update_user_profile
from config import DB_PATH, SUBSTATION_LIMIT_KW, BASE_TARIFF_RUB
from database import get_user_balance, get_user_connector_type, update_user_balance, get_ev_models, get_tariffs, \
    get_stations_info, get_forecasts, update_station_load_from_sessions, retrain_forecasts_for_stations, add_log, \
    get_user_transactions
from ui.helpers import clear_session, get_current_load_data, get_best_station, calculate_total_load, do_optimize
from ui.map_view import render_map


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
