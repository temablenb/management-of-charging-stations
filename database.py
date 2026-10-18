import sqlite3
from datetime import datetime

import pandas as pd
from config import DB_PATH


def init_schema():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                max_power_kw REAL NOT NULL,
                location TEXT,
                lat REAL,
                lon REAL,
                is_active INTEGER NOT NULL DEFAULT 1,
                connector_type TEXT DEFAULT 'CCS'
            );
            CREATE TABLE IF NOT EXISTS history (
                station_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                load_kw REAL NOT NULL,
                temperature REAL,
                event_flag INTEGER DEFAULT 0,
                PRIMARY KEY (station_id, timestamp),
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                predicted_load_kw REAL NOT NULL,
                mae REAL,
                aic REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS tariffs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                planned_load_kw REAL NOT NULL,
                tariff_multiplier REAL NOT NULL,
                new_price REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS ev_models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                battery_kwh REAL NOT NULL,
                max_charge_kw REAL,
                connector_type TEXT,
                is_custom INTEGER NOT NULL DEFAULT 0,
                UNIQUE(brand, model)
            );
        """)

        ev_models = [
            ("Tesla", "Model 3 Standard Range", 57, 170, "CCS"),
            ("Tesla", "Model 3 Long Range", 82, 250, "CCS"),
            ("Tesla", "Model Y Long Range", 82, 250, "CCS"),
            ("Tesla", "Model S", 100, 250, "CCS"),
            ("BYD", "Atto 3", 60, 88, "CCS"),
            ("BYD", "Han EV", 85, 120, "CCS"),
            ("BYD", "Dolphin", 45, 60, "CCS"),
            ("BYD", "Seal", 82, 150, "CCS"),
            ("Lixiang", "L9", 45, 40, "GB/T"),
            ("Zeekr", "001", 100, 200, "GB/T"),
            ("Nio", "ET5", 75, 140, "CCS"),
            ("Hyundai", "Ioniq 5 Standard", 58, 175, "CCS"),
            ("Hyundai", "Ioniq 5 Long Range", 77, 220, "CCS"),
            ("Hyundai", "Ioniq 6", 77, 239, "CCS"),
            ("Kia", "EV6 Standard", 58, 175, "CCS"),
            ("Kia", "EV6 Long Range", 77, 240, "CCS"),
            ("Volkswagen", "ID.4 Pure", 52, 110, "CCS"),
            ("Volkswagen", "ID.4 Pro", 82, 135, "CCS"),
            ("BMW", "iX3", 80, 150, "CCS"),
            ("BMW", "i4 eDrive40", 84, 205, "CCS"),
            ("Mercedes", "EQC 400", 80.0, 110, "CCS"),
            ("Audi", "e-tron 55", 95, 150, "CCS"),
            ("Renault", "Zoe R135", 52, 50, "Type2"),
            ("Nissan", "Leaf 40 kWh", 40, 50, "CHAdeMO"),
            ("Nissan", "Leaf 62 kWh", 62, 98, "CHAdeMO"),
            ("Lada", "e-Largus", 54, 50, "CCS"),
            ("Evolute", "i-Pro", 53, 60, "GB/T"),
            ("Evolute", "i-Joy", 40, 60, "GB/T"),
            ("Moskvich", "3e", 50, 80, "GB/T"),
            ("Atom", "Atom", 46, 80, "CCS"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO ev_models (brand, model, battery_kwh, max_charge_kw, connector_type) VALUES (?,?,?,?,?)",
            ev_models
        )

        stations = [
            (1, "ТОСК - Октябрьская", 100.0, "Октябрьская ул., 16", 52.725063, 41.448077, 1, "CCS"),
            (2, "Sitronics Electro", 95.0, "Бокинский Промышленный узел, 52", 52.659879, 41.413893, 1, "CCS"),
            (3, "ТОСК - Советская", 100.0, "Советская ул., 99А", 52.724424, 41.458045, 1, "CCS"),
            (4, "Krata Energy", 90.0, "ул. Монтажников, 1", 52.741992, 41.483138, 1, "GB/T"),
            (5, "ТОСК - Студенецкая", 100.0, "ул. Студенецкая Набережная, 20А", 52.728261, 41.444543, 1, "CCS"),
            (6, "Амакс", 85.0, "ул. им. Маршала Малиновского, 101", 52.702598, 41.513037, 1, "GB/T"),
            (7, "Зарядная станция - Северо-Западная", 80.0, "Северо-Западная ул., 5", 52.770808, 41.404505, 1, "CCS"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO stations (id, name, max_power_kw, location, lat, lon, is_active, connector_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            stations
        )


def init_accounts_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_accounts (
                user_id INTEGER PRIMARY KEY,
                balance REAL NOT NULL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                transaction_type TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
        """)
        conn.execute("""
            INSERT OR IGNORE INTO user_accounts (user_id, balance)
            SELECT id, 0.0 FROM users
        """)


