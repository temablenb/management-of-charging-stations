import hashlib
import sqlite3
import pandas as pd
from datetime import datetime
from config import BASE_TARIFF_RUB
from database import DB_PATH, add_log, get_user_balance, update_user_balance, get_user_connector_type, \
    get_station_connector_type


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def init_users_table():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                ev_model_id INTEGER,
                car_model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS charging_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                station_id INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                energy_kwh REAL,
                total_cost REAL,
                price_per_kwh REAL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
            CREATE TABLE IF NOT EXISTS favorite_stations (
                user_id INTEGER NOT NULL,
                station_id INTEGER NOT NULL,
                PRIMARY KEY (user_id, station_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(station_id) REFERENCES stations(id)
            );
        """)
        try:
            conn.execute("ALTER TABLE charging_sessions ADD COLUMN price_per_kwh REAL")
        except Exception:
            pass


def register_user(username: str, password: str, email: str = "",
                  ev_model_id: int = None) -> tuple[bool, str]:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, email, ev_model_id) VALUES (?, ?, ?, ?)",
                (username.strip(), hash_password(password), email.strip(), ev_model_id)
            )
            user_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO user_accounts (user_id, balance) VALUES (?, 0.0)",
                (user_id,)
            )

            return True, "Регистрация успешна!"
    except sqlite3.IntegrityError:
        return False, "Пользователь с таким именем уже существует."
    except Exception as e:
        return False, f"Ошибка: {e}"


def login_user(username: str, password: str) -> tuple[bool, str, dict | None]:
    if username == "admin" and password == "admin":
        return True, "Добро пожаловать, администратор!", {"id": 0, "username": "admin", "role": "admin"}

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT id, username, email, ev_model_id FROM users WHERE username=? AND password_hash=?",
            (username.strip(), hash_password(password))
        ).fetchone()

        if row:
            user = {"id": row[0], "username": row[1], "email": row[2],
                    "ev_model_id": row[3], "role": "user"}
            return True, f"Добро пожаловать, {row[1]}!", user
        return False, "Неверный логин или пароль.", None


def get_user_sessions(user_id: int):
    import pandas as pd
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT cs.*, s.name as station_name
            FROM charging_sessions cs
            JOIN stations s ON cs.station_id = s.id
            WHERE cs.user_id = ?
            ORDER BY cs.start_time DESC
        """, conn, params=(user_id,))


def add_charging_session(user_id: int, station_id: int, start_time: str,
                         end_time: str, energy_kwh: float, total_cost: float):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO charging_sessions (user_id, station_id, start_time, end_time, energy_kwh, total_cost)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, station_id, start_time, end_time, round(energy_kwh, 2), round(total_cost, 2)))


