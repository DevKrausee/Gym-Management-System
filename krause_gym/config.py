import hashlib
import hmac
import inspect
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import flet as ft
 
APP_NAME = "BSIT-2B Gym"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PLANS = {
    "Day Pass (Walk-in)": {"price": 50.0, "days": 1},
    "Weekly": {"price": 250.0, "days": 7},
    "Monthly": {"price": 800.0, "days": 30},
    "Quarterly": {"price": 2000.0, "days": 90},
}
VIP_PLANS = {name: details for name, details in PLANS.items() if name != "Day Pass (Walk-in)"}
PAYMENT_METHODS = ["Cash", "GCash", "Maya", "Bank Transfer"]
EXTENSIONS = ["None", "Jr.", "Sr.", "II", "III", "IV", "V"]
IDLE_LOGOUT_SECONDS = 10 * 60
 
# Layout sizes shared across pages so tabs, filters and cards line up.
TAB_WIDTH, TAB_HEIGHT = 210, 44
FIELD_WIDTH, FIELD_HEIGHT = 190, 48
FIELD_BORDER_COLOR = "#71717A"
CARD_WIDTH = 200
 
# Aliases so the same code runs on different Flet versions.
Button = getattr(ft, "Button", None) or ft.ElevatedButton
DropdownItem = getattr(ft, "DropdownOption", None) or ft.dropdown.Option
 
 
def _padding_helper(name):
    """Padding helpers that work on both old (ft.padding.*) and new (ft.Padding.*) Flet."""
    padding_class = getattr(ft, "Padding", None)
    if padding_class is not None and hasattr(padding_class, name):
        return getattr(padding_class, name)
    return getattr(ft.padding, name)
 
 
pad_all = _padding_helper("all")
pad_only = _padding_helper("only")
pad_symmetric = _padding_helper("symmetric")
 
 
def field_style(**overrides):
    """One look for every text field and dropdown in the app.
 
    dense=False matters: dense inputs ignore Flutter's 48px minimum height, so a field with
    height=48 would draw about 36px tall next to 48px dropdowns and buttons.
    """
    style = dict(
        height=FIELD_HEIGHT,
        dense=False,
        text_size=13,
        content_padding=pad_symmetric(horizontal=12, vertical=12),
        border=ft.OutlineInputBorder(border_radius=8, side=ft.BorderSide(1, FIELD_BORDER_COLOR)),
    )
    style.update(overrides)
    return style
 
 
def _left_alignment():
    """Return a left-center alignment supported by old and new Flet APIs."""
    alignment_cls = getattr(ft, "Alignment", None)
    if alignment_cls is not None:
        try:
            return alignment_cls(-1, 0)
        except Exception:
            pass
    alignment_module = getattr(ft, "alignment", None)
    if alignment_module is not None and hasattr(alignment_module, "center_left"):
        return alignment_module.center_left
    return None
 
 
LEFT_ALIGNMENT = _left_alignment()
 
 
def summarize_payment_methods(totals):
    """Return compact payment summary cards while retaining method-level records."""
    cards = [
        ("Filtered Cash", float(totals.get("Cash", 0.0))),
        (
            "E-Wallet",
            sum(float(totals.get(method, 0.0)) for method in ("GCash", "Maya", "Bank Transfer")),
        ),
    ]
    other_methods = [
        name for name in totals if name not in ("Cash", "GCash", "Maya", "Bank Transfer")
    ]
    cards.extend((f"Filtered {method}", float(totals.get(method, 0.0))) for method in other_methods)
    return cards
 
 
def receipt_number(payment_date, payment_id):
    day_stamp = date.fromisoformat(str(payment_date)[:10]).strftime("%Y%m%d")
    return f"KGM-{day_stamp}-{int(payment_id):04d}"
 
 
def _middle_initial(middle_name):
    middle_name = (middle_name or "").strip()
    return f"{middle_name[0].upper()}." if middle_name else ""
 
 
def build_full_name(first_name, middle_name="", last_name="", extension=""):
    """'Juan D. Cruz Jr.' - stored in customers.full_name and used on receipts and records."""
    name = " ".join(part for part in (first_name, _middle_initial(middle_name), last_name) if part)
    return f"{name} {extension}" if extension and extension != "None" else name
 
 
def build_list_name(first_name, middle_name="", last_name="", extension=""):
    """'Cruz, Juan D. Jr.' - used for the sorted customer list and customer pickers.
    Records saved before names were split have no last name, so they show as typed."""
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    if not last_name:
        return first_name
    given_names = " ".join(
        part
        for part in (
            first_name,
            _middle_initial(middle_name),
            extension if extension and extension != "None" else "",
        )
        if part
    )
    return f"{last_name}, {given_names}"
 
 
def date_from_picker(value):
    """Turn what the calendar sends back into a plain date without ever shifting the day.
    The value can arrive as a naive local midnight, a UTC midnight, or local midnight written in UTC
    (at UTC+8 that lands on the previous evening). UTC midnight is taken as that date; any other
    time-zone-aware value is converted to this computer's local time first."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            utc_value = value.astimezone(timezone.utc)
            if (utc_value.hour, utc_value.minute, utc_value.second) != (0, 0, 0):
                value = value.astimezone()
        return value.date()
    return value
 
 
def capitalize_lowercase_name(value):
    """Capitalise a name typed entirely in lowercase ('renz' -> 'Renz', 'mary-ann' -> 'Mary-Ann').
    Anything that already has a capital letter ('de la Cruz', 'McDonald', 'MARIA') is left as typed.
    """
    if value and value == value.lower():
        return re.sub(r"(?<![^\W\d_])[^\W\d_]", lambda match: match.group(0).upper(), value)
    return value
 
 
def row_full_name(row):
    """'Juan D. Cruz Jr.' from any row that has the four name columns (used in messages)."""
    return build_full_name(
        row["first_name"], row["middle_name"], row["last_name"], row["extension"]
    )
 
 
def format_clock_time(iso_timestamp):
    """'2026-10-26T17:12:03' -> '5:12 PM'"""
    return datetime.fromisoformat(iso_timestamp).strftime("%I:%M %p").lstrip("0")
 
 
def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 310000
    ).hex()

