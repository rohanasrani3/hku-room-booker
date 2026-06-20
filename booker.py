"""
Booking logic for HKU Chi Wah Learning Commons.

Actual page structure (discovered 2026-06-19):
  - Booking form URL:
      NewBooking.aspx?library=5&ftype=29&facility=FACILITY&date=YYYYMMDD&session=HHMMHHMM
  - Sessions are 1-hour blocks, e.g. '09001000' = 09:00–10:00
    (last slot of day: '23002345' = 23:00–23:45)
  - URL params pre-select date, facility, and first session checkbox
  - Submit → optional Yes/No confirm → optional Skip Email → result
  - Known Chi Wah study room facility IDs: 258–276 (non-contiguous)
"""

import logging
from datetime import date, time

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from auth import login

log = logging.getLogger(__name__)

BASE = "https://booking.lib.hku.hk/Secure"

# Chi Wah study room facility IDs (scraped from status page, June 2026).
# Study Rooms 2–20 (room numbers skip 1,6,11,16,17 which don't exist).
STUDY_ROOM_FACILITIES = [258, 259, 260, 261, 263, 264, 265, 266, 268, 269, 270, 271, 274, 275, 276]

ROOM_TYPE_CONFIG = {
    "group":      {"library": 5, "ftype": 29, "facilities": STUDY_ROOM_FACILITIES},
    "discussion": {"library": 5, "ftype": 30, "facilities": STUDY_ROOM_FACILITIES},  # ftype 30 = TBC
}


# ── Session helpers ───────────────────────────────────────────────────────────

def _session_str(start_hour: int) -> str:
    """Return the HHMMHHMM session string for an hour-block starting at start_hour."""
    if start_hour == 23:
        return "23002345"
    return f"{start_hour:02d}00{start_hour + 1:02d}00"


def _sessions_for(start: time, duration_hours: int) -> list[str]:
    """List of session strings covering start_time + duration_hours hours."""
    return [_session_str(start.hour + i) for i in range(duration_hours)]


# ── Booking helpers ───────────────────────────────────────────────────────────

async def _visible(page: Page, selector: str, timeout: int = 3_000) -> bool:
    """Return True if the element appears within timeout ms."""
    try:
        await page.locator(selector).wait_for(state="visible", timeout=timeout)
        return True
    except PWTimeout:
        return False


async def _try_book_facility(
    page: Page,
    facility_id: int,
    library: int,
    ftype: int,
    target_date: date,
    sessions: list[str],
    dry_run: bool,
) -> bool:
    """Try to book one specific facility. Returns True on confirmed success."""
    date_str    = target_date.strftime("%Y%m%d")
    date_iso    = target_date.strftime("%Y-%m-%d")
    booking_url = (
        f"{BASE}/NewBooking.aspx?"
        f"library={library}&ftype={ftype}"
        f"&facility={facility_id}&date={date_str}&session={sessions[0]}"
    )

    log.info(f"  Trying facility {facility_id}")
    await page.goto(booking_url, wait_until="networkidle")

    # Bail out if we were redirected off the booking form
    if "NewBooking.aspx" not in page.url:
        log.warning(f"  Facility {facility_id}: unexpected redirect → {page.url}")
        return False

    # Verify all required session checkboxes exist and are available
    for session in sessions:
        cb = page.locator(f"input[type='checkbox'][value='{session}']")
        if not await cb.count():
            log.warning(f"  Session {session} not on form (outside library hours?)")
            return False
        if not await cb.is_enabled():
            log.info(f"  Facility {facility_id}: session {session} is already booked")
            return False

    # Tick all required sessions (first one is pre-checked by URL param)
    for session in sessions:
        cb = page.locator(f"input[type='checkbox'][value='{session}']")
        if not await cb.is_checked():
            await cb.click()
            log.info(f"  Checked session {session}")

    # Ensure correct date is selected (URL param pre-selects it, but verify)
    current_date = await page.evaluate("document.getElementById('main_ddlDate').value")
    if current_date != date_iso:
        await page.select_option("select#main_ddlDate", date_iso)
        log.info(f"  Corrected date → {date_iso}")

    if dry_run:
        log.info("  [dry-run] Stopping before Submit.")
        return True

    # ── Submit ────────────────────────────────────────────────────────────────
    await page.click("input[name='ctl00$main$btnSubmit']")
    await page.wait_for_load_state("networkidle")

    # Optional Yes/No confirmation step
    if await _visible(page, "input[name='ctl00$main$btnSubmitYes']"):
        await page.click("input[name='ctl00$main$btnSubmitYes']")
        await page.wait_for_load_state("networkidle")

    # Optional email step — always skip
    if await _visible(page, "input[name='ctl00$main$btnSkipEmail']"):
        await page.click("input[name='ctl00$main$btnSkipEmail']")
        await page.wait_for_load_state("networkidle")

    # ── Detect outcome ────────────────────────────────────────────────────────
    page_text = (await page.inner_text("body")).lower()

    error_words = ["not available", "already booked", "conflict", "exceed", "invalid", "error"]
    if any(w in page_text for w in error_words):
        log.info(f"  Facility {facility_id}: server rejected booking")
        return False

    success_words = ["successfully", "confirmed", "booking ref", "receipt", "thank", "booked"]
    if any(w in page_text for w in success_words):
        if await _visible(page, "input[name='ctl00$main$btnCloseResult']", timeout=2_000):
            await page.click("input[name='ctl00$main$btnCloseResult']")
        log.info(f"  Facility {facility_id}: BOOKED ✓")
        return True

    log.warning(f"  Facility {facility_id}: ambiguous result → {page_text[:300]}")
    return False


# ── Public entry point ────────────────────────────────────────────────────────

async def book_room(
    target_date: date,
    start_time: time,
    duration_hours: int,
    room_type: str,
    headless: bool = True,
    dry_run: bool = False,
) -> bool:
    """
    Login, then try each Chi Wah facility in order until one is successfully booked
    for target_date, start_time, duration_hours hours.  Returns True on success.
    """
    cfg      = ROOM_TYPE_CONFIG[room_type]
    sessions = _sessions_for(start_time, duration_hours)
    log.info(
        f"Booking {room_type} room | {target_date} | "
        f"{start_time.strftime('%H:%M')} for {duration_hours}h | "
        f"sessions={sessions}"
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()
        try:
            await login(page)
            for facility_id in cfg["facilities"]:
                try:
                    ok = await _try_book_facility(
                        page, facility_id,
                        cfg["library"], cfg["ftype"],
                        target_date, sessions, dry_run,
                    )
                    if ok:
                        return True
                except Exception:
                    log.exception(f"  Exception on facility {facility_id} — trying next")
            log.error("All facilities tried — none available.")
            return False
        finally:
            await browser.close()