def init_logs_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'INFO',
                message TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


def save_history(records: list):
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO history (station_id, timestamp, load_kw, temperature, event_flag) VALUES (?, ?, ?, ?, ?)",
            records
        )


def get_history(station_id: int | None = None) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        if station_id is not None:
            return pd.read_sql(
                "SELECT * FROM history WHERE station_id=? ORDER BY timestamp",
                conn, params=(station_id,)
            )
        return pd.read_sql("SELECT * FROM history ORDER BY timestamp", conn)


def save_forecast(df: pd.DataFrame):
    with sqlite3.connect(DB_PATH) as conn:
        df.to_sql("forecasts", conn, if_exists="append", index=False)


def get_forecasts(station_id: int) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql(
            "SELECT * FROM forecasts WHERE station_id=? ORDER BY created_at DESC, timestamp ASC",
            conn, params=(station_id,)
        )


def save_tariffs(records: list):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM tariffs")
        conn.executemany(
            "INSERT INTO tariffs (station_id, timestamp, planned_load_kw, tariff_multiplier, new_price) VALUES (?, ?, ?, ?, ?)",
            records
        )


def get_tariffs() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        query = """
            SELECT 
                CAST(station_id AS INTEGER) as station_id, 
                timestamp, 
                planned_load_kw, 
                tariff_multiplier, 
                new_price 
            FROM tariffs 
            ORDER BY timestamp
        """
        return pd.read_sql(query, conn)


def save_manual_load(records: list):
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO history (station_id, timestamp, load_kw, temperature, event_flag) VALUES (?, ?, ?, ?, ?)",
            records
        )


def get_manual_loads() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT * FROM history 
            WHERE timestamp >= datetime('now', '-1 day')
            ORDER BY timestamp
        """, conn)


def save_load_adjustment(station_id: int, timestamp: str, adjustment_factor: float):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO manual_load_adjustments (station_id, timestamp, adjustment_factor)
            VALUES (?, ?, ?)
        """, (station_id, timestamp, adjustment_factor))


