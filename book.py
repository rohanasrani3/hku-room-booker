#!/usr/bin/env python3
"""
HKU Chi Wah automatic room booker.

The booking window for a given date opens at midnight HKT on the day before.
This script sleeps until that exact moment, then fires the Playwright booking.

Sessions are 1-hour blocks (08:00–09:00, 09:00–10:00, … 22:00–23:00, 23:00–23:45).
--duration is the number of consecutive hours to book (integer, 1–4).

Usage:
    python book.py --date YYYY-MM-DD --time HH:MM --duration HOURS \\
                   --room-type [group|discussion]

    python book.py --date tomorrow   --time 10:00 --duration 2 --room-type group
    python book.py --date 2026-06-22 --time 09:00 --duration 3 --room-type group

Flags:
    --no-headless   Show the browser window (useful for debugging)
    --dry-run       Go through all steps but skip the final form submit
    --now           Skip the midnight wait and book immediately

Background (keep running after closing terminal):
    nohup python book.py --date tomorrow --time 10:00 --duration 2 \\
          --room-type group > /dev/null 2>&1 & disown
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import LOG_FILE, HKT_TIMEZONE
from booker import book_room

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
        description="Automatically book a Chi Wah study room at HKU library.",
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
        "--room-type", choices=["group", "discussion"], default="group",
        help="'group' = group study room (≥3 people); 'discussion' = AV/discussion room",
    )
    p.add_argument(
        "--no-headless", action="store_true",
        help="Show the Chromium browser window (for debugging)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Fill in the form but do NOT submit",
    )
    p.add_argument(
        "--now", action="store_true",
        help="Skip the midnight wait and book immediately",
    )
    return p.parse_args()


def resolve_date(raw: str) -> date:
    if raw.lower() == "tomorrow":
        return date.today() + timedelta(days=1)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        sys.exit(f"Invalid date '{raw}'. Use YYYY-MM-DD or 'tomorrow'.")


def midnight_hkt_before(target: date) -> datetime:
    """HKT midnight that opens the booking window for target (00:00 of the day before)."""
    prev = target - timedelta(days=1)
    return datetime(prev.year, prev.month, prev.day, 0, 0, 0, tzinfo=HKT)


def seconds_until(dt: datetime) -> float:
    return (dt - datetime.now(tz=HKT)).total_seconds()


async def main() -> None:
    setup_logging()
    args = parse_args()
    log = logging.getLogger(__name__)

    target_date    = resolve_date(args.date)
    duration_hours = args.duration

    if duration_hours < 1 or duration_hours > 4:
        sys.exit("--duration must be between 1 and 4 hours.")

    try:
        start_time = datetime.strptime(args.start_time, "%H:%M").time()
    except ValueError:
        sys.exit(f"Invalid time '{args.start_time}'. Use HH:MM in 24h format.")

    if start_time.minute != 0:
        sys.exit("Start time must be on the hour (e.g. 10:00, not 10:30). Sessions are 1-hour blocks.")

    log.info(
        f"Queued: {target_date} | {args.start_time} | "
        f"{duration_hours}h | {args.room_type} room"
    )

    if not args.now:
        opening   = midnight_hkt_before(target_date)
        wait_secs = seconds_until(opening)
        if wait_secs > 0:
            log.info(
                f"Waiting until {opening.strftime('%Y-%m-%d %H:%M HKT')} "
                f"({wait_secs/3600:.1f}h away)..."
            )
            time.sleep(wait_secs)
            log.info("Booking window open — starting now.")
        else:
            log.info("Booking window already open — proceeding immediately.")
    else:
        log.info("--now flag set — booking immediately.")

    for attempt in range(1, 4):
        log.info(f"Attempt {attempt}/3")
        success = await book_room(
            target_date=target_date,
            start_time=start_time,
            duration_hours=duration_hours,
            room_type=args.room_type,
            headless=not args.no_headless,
            dry_run=args.dry_run,
        )
        if success:
            log.info(f"DONE — {target_date} {args.start_time} ({duration_hours}h, {args.room_type})")
            sys.exit(0)
        if attempt < 3:
            log.warning("Retrying in 30 seconds...")
            time.sleep(30)

    log.error(f"FAILED after 3 attempts — {target_date} {args.start_time} ({args.room_type})")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
