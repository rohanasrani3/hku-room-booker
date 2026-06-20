import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HKU_UID: str = os.environ.get("HKU_UID", "")
HKU_PIN: str = os.environ.get("HKU_PIN", "")

BOOKING_BASE_URL = "https://booking.lib.hku.hk/"

# Chi Wah Learning Commons room type → booking page URL
# lib=5 is Chi Wah; ftype=29 is group study rooms (verified), ftype=30 is discussion/AV (to confirm)
ROOM_URLS: dict[str, str] = {
    "group":      "https://booking.lib.hku.hk/FView.aspx?lib=5&ftype=29",
    "discussion": "https://booking.lib.hku.hk/FView.aspx?lib=5&ftype=30",
}

LOG_FILE = Path(__file__).parent / "logs" / "bookings.log"
HKT_TIMEZONE = "Asia/Hong_Kong"
