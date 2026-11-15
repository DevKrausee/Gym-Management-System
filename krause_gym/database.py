"""CSV persistence for the gym application.

Each table is a UTF-8 CSV file. Writes are serialized and committed by replacing the
affected file only after a complete row set has been written.
"""

import csv
import os
import tempfile
import threading
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path


class DataError(ValueError):
    """Raised when a write would violate an application data rule."""


TABLES = {
    "customers": ("id", "full_name", "phone", "email", "created_at", "first_name", "middle_name", "last_name", "extension"),
    "memberships": ("id", "customer_id", "plan_name", "start_date", "end_date", "plan_price", "payment_status", "created_at", "membership_type", "vip_plan_name"),
    "payments": ("id", "customer_id", "membership_id", "amount", "payment_date", "method", "receipt_no", "note", "recorded_by", "voided", "void_reason", "voided_by", "voided_at", "recorded_at"),
    "users": ("id", "username", "display_name", "role", "password_salt", "password_hash", "active", "created_at"),
    "payment_admin_auth": ("id", "username", "password_salt", "password_hash", "created_at"),
    "app_settings": ("key", "value"),
    "attendance": ("id", "customer_id", "check_in", "check_out", "auto_closed", "recorded_by"),
    "vip_prices": ("plan_name", "price", "active"),
    "vip_benefits": ("benefit_key", "label", "enabled"),
    "vip_lockers": ("id", "locker_no", "active"),
    "vip_locker_assignments": ("id", "locker_id", "customer_id", "assigned_at", "released_at", "assigned_by", "released_by"),
    "vip_locker_waitlist": ("id", "customer_id", "requested_at", "status", "note", "recorded_by", "updated_at"),
    "vip_assessments": ("id", "customer_id", "assessed_at", "weight", "height", "measurements", "notes", "recorded_by"),
    "vip_lounge_visits": ("id", "customer_id", "entered_at", "exited_at", "recorded_by", "voided", "void_reason", "voided_by", "voided_at"),
    "vip_trainers": ("id", "name", "active", "phone", "working_days", "available_from", "available_to"),
    "vip_training_sessions": ("id", "customer_id", "trainer_id", "starts_at", "status", "notes", "recorded_by", "updated_at", "booking_type", "session_fee", "payment_id"),
    "vip_audit": ("id", "action", "entity", "entity_id", "details", "performed_by", "performed_at"),
}

KEYS = {
    "app_settings": ("key",), "vip_prices": ("plan_name",),
    "vip_benefits": ("benefit_key",), "payment_admin_auth": ("id",),
    "users": ("id",), "customers": ("id",), "memberships": ("id",),
    "payments": ("id",), "attendance": ("id",), "vip_lockers": ("id",),
    "vip_locker_assignments": ("id",), "vip_locker_waitlist": ("id",),
    "vip_assessments": ("id",), "vip_lounge_visits": ("id",),
    "vip_trainers": ("id",), "vip_training_sessions": ("id",), "vip_audit": ("id",),
}
UNIQUE_FIELDS = {"users": (("username", True),), "vip_lockers": (("locker_no", True),), "payments": (("receipt_no", False),)}
INTEGER_FIELDS = {"id", "customer_id", "membership_id", "recorded_by", "voided_by", "active", "auto_closed", "locker_id", "assigned_by", "released_by", "enabled", "trainer_id", "payment_id", "entity_id", "performed_by", "voided"}
NUMBER_FIELDS = {"amount", "plan_price", "price", "session_fee"}


def _convert(field, value):
    if value == "":
        return None
    if field in INTEGER_FIELDS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field in NUMBER_FIELDS:
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


