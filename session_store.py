import json
import os

SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".session_cache.json")


def save_session_to_disk(user: dict):
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump({"id": user["id"], "role": user.get("role", "user")}, f)
    except Exception:
        pass


def load_session_from_disk() -> dict | None:
    try:
        if not os.path.exists(SESSION_FILE):
            return None
        with open(SESSION_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def clear_session_from_disk():
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass