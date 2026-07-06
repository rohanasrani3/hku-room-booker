#!/usr/bin/env python3
"""Queue a future HKU room booking in bookings.json."""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from booker import BOOKING_TARGETS
from config import HKT_TIMEZONE

HKT = ZoneInfo(HKT_TIMEZONE)
BOOKINGS_FILE = Path(__file__).parent / "bookings.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue a future booking for the scheduled GitHub Action.")
    parser.add_argument("--date", required=True, help="Target booking date, YYYY-MM-DD.")
    parser.add_argument("--time", required=True, dest="start_time", help="Start time, HH:MM on the hour.")
    parser.add_argument("--duration", type=int, required=True, help="Hours to book, 1-4.")
    parser.add_argument(
        "--room-target",
        "--room-type",
        dest="room_target",
        choices=BOOKING_TARGETS,
        default="all_study_rooms",
        help="Study-space target.",
    )
    parser.add_argument("--purpose", default="Study", help="Booking description/purpose.")
    return parser.parse_args()


def load_bookings() -> list[dict]:
    if not BOOKINGS_FILE.exists():
        return []

    with open(BOOKINGS_FILE) as f:
        data = json.load(f)

    if not isinstance(data, list):
        sys.exit("bookings.json must contain a JSON list.")
    return data


def validate_args(args: argparse.Namespace) -> tuple[str, str]:
    try:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    except ValueError:
        sys.exit("Date must be YYYY-MM-DD.")

    try:
        start_time = datetime.strptime(args.start_time, "%H:%M").time()
    except ValueError:
        sys.exit("Time must be HH:MM in 24-hour format.")

    if start_time.minute != 0:
        sys.exit("Start time must be on the hour.")
    if args.duration < 1 or args.duration > 4:
        sys.exit("Duration must be between 1 and 4 hours.")
    if start_time.hour + args.duration > 24:
        sys.exit("Booking duration cannot run past midnight.")

    today_hkt = datetime.now(tz=HKT).date()
    earliest_schedulable = today_hkt + timedelta(days=2)
    if target_date < earliest_schedulable:
        sys.exit(
            "Future automatic bookings must be at least two HKT dates away. "
            "Use action=book_now for dates whose booking window is already open."
        )

    return target_date.isoformat(), start_time.strftime("%H:%M")


def main() -> None:
    args = parse_args()
    target_date, start_time = validate_args(args)
    bookings = load_bookings()

    entry = {
        "id": f"{target_date}-{start_time}-{args.room_target}-{datetime.now(tz=HKT).strftime('%Y%m%d%H%M%S')}",
        "date": target_date,
        "time": start_time,
        "duration": args.duration,
        "room_target": args.room_target,
        "purpose": args.purpose,
        "status": "pending",
        "created_at": datetime.now(tz=HKT).isoformat(timespec="seconds"),
        "attempt_count": 0,
    }
    bookings.append(entry)

    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=2)
        f.write("\n")

    print(
        f"Queued {entry['date']} {entry['time']} for {entry['duration']}h "
        f"with target={entry['room_target']}."
    )


if __name__ == "__main__":
    main()
