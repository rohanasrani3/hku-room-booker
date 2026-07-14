# HKU Room Booker

Automated room booking for HKU library study spaces, designed to run from each user's own GitHub fork.

HKU study rooms are useful but competitive. The booking window opens at midnight HKT on the day before the target date, which means students often need to stay awake, refresh the booking site, and race through the same form just to reserve a room for normal study sessions (or wait 15 minutes everytime otherwise). This project removes that repetitive work while keeping credentials private: each user forks the repo, stores their own HKU credentials as GitHub Actions secrets, and runs bookings from their own GitHub account.

No need to worry about your uid-password leaking out as long as you're storing it securely in GitHub Secrets :)

## Setup

Executing the current model requires a GitHub Account.

1. Fork this repository.
2. In your fork, go to `Settings -> Secrets and variables -> Actions`.
3. Add these repository secrets:
   - `HKU_UID` (your uid)
   - `HKU_PIN` (your password)
4. Go to `Actions -> HKU Room Booker`.
5. Run the workflow after entering details.

The workflow page asks for:

- `date`: target date in `YYYY-MM-DD`
- `time`: start time, on the hour
- `duration`: number of hours
- `room_target`: room target dropdown

## What It Does

- Books HKU library study spaces through the official booking portal.
- Supports instant bookings for today or tomorrow.
- Queues future bookings and runs them automatically when the booking window opens.
- Supports Chi Wah, Main Library, Dental, Law, Medical, Music, discussion rooms, single study rooms, study booths, and broad target groups.
- Runs through GitHub Actions, so users do not need to keep a laptop awake.
- Stores HKU credentials only in the user's own fork as repository secrets.
- Writes booking status back to `bookings.json`.

## How It Works

There are two booking paths:

- **Immediate booking:** if the selected date is today or tomorrow HKT, the manual workflow runs `book.py` directly.
- **Future booking:** if the selected date is after tomorrow, the manual workflow adds a pending entry to `bookings.json`. The scheduled workflow starts before midnight HKT, waits locally until the booking window opens, and then books due entries.

The schedule is intentionally set to `23:45 HKT` instead of exactly midnight. GitHub scheduled workflows can be delayed at the top of the hour, so the workflow starts earlier and lets Python wait until midnight before attempting the booking.

## Room Targets

Room targets are configured in [`data/room_catalog.json`](data/room_catalog.json). The current workflow dropdown includes:

- `all_study_rooms`
- `chi_wah_study_rooms`
- `chi_wah_study_booths`
- `discussion_rooms`
- `single_study_rooms`
- `study_tables`
- `main_library_discussion_rooms`
- `main_library_single_study_rooms`
- `dental_discussion_rooms`
- `law_discussion_rooms`
- `medical_discussion_rooms`
- `medical_single_study_rooms`
- `music_discussion_rooms`

## Local Usage

Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

Create a local `.env` file:

```env
HKU_UID=your_uid
HKU_PIN=your_pin
```

Run an immediate booking:

```bash
python3 book.py --date tomorrow --time 10:00 --duration 2 --room-target all_study_rooms
```

Queue or run automatically based on date:

```bash
python3 run_manual.py --date 2026-07-20 --time 10:00 --duration 2 --room-target discussion_rooms
```

Run due scheduled bookings:

```bash
python3 run_scheduled.py
```

## Repository Layout

```text
.
|-- .github/workflows/book.yml   # Manual and scheduled GitHub Actions workflow
|-- auth.py                      # HKU login flow
|-- book.py                      # Immediate booking entrypoint
|-- booker.py                    # Browser automation and result detection
|-- bookings.json                # Future booking queue and status store
|-- config.py                    # Settings and environment loading
|-- data/
|   |-- room_catalog.json        # Room targets, aliases, facility IDs
|   `-- settings.json            # Runtime defaults
|-- queue_booking.py             # Adds future bookings to bookings.json
|-- room_catalog.py              # Loads and validates room catalogue data
|-- run_manual.py                # Chooses immediate vs future booking
`-- run_scheduled.py             # Runs due queued bookings
```

## PS
 - Not related with HKU in any ways, just an independent project.
 - This booker should function properly as long as HKU decides to change their website structure or add more security.
 - Please do attend your bookings.
 - UI in-dev.
