import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent
SETTINGS_FILE = ROOT / "data" / "settings.json"


def _settings() -> dict:
    with open(SETTINGS_FILE) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("data/settings.json must contain a JSON object.")
    return data


def _setting(key: str, env_name: str | None = None) -> str:
    env_key = env_name or key.upper()
    if env_key in os.environ:
        return os.environ[env_key]
    value = SETTINGS.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Missing string setting '{key}'.")
    return value


def _bool_setting(key: str, env_name: str | None = None) -> bool:
    env_key = env_name or key.upper()
    if env_key in os.environ:
        return os.environ[env_key].strip().lower() not in {"0", "false", "no"}
    value = SETTINGS.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Missing boolean setting '{key}'.")
    return value


SETTINGS = _settings()

HKU_UID: str = os.environ.get("HKU_UID", "")
HKU_PIN: str = os.environ.get("HKU_PIN", "")

BOOKING_BASE_URL = _setting("booking_base_url")
BOOKING_SECURE_BASE_URL = _setting("booking_secure_base_url")
DEFAULT_BOOKING_PURPOSE = _setting("default_booking_purpose", "BOOKING_PURPOSE")
DEFAULT_ROOM_TARGET = _setting("default_room_target")
HEADLESS = _bool_setting("headless")

LOG_FILE = ROOT / "logs" / "bookings.log"
HKT_TIMEZONE = _setting("timezone", "HKT_TIMEZONE")
