"""Booking logic for HKU Library bookable study spaces."""

from dataclasses import dataclass
import logging
from datetime import date, time
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from auth import login
from config import BOOKING_SECURE_BASE_URL, DEFAULT_BOOKING_PURPOSE
from room_catalog import (
    BOOKING_TARGETS,
    FacilityCandidate,
    STATIC_TARGET_FACILITIES,
    TARGET_RULES,
    TargetRule,
    normalize_target,
)

log = logging.getLogger(__name__)

BASE = BOOKING_SECURE_BASE_URL.rstrip("/")
NEW_BOOKING_URL = f"{BASE}/NewBooking.aspx"


@dataclass(frozen=True)
class BookingResult:
    status: str
    reason: str

    @property
    def success(self) -> bool:
        return self.status == "booked"

    @property
    def retryable(self) -> bool:
        return self.status == "retryable_error"


@dataclass(frozen=True)
class FacilityAttemptResult:
    status: str
    reason: str

    @property
    def booked(self) -> bool:
        return self.status == "booked"


RETRYABLE_ERROR = "retryable_error"
UNAVAILABLE = "unavailable"
TERMINAL_REJECTED = "terminal_rejected"


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


def _booking_record_date_labels(target_date: date) -> tuple[str, ...]:
    return (
        target_date.isoformat(),
        target_date.strftime("%Y/%m/%d"),
        target_date.strftime("%d/%m/%Y"),
        f"{target_date.day}/{target_date.month}/{target_date.year}",
        target_date.strftime("%d %b %Y").lower(),
        target_date.strftime("%b %d, %Y").lower(),
    )


# ── Booking helpers ───────────────────────────────────────────────────────────

async def _select_options(page: Page, selector: str) -> list[dict[str, str]]:
    return await page.locator(selector).evaluate(
        """select => [...select.options].map(option => ({
            value: option.value,
            text: option.textContent.trim()
        })).filter(option => option.value)"""
    )


async def _select_option_and_wait(page: Page, selector: str, value: str) -> None:
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=10_000):
            await page.select_option(selector, value)
    except PWTimeout:
        await page.wait_for_load_state("domcontentloaded")


def _compact_text(raw: str) -> str:
    return " ".join(raw.lower().split())


async def _page_text(page: Page) -> str:
    try:
        return _compact_text(await page.inner_text("body", timeout=5_000))
    except PWTimeout:
        return ""


async def _click_and_settle(page: Page, selector: str, label: str) -> None:
    log.info("  Clicking %s", label)
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15_000):
            await page.click(selector, timeout=10_000)
    except PWTimeout:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except PWTimeout:
            pass
        await page.wait_for_timeout(750)


async def _click_visible_if_present(page: Page, selector: str, label: str) -> bool:
    locator = page.locator(selector)
    try:
        await locator.wait_for(state="visible", timeout=3_000)
    except PWTimeout:
        return False
    await _click_and_settle(page, selector, label)
    return True


def _classify_portal_text(page_text: str) -> FacilityAttemptResult | None:
    """Classify explicit portal messages. My Booking Record is checked separately."""
    if not page_text:
        return FacilityAttemptResult(RETRYABLE_ERROR, "Portal returned an empty or unreadable result page.")

    success_phrases = (
        "booking is successful",
        "booking successful",
        "successfully booked",
        "booking has been confirmed",
        "booking confirmed",
        "booking reference",
        "booking ref",
        "reservation is confirmed",
    )
    if any(phrase in page_text for phrase in success_phrases):
        return FacilityAttemptResult("booked", "Portal reported a successful booking.")

    terminal_phrases = (
        "you have already made a booking",
        "you have made a booking",
        "already have a booking",
        "another booking",
        "same time slot",
        "same timeslot",
        "overlapping booking",
        "booking quota",
        "quota exceeded",
        "maximum number of booking",
        "maximum number of bookings",
        "maximum booking",
        "exceed the maximum",
        "exceeded the maximum",
        "not eligible",
        "not allowed",
        "suspended",
        "blacklisted",
    )
    if any(phrase in page_text for phrase in terminal_phrases):
        return FacilityAttemptResult(
            TERMINAL_REJECTED,
            "Portal rejected the request because the user cannot make this booking.",
        )

    unavailable_phrases = (
        "not available",
        "already booked",
        "has been booked",
        "session is full",
        "no available",
        "selected session is not available",
        "selected sessions are not available",
    )
    if any(phrase in page_text for phrase in unavailable_phrases):
        return FacilityAttemptResult(UNAVAILABLE, "This facility/session is unavailable.")

    validation_phrases = (
        "invalid booking",
        "invalid session",
        "invalid date",
        "required field",
        "cannot be blank",
        "booking error",
    )
    if any(phrase in page_text for phrase in validation_phrases):
        return FacilityAttemptResult(
            TERMINAL_REJECTED,
            "Portal rejected the request with a validation error.",
        )

    return None


