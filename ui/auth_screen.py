import streamlit as st

from auth import login_user, register_user
from database import get_ev_models, add_custom_ev_model
from ui.helpers import save_session

EV_PLACEHOLDER = "— Выбрать из списка —"


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
