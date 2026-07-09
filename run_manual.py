#!/usr/bin/env python3
"""Dispatch a manual request as immediate or future based on the target date."""

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from booker import BOOKING_TARGETS
from config import HKT_TIMEZONE

HKT = ZoneInfo(HKT_TIMEZONE)
ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or queue an HKU room booking.")
    parser.add_argument("--date", required=True, help="Target booking date, YYYY-MM-DD.")
    parser.add_argument("--time", required=True, dest="start_time", help="Start time, HH:MM.")
    parser.add_argument("--duration", required=True, help="Hours to book, 1-4.")
    parser.add_argument(
        "--room-target",
        "--room-type",
        dest="room_target",
        choices=BOOKING_TARGETS,
        default="all_study_rooms",
        help="Study-space target.",
    )
    return parser.parse_args()


def parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        sys.exit("Date must be YYYY-MM-DD.")


def main() -> None:
    args = parse_args()
    target_date = parse_date(args.date)
    today_hkt = datetime.now(tz=HKT).date()

    if target_date < today_hkt:
        sys.exit("Target date is in the past.")

    base_args = [
        "--date", args.date,
        "--time", args.start_time,
        "--duration", args.duration,
        "--room-target", args.room_target,
        "--purpose", "Study",
    ]

    if target_date <= today_hkt + timedelta(days=1):
        print("Booking window is open or opens today; running immediate booking.", flush=True)
        command = [sys.executable, "book.py", *base_args, "--now"]
    else:
        print("Booking date is after tomorrow; queueing future automatic booking.", flush=True)
        command = [sys.executable, "queue_booking.py", *base_args]

    raise SystemExit(subprocess.run(command, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
