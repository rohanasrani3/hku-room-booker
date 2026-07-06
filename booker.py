"""Booking logic for HKU Library bookable study spaces."""

from dataclasses import dataclass
import logging
from datetime import date, time
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from auth import login

log = logging.getLogger(__name__)

BASE = "https://booking.lib.hku.hk/Secure"
NEW_BOOKING_URL = f"{BASE}/NewBooking.aspx"


@dataclass(frozen=True)
class TargetRule:
    description: str
    library_keywords: tuple[str, ...] = ()
    type_keywords: tuple[str, ...] = ()
    type_exact: tuple[str, ...] = ()
    exclude_type_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class FacilityCandidate:
    library_id: int
    library_name: str
    ftype_id: int
    type_name: str
    facility_id: int
    facility_name: str


TARGET_RULES: dict[str, TargetRule] = {
    "all_study_rooms": TargetRule(
        "All bookable HKU study rooms, discussion rooms, single study rooms, and study booths",
        type_keywords=("study room", "discussion room", "study booth"),
        exclude_type_keywords=("study table",),
    ),
    "chi_wah_study_rooms": TargetRule(
        "Chi Wah Learning Commons study rooms",
        library_keywords=("chi wah",),
        type_exact=("study room",),
    ),
    "chi_wah_study_booths": TargetRule(
        "Chi Wah Learning Commons study booths",
        library_keywords=("chi wah",),
        type_exact=("study booth",),
    ),
    "discussion_rooms": TargetRule(
        "Discussion rooms in all HKU libraries",
        type_exact=("discussion room",),
    ),
    "single_study_rooms": TargetRule(
        "Single study rooms in all HKU libraries",
        type_keywords=("single study room",),
    ),
    "study_tables": TargetRule(
        "Bookable study tables",
        type_keywords=("study table",),
    ),
    "main_library_discussion_rooms": TargetRule(
        "Main Library discussion rooms",
        library_keywords=("main library",),
        type_exact=("discussion room",),
    ),
    "main_library_single_study_rooms": TargetRule(
        "Main Library single study rooms",
        library_keywords=("main library",),
        type_keywords=("single study room",),
    ),
    "dental_discussion_rooms": TargetRule(
        "Dental Library discussion rooms",
        library_keywords=("dental",),
        type_exact=("discussion room",),
    ),
    "law_discussion_rooms": TargetRule(
        "Law Library discussion rooms",
        library_keywords=("law library",),
        type_exact=("discussion room",),
    ),
    "medical_discussion_rooms": TargetRule(
        "Medical Library discussion rooms",
        library_keywords=("medical library",),
        type_exact=("discussion room",),
    ),
    "medical_single_study_rooms": TargetRule(
        "Medical Library single study rooms",
        library_keywords=("medical library",),
        type_keywords=("single study room",),
    ),
    "music_discussion_rooms": TargetRule(
        "Music Library discussion rooms",
        library_keywords=("music library",),
        type_exact=("discussion room",),
    ),
}

TARGET_ALIASES = {
    "all": "all_study_rooms",
    "group": "chi_wah_study_rooms",
    "study": "chi_wah_study_rooms",
    "booth": "chi_wah_study_booths",
    "discussion": "discussion_rooms",
    "single": "single_study_rooms",
}

BOOKING_TARGETS = tuple(sorted((*TARGET_RULES.keys(), *TARGET_ALIASES.keys())))

# Fallback for the old Chi Wah-only path if live dropdown discovery fails.
CHI_WAH_STUDY_ROOM_FALLBACKS = [
    FacilityCandidate(5, "Chi Wah Learning Commons", 29, "Study Room", facility_id, f"Study Room {room_no}")
    for facility_id, room_no in (
        (258, 2), (259, 3), (260, 4), (261, 5), (263, 7), (264, 8),
        (265, 9), (266, 10), (268, 12), (269, 13), (270, 14),
        (271, 15), (274, 18), (275, 19), (276, 20), (277, 21),
    )
]


# ── Session helpers ───────────────────────────────────────────────────────────

def _session_str(start_hour: int) -> str:
    """Return the HHMMHHMM session string for an hour-block starting at start_hour."""
    if start_hour == 23:
        return "23002345"
    return f"{start_hour:02d}00{start_hour + 1:02d}00"


def _sessions_for(start: time, duration_hours: int) -> list[str]:
    """List of session strings covering start_time + duration_hours hours."""
    return [_session_str(start.hour + i) for i in range(duration_hours)]


