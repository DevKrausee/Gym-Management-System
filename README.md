# BSIT-2B Gym — VIP Edition (CSV build)

This build stores application data in UTF-8 CSV files under `data/`. The app retains its customers, memberships, payments, attendance, user accounts, VIP lockers, waitlist, trainer appointments, audit history, and existing workflows.

## Existing records

The CSV files in `data/` were migrated from the supplied project archive. They contain one file per data table. On launch, the app fills in newly introduced columns and default VIP settings while retaining existing records. If you move or replace the `data/` folder, close the app first and keep a backup copy.

## Run

1. Open a terminal in this project folder.
2. Install the dependency: `python -m pip install -r requirements.txt`
3. Start the app: `python main.py`

## Data files

`data/` contains `customers.csv`, `memberships.csv`, `payments.csv`, `attendance.csv`, `users.csv`, settings, and the VIP service tables. Each CSV has a header row. The app writes changes through temporary files and replaces the affected CSV after the complete file is written.

The original Flet screens, account roles, password checks, payment authorization and voiding, membership date rules, attendance history, and VIP workflows are retained. CSV files do not enforce relational constraints like a relational database; the app validates those rules in its business logic before saving.
