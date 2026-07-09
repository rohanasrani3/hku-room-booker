"""
HKU Library authentication via the HKUL Authentication portal.

Confirmed login flow (probed 2026-06-19):
  booking.lib.hku.hk → lib.hku.hk/hkulauth/legacy/authMain?uri=...
  Form fields: name='userid' (HKU UID), name='password' (PIN)
  Submit:      input[name='submit']
"""

import re
import logging
from playwright.async_api import Page

from config import BOOKING_BASE_URL, HKU_UID, HKU_PIN

log = logging.getLogger(__name__)


async def login(page: Page) -> None:
    """Navigate to the booking site and authenticate via the HKUL auth portal."""
    if not HKU_UID or not HKU_PIN:
        raise RuntimeError("HKU_UID and HKU_PIN must be set in the environment or .env")

    log.info(f"Opening {BOOKING_BASE_URL}")
    await page.goto(BOOKING_BASE_URL, wait_until="commit", timeout=30_000)

    # booking.lib.hku.hk redirects to lib.hku.hk/hkulauth/legacy/authMain?uri=...
    await page.wait_for_url(
        re.compile(r"lib\.hku\.hk/hkulauth", re.IGNORECASE),
        timeout=15_000,
    )
    log.info(f"Reached login page: {page.url}")

    # Confirmed field names from live page inspection
    await page.fill("input[name='userid']", HKU_UID)
    await page.fill("input[name='password']", HKU_PIN)
    await page.click("input[name='submit']")

    # Wait until redirected back to the booking system
    await page.wait_for_url(
        re.compile(r"booking\.lib\.hku\.hk"),
        timeout=20_000,
    )
    await page.wait_for_load_state("domcontentloaded", timeout=20_000)
    log.info("Login successful — back on booking site.")