def _session_time(session_part: str) -> str:
    """Convert HHMM from a session token into HH:MM."""
    return f"{session_part[:2]}:{session_part[2:]}"


def _booking_record_times(sessions: list[str]) -> tuple[str, str]:
    return _session_time(sessions[0][:4]), _session_time(sessions[-1][4:])


# ── Booking helpers ───────────────────────────────────────────────────────────

async def _visible(page: Page, selector: str, timeout: int = 3_000) -> bool:
    """Return True if the element appears within timeout ms."""
    try:
        await page.locator(selector).wait_for(state="visible", timeout=timeout)
        return True
    except PWTimeout:
        return False


async def _select_options(page: Page, selector: str) -> list[dict[str, str]]:
    return await page.locator(selector).evaluate(
        """select => [...select.options].map(option => ({
            value: option.value,
            text: option.textContent.trim()
        })).filter(option => option.value)"""
    )


async def _select_option_and_wait(page: Page, selector: str, value: str) -> None:
    try:
        async with page.expect_navigation(wait_until="networkidle", timeout=10_000):
            await page.select_option(selector, value)
    except PWTimeout:
        await page.wait_for_load_state("networkidle")


async def _matching_booking_record_exists(
    page: Page,
    target_date: date,
    sessions: list[str],
) -> bool:
    """Return True if My Booking Record already contains this date/time."""
    start_label, end_label = _booking_record_times(sessions)

    await page.goto(f"{BASE}/MyBookingRecord.aspx", wait_until="networkidle")
    rows = await page.locator("tr").evaluate_all(
        """rows => rows.map(row => [...row.cells]
            .map(cell => cell.innerText.trim())
            .filter(Boolean))"""
    )

    for cells in rows:
        row_text = " ".join(cells).lower()
        if (
            target_date.isoformat() in row_text
            and start_label in row_text
            and end_label in row_text
            and "booked" in row_text
        ):
            log.info("Matching booking already appears in My Booking Record: %s", " | ".join(cells))
            return True

    return False


def _normalize_target(room_target: str) -> str:
    normalized = room_target.strip().lower().replace("-", "_")
    normalized = TARGET_ALIASES.get(normalized, normalized)
    if normalized not in TARGET_RULES:
        known = ", ".join(sorted(TARGET_RULES))
        raise ValueError(f"Unknown room target '{room_target}'. Known targets: {known}")
    return normalized


def _matches_rule(rule: TargetRule, library_name: str, type_name: str) -> bool:
    library = library_name.lower()
    ftype = type_name.lower()

    if rule.library_keywords and not any(keyword in library for keyword in rule.library_keywords):
        return False
    if rule.type_exact and ftype not in rule.type_exact:
        return False
    if rule.type_keywords and not any(keyword in ftype for keyword in rule.type_keywords):
        return False
    if rule.exclude_type_keywords and any(keyword in ftype for keyword in rule.exclude_type_keywords):
        return False
    return True


async def _discover_facilities(page: Page, room_target: str) -> list[FacilityCandidate]:
    """Discover live facility IDs from the HKU booking form dropdowns."""
    normalized = _normalize_target(room_target)
    rule = TARGET_RULES[normalized]
    candidates: list[FacilityCandidate] = []

    await page.goto(NEW_BOOKING_URL, wait_until="networkidle")
    libraries = await _select_options(page, "#main_ddlLibrary")

    for library in libraries:
        if rule.library_keywords and not _matches_rule(
            TargetRule("", library_keywords=rule.library_keywords),
            library["text"],
            "",
        ):
            continue

        await page.goto(NEW_BOOKING_URL, wait_until="networkidle")
        await _select_option_and_wait(page, "#main_ddlLibrary", library["value"])
        facility_types = await _select_options(page, "#main_ddlType")

        for facility_type in facility_types:
            if not _matches_rule(rule, library["text"], facility_type["text"]):
                continue

            await page.goto(NEW_BOOKING_URL, wait_until="networkidle")
            await _select_option_and_wait(page, "#main_ddlLibrary", library["value"])
            await _select_option_and_wait(page, "#main_ddlType", facility_type["value"])
            facilities = await _select_options(page, "#main_ddlFacility")

            for facility in facilities:
                candidates.append(
                    FacilityCandidate(
                        library_id=int(library["value"]),
                        library_name=library["text"],
                        ftype_id=int(facility_type["value"]),
                        type_name=facility_type["text"],
                        facility_id=int(facility["value"]),
                        facility_name=facility["text"],
                    )
                )

    if not candidates and normalized == "chi_wah_study_rooms":
        log.warning("Live discovery found no Chi Wah study rooms; using static fallback IDs.")
        candidates = CHI_WAH_STUDY_ROOM_FALLBACKS

    log.info("Discovered %s facilities for target '%s'.", len(candidates), normalized)
    for candidate in candidates[:20]:
        log.info(
            "  %s | %s | %s",
            candidate.library_name,
            candidate.type_name,
            candidate.facility_name,
        )
    if len(candidates) > 20:
        log.info("  ...and %s more facilities", len(candidates) - 20)

    return candidates