def get_load_adjustments() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT * FROM manual_load_adjustments
            ORDER BY created_at DESC
        """, conn)


def get_stations_info() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("SELECT * FROM stations ORDER BY id", conn)


def clear_future_data(from_timestamp: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"DELETE FROM history WHERE timestamp >= '{from_timestamp}'")
        conn.execute("DELETE FROM forecasts")
        conn.execute("DELETE FROM tariffs")
        conn.execute("DELETE FROM manual_load_adjustments")


def update_station_load_from_sessions():
    with sqlite3.connect(DB_PATH) as conn:
        active = pd.read_sql("""
            SELECT station_id, COUNT(*) as active_count
            FROM charging_sessions
            WHERE end_time IS NULL
            GROUP BY station_id
        """, conn)

        stations = pd.read_sql("SELECT id, max_power_kw FROM stations", conn)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        records = []
        for _, st in stations.iterrows():
            sid = st['id']
            max_pw = float(st['max_power_kw'])

            count_row = active[active['station_id'] == sid]
            count = int(count_row['active_count'].iloc[0]) if not count_row.empty else 0

            load = max_pw * (0.10 + 0.17 * count)
            load = min(load, max_pw * 0.95)
            records.append((sid, now, round(load, 2), 18.0, 0))

        conn.executemany(
            "INSERT OR REPLACE INTO history "
            "(station_id, timestamp, load_kw, temperature, event_flag) "
            "VALUES (?, ?, ?, ?, ?)",
            records
        )


def get_user_by_id(user_id: int) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, username, email, car_model, ev_model_id FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if row:
            return {
                "id": row[0], "username": row[1],
                "email": row[2], "car_model": row[3],
                "ev_model_id": row[4], "role": "user"
            }
        return None


def add_log(event_type: str, message: str, details: str = None, level: str = "INFO"):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO system_logs (event_type, level, message, details)
            VALUES (?, ?, ?, ?)
        """, (event_type, level, message, details))


def get_logs(limit: int = 100, level: str = None) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        if level:
            return pd.read_sql("""
                SELECT * FROM system_logs
                WHERE level = ?
                ORDER BY created_at DESC LIMIT ?
            """, conn, params=(level, limit))
        return pd.read_sql("""
            SELECT * FROM system_logs
            ORDER BY created_at DESC LIMIT ?
        """, conn, params=(limit,))


def get_system_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        total_sessions = conn.execute(
            "SELECT COUNT(*) FROM charging_sessions WHERE end_time IS NOT NULL"
        ).fetchone()[0]

        active_sessions = conn.execute(
            "SELECT COUNT(*) FROM charging_sessions WHERE end_time IS NULL"
        ).fetchone()[0]

        total_energy = conn.execute(
            "SELECT COALESCE(SUM(energy_kwh), 0) FROM charging_sessions WHERE end_time IS NOT NULL"
        ).fetchone()[0]

        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(total_cost), 0) FROM charging_sessions WHERE end_time IS NOT NULL"
        ).fetchone()[0]

        total_users = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        optimizations_today = conn.execute("""
            SELECT COUNT(*) FROM system_logs
            WHERE event_type = 'OPTIMIZATION'
            AND date(created_at) = date('now')
        """).fetchone()[0]

        last_optimization = conn.execute("""
            SELECT created_at FROM system_logs
            WHERE event_type = 'OPTIMIZATION' AND level = 'INFO'
            ORDER BY created_at DESC LIMIT 1
        """).fetchone()

        errors_today = conn.execute("""
            SELECT COUNT(*) FROM system_logs
            WHERE level = 'ERROR'
            AND date(created_at) = date('now')
        """).fetchone()[0]

        busiest_station = conn.execute("""
            SELECT s.name, COUNT(cs.id) as cnt
            FROM charging_sessions cs
            JOIN stations s ON cs.station_id = s.id
            WHERE cs.end_time IS NOT NULL
            GROUP BY s.name ORDER BY cnt DESC LIMIT 1
        """).fetchone()

        avg_session_kwh = conn.execute("""
            SELECT COALESCE(AVG(energy_kwh), 0)
            FROM charging_sessions WHERE end_time IS NOT NULL
        """).fetchone()[0]

        return {
            "total_sessions": total_sessions,
            "active_sessions": active_sessions,
            "total_energy_kwh": round(total_energy, 1),
            "total_revenue": round(total_revenue, 2),
            "total_users": total_users,
            "optimizations_today": optimizations_today,
            "last_optimization": last_optimization[0] if last_optimization else None,
            "errors_today": errors_today,
            "busiest_station": busiest_station[0] if busiest_station else "—",
            "avg_session_kwh": round(avg_session_kwh, 1),
        }


