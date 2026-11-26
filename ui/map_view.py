import pandas as pd
import pydeck as pdk
import streamlit as st

from config import MAP_CENTER_LAT, MAP_CENTER_LON, MAP_ZOOM
from ui.helpers import get_status_color


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
