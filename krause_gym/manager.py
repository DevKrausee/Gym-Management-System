"""Application business logic for accounts, customers, memberships, payments, and attendance."""

import hmac
import math
import re
import secrets
from datetime import date, datetime, timedelta

from .database import DataError
from .config import (
    EXTENSIONS,
    PAYMENT_METHODS,
    PLANS,
    VIP_PLANS,
    build_full_name,
    capitalize_lowercase_name,
    hash_password,
    receipt_number,
)


class GymManager:
    def __init__(self, db):
        self.db = db
        self.current_user = None  # set at sign-in: {"id", "username", "display_name", "role"}
 
    # --- Accounts ---
    def _require_user(self):
        if not self.current_user:
            raise ValueError("Sign in first.")
        return self.current_user["id"]
 
    def _require_owner(self):
        if not self.current_user or self.current_user["role"] != "owner":
            raise ValueError("Only the owner can do this.")
 
    @staticmethod
    def _user_to_dict(row):
        return {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
        }
 
    @staticmethod
    def _check_password(password):
        if len(password or "") < 8:
            raise ValueError("Password must contain at least 8 characters.")
 
    @staticmethod
    def _validate_account(display_name, username, password):
        display_name = " ".join((display_name or "").split())
        username = (username or "").strip()
        if len(display_name) < 2:
            raise ValueError("Enter the person's name (at least 2 characters).")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise ValueError(
                "Username must be 3-32 characters: letters, numbers, dot, dash or underscore."
            )
        GymManager._check_password(password)
        return display_name, username
 
    def _insert_user(self, display_name, username, role, password):
        salt = secrets.token_hex(16)
        if any(user["username"].casefold()==username.casefold() for user in self.db.rows("users")):
            raise ValueError("That username is already taken.")
        return self.db.insert("users", {"username": username, "display_name": display_name,
            "role": role, "password_salt": salt, "password_hash": hash_password(password, salt), "active": 1,
            "created_at": datetime.now().isoformat(timespec="seconds")})
 
    def _set_password(self, user_id, password):
        salt = secrets.token_hex(16)
        self.db.update("users", {"id": user_id}, {"password_salt": salt, "password_hash": hash_password(password, salt)})
 
    def has_users(self):
        return bool(self.db.rows("users"))
 
    def create_owner(self, display_name, username, password):
        if self.has_users():
            raise ValueError("An account already exists. Sign in instead.")
        display_name, username = self._validate_account(display_name, username, password)
        user_id = self._insert_user(display_name, username, "owner", password)
        return self._user_to_dict(self.db.get("users", id=user_id))
 
    def create_staff(self, display_name, username, password):
        self._require_owner()
        display_name, username = self._validate_account(display_name, username, password)
        return self._insert_user(display_name, username, "staff", password)
 
    def authenticate(self, username, password):
        """Return the user dict if the username and password match an active account, else None."""
        row = self.db.get("users", username=(username or "").strip())
        digest = hash_password(password or "", row["password_salt"] if row else "00" * 16)
        if row and row["active"] and hmac.compare_digest(digest, row["password_hash"]):
            return self._user_to_dict(row)
        return None
 
    def verify_password(self, user_id, password):
        row = self.db.get("users", id=user_id)
        return bool(row) and hmac.compare_digest(
            hash_password(password or "", row["password_salt"]), row["password_hash"]
        )
 
    def list_users(self):
        rows=self.db.where("users", order=lambda row: (0 if row["role"] == "owner" else 1, row["display_name"].casefold()))
        fields=("id","display_name","username","role","active")
        return [{key:row.get(key) for key in fields} for row in rows]
 
    def set_user_active(self, user_id, active):
        self._require_owner()
        row = self.db.get("users", id=user_id)
        if not row:
            raise ValueError("Account not found.")
        if row["role"] == "owner":
            raise ValueError("The owner account can't be disabled.")
        self.db.update("users", {"id": user_id}, {"active": 1 if active else 0})

    def update_staff_name(self, user_id, display_name):
        self._require_owner()
        display_name = " ".join((display_name or "").split())
        if len(display_name) < 2:
            raise ValueError("Enter the staff member's name (at least 2 characters).")
        row = self.db.get("users", id=user_id)
        if not row or row["role"] != "staff":
            raise ValueError("Staff account not found.")
        self.db.update("users", {"id": user_id}, {"display_name": display_name})
 
    def reset_password(self, user_id, new_password):
        self._require_owner()
        self._check_password(new_password)
        if not self.db.get("users", id=user_id):
            raise ValueError("Account not found.")
        self._set_password(user_id, new_password)
 
    def has_recovery_code(self):
        return self.db.get("app_settings", key="recovery_hash") is not None
 
    def new_recovery_code(self):
        """Create a new owner recovery code and store only its hash. The caller shows it once."""
        code = "-".join(secrets.token_hex(2).upper() for _ in range(4))
        salt = secrets.token_hex(16)
        with self.db.transaction() as tx:
            for key, value in (("recovery_salt", salt), ("recovery_hash", hash_password(code.replace("-", ""), salt))):
                if tx.get("app_settings", key=key): tx.update("app_settings", {"key": key}, {"value": value})
                else: tx.insert("app_settings", {"key": key, "value": value})
        return code
 
    def recover_owner_password(self, code, new_password):
        """Reset the owner's password with the recovery code. Returns a NEW recovery code."""
        self._check_password(new_password)
        recovery_salt = self.db.get("app_settings", key="recovery_salt")
        stored_hash = self.db.get("app_settings", key="recovery_hash")
        if not (recovery_salt and stored_hash):
            raise ValueError("No recovery code has been set up for this system.")
        entered = "".join(character for character in (code or "").upper() if character.isalnum())
        if not hmac.compare_digest(
            hash_password(entered, recovery_salt["value"]), stored_hash["value"]
        ):
            raise ValueError("Incorrect recovery code.")
        owner = self.db.get("users", role="owner")
        if not owner:
            raise ValueError("No owner account found.")
        self._set_password(owner["id"], new_password)
        return self.new_recovery_code()
 
    # --- Customers / memberships / payments ---
    @staticmethod
    def _clean_name(first_name, middle_name, last_name, extension):
        """First and last name are required; middle name and extension are optional."""
        first_name, middle_name, last_name = (
            capitalize_lowercase_name(" ".join((value or "").split()))
            for value in (first_name, middle_name, last_name)
        )
        extension = (extension or "").strip()
        if extension == "None":
            extension = ""
        if not first_name:
            raise ValueError("First name is required.")
        if not last_name:
            raise ValueError("Last name is required.")
        if extension and extension not in EXTENSIONS:
            raise ValueError("Choose a valid name extension.")
        return first_name, middle_name, last_name, extension
 
    def add_customer(
        self, first_name, middle_name="", last_name="", extension="", phone="", email=""
    ):
        first_name, middle_name, last_name, extension = self._clean_name(
            first_name, middle_name, last_name, extension
        )
        return self.db.insert("customers", {
            "full_name": build_full_name(first_name, middle_name, last_name, extension),
            "first_name": first_name, "middle_name": middle_name, "last_name": last_name,
            "extension": extension, "phone": phone.strip(), "email": email.strip(),
            "created_at": datetime.now().isoformat(timespec="seconds")})
 
    def update_customer(
        self,
        customer_id,
        first_name,
        middle_name="",
        last_name="",
        extension="",
        phone="",
        email="",
    ):
        first_name, middle_name, last_name, extension = self._clean_name(
            first_name, middle_name, last_name, extension
        )
        self.db.update("customers", {"id": customer_id}, {
            "full_name": build_full_name(first_name, middle_name, last_name, extension),
            "first_name": first_name, "middle_name": middle_name, "last_name": last_name,
            "extension": extension, "phone": phone.strip(), "email": email.strip()})
 
    def search_customers(self, query=""):
        words = (query or "").replace(",", " ").split()
        memberships = self.db.rows("memberships")
        result = []
        for customer in self.db.rows("customers"):
            haystack = " ".join(str(customer.get(key) or "") for key in ("full_name", "first_name", "middle_name", "last_name", "phone", "email")).casefold()
            if all(word.casefold() in haystack for word in words):
                row = dict(customer)
                latest = max((m for m in memberships if m["customer_id"] == customer["id"]), key=lambda m: m["id"], default=None)
                row["plan"] = latest["plan_name"] if latest else None
                row["end_date"] = latest["end_date"] if latest else None
                result.append(row)
        return sorted(result, key=lambda c: ((c.get("last_name") or c.get("first_name") or "").casefold(), (c.get("first_name") or "").casefold()))
 
    def find_members(self, query, limit=9):
        """Members matching a name, phone or member ID, with an exact ID match listed first.
 
        Each row also says whether the member is inside right now and has an active membership today.
        """
        today = date.today().isoformat()
        typed_text = (query or "").strip()
        member_id = int(typed_text) if typed_text.isdigit() else -1
        words = (query or "").replace(",", " ").split()
        visits, memberships = self.db.rows("attendance"), self.db.rows("memberships")
        result = []
        for c in self.db.rows("customers"):
            haystack = " ".join(str(c.get(k) or "") for k in ("full_name", "first_name", "middle_name", "last_name", "phone", "email")).casefold()
            if c["id"] != member_id and not all(word.casefold() in haystack for word in words):
                continue
            active = sorted((m for m in memberships if m["customer_id"] == c["id"] and m["start_date"] <= today <= m["end_date"]), key=lambda m: (m["end_date"], m["id"]), reverse=True)
            open_visits = [a for a in visits if a["customer_id"] == c["id"] and not a.get("check_out")]
            row = {key: c.get(key) for key in ("id", "full_name", "first_name", "middle_name", "last_name", "extension", "phone")}
            row.update(inside_since=max(open_visits, key=lambda a:a["id"])["check_in"] if open_visits else None,
                       active_until=active[0]["end_date"] if active else None, plan=active[0]["plan_name"] if active else None)
            result.append(row)
        result.sort(key=lambda c: (c["id"] != member_id, (c.get("last_name") or c["first_name"] or "").casefold(), (c.get("first_name") or "").casefold()))
        return result[:limit]
 
    def membership_summary(self, membership_id):
        m = self.db.get("memberships", id=membership_id)
        if not m: return None
        c = self.db.get("customers", id=m["customer_id"])
        return {**m, "paid": sum(float(p["amount"] or 0) for p in self.db.rows("payments") if p.get("membership_id") == membership_id and not p.get("voided")), **{key:c.get(key) for key in ("first_name", "middle_name", "last_name", "extension")}}
 
    def payable_memberships(self, customer_id):
        """A member's memberships that still have a balance, oldest first."""
        rows = [self.membership_summary(m["id"]) for m in self.db.rows("memberships") if m["customer_id"] == customer_id]
        rows.sort(key=lambda m: (m["start_date"], m["id"]))
        return [
            membership
            for membership in rows
            if float(membership["plan_price"]) - float(membership["paid"]) > 0.005
        ]

    def vip_outstanding_balance(self, customer_id):
        """Total unpaid membership balance that must be settled before VIP registration or upgrade."""
        return sum(
            max(0.0, float(row["plan_price"]) - float(row["paid"]))
            for row in self.payable_memberships(customer_id)
        )
 
    def membership_standing(self, customer_id):
        """Latest membership plus the total still owed (renewal is blocked while money is owed)."""
        latest = max((m for m in self.db.rows("memberships") if m["customer_id"] == customer_id), key=lambda m:(m["end_date"],m["id"]), default=None)
        unpaid_memberships = self.payable_memberships(customer_id)
        return {
            "latest": latest,
            "owed": sum(
                float(membership["plan_price"]) - float(membership["paid"])
                for membership in unpaid_memberships
            ),
            "owed_membership_id": unpaid_memberships[0]["id"] if unpaid_memberships else None,
        }
 
    def inside_now(self):
        people = {c["id"]: c for c in self.db.rows("customers")}
        return [{**{k: people[a["customer_id"]].get(k) for k in ("id", "first_name", "middle_name", "last_name", "extension")}, "check_in": a["check_in"]}
                for a in sorted(self.db.rows("attendance"), key=lambda a:a["check_in"]) if not a.get("check_out") and a["customer_id"] in people]
 
    def add_membership(self, customer_id, plan_name, start_text):
        if plan_name not in PLANS:
            raise ValueError("Choose a valid membership plan.")
        try:
            start_date = date.fromisoformat(start_text)
        except ValueError:
            raise ValueError("Start date must use YYYY-MM-DD.")
 
        # Balance check and insert share one transaction, so rapid double-clicks
        # cannot bypass the renewal rule.
        end_date = start_date + timedelta(days=PLANS[plan_name]["days"] - 1)
        with self.db.transaction() as tx:
            unpaid_membership = None
            payments = tx.rows("payments")
            for item in sorted((m for m in tx.rows("memberships") if m["customer_id"] == customer_id), key=lambda m:m["id"]):
                paid = sum(float(p["amount"] or 0) for p in payments if p.get("membership_id") == item["id"] and not p.get("voided"))
                balance = max(0.0, float(item["plan_price"]) - paid)
                if balance > 0.005:
                    unpaid_membership = {**item, "balance": balance}
                    break
            if unpaid_membership:
                raise ValueError(
                    f"Renewal blocked: {unpaid_membership['plan_name']} membership "
                    f"(ID {unpaid_membership['id']}) still has an outstanding balance "
                    f"of ₱{unpaid_membership['balance']:,.2f}. Settle the balance before "
                    "creating another membership."
                )
            return tx.insert("memberships", {"customer_id": customer_id, "plan_name": plan_name,
                "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                "plan_price": self.regular_price(plan_name), "payment_status": "Unpaid",
                "membership_type": "Regular", "vip_plan_name": "", "created_at": datetime.now().isoformat(timespec="seconds")})
 
    def delete_customer(self, customer_id):
        self._require_owner()
        # Customers with any linked records are kept to preserve history.
        linked_record_count = sum(self.db.count(table, lambda row:row.get("customer_id")==customer_id) for table in ("memberships", "payments", "attendance"))
        if linked_record_count:
            raise ValueError(
                "This customer has membership, payment, or attendance history, so the record is kept."
            )
        self.db.delete("customers", {"id": customer_id})
 
    def delete_membership(self, membership_id):
        self._require_owner()
        active_payment_count = self.db.count("payments", lambda p:p.get("membership_id")==membership_id and not p.get("voided"))
        if active_payment_count:
            raise ValueError(
                "This membership has payments. Void its payments first before deleting the membership."
            )
        with self.db.transaction() as tx:
            # Preserve the former SET NULL relationship for retained voided payments.
            tx.update("payments", {"membership_id":membership_id}, {"membership_id":None})
            tx.delete("memberships", {"id": membership_id})
 
    def regular_price(self, plan_name):
        if plan_name not in PLANS:
            raise ValueError("Choose a valid membership plan.")
        row = self.db.get("app_settings", key=f"regular_price:{plan_name}")
        try:
            return max(0.0, float(row["value"])) if row else float(PLANS[plan_name]["price"])
        except (TypeError, ValueError):
            return float(PLANS[plan_name]["price"])

    def set_regular_price(self, plan_name, price):
        self._require_owner()
        if plan_name not in PLANS:
            raise ValueError("Choose a valid membership plan.")
        try:
            price = round(float(price), 2)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid membership price.")
        if not math.isfinite(price) or price < 0:
            raise ValueError("Membership price must be a finite amount of zero or more.")
        key = f"regular_price:{plan_name}"
        if self.db.get("app_settings", key=key): self.db.update("app_settings", {"key":key}, {"value":str(price)})
        else: self.db.insert("app_settings", {"key":key,"value":str(price)})

    def payment_scope(self, alias=""):
        """Return (condition, params) limiting payment rows to what the signed-in person may see.
 
        The owner sees every payment, staff see only the ones they recorded, and nobody signed in
        sees none.
        """
        column = f"{alias}.recorded_by" if alias else "recorded_by"
        user = self.current_user
        if user and user["role"] == "owner":
            return "", ()
        return f"{column}=?", (user["id"] if user else -1,)
 
    def can_void(self, payment):
        """Owner: any payment. Staff: only their own, on the day they recorded it."""
        user = self.current_user
        if not user or payment["voided"]:
            return False
        if user["role"] == "owner":
            return True
        recorded_at = payment["recorded_at"]
        return (
            payment["recorded_by"] == user["id"]
            and bool(recorded_at)
            and recorded_at[:10] == date.today().isoformat()
        )
 
    def _refresh_membership_status(self, tx, membership_id):
        if membership_id is None:
            return
        membership = tx.get("memberships", id=membership_id)
        if not membership:
            return
        paid = sum(float(p["amount"] or 0) for p in tx.rows("payments") if p.get("membership_id")==membership_id and not p.get("voided"))
        price = float(membership["plan_price"])
        status = "Paid" if paid >= price - 0.005 else ("Partial" if paid > 0 else "Unpaid")
        tx.update("memberships", {"id":membership_id}, {"payment_status":status})
 
    def void_payment(self, payment_id, reason, authorized=False):
        """Void a payment. Payments are never deleted: the record stays, marked VOID with a reason.
 
        The owner may void any payment; staff only their own, on the day they recorded it.
        """
        user_id = self._require_user()
        if not authorized:
            raise ValueError("Password confirmation is required to void a payment.")
        reason = " ".join((reason or "").split())
        if len(reason) < 3:
            raise ValueError("A reason (at least 3 characters) is required to void a payment.")
        with self.db.transaction() as tx:
            payment = tx.get("payments", id=payment_id)
            if not payment:
                raise ValueError("Payment record not found.")
            if self.current_user["role"] != "owner":
                if payment["recorded_by"] != user_id:
                    raise ValueError("You can only void payments you recorded yourself.")
                if (
                    not payment["recorded_at"]
                    or payment["recorded_at"][:10] != date.today().isoformat()
                ):
                    raise ValueError(
                        "Staff can only void a payment on the day it was recorded. Ask the owner to void it."
                    )
            if payment["voided"]:
                raise ValueError("This payment is already voided.")
            tx.update("payments", {"id":payment_id}, {"voided":1,"void_reason":reason,"voided_by":user_id,"voided_at":datetime.now().isoformat(timespec="seconds")})
            self._refresh_membership_status(tx, payment.get("membership_id"))
 
    def delete_attendance(self, attendance_id):
        self._require_owner()
        self.db.delete("attendance", {"id":attendance_id})
 
    def active_membership(self, customer_id, on_date=None):
        """Access is determined by membership dates, not payment status."""
        day = on_date or date.today().isoformat()
        return max((m for m in self.db.rows("memberships") if m["customer_id"]==customer_id and m["start_date"]<=day<=m["end_date"]),key=lambda m:(m["end_date"],m["id"]),default=None)
 
    def membership_balance(self, membership_id):
        membership = self.db.get("memberships", id=membership_id)
        if not membership:
            return 0.0
        paid = sum(float(p["amount"] or 0) for p in self.db.rows("payments") if p.get("membership_id")==membership_id and not p.get("voided"))
        return max(0.0, float(membership["plan_price"]) - float(paid))
 
    def record_payment(
        self,
        customer_id,
        membership_id,
        amount,
        payment_date_text,
        note="",
        method="Cash",
        authorized=False,
    ):
        if not authorized:
            raise ValueError("Password confirmation is required to record a payment.")
        recorded_by = self._require_user()
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid amount.")
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if method not in PAYMENT_METHODS:
            raise ValueError("Choose a valid payment method.")
        try:
            payment_date = date.fromisoformat(payment_date_text)
        except ValueError:
            raise ValueError("Payment date must use YYYY-MM-DD.")
        with self.db.transaction() as tx:
            membership = tx.get("memberships", id=membership_id, customer_id=customer_id)
            if not membership:
                raise ValueError("Select a valid membership.")
            already_paid = sum(float(p["amount"] or 0) for p in tx.rows("payments") if p.get("membership_id")==membership_id and not p.get("voided"))
            balance = max(0.0, float(membership["plan_price"]) - float(already_paid))
            if amount > balance + 0.00001:
                raise ValueError(f"Payment exceeds balance ₱{balance:,.2f}.")
            payment_id = tx.insert("payments", {"customer_id":customer_id,"membership_id":membership_id,"amount":amount,
                "payment_date":payment_date.isoformat(),"method":method,"note":note.strip(),"recorded_by":recorded_by,
                "recorded_at":datetime.now().isoformat(timespec="seconds"),"voided":0,
                "receipt_no":None})
            tx.update("payments", {"id":payment_id}, {"receipt_no":receipt_number(payment_date.isoformat(),payment_id)})
            paid = float(already_paid) + amount
            price = float(membership["plan_price"])
            status = "Paid" if paid >= price - 0.005 else ("Partial" if paid > 0 else "Unpaid")
            tx.update("memberships", {"id":membership_id}, {"payment_status":status})
        return payment_id
 
    def close_stale_checkins(self):
        """Close check-ins left open from earlier days at 23:59:59 and flag them as auto-closed."""
        today=date.today().isoformat()
        with self.db.transaction() as tx:
            for visit in tx.rows("attendance"):
                if not visit.get("check_out") and visit["check_in"][:10] < today:
                    visit["check_out"]=visit["check_in"][:10]+"T23:59:59"; visit["auto_closed"]=1
 
    def check_in(self, customer_id):
        recorded_by = self._require_user()
        self.close_stale_checkins()
        # Membership dates (not payment status) decide access. Check and insert share one
        # transaction so rapid clicks cannot create duplicate open check-ins.
        today = date.today().isoformat()
        with self.db.transaction() as tx:
            active_membership_row = any(m["customer_id"]==customer_id and m["start_date"]<=today<=m["end_date"] for m in tx.rows("memberships"))
            if not active_membership_row:
                raise ValueError("No active membership for today. Add or renew a membership first.")
            if any(a["customer_id"]==customer_id and not a.get("check_out") for a in tx.rows("attendance")):
                raise ValueError("This customer is already checked in.")
            tx.insert("attendance", {"customer_id":customer_id,"check_in":datetime.now().isoformat(timespec="seconds"),"recorded_by":recorded_by,"check_out":None,"auto_closed":0})
 
    def check_out(self, customer_id):
        self.close_stale_checkins()
        open_visit = max((a for a in self.db.rows("attendance") if a["customer_id"]==customer_id and not a.get("check_out")),key=lambda a:a["check_in"],default=None)
        if not open_visit:
            raise ValueError("This customer does not have an open check-in.")
        self.db.update("attendance", {"id":open_visit["id"]}, {"check_out":datetime.now().isoformat(timespec="seconds")})
 
    def dashboard_stats(self):
        today = date.today().isoformat()
        payments=[p for p in self.db.rows("payments") if p.get("recorded_by")== (self.current_user["id"] if self.current_user else -1) or (self.current_user and self.current_user["role"]=="owner")]
        voided=[p for p in payments if p.get("voided") and (p.get("voided_at") or "")[:10]==today]
        active={m["customer_id"] for m in self.db.rows("memberships") if m["start_date"]<=today<=m["end_date"]}
        outstanding=sum(self.membership_balance(m["id"]) for m in self.db.rows("memberships"))
        return {"customers":len(self.db.rows("customers")),"active":len(active),
                "income":sum(float(p["amount"] or 0) for p in payments if p["payment_date"]==today and not p.get("voided")),
                "voids_today":len(voided),"voids_amount":sum(float(p["amount"] or 0) for p in voided),
                "checkins":sum(1 for a in self.db.rows("attendance") if a["check_in"][:10]==today),"outstanding":outstanding}

    # --- VIP membership and services ---
    def vip_summary(self):
        today = date.today().isoformat()
        return {
            "total": len({m["customer_id"] for m in self.db.rows("memberships") if m.get("membership_type")=="VIP"}),
            "active": len({m["customer_id"] for m in self.db.rows("memberships") if m.get("membership_type")=="VIP" and m["start_date"]<=today<=m["end_date"]}),
            "expired": len({m["customer_id"] for m in self.db.rows("memberships") if m.get("membership_type")=="VIP" and m["end_date"]<today}),
            "lockers": self.db.count("vip_lockers",lambda x:bool(x.get("active"))),
            "occupied": sum(1 for a in self.db.rows("vip_locker_assignments") if not a.get("released_at") and any(l["id"]==a["locker_id"] and l.get("active") for l in self.db.rows("vip_lockers"))),
            "training": sum(1 for s in self.db.rows("vip_training_sessions") if s["starts_at"][:10]==today),
            "completed": sum(1 for s in self.db.rows("vip_training_sessions") if s["status"]=="Completed" and s["starts_at"][:7]==today[:7]),
            "revenue": sum(float(p["amount"] or 0) for p in self.db.rows("payments") if not p.get("voided") and (p.get("note") or "").startswith("VIP ") and p["payment_date"][:7]==today[:7] and (self.current_user and (self.current_user["role"]=="owner" or p.get("recorded_by")==self.current_user["id"]))),
        }

    def vip_members(self):
        today = date.today().isoformat()
        customers={c["id"]:c for c in self.db.rows("customers")}; lockers={l["id"]:l["locker_no"] for l in self.db.rows("vip_lockers")}
        result=[]
        for m in self.db.rows("memberships"):
            c=customers.get(m["customer_id"])
            if m.get("membership_type")!="VIP" or not c: continue
            assigned=next((a for a in self.db.rows("vip_locker_assignments") if a["customer_id"]==c["id"] and not a.get("released_at")),None)
            result.append({"customer_id":c["id"],"full_name":c["full_name"],"membership_id":m["id"],"plan_name":m["plan_name"],"start_date":m["start_date"],"end_date":m["end_date"],"membership_type":m["membership_type"],"status":"Active" if m["start_date"]<=today<=m["end_date"] else "Expired","locker":lockers.get(assigned["locker_id"]) if assigned else None})
        result.sort(key=lambda r:r["full_name"].casefold())
        result.sort(key=lambda r:r["end_date"],reverse=True)
        return result

    def vip_expiring_soon(self, days=30):
        today=date.today()
        cutoff=(today+timedelta(days=days)).isoformat()
        customers={c["id"]:c for c in self.db.rows("customers")}; all_memberships=self.db.rows("memberships")
        latest={cid:max((m for m in all_memberships if m["customer_id"]==cid),key=lambda m:(m["end_date"],m["id"])) for cid in {m["customer_id"] for m in all_memberships}}
        result=[]
        for m in latest.values():
            if m.get("membership_type")=="VIP" and m["start_date"]<=today.isoformat() and m["end_date"]<=cutoff and m["customer_id"] in customers:
                c=customers[m["customer_id"]]; result.append({"customer_id":c["id"],"full_name":c["full_name"],"phone":c["phone"],"plan_name":m["plan_name"],"start_date":m["start_date"],"end_date":m["end_date"]})
        today_text=today.isoformat()
        return sorted(result,key=lambda r:(0 if r["end_date"]<today_text else 1,-date.fromisoformat(r["end_date"]).toordinal() if r["end_date"]<today_text else date.fromisoformat(r["end_date"]).toordinal(),r["full_name"].casefold()))

    def vip_renew(self, customer_id, plan_name):
        if plan_name not in VIP_PLANS: raise ValueError("Choose a valid VIP membership duration.")
        latest=max((m for m in self.db.rows("memberships") if m["customer_id"]==customer_id and m.get("membership_type")=="VIP"),key=lambda m:(m["end_date"],m["id"]),default=None)
        if not latest: raise ValueError("This customer does not have a VIP membership to renew.")
        today=date.today()
        previous_end=date.fromisoformat(latest['end_date'])
        start=max(today,previous_end+timedelta(days=1))
        return self.add_vip_membership(customer_id,plan_name,start.isoformat())

    def _vip_audit(self, action, entity, entity_id=None, details=''):
        self.db.insert("vip_audit",{"action":action,"entity":entity,"entity_id":entity_id,"details":details,"performed_by":self._require_user(),"performed_at":datetime.now().isoformat(timespec="seconds")})

    def vip_set_price(self, plan_name, price):
        self._require_owner()
        if plan_name not in VIP_PLANS: raise ValueError("Choose a valid VIP membership duration.")
        price=float(price)
        if price < 0: raise ValueError("Price cannot be negative.")
        existing=self.db.get("vip_prices",plan_name=plan_name)
        if existing:self.db.update("vip_prices",{"plan_name":plan_name},{"price":price,"active":1})
        else:self.db.insert("vip_prices",{"plan_name":plan_name,"price":price,"active":1})
        self._vip_audit("Price updated","vip_price",None,f"{plan_name}: ₱{price:.2f}")

    def vip_price(self, plan_name):
        row=self.db.get("vip_prices",plan_name=plan_name)
        if row and not row.get("active"): row=None
        return float(row["price"]) if row else None

    def vip_benefits(self):
        return self.db.where("vip_benefits",order=lambda r:r["benefit_key"])

    def vip_benefit_enabled(self, key):
        row=self.db.get("vip_benefits",benefit_key=key)
        return bool(row and row["enabled"])

    def vip_set_benefit(self, key, enabled):
        self._require_owner()
        self.db.update("vip_benefits",{"benefit_key":key},{"enabled":int(bool(enabled))})
        self._vip_audit("Benefit availability updated","vip_benefit",None,f"{key}: {'enabled' if enabled else 'disabled'}")

    def add_vip_membership(self, customer_id, plan_name, start_text):
        if plan_name not in VIP_PLANS: raise ValueError("VIP Day Pass is not offered. Choose a weekly, monthly, or quarterly VIP plan.")
        price=self.vip_price(plan_name)
        if price is None: raise ValueError("VIP pricing is not configured for this duration.")
        try: start=date.fromisoformat(start_text)
        except ValueError: raise ValueError("Start date must use YYYY-MM-DD.")
        end=start+timedelta(days=VIP_PLANS[plan_name]["days"]-1)
        with self.db.transaction() as tx:
            owed=None
            for item in sorted((m for m in tx.rows("memberships") if m["customer_id"]==customer_id),key=lambda m:m["id"]):
                paid=sum(float(p["amount"] or 0) for p in tx.rows("payments") if p.get("membership_id")==item["id"] and not p.get("voided"))
                balance=max(0,float(item["plan_price"])-paid)
                if balance>0.005: owed={**item,"balance":balance}; break
            if owed: raise ValueError(f"Registration blocked: {owed['plan_name']} (ID {owed['id']}) has ₱{owed['balance']:,.2f} outstanding.")
            membership_id=tx.insert("memberships",{"customer_id":customer_id,"plan_name":f"VIP {plan_name}","start_date":start.isoformat(),"end_date":end.isoformat(),"plan_price":price,"membership_type":"VIP","vip_plan_name":plan_name,"payment_status":"Unpaid","created_at":datetime.now().isoformat(timespec="seconds")})
        self._vip_audit("VIP registered","membership",membership_id,f"{plan_name}; ₱{price:.2f}")
        return membership_id,price

    def vip_upgrade_quote(self, membership_id, today=None):
        today=today or date.today()
        row=self.db.get("memberships",id=membership_id)
        if not row or row["membership_type"]=='VIP': raise ValueError("Select an active Regular membership.")
        start=date.fromisoformat(row["start_date"]); end=date.fromisoformat(row["end_date"])
        if not start<=today<=end: raise ValueError("Only an active Regular membership can be upgraded.")
        plan=row["plan_name"]
        if plan not in VIP_PLANS: raise ValueError("This regular membership duration cannot be upgraded to VIP. Choose a weekly, monthly, or quarterly VIP plan instead.")
        owing=sum(float(item['plan_price'])-float(item['paid']) for item in self.payable_memberships(row['customer_id']))
        if owing>0.005: raise ValueError(f"Settle the outstanding membership balance of ₱{owing:,.2f} first.")
        days=(end-today).days+1
        price=self.vip_price(plan)
        if price is None: raise ValueError("VIP pricing is not configured for this duration.")
        membership_days=max(1,(end-start).days+1)
        regular_price=float(row['plan_price'])
        vip_remaining=round(price*days/membership_days+1e-9,2)
        regular_remaining=round(regular_price*days/membership_days+1e-9,2)
        amount=max(0,round(vip_remaining-regular_remaining+1e-9,2))
        return {"membership":row,"vip_price":price,"regular_price":regular_price,
                "vip_remaining_value":vip_remaining,"regular_remaining_value":regular_remaining,
                "days":days,"membership_days":membership_days,"amount":amount,"plan":plan}

    def vip_upgrade(self, membership_id, payment_date_text, method="Cash", authorized=False):
        if not authorized: raise ValueError("Payment authorization is required.")
        uid=self._require_user(); quote=self.vip_upgrade_quote(membership_id)
        if method not in PAYMENT_METHODS: raise ValueError("Choose a valid payment method.")
        try: paydate=date.fromisoformat(payment_date_text)
        except ValueError: raise ValueError("Payment date must use YYYY-MM-DD.")
        m=quote["membership"]
        with self.db.transaction() as tx:
            pid=None
            if quote['amount']>0:
                pid=tx.insert("payments",{"customer_id":m['customer_id'],"membership_id":None,"amount":quote['amount'],"payment_date":paydate.isoformat(),"method":method,"note":f"VIP upgrade: {quote['plan']}","recorded_by":uid,"recorded_at":datetime.now().isoformat(timespec='seconds'),"voided":0})
                tx.update("payments",{"id":pid},{"receipt_no":receipt_number(paydate.isoformat(),pid)})
            tx.update("memberships",{"id":membership_id},{"membership_type":"VIP","vip_plan_name":quote['plan'],"plan_name":f"VIP {quote['plan']}"})
        receipt=f"Receipt {receipt_number(paydate.isoformat(),pid)}; " if pid else "No payment due; "
        self._vip_audit("Regular upgraded to VIP","membership",membership_id,
                        f"{receipt}remaining VIP value ₱{quote['vip_remaining_value']:.2f}; regular value ₱{quote['regular_remaining_value']:.2f}; paid ₱{quote['amount']:.2f}")
        return pid,quote

    def vip_add_locker(self, locker_no):
        self._require_owner(); no=(locker_no or '').strip()
        if not no: raise ValueError("Enter a locker number.")
        if len(no)>24 or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*",no):
            raise ValueError("Use up to 24 letters or numbers, with optional hyphens between groups (for example, A-12).")
        no=no.upper()
        if any(l["locker_no"].casefold()==no.casefold() for l in self.db.rows("vip_lockers")):
            raise ValueError("That locker label already exists.")
        lid=self.db.insert("vip_lockers",{"locker_no":no,"active":1})
        self._vip_audit("Locker added","locker",lid,no); return lid

    def vip_rename_locker(self, locker_id, locker_no):
        self._require_owner()
        no=(locker_no or '').strip()
        if not no:raise ValueError("Enter a locker label.")
        if len(no)>24 or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*",no):
            raise ValueError("Use up to 24 letters or numbers, with optional hyphens between groups (for example, A-12).")
        no=no.upper()
        locker=self.db.get("vip_lockers",id=locker_id)
        if not locker:raise ValueError("Locker not found.")
        if any(l["locker_no"].casefold()==no.casefold() and l["id"]!=locker_id for l in self.db.rows("vip_lockers")):
            raise ValueError("That locker label already exists.")
        self.db.update("vip_lockers",{"id":locker_id},{"locker_no":no})
        self._vip_audit("Locker label updated","locker",locker_id,f"{locker['locker_no']} → {no}")
        return no

    def vip_assign_locker(self, customer_id, locker_id):
        if not self.vip_benefit_enabled("locker"): raise ValueError("Locker benefit is currently unavailable.")
        uid=self._require_user(); today=date.today().isoformat()
        with self.db.transaction() as tx:
            if not any(m["customer_id"]==customer_id and m.get("membership_type")=="VIP" and m["start_date"]<=today<=m["end_date"] for m in tx.rows("memberships")): raise ValueError("An active VIP membership is required.")
            if any(a["customer_id"]==customer_id and not a.get("released_at") for a in tx.rows("vip_locker_assignments")): raise ValueError("This member already has an assigned locker.")
            if not (locker:=tx.get("vip_lockers",id=locker_id)) or not locker.get("active"): raise ValueError("Choose an available locker.")
            if any(a["locker_id"]==locker_id and not a.get("released_at") for a in tx.rows("vip_locker_assignments")): raise ValueError("That locker has already been assigned.")
            tx.insert("vip_locker_assignments",{"locker_id":locker_id,"customer_id":customer_id,"assigned_by":uid,"assigned_at":datetime.now().isoformat(timespec="seconds")})
        self._vip_audit("Locker assigned","locker_assignment",None,f"Member {customer_id}; locker {locker_id}")

    def vip_release_locker(self, assignment_id):
        uid=self._require_user(); self.db.update("vip_locker_assignments",{"id":assignment_id,"released_at":None},{"released_at":datetime.now().isoformat(timespec='seconds'),"released_by":uid}); self._vip_audit("Locker released","locker_assignment",assignment_id)

    def vip_set_locker_active(self, locker_id, active):
        self._require_owner()
        locker=self.db.get("vip_lockers",id=locker_id)
        if not locker: raise ValueError("Locker not found.")
        if not active and any(a["locker_id"]==locker_id and not a.get("released_at") for a in self.db.rows("vip_locker_assignments")):
            raise ValueError("Release the assigned member before marking this locker unavailable.")
        self.db.update("vip_lockers",{"id":locker_id},{"active":int(bool(active))})
        self._vip_audit("Locker availability changed","locker",locker_id,f"{locker['locker_no']}: {'Available' if active else 'Unavailable'}")

    def vip_waitlist_add(self, customer_id, note=''):
        uid=self._require_user(); today=date.today().isoformat()
        if not any(m["customer_id"]==customer_id and m.get("membership_type")=="VIP" and m["start_date"]<=today<=m["end_date"] for m in self.db.rows("memberships")):
            raise ValueError("An active VIP membership is required for the locker waitlist.")
        if any(w["customer_id"]==customer_id and w["status"]=="Waiting" for w in self.db.rows("vip_locker_waitlist")):
            raise ValueError("This member is already on the locker waitlist.")
        wid=self.db.insert("vip_locker_waitlist",{"customer_id":customer_id,"note":(note or '').strip(),"recorded_by":uid,"status":"Waiting","requested_at":datetime.now().isoformat(timespec="seconds"),"updated_at":datetime.now().isoformat(timespec="seconds")})
        self._vip_audit("Locker waitlist added","locker_waitlist",wid,f"Member {customer_id}")
        return wid

    def vip_waitlist_assign(self, waitlist_id, locker_id):
        uid=self._require_user(); today=date.today().isoformat()
        with self.db.transaction() as c:
            item=c.get("vip_locker_waitlist",id=waitlist_id,status="Waiting")
            locker=c.get("vip_lockers",id=locker_id)
            if locker and not locker.get("active"): locker=None
            if not item or not locker: raise ValueError("Select a waiting member and an available locker.")
            if not any(m["customer_id"]==item['customer_id'] and m.get("membership_type")=="VIP" and m["start_date"]<=today<=m["end_date"] for m in c.rows("memberships")):
                raise ValueError("This member no longer has an active VIP membership.")
            if any(a["customer_id"]==item['customer_id'] and not a.get("released_at") for a in c.rows("vip_locker_assignments")):
                raise ValueError("This member already has an assigned locker.")
            if any(a["locker_id"]==locker_id and not a.get("released_at") for a in c.rows("vip_locker_assignments")):
                raise ValueError("That locker was just assigned. Choose another available locker.")
            c.insert("vip_locker_assignments",{"locker_id":locker_id,"customer_id":item['customer_id'],"assigned_by":uid,"assigned_at":datetime.now().isoformat(timespec="seconds")})
            c.update("vip_locker_waitlist",{"id":waitlist_id},{"status":"Assigned","updated_at":datetime.now().isoformat(timespec='seconds')})
            c.insert("vip_audit",{"action":"Waitlist member assigned","entity":"locker_waitlist","entity_id":waitlist_id,"details":f"Locker {locker['locker_no']}","performed_by":uid})

    def vip_waitlist_cancel(self, waitlist_id):
        uid=self._require_user()
        with self.db.transaction() as c:
            updated=c.update("vip_locker_waitlist",{"id":waitlist_id,"status":"Waiting"},{"status":"Cancelled","updated_at":datetime.now().isoformat(timespec='seconds')})
            if updated!=1: raise ValueError("This waitlist request is no longer waiting.")
            c.insert("vip_audit",{"action":"Locker waitlist cancelled","entity":"locker_waitlist","entity_id":waitlist_id,"performed_by":uid})

    def vip_reopen_training(self, session_id, reason):
        self._require_owner(); reason=' '.join((reason or '').split())
        if len(reason)<3: raise ValueError("Enter a correction reason.")
        with self.db.transaction() as c:
            row=c.get("vip_training_sessions",id=session_id)
            if not row or row['status']=='Scheduled': raise ValueError("Only a terminal training session can be corrected.")
            starts=datetime.fromisoformat(row['starts_at'])
            if any(s["id"]!=session_id and s["trainer_id"]==row["trainer_id"] and s["status"]=="Scheduled" and abs((datetime.fromisoformat(s["starts_at"])-starts).total_seconds())<3600 for s in c.rows("vip_training_sessions")):
                raise ValueError("Another scheduled session conflicts with this correction.")
            if sum(1 for s in c.rows("vip_training_sessions") if s["customer_id"]==row["customer_id"] and s["status"]=="Scheduled" and s["id"]!=session_id)>=3:
                raise ValueError("The member already has three scheduled sessions; cancel one before reopening this session.")
            previous=row['status']; uid=self.current_user['id']
            c.update("vip_training_sessions",{"id":session_id},{"status":"Scheduled","updated_at":datetime.now().isoformat(timespec='seconds')})
            c.insert("vip_audit",{"action":"Training session corrected","entity":"training_session","entity_id":session_id,"details":f"{previous} → Scheduled: {reason}","performed_by":uid})

    @staticmethod
    def _clean_trainer_details(name, phone, working_days, available_from, available_to):
        name=' '.join((name or '').split())
        if len(name)<2: raise ValueError("Enter the trainer's name.")
        day_names=("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
        selected={part.strip().title()[:3] for part in (working_days or '').split(',') if part.strip()}
        if not selected or not selected.issubset(day_names):
            raise ValueError("Enter working days as comma-separated abbreviations, such as Mon,Tue,Wed.")
        normalized_days=','.join(day for day in day_names if day in selected)
        try:
            starts=datetime.strptime((available_from or '').strip(),'%H:%M').time()
            ends=datetime.strptime((available_to or '').strip(),'%H:%M').time()
        except ValueError:
            raise ValueError("Availability times must use 24-hour HH:MM format.")
        if starts>=ends: raise ValueError("Availability end time must be later than the start time.")
        return name,(phone or '').strip(),normalized_days,starts.strftime('%H:%M'),ends.strftime('%H:%M')

    def vip_add_trainer(self, name, phone='', working_days='Mon,Tue,Wed,Thu,Fri,Sat', available_from='08:00', available_to='21:00'):
        self._require_owner()
        name,phone,days,start,end=self._clean_trainer_details(name,phone,working_days,available_from,available_to)
        tid=self.db.insert("vip_trainers",{"name":name,"phone":phone,"working_days":days,"available_from":start,"available_to":end,"active":1})
        self._vip_audit("Trainer added","trainer",tid,f"{name}; {days} {start}-{end}")
        return tid

    def vip_update_trainer(self, trainer_id, name, phone='', working_days='Mon,Tue,Wed,Thu,Fri,Sat', available_from='08:00', available_to='21:00', active=True):
        self._require_owner()
        if not self.db.get("vip_trainers",id=trainer_id):
            raise ValueError("Trainer not found.")
        name,phone,days,start,end=self._clean_trainer_details(name,phone,working_days,available_from,available_to)
        self.db.update("vip_trainers",{"id":trainer_id},{"name":name,"phone":phone,"working_days":days,"available_from":start,"available_to":end,"active":int(bool(active))})
        self._vip_audit("Trainer updated","trainer",trainer_id,f"{name}; {days} {start}-{end}; {'active' if active else 'inactive'}")

    def vip_set_trainer_active(self, trainer_id, active):
        self._require_owner()
        self.db.update("vip_trainers",{"id":trainer_id},{"active":int(bool(active))})
        self._vip_audit("Trainer availability changed","trainer",trainer_id,"Active" if active else "Inactive")

    def vip_training_rate(self):
        row=self.db.get("app_settings",key="vip_training_rate")
        try:return max(0.0,float(row['value'])) if row else 0.0
        except (TypeError,ValueError):return 0.0

    def vip_set_training_rate(self, price):
        self._require_owner()
        try:price=round(float(price),2)
        except (TypeError,ValueError):raise ValueError("Enter a valid personal-training price.")
        if not math.isfinite(price) or price<=0:raise ValueError("The paid training rate must be a finite amount greater than zero.")
        key="vip_training_rate"
        if self.db.get("app_settings",key=key): self.db.update("app_settings",{"key":key},{"value":str(price)})
        else:self.db.insert("app_settings",{"key":key,"value":str(price)})
        self._vip_audit("Personal training rate updated","training_rate",None,f"₱{price:.2f} per session")

    def vip_training_included(self, customer_id, today=None):
        if not self.vip_benefit_enabled("training"):return False
        day=today or date.today()
        if isinstance(day,datetime):day=day.date()
        if isinstance(day,date):day=day.isoformat()
        return any(m["customer_id"]==customer_id and m.get("membership_type")=="VIP" and m["start_date"]<=day<=m["end_date"] for m in self.db.rows("memberships"))

    def _training_slot(self, trainer_id, starts_at):
        trainer=self.db.get("vip_trainers",id=trainer_id)
        if trainer and not trainer.get("active"): trainer=None
        if not trainer:raise ValueError("Choose an active trainer.")
        try:appointment=datetime.fromisoformat(starts_at)
        except ValueError:raise ValueError("Session start must be a valid date and time.")
        weekday=("Mon","Tue","Wed","Thu","Fri","Sat","Sun")[appointment.weekday()]
        if weekday not in (trainer['working_days'] or '').split(','):
            raise ValueError(f"{trainer['name']} is not available on {weekday}.")
        start_time=datetime.strptime(trainer['available_from'],'%H:%M').time()
        end_time=datetime.strptime(trainer['available_to'],'%H:%M').time()
        available_start=datetime.combine(appointment.date(),start_time)
        available_end=datetime.combine(appointment.date(),end_time)
        if appointment<available_start or appointment+timedelta(hours=1)>available_end:
            raise ValueError(f"Choose a time within {trainer['available_from']}–{trainer['available_to']}; sessions are one hour.")
        if any(s["trainer_id"]==trainer_id and s["status"]=="Scheduled" and abs((datetime.fromisoformat(s["starts_at"])-appointment).total_seconds())<3600 for s in self.db.rows("vip_training_sessions")):
            raise ValueError("Trainer already has a session within one hour of that time.")
        return trainer,appointment

    def vip_schedule_training(self, customer_id, trainer_id, starts_at, notes=''):
        if not self.vip_benefit_enabled("training"): raise ValueError("Training benefit is currently unavailable.")
        uid=self._require_user(); today=date.today().isoformat()
        if not any(m["customer_id"]==customer_id and m.get("membership_type")=="VIP" and m["start_date"]<=today<=m["end_date"] for m in self.db.rows("memberships")): raise ValueError("An active VIP membership is required.")
        if not self.vip_training_included(customer_id):raise ValueError("This member's VIP membership does not include personal training.")
        self._training_slot(trainer_id,starts_at)
        if sum(1 for s in self.db.rows("vip_training_sessions") if s["customer_id"]==customer_id and s["status"]=="Scheduled")>=3: raise ValueError("A member may hold at most three upcoming sessions.")
        sid=self.db.insert("vip_training_sessions",{"customer_id":customer_id,"trainer_id":trainer_id,"starts_at":starts_at,"notes":notes.strip(),"recorded_by":uid,"booking_type":"VIP Included","session_fee":0,"status":"Scheduled","updated_at":datetime.now().isoformat(timespec="seconds")}); self._vip_audit("Training scheduled","training_session",sid,"VIP included"); return sid

    def vip_schedule_paid_training(self, customer_id, trainer_id, starts_at, notes='', method='Cash', authorized=False, expected_fee=None):
        if not authorized:raise ValueError("Password confirmation is required to book paid personal training.")
        uid=self._require_user()
        if self.vip_training_included(customer_id):raise ValueError("This member has personal training included with VIP; use the included booking option.")
        fee=self.vip_training_rate()
        if fee<=0:raise ValueError("The owner must set a paid personal-training rate before non-VIP bookings can be made.")
        if expected_fee is not None and round(float(expected_fee),2)!=round(fee,2):
            raise ValueError("The training price changed. Review the current price and confirm the booking again.")
        if method not in PAYMENT_METHODS:raise ValueError("Choose a valid payment method.")
        trainer,appointment=self._training_slot(trainer_id,starts_at)
        with self.db.transaction() as tx:
            appointment_dt=datetime.fromisoformat(starts_at)
            if any(s["trainer_id"]==trainer_id and s["status"]=="Scheduled" and abs((datetime.fromisoformat(s["starts_at"])-appointment_dt).total_seconds())<3600 for s in tx.rows("vip_training_sessions")):
                raise ValueError("Trainer already has a session within one hour of that time.")
            if sum(1 for s in tx.rows("vip_training_sessions") if s["customer_id"]==customer_id and s["status"]=="Scheduled")>=3:
                raise ValueError("A member may hold at most three upcoming sessions.")
            session_id=tx.insert("vip_training_sessions",{"customer_id":customer_id,"trainer_id":trainer_id,"starts_at":starts_at,"notes":notes.strip(),"recorded_by":uid,"booking_type":"Paid","session_fee":fee,"status":"Scheduled","updated_at":datetime.now().isoformat(timespec="seconds")})
            payment_id=tx.insert("payments",{"customer_id":customer_id,"membership_id":None,"amount":fee,"payment_date":date.today().isoformat(),"method":method,"note":f"Personal training session #{session_id}","recorded_by":uid,"recorded_at":datetime.now().isoformat(timespec='seconds'),"voided":0})
            tx.update("payments",{"id":payment_id},{"receipt_no":receipt_number(date.today().isoformat(),payment_id)})
            tx.update("vip_training_sessions",{"id":session_id},{"payment_id":payment_id})
        self._vip_audit("Paid training scheduled","training_session",session_id,f"{trainer['name']}; {appointment.isoformat(timespec='minutes')}; ₱{fee:.2f}")
        return session_id,payment_id

    def vip_training_status(self, session_id, status, notes=''):
        if status not in ('Completed','Cancelled','Missed'): raise ValueError("Choose a valid session status.")
        uid=self._require_user()
        with self.db.transaction() as tx:
            updated=tx.update("vip_training_sessions",{"id":session_id,"status":"Scheduled"},{"status":status,"notes":notes.strip(),"updated_at":datetime.now().isoformat(timespec='seconds')})
            if updated != 1:
                raise ValueError("This session is no longer scheduled and cannot be changed again.")
            tx.insert("vip_audit",{"action":f"Training {status.lower()}","entity":"training_session","entity_id":session_id,"performed_by":uid})

