import os

DDB_PATH = os.environ.get(
    "DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ev_charging_opt.db"),
)

SUBSTATION_LIMIT_KW = 420.0
BASE_TARIFF_RUB = 10.0
TARIFF_MIN_MULT = 0.7
TARIFF_MAX_MULT = 1.6

NUM_STATIONS = 7
SIMULATION_DAYS = 30
FORECAST_HORIZON = 24
HOLDOUT_HOURS = 48

MAP_CENTER_LAT = 52.7200
MAP_CENTER_LON = 41.4600
MAP_ZOOM = 13

MAP_TILES = "CartoDB positron"