def get_forecast_summary(station_id: int) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT timestamp, predicted_load_kw, upper_bound_kw, lower_bound_kw
            FROM forecasts
            WHERE station_id = ?
              AND timestamp >= (SELECT MAX(created_at) FROM forecasts WHERE station_id = ?)
              AND timestamp >= datetime('now')
            ORDER BY timestamp ASC
        """, conn, params=(station_id, station_id))


def set_station_active(station_id: int, is_active: bool):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE stations SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, station_id)
        )


def get_station_status(station_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT is_active FROM stations WHERE id = ?", (station_id,)
        ).fetchone()
        return bool(row[0]) if row else True


def get_ev_models() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("SELECT * FROM ev_models ORDER BY brand, model", conn)


def add_custom_ev_model(brand: str, model: str, battery_kwh: float,
                        max_charge_kw: float, connector_type: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO ev_models (brand, model, battery_kwh, max_charge_kw, connector_type, is_custom) VALUES (?,?,?,?,?,1)",
            (brand.strip(), model.strip(), battery_kwh, max_charge_kw, connector_type)
        )
        if cursor.lastrowid:
            return cursor.lastrowid
        row = conn.execute("SELECT id FROM ev_models WHERE brand=? AND model=?", (brand, model)).fetchone()
        return row[0] if row else -1


def get_user_balance(user_id: int) -> float:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT balance FROM user_accounts WHERE user_id=?",
            (user_id,)
        ).fetchone()
        return float(row[0]) if row else 0.0


def update_user_balance(user_id: int, amount: float, transaction_type: str = "charge", description: str = "") -> tuple[bool, str]:
    with sqlite3.connect(DB_PATH) as conn:
        try:
            current = get_user_balance(user_id)
            new_balance = current + amount

            if new_balance < 0:
                return False, f"Недостаточно средств. Текущий баланс: {current:.2f} руб"

            conn.execute("""
                UPDATE user_accounts 
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (round(new_balance, 2), user_id))

            conn.execute("""
                INSERT INTO transactions (user_id, amount, transaction_type, description)
                VALUES (?, ?, ?, ?)
            """, (user_id, round(amount, 2), transaction_type, description))

            return True, f"Баланс обновлён: {new_balance:.2f} руб"
        except Exception as e:
            return False, f"Ошибка при обновлении баланса: {e}"


def get_user_transactions(user_id: int, limit: int = 20) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT id, amount, transaction_type, description, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, conn, params=(user_id, limit))


def get_user_connector_type(user_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT ev_model_id FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        if not row or not row[0]:
            return None

        ev_row = conn.execute(
            "SELECT connector_type FROM ev_models WHERE id=?",
            (row[0],)
        ).fetchone()
        return ev_row[0] if ev_row else None


def get_station_connector_type(station_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT connector_type FROM stations WHERE id = ?",
            (station_id,)
        ).fetchone()
        return row[0] if row else "CCS"


def get_last_forecast_created_at(station_id: int) -> datetime | None:
    with sqlite3.connect(DB_PATH, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        row = conn.execute(
            "SELECT MAX(created_at) FROM forecasts WHERE station_id = ?",
            (station_id,)
        ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None


def retrain_forecast_if_needed(station_id: int, min_hours_since_retrain: int = 6) -> bool:
    last_retrain = get_last_forecast_created_at(station_id)
    if last_retrain is None:
        from ml_forecast import train_and_predict_station
        try:
            train_and_predict_station(station_id)
            return True
        except Exception as e:
            print(f"[retrain] Ошибка обучения станции {station_id}: {e}")
            return False

    hours_since = (datetime.now() - last_retrain).total_seconds() / 3600
    if hours_since >= min_hours_since_retrain:
        from ml_forecast import train_and_predict_station
        try:
            train_and_predict_station(station_id)
            return True
        except Exception as e:
            print(f"[retrain] Ошибка переобучения станции {station_id}: {e}")
            return False

    return False


def retrain_forecasts_for_stations(station_ids: list, min_hours_since_retrain: int = 6) -> list:
    retrained = []
    for sid in station_ids:
        if retrain_forecast_if_needed(sid, min_hours_since_retrain):
            retrained.append(sid)
    return retrained