class CsvDatabase:
    """Small table store with explicit row operations and atomic CSV commits."""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or Path(__file__).resolve().parent.parent / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._next = {}
        for table, columns in TABLES.items():
            path = self._path(table)
            if not path.exists():
                self._write(table, [], columns)
            rows = self._read(table)
            key = KEYS.get(table, ("id",))[0]
            ids = [row.get(key) for row in rows if isinstance(row.get(key), int)]
            self._next[table] = max(ids, default=0) + 1 if key == "id" else 1
        self._upgrade_imported_rows()
        self._seed_defaults()

    def _upgrade_imported_rows(self):
        """Add columns introduced by newer app versions and migrate the former owner login."""
        for table, columns in TABLES.items():
            rows=self._read(table)
            if any(set(row)!=set(columns) for row in rows):
                normalized=[{column:row.get(column,"") for column in columns} for row in rows]
                self._write(table,normalized,columns)
        defaults={"customers":{"phone":"","email":"","middle_name":"","last_name":"","extension":""},
            "memberships":{"payment_status":"Unpaid","membership_type":"Regular","vip_plan_name":""},
            "payments":{"method":"Cash","voided":0,"void_reason":"","note":""},
            "attendance":{"auto_closed":0},"users":{"active":1},"vip_prices":{"active":1},
            "vip_benefits":{"enabled":1},"vip_lockers":{"active":1},"vip_locker_waitlist":{"status":"Waiting","note":""},
            "vip_lounge_visits":{"voided":0,"void_reason":""},"vip_trainers":{"active":1,"phone":"","working_days":"Mon,Tue,Wed,Thu,Fri,Sat","available_from":"08:00","available_to":"21:00"},
            "vip_training_sessions":{"status":"Scheduled","notes":"","booking_type":"VIP Included","session_fee":0}}
        for table,fields in defaults.items():
            rows=self._read(table); dirty=False
            for row in rows:
                for field,value in fields.items():
                    if row.get(field) is None or row.get(field)=="":row[field]=value; dirty=True
            if dirty:self._write(table,rows)
        customers=self._read("customers")
        changed=False
        for customer in customers:
            if not customer.get("first_name") and not customer.get("last_name"):
                customer["first_name"]=customer.get("full_name") or ""; changed=True
        if changed:self._write("customers",customers)
        users=self._read("users")
        legacy=self._read("payment_admin_auth")
        if not users and legacy:
            admin=legacy[0]
            self.insert("users",{"username":admin["username"],"display_name":admin["username"],"role":"owner","password_salt":admin["password_salt"],"password_hash":admin["password_hash"],"active":1})
        payments=self._read("payments"); changed=False
        if any(not payment.get("receipt_no") for payment in payments):
            from .config import receipt_number
            for payment in payments:
                if not payment.get("receipt_no"):
                    payment["receipt_no"]=receipt_number(payment["payment_date"],payment["id"]); changed=True
        if changed:self._write("payments",payments)

    def _seed_defaults(self):
        for name,price in (("Weekly",450),("Monthly",1400),("Quarterly",3500)):
            if not self.get("vip_prices",plan_name=name):self.insert("vip_prices",{"plan_name":name,"price":price,"active":1})
        if self.get("vip_prices",plan_name="Day Pass (Walk-in)"):
            self.update("vip_prices",{"plan_name":"Day Pass (Walk-in)"},{"active":0})
        if not self.get("app_settings",key="vip_training_rate"):
            self.insert("app_settings",{"key":"vip_training_rate","value":"0"})
        for key,label in (("locker","Reserved locker"),("training","Personal training")):
            if not self.get("vip_benefits",benefit_key=key):self.insert("vip_benefits",{"benefit_key":key,"label":label,"enabled":1})
        self.delete("vip_benefits",{"benefit_key":"lounge"})
        self.delete("vip_benefits",{"benefit_key":"assessment"})

    def _path(self, table):
        if table not in TABLES:
            raise KeyError(f"Unknown CSV table: {table}")
        return self.data_dir / f"{table}.csv"

    def _read(self, table):
        with self._path(table).open("r", newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            return [{key: _convert(key, value) for key, value in row.items()} for row in reader]

    def _write(self, table, rows, columns=None):
        columns = tuple(columns or TABLES[table])
        fd, temp_name = tempfile.mkstemp(prefix=f".{table}-", suffix=".csv", dir=self.data_dir)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows({key: row.get(key, "") for key in columns} for row in rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self._path(table))
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def rows(self, table):
        with self._lock:
            return self._read(table)

    def get(self, table, **criteria):
        def matches(row):
            return all((str(row.get(key) or "").casefold()==str(value or "").casefold()) if table=="users" and key=="username" else row.get(key)==value for key,value in criteria.items())
        return next((row for row in self.rows(table) if matches(row)), None)

    def where(self, table, predicate=None, order=None, reverse=False, limit=None):
        result = [row for row in self.rows(table) if predicate is None or predicate(row)]
        if order:
            result.sort(key=order, reverse=reverse)
        return result[:limit] if limit is not None else result

    def count(self, table, predicate=None):
        return len(self.where(table, predicate))

    def insert(self, table, values):
        with self.transaction() as tx:
            return tx.insert(table, values)

    def update(self, table, criteria, changes):
        with self.transaction() as tx:
            return tx.update(table, criteria, changes)

    def delete(self, table, criteria):
        with self.transaction() as tx:
            return tx.delete(table, criteria)

    @contextmanager
    def transaction(self):
        with self._lock:
            tx = CsvTransaction(self)
            yield tx
            tx.commit()


class CsvTransaction:
    def __init__(self, database):
        self.database = database
        self.changed = {}

    def rows(self, table):
        return self.changed.setdefault(table, self.database._read(table))

    def get(self, table, **criteria):
        return next((row for row in self.rows(table) if all(row.get(k) == v for k, v in criteria.items())), None)

    def insert(self, table, values):
        row = {key: "" for key in TABLES[table]}
        row.update(values)
        now=datetime.now().isoformat(timespec="seconds")
        timestamp_fields={"customers":("created_at",),"memberships":("created_at",),"vip_locker_assignments":("assigned_at",),"vip_locker_waitlist":("requested_at","updated_at"),"vip_training_sessions":("updated_at",),"vip_audit":("performed_at",)}
        for field in timestamp_fields.get(table,()):
            if not row.get(field):row[field]=now
        key = KEYS.get(table, ("id",))[0]
        if key == "id" and row.get("id") in (None, ""):
            row["id"] = self.database._next[table]
            self.database._next[table] += 1
        unique_key = KEYS.get(table)
        if unique_key and any(all(existing.get(k) == row.get(k) for k in unique_key) for existing in self.rows(table)):
            raise DataError(f"A {table} record with that key already exists.")
        for field, ignore_case in UNIQUE_FIELDS.get(table, ()):
            value=row.get(field)
            if value in (None, ""): continue
            comparable=str(value).casefold() if ignore_case else value
            if any((str(existing.get(field)).casefold() if ignore_case else existing.get(field))==comparable for existing in self.rows(table)):
                raise DataError(f"A {table} record with that {field.replace('_',' ')} already exists.")
        self.rows(table).append(row)
        return row.get(key)

    def update(self, table, criteria, changes):
        count = 0
        for field, ignore_case in UNIQUE_FIELDS.get(table, ()):
            if field not in changes or changes[field] in (None, ""): continue
            value=str(changes[field]).casefold() if ignore_case else changes[field]
            if any(all(row.get(k)==v for k,v in criteria.items()) is False and (str(row.get(field)).casefold() if ignore_case else row.get(field))==value for row in self.rows(table)):
                raise DataError(f"A {table} record with that {field.replace('_',' ')} already exists.")
        for row in self.rows(table):
            if all(row.get(key) == value for key, value in criteria.items()):
                row.update(changes)
                count += 1
        return count

    def delete(self, table, criteria):
        rows = self.rows(table)
        keep = [row for row in rows if not all(row.get(key) == value for key, value in criteria.items())]
        count = len(rows) - len(keep)
        self.changed[table] = keep
        return count

    def commit(self):
        backups={table:self.database._path(table).read_bytes() for table in self.changed}
        written=[]
        try:
            for table,rows in self.changed.items():
                self.database._write(table,rows)
                written.append(table)
        except Exception:
            for table in reversed(written):
                path=self.database._path(table)
                fd,temp_name=tempfile.mkstemp(prefix=f".{table}-restore-",dir=self.database.data_dir)
                try:
                    with os.fdopen(fd,"wb") as stream:
                        stream.write(backups[table]); stream.flush(); os.fsync(stream.fileno())
                    os.replace(temp_name,path)
                finally:
                    if os.path.exists(temp_name):os.unlink(temp_name)
            raise