async def _matching_booking_record_exists(
    page: Page,
    target_date: date,
    sessions: list[str],
    attempts: int = 1,
    pause_ms: int = 2_000,
) -> bool:
    """Return True if My Booking Record already contains this date/time."""
    start_label, end_label = _booking_record_times(sessions)
    date_labels = _booking_record_date_labels(target_date)

    log.info("Checking My Booking Record for an existing matching booking...")
    for attempt in range(1, attempts + 1):
        try:
            await page.goto(f"{BASE}/MyBookingRecord.aspx", wait_until="domcontentloaded", timeout=20_000)
            rows = await page.locator("tr").evaluate_all(
                """rows => rows.map(row => [...row.cells]
                    .map(cell => cell.innerText.trim())
                    .filter(Boolean))"""
            )
        except PWTimeout:
            log.warning("Timed out while checking My Booking Record.")
            rows = []
        except Exception:
            log.exception("Could not check My Booking Record.")
            rows = []

        for cells in rows:
            row_text = _compact_text(" ".join(cells))
            if (
                any(label in row_text for label in date_labels)
                and start_label in row_text
                and end_label in row_text
                and "booked" in row_text
            ):
                log.info("Matching booking already appears in My Booking Record: %s", " | ".join(cells))
                return True

        if attempt < attempts:
            await page.wait_for_timeout(pause_ms)

    return False


