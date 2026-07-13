#!/usr/bin/env python3
"""Run due future bookings from bookings.json."""

import json
import subprocess
import sys
import time as sleeper
from datetime import datetime, timedelta, date, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config import DEFAULT_ROOM_TARGET, HKT_TIMEZONE

HKT = ZoneInfo(HKT_TIMEZONE)
BOOKINGS_FILE = Path(__file__).parent / "bookings.json"


def today_hkt() -> date:
    return datetime.now(tz=HKT).date()


def booking_window_target() -> date:
    return today_hkt() + timedelta(days=1)


def parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def booking_target(entry: dict) -> str:
    return entry.get("room_target") or entry.get("room_type") or DEFAULT_ROOM_TARGET


def wait_until_booking_window() -> None:
    now = datetime.now(tz=HKT)
    if now.hour != 23:
        return

    midnight = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=HKT)
    wait_seconds = (midnight - now).total_seconds()
    if wait_seconds > 0:
        print(f"Scheduled runner started before midnight HKT; waiting {wait_seconds / 60:.1f} minutes.")
        sleeper.sleep(wait_seconds + 1)


def save_bookings(bookings: list[dict]) -> None:
    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=2)
        f.write("\n")


def main() -> None:
    if not BOOKINGS_FILE.exists():
        print("bookings.json not found — nothing to do.")
        return

    with open(BOOKINGS_FILE) as f:
        bookings = json.load(f)

    if not isinstance(bookings, list):
        print("bookings.json must contain a JSON list.")
        sys.exit(1)

    wait_until_booking_window()

    now = datetime.now(tz=HKT).isoformat(timespec="seconds")
    target = booking_window_target()
    print(f"Midnight HKT — looking for pending bookings on {target.isoformat()}...")

    any_attempted = False
    any_failed = False
    for entry in bookings:
        if entry.get("status") != "pending":
            continue

        entry_date = parse_date(entry.get("date", ""))
        if entry_date is None:
            entry["status"] = "invalid"
            entry["last_error"] = "Invalid or missing date."
            entry["updated_at"] = now
            any_failed = True
            continue

        if entry_date < target:
            entry["status"] = "expired"
            entry["last_error"] = "Booking window has already passed."
            entry["updated_at"] = now
            print(f"  Marked expired: {entry.get('date')} {entry.get('time')}")
            continue

        if entry_date != target:
            continue

        any_attempted = True
        entry["attempt_count"] = int(entry.get("attempt_count", 0)) + 1
        entry["last_attempt_at"] = now
        print(
            f"  Booking: {entry['date']} {entry['time']} "
            f"{entry['duration']}h target={booking_target(entry)}"
        )

        result = subprocess.run(
            [
                sys.executable, "book.py",
                "--date",      entry["date"],
                "--time",      entry["time"],
                "--duration",  str(entry["duration"]),
                "--room-target", booking_target(entry),
            ]
        )
        if result.returncode == 0:
            entry["status"] = "booked"
            entry.pop("last_error", None)
        elif result.returncode == 2:
            entry["status"] = "unavailable"
            entry["last_error"] = "No matching room could be booked for this date/time."
            any_failed = True
        else:
            entry["status"] = "failed"
            entry["last_error"] = f"book.py exited with {result.returncode}"
            any_failed = True
        entry["updated_at"] = now

    if not any_attempted:
        print(f"  No pending bookings for {target.isoformat()}.")

    save_bookings(bookings)

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
