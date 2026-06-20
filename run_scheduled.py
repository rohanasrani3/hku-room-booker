#!/usr/bin/env python3
"""
Reads bookings.json and books any pending entries whose date = tomorrow HKT.

The cron in book.yml fires at 16:00 UTC = midnight HKT.  At that moment,
"tomorrow HKT" is the date whose booking window just opened.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HKT = ZoneInfo("Asia/Hong_Kong")
BOOKINGS_FILE = Path(__file__).parent / "bookings.json"


def tomorrow_hkt() -> str:
    return (datetime.now(tz=HKT).date() + timedelta(days=1)).strftime("%Y-%m-%d")


def main() -> None:
    if not BOOKINGS_FILE.exists():
        print("bookings.json not found — nothing to do.")
        return

    with open(BOOKINGS_FILE) as f:
        bookings = json.load(f)

    target = tomorrow_hkt()
    print(f"Midnight HKT — looking for pending bookings on {target}...")

    any_attempted = False
    for entry in bookings:
        if entry.get("status") != "pending":
            continue
        if entry.get("date") != target:
            continue

        any_attempted = True
        print(f"  → Booking: {entry['date']} {entry['time']} "
              f"{entry['duration']}h {entry.get('room_type', 'group')}")

        result = subprocess.run(
            [
                sys.executable, "book.py",
                "--date",      entry["date"],
                "--time",      entry["time"],
                "--duration",  str(entry["duration"]),
                "--room-type", entry.get("room_type", "group"),
                "--now",
            ]
        )
        entry["status"] = "booked" if result.returncode == 0 else "failed"

    if not any_attempted:
        print(f"  No pending bookings for {target}.")

    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=2)


if __name__ == "__main__":
    main()
