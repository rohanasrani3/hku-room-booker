import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

HKU_UID: str = os.environ.get("HKU_UID", "")
HKU_PIN: str = os.environ.get("HKU_PIN", "")

BOOKING_BASE_URL = "https://booking.lib.hku.hk/getpatron.aspx"

LOG_FILE = Path(__file__).parent / "logs" / "bookings.log"
HKT_TIMEZONE = "Asia/Hong_Kong"