async def _try_book_facility(
    page: Page,
    candidate: FacilityCandidate,
    target_date: date,
    sessions: list[str],
    purpose: str,
    dry_run: bool,
) -> bool:
    """Try to book one specific facility. Returns True on confirmed success."""
    date_str    = target_date.strftime("%Y%m%d")
    date_iso    = target_date.strftime("%Y-%m-%d")
    query = urlencode(
        {
            "library": candidate.library_id,
            "ftype": candidate.ftype_id,
            "facility": candidate.facility_id,
            "date": date_str,
            "session": sessions[0],
        }
    )
    booking_url = f"{NEW_BOOKING_URL}?{query}"

    log.info(
        "  Trying %s | %s | %s (%s)",
        candidate.library_name,
        candidate.type_name,
        candidate.facility_name,
        candidate.facility_id,
    )
    await page.goto(booking_url, wait_until="networkidle")

    # Bail out if we were redirected off the booking form
    if "NewBooking.aspx" not in page.url:
        log.warning(f"  Facility {candidate.facility_id}: unexpected redirect → {page.url}")
        return False

    # Verify all required session checkboxes exist and are available
    for session in sessions:
        cb = page.locator(f"input[type='checkbox'][value='{session}']")
        if not await cb.count():
            log.warning(f"  Session {session} not on form (outside library hours?)")
            return False
        if not await cb.is_enabled():
            log.info(f"  Facility {candidate.facility_id}: session {session} is already booked")
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

    if await page.locator("#main_txtUserDescription").count():
        await page.fill("#main_txtUserDescription", purpose)

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
        if await _matching_booking_record_exists(page, target_date, sessions):
            log.info(f"  Facility {candidate.facility_id}: booking verified in My Booking Record")
            return True
        log.info(f"  Facility {candidate.facility_id}: server rejected booking")
        return False

    success_words = ["successfully", "confirmed", "booking ref", "receipt", "thank", "booked"]
    if any(w in page_text for w in success_words):
        if await _visible(page, "input[name='ctl00$main$btnCloseResult']", timeout=2_000):
            await page.click("input[name='ctl00$main$btnCloseResult']")
        log.info(f"  Facility {candidate.facility_id}: BOOKED")
        return True

    if await _matching_booking_record_exists(page, target_date, sessions):
        log.info(f"  Facility {candidate.facility_id}: booking verified in My Booking Record")
        return True

    log.warning(f"  Facility {candidate.facility_id}: ambiguous result → {page_text[:300]}")
    return False


# ── Public entry point ────────────────────────────────────────────────────────

async def book_room(
    target_date: date,
    start_time: time,
    duration_hours: int,
    room_target: str,
    purpose: str = "Study",
    headless: bool = True,
    dry_run: bool = False,
) -> bool:
    """
    Login, then try each matching HKU facility in order until one is successfully booked
    for target_date, start_time, duration_hours hours.  Returns True on success.
    """
    sessions = _sessions_for(start_time, duration_hours)
    normalized_target = _normalize_target(room_target)
    log.info(
        f"Booking target={normalized_target} | {target_date} | "
        f"{start_time.strftime('%H:%M')} for {duration_hours}h | "
        f"sessions={sessions}"
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        ctx     = await browser.new_context()
        page    = await ctx.new_page()
        try:
            await login(page)
            if await _matching_booking_record_exists(page, target_date, sessions):
                log.info("DONE — matching booking already exists.")
                return True

            candidates = await _discover_facilities(page, normalized_target)
            if not candidates:
                log.error("No matching facilities found for target '%s'.", normalized_target)
                return False

            for candidate in candidates:
                try:
                    ok = await _try_book_facility(
                        page,
                        candidate,
                        target_date,
                        sessions,
                        purpose,
                        dry_run,
                    )
                    if ok:
                        return True
                except Exception:
                    log.exception(f"  Exception on facility {candidate.facility_id} — trying next")
            log.error("All facilities tried — none available.")
            return False
        finally:
            await browser.close()
