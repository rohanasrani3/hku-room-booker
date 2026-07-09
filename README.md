# HKU Room Booker Template

Forkable automation repo for booking HKU library study spaces through GitHub Actions.

This repo is the execution engine. It stores no shared UI and should be forked by each user so their HKU credentials remain in their own GitHub Actions secrets.

## User Setup

1. Fork this repo.
2. In the fork, go to `Settings -> Secrets and variables -> Actions`.
3. Add repository secrets:
   - `HKU_UID`
   - `HKU_PIN`
4. Go to `Actions -> HKU Room Booker`.
5. Run the workflow manually, or use the shared UI repo to dispatch this workflow.

## Manual GitHub Actions Use

Open `Actions -> HKU Room Booker -> Run workflow`.

Enter the date, time, duration, and room target. If the date is today or tomorrow HKT, the workflow books immediately. If the date is after tomorrow, it queues the request in `bookings.json`; the midnight HKT cron will run it when the booking window opens.

## Shared UI

The graphical interface now lives in a separate repo:

```text
/home/rohan/Desktop/hku-room-booker-ui
```

Deploy that UI once with GitHub Pages. Every user can open the same UI and dispatch their own fork by entering their GitHub owner, repo, branch, workflow file, and GitHub token.

## Local CLI

```bash
python3 book.py --date tomorrow --time 10:00 --duration 2 --room-target all_study_rooms --now
```

Available room targets are listed in `booker.py` as `TARGET_RULES`.