def _normalize_target(room_target: str) -> str:
    return normalize_target(room_target)


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
    if normalized in STATIC_TARGET_FACILITIES:
        candidates = STATIC_TARGET_FACILITIES[normalized]
        log.info("Using %s static facilities for target '%s'.", len(candidates), normalized)
        return candidates

    rule = TARGET_RULES[normalized]
    candidates: list[FacilityCandidate] = []

    log.info("No static facility map for target '%s'; using live dropdown discovery.", normalized)
    await page.goto(NEW_BOOKING_URL, wait_until="domcontentloaded", timeout=20_000)
    libraries = await _select_options(page, "#main_ddlLibrary")

    for library in libraries:
        if rule.library_keywords and not _matches_rule(
            TargetRule("", library_keywords=rule.library_keywords),
            library["text"],
            "",
        ):
            continue

        await page.goto(NEW_BOOKING_URL, wait_until="domcontentloaded", timeout=20_000)
        await _select_option_and_wait(page, "#main_ddlLibrary", library["value"])
        facility_types = await _select_options(page, "#main_ddlType")

        for facility_type in facility_types:
            if not _matches_rule(rule, library["text"], facility_type["text"]):
                continue

            await page.goto(NEW_BOOKING_URL, wait_until="domcontentloaded", timeout=20_000)
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
) -> FacilityAttemptResult:
    """Try to book one specific facility and classify the result."""
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
    await page.goto(booking_url, wait_until="domcontentloaded", timeout=20_000)

    # Bail out if we were redirected off the booking form
    if "NewBooking.aspx" not in page.url:
        log.warning(f"  Facility {candidate.facility_id}: unexpected redirect → {page.url}")
        return FacilityAttemptResult(RETRYABLE_ERROR, f"Unexpected redirect to {page.url}")

    # Verify all required session checkboxes exist and are available
    for session in sessions:
        cb = page.locator(f"input[type='checkbox'][value='{session}']")
        if not await cb.count():
            log.warning(f"  Session {session} not on form (outside library hours?)")
            return FacilityAttemptResult(UNAVAILABLE, "Requested session is not on this facility form.")
        if not await cb.is_enabled():
            log.info(f"  Facility {candidate.facility_id}: session {session} is already booked")
            return FacilityAttemptResult(UNAVAILABLE, "Requested session is already booked for this facility.")

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
        await page.fill("#main_txtUserDescription", DEFAULT_BOOKING_PURPOSE)

    # ── Submit ────────────────────────────────────────────────────────────────
    await _click_and_settle(page, "input[name='ctl00$main$btnSubmit']", "Submit")

    # Optional Yes/No confirmation step
    await _click_visible_if_present(page, "input[name='ctl00$main$btnSubmitYes']", "confirmation")

    # Optional email step — always skip
    await _click_visible_if_present(page, "input[name='ctl00$main$btnSkipEmail']", "Skip email")

    # ── Detect outcome ────────────────────────────────────────────────────────
    page_text = await _page_text(page)
    portal_result = _classify_portal_text(page_text)

    if portal_result and portal_result.booked:
        await _click_visible_if_present(page, "input[name='ctl00$main$btnCloseResult']", "Close result")
        if await _matching_booking_record_exists(page, target_date, sessions, attempts=6, pause_ms=2_000):
            log.info(f"  Facility {candidate.facility_id}: BOOKED")
            return portal_result
        log.warning("  Portal reported success, but My Booking Record could not confirm it yet.")
        log.info(f"  Facility {candidate.facility_id}: BOOKED based on explicit portal success")
        return portal_result

    if await _matching_booking_record_exists(page, target_date, sessions, attempts=6, pause_ms=2_000):
        log.info(f"  Facility {candidate.facility_id}: booking verified in My Booking Record")
        return FacilityAttemptResult("booked", "Booking verified in My Booking Record.")

    if portal_result:
        log.info(f"  Facility {candidate.facility_id}: {portal_result.reason}")
        return portal_result

    log.warning(f"  Facility {candidate.facility_id}: ambiguous result -> {page_text[:300]}")
    return FacilityAttemptResult(
        RETRYABLE_ERROR,
        "Portal result was ambiguous and My Booking Record did not confirm the booking.",
    )


# ── Public entry point ────────────────────────────────────────────────────────

async def book_room(
    target_date: date,
    start_time: time,
    duration_hours: int,
    room_target: str,
    headless: bool = True,
) -> BookingResult:
    """
    Login, then try each matching HKU facility in order until one is successfully booked
    for target_date, start_time, duration_hours hours.
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
                return BookingResult("booked", "Matching booking already exists.")

            candidates = await _discover_facilities(page, normalized_target)
            if not candidates:
                log.error("No matching facilities found for target '%s'.", normalized_target)
                return BookingResult(UNAVAILABLE, f"No matching facilities found for target '{normalized_target}'.")

            had_unavailable = False
            last_retryable_error = ""
            for candidate in candidates:
                try:
                    result = await _try_book_facility(
                        page,
                        candidate,
                        target_date,
                        sessions,
                    )
                    if result.booked:
                        return BookingResult("booked", result.reason)
                    if result.status == TERMINAL_REJECTED:
                        log.error("Portal says this booking cannot be made: %s", result.reason)
                        return BookingResult(TERMINAL_REJECTED, result.reason)
                    if result.status == RETRYABLE_ERROR:
                        log.warning("Retryable portal/automation issue: %s", result.reason)
                        return BookingResult(RETRYABLE_ERROR, result.reason)
                    had_unavailable = True
                except Exception:
                    last_retryable_error = f"Exception on facility {candidate.facility_id}."
                    log.exception(f"  Exception on facility {candidate.facility_id} — trying next")
            if had_unavailable:
                log.error("All facilities tried — none available for the requested time.")
                return BookingResult(
                    UNAVAILABLE,
                    "All matching facilities are unavailable for the requested time.",
                )
            log.error("Unable to complete booking due to automation errors.")
            return BookingResult(
                RETRYABLE_ERROR,
                last_retryable_error or "No facility attempt completed.",
            )
        finally:
            await browser.close()
