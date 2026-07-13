#!/usr/bin/env python3
"""
HKU Library automatic room booker.

The booking window for a given date opens at midnight HKT on the day before.
Future bookings should be queued with run_manual.py or queue_booking.py.

Sessions are 1-hour blocks (08:00–09:00, 09:00–10:00, … 22:00–23:00, 23:00–23:45).
--duration is the number of consecutive hours to book (integer, 1–4).

Usage:
    python book.py --date YYYY-MM-DD --time HH:MM --duration HOURS \\
                   --room-target all_study_rooms

    python book.py --date tomorrow   --time 10:00 --duration 2 --room-target all_study_rooms
    python book.py --date 2026-06-22 --time 09:00 --duration 3 --room-target discussion_rooms

Background (keep running after closing terminal):
    nohup python book.py --date tomorrow --time 10:00 --duration 2 \\
          --room-target all_study_rooms > /dev/null 2>&1 & disown
"""

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import DEFAULT_ROOM_TARGET, HEADLESS, LOG_FILE, HKT_TIMEZONE
from booker import book_room
from room_catalog import normalize_target

HKT = ZoneInfo(HKT_TIMEZONE)


def setup_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Automatically book an HKU library study room.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--date", required=True,
        help="Target booking date: YYYY-MM-DD or 'tomorrow'",
    )
    p.add_argument(
        "--time", required=True, dest="start_time",
        help="Start time in 24h format, e.g. 10:00",
    )
    p.add_argument(
        "--duration", type=int, required=True,
        help="Number of consecutive 1-hour sessions to book (1–4)",
    )
    p.add_argument(
        "--room-target",
        dest="room_target",
        default=DEFAULT_ROOM_TARGET,
        help="Study-space target.",
    )
    return p.parse_args()


def resolve_date(raw: str) -> date:
    if raw.lower() == "tomorrow":
        return datetime.now(tz=HKT).date() + timedelta(days=1)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        sys.exit(f"Invalid date '{raw}'. Use YYYY-MM-DD or 'tomorrow'.")


async def main() -> None:
    setup_logging()
    args = parse_args()
    log = logging.getLogger(__name__)

    target_date    = resolve_date(args.date)
    duration_hours = args.duration
    today_hkt = datetime.now(tz=HKT).date()

    if duration_hours < 1 or duration_hours > 4:
        sys.exit("--duration must be between 1 and 4 hours.")
    try:
        args.room_target = normalize_target(args.room_target)
    except ValueError as exc:
        sys.exit(str(exc))

    try:
        start_time = datetime.strptime(args.start_time, "%H:%M").time()
    except ValueError:
        sys.exit(f"Invalid time '{args.start_time}'. Use HH:MM in 24h format.")

    if start_time.minute != 0:
        sys.exit("Start time must be on the hour (e.g. 10:00, not 10:30). Sessions are 1-hour blocks.")
    if start_time.hour + duration_hours > 24:
        sys.exit("Booking duration cannot run past midnight.")
    if target_date < today_hkt:
        sys.exit("Target date is in the past.")
    if target_date > today_hkt + timedelta(days=1):
        sys.exit(
            "The booking window is not open for that date yet. "
            "Use the manual workflow to queue it automatically."
        )

    log.info(
        f"Queued: {target_date} | {args.start_time} | "
        f"{duration_hours}h | target={args.room_target}"
    )

    log.info("Booking immediately.")

    for attempt in range(1, 4):
        log.info(f"Attempt {attempt}/3")
        result = await book_room(
            target_date=target_date,
            start_time=start_time,
            duration_hours=duration_hours,
            room_target=args.room_target,
            headless=HEADLESS,
        )
        if result.success:
            log.info(f"DONE — {target_date} {args.start_time} ({duration_hours}h, {args.room_target})")
            sys.exit(0)
        if not result.retryable:
            log.error("STOPPED — %s", result.reason)
            sys.exit(2)
        if attempt < 3:
            log.warning("Retrying in 30 seconds after retryable issue: %s", result.reason)
            await asyncio.sleep(30)

    log.error(f"FAILED after 3 attempts — {target_date} {args.start_time} ({args.room_target})")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