def get_active_sessions() -> pd.DataFrame:
    import pandas as pd
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT cs.*, s.name as station_name, s.max_power_kw
            FROM charging_sessions cs
            JOIN stations s ON cs.station_id = s.id
            WHERE cs.end_time IS NULL
            ORDER BY cs.start_time DESC
        """, conn, params=())


def start_charging_session(user_id: int, station_id: int,
                           price_per_kwh: float = BASE_TARIFF_RUB) -> tuple[bool, str, int | None]:
    with sqlite3.connect(DB_PATH) as conn:
        active = conn.execute("""
            SELECT id FROM charging_sessions
            WHERE user_id = ? AND end_time IS NULL
        """, (user_id,)).fetchone()
        if active:
            return False, "У вас уже есть активная сессия зарядки. Завершите её перед началом новой.", None

        user_connector = get_user_connector_type(user_id)
        station_connector = get_station_connector_type(station_id)

        if user_connector and station_connector:
            if user_connector != station_connector:
                return False, (
                    f"Несовместимый разъём! Ваш автомобиль: {user_connector}, "
                    f"станция: {station_connector}. Выберите другую станцию."
                ), None

        balance = get_user_balance(user_id)
        if balance < 100:
            return False, (
                f"Недостаточно средств на счёте. Минимальный баланс для зарядки: 100 руб. "
                f"Ваш баланс: {balance:.2f} руб. Пополните счёт."
            ), None

        active_on_station = conn.execute("""
            SELECT COUNT(*) FROM charging_sessions
            WHERE station_id = ? AND end_time IS NULL
        """, (station_id,)).fetchone()[0]

        station = conn.execute(
            "SELECT max_power_kw, is_active FROM stations WHERE id = ?",
            (station_id,)
        ).fetchone()

        if not station:
            return False, "Станция не найдена.", None

        if not station[1]:
            return False, "Станция временно отключена администратором.", None

        if active_on_station >= 5:
            return False, "Станция перегружена. Максимум 5 автомобилей одновременно. Попробуйте другую станцию.", None

        warning = ""
        if active_on_station >= 3:
            warning = f" Высокая загрузка ({active_on_station}/5 мест занято) — скорость зарядки может быть снижена."

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute("""
            INSERT INTO charging_sessions (user_id, station_id, start_time, price_per_kwh)
            VALUES (?, ?, ?, ?)
        """, (user_id, station_id, now, round(price_per_kwh, 2)))
        session_id = cursor.lastrowid

        add_log(
            "CHARGING",
            f"Зарядка начата: пользователь ID={user_id}, станция ID={station_id}, тариф={price_per_kwh:.2f} руб/кВт·ч",
            f"Занято мест на станции: {active_on_station + 1}/5, Баланс: {balance:.2f} руб"
        )

        return True, f"Зарядка началась! Тариф зафиксирован: {price_per_kwh:.2f} руб/кВт·ч.{warning}", session_id


def finish_charging_session(session_id: int, energy_kwh: float) -> tuple[bool, str]:
    with sqlite3.connect(DB_PATH) as conn:
        session = conn.execute(
            "SELECT id, user_id, start_time, price_per_kwh FROM charging_sessions WHERE id = ? AND end_time IS NULL",
            (session_id,)
        ).fetchone()

        if not session:
            return False, "Сессия не найдена или уже завершена."

        user_id = session[1]
        price_per_kwh = session[3] if session[3] else BASE_TARIFF_RUB
        total_cost = round(energy_kwh * price_per_kwh, 2)

        success, msg = update_user_balance(
            user_id,
            -total_cost,
            "charge",
            f"Зарядка сессия #{session_id}, {energy_kwh:.1f} кВт·ч"
        )

        if not success:
            return False, f"Ошибка списания: {msg}"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            UPDATE charging_sessions
            SET end_time = ?, energy_kwh = ?, total_cost = ?
            WHERE id = ?
        """, (now, round(energy_kwh, 2), total_cost, session_id))

        new_balance = get_user_balance(user_id)

        add_log(
            "CHARGING",
            f"Зарядка завершена: сессия ID={session_id}, энергия={energy_kwh:.1f} кВт·ч, сумма={total_cost:.2f} руб",
            f"Тариф: {price_per_kwh:.2f} руб/кВт·ч, Баланс после: {new_balance:.2f} руб"
        )

        return True, f"Зарядка завершена! Заряжено: {energy_kwh:.1f} кВт·ч × {price_per_kwh:.2f} руб = {total_cost:.2f} руб. Остаток на счёте: {new_balance:.2f} руб"


def get_user_active_session(user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("""
            SELECT cs.id, cs.station_id, cs.start_time, s.name as station_name, s.max_power_kw
            FROM charging_sessions cs
            JOIN stations s ON cs.station_id = s.id
            WHERE cs.user_id = ? AND cs.end_time IS NULL
        """, (user_id,)).fetchone()
        if row:
            return {"id": row[0], "station_id": row[1], "start_time": row[2],
                    "station_name": row[3], "max_power_kw": row[4]}
        return None


def get_favorite_stations(user_id: int):
    import pandas as pd
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT s.* FROM favorite_stations fs
            JOIN stations s ON fs.station_id = s.id
            WHERE fs.user_id = ?
        """, conn, params=(user_id,))


def toggle_favorite(user_id: int, station_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        exists = conn.execute(
            "SELECT 1 FROM favorite_stations WHERE user_id=? AND station_id=?",
            (user_id, station_id)
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM favorite_stations WHERE user_id=? AND station_id=?", (user_id, station_id))
            return False
        else:
            conn.execute("INSERT INTO favorite_stations (user_id, station_id) VALUES (?, ?)", (user_id, station_id))
            return True


def update_user_profile(user_id: int, email: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET email=? WHERE id=?",
            (email.strip(), user_id)
        )


def get_all_users():
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql("""
            SELECT u.id, u.username, u.email, 
                   CASE 
                       WHEN u.ev_model_id IS NOT NULL THEN 
                           e.brand || ' ' || e.model || ' (' || e.battery_kwh || ' кВт·ч)'
                       ELSE u.car_model
                   END as car_model,
                   u.created_at
            FROM users u
            LEFT JOIN ev_models e ON u.ev_model_id = e.id
            ORDER BY u.created_at DESC
        """, conn)
