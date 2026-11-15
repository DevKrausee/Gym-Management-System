"""Payment screens, payment history, summaries, receipts, and void workflows."""

from datetime import date, timedelta

import flet as ft

from ..database import DataError

from ..config import (
    Button,
    CARD_WIDTH,
    DropdownItem,
    FIELD_HEIGHT,
    FIELD_WIDTH,
    PAYMENT_METHODS,
    TAB_HEIGHT,
    TAB_WIDTH,
    build_list_name,
    field_style,
    pad_all,
    pad_symmetric,
    row_full_name,
    summarize_payment_methods,
)



class PaymentsMixin:
    def payment_page(self):
        # Any signed-in user may open Payments; sensitive actions ask for a password separately.
        self._render_payment_page()
    def _tab_style(self, selected):
        """One style for every payment tab; only the background changes when selected."""
        return ft.ButtonStyle(
            bgcolor=self.ORANGE if selected else self.SURFACE_ALT,
            color="white",
            padding=pad_symmetric(horizontal=16, vertical=10),
            shape=ft.RoundedRectangleBorder(radius=8),
        )
    def _tab_button(self, label, selected):
        """Fixed-size tab so all three payment sub-pages are identical in width and height."""
        text = ft.Text(
            label, no_wrap=True, size=13, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER
        )
        return Button(
            text,
            width=TAB_WIDTH,
            height=TAB_HEIGHT,
            style=self._tab_style(selected),
            on_click=lambda event, name=label: self.show_payment_subpage(name),
        )
    def _render_payment_page(self):
        page_content = self.new_page("Payments History")
        self.title_label.value = "Payments History"
        self.payment_sub_buttons = {}
        tab_row = ft.Row(spacing=8)
        for label in ("Record Payment", "Outstanding Balance", "Payment History"):
            tab = self._tab_button(label, label == "Record Payment")
            tab_row.controls.append(tab)
            self.payment_sub_buttons[label] = tab
        self.payment_panel = ft.Column(
            spacing=15, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
        page_content.controls.append(tab_row)
        page_content.controls.append(self.payment_panel)
        self.show_payment_subpage("Record Payment")
    def show_payment_subpage(self, name):
        self.record_activity()
        self.payment_panel.controls.clear()
        for tab_label, tab in self.payment_sub_buttons.items():
            tab.style = self._tab_style(tab_label == name)
        if name == "Record Payment":
            self.build_record_payment_page()
        elif name == "Outstanding Balance":
            self.build_outstanding_balance_page()
        else:
            self.build_payment_history_page()
        self.page.update()
    def build_record_payment_page(self):
        panel = self.payment_panel
        self.selected_payment_membership_id = None
        form_body = self.add_section(
            panel,
            "Record Payment",
            "Find the member, pick the membership they are paying for, then enter the amount. "
            "Partial payments are fine.",
        )
        self.payment_search_field = ft.TextField(
            label="Search name, phone or member ID",
            width=520,
            label_style=ft.TextStyle(size=13),
            on_change=lambda event: self.refresh_payable_results(),
            on_submit=lambda event: self.payable_search_enter(),
            **field_style(),
        )
        self.payment_results = ft.Column(
            spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
        self.payment_form = ft.Column(
            spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
        form_body.controls.extend(
            [self.payment_search_field, self.payment_results, self.payment_form]
        )
        self.refresh_payable_results()
        self.draw_payment_form()
 
        tips_body = self.add_section(
            panel, "Payment Tips", "Choose the correct membership before recording a payment."
        )
        tips_body.controls.append(
            ft.Text(
                "You can record a partial payment or use Pay Full Balance to fill the remaining amount. "
                "A receipt is generated after a successful payment.",
                color=self.TEXT_MUTED,
                size=13,
            )
        )
    def _payable_cards(self, member):
        """One card per unpaid membership of this member (or a single 'nothing owed' card)."""
        name = build_list_name(
            member["first_name"], member["middle_name"], member["last_name"], member["extension"]
        )
        member_line = self.styled_text(
            f"Member ID {member['id']}  •  {member['phone'] or 'no phone'}",
            12,
            color=self.TEXT_MUTED,
        )
        owed = self.manager.payable_memberships(member["id"])
 
        def make_card(*parts):
            return ft.Container(
                bgcolor=self.SURFACE_ALT,
                border_radius=10,
                padding=pad_symmetric(horizontal=14, vertical=10),
                content=(
                    parts[0]
                    if len(parts) == 1
                    else ft.Row(list(parts), vertical_alignment=ft.CrossAxisAlignment.CENTER)
                ),
            )
 
        if not owed:
            return [
                make_card(
                    ft.Column(
                        [
                            self.styled_text(name, 15, True),
                            member_line,
                            self.styled_text(
                                "Nothing owed: no unpaid membership.", 12, color=self.TEXT_MUTED
                            ),
                        ],
                        spacing=2,
                    )
                )
            ]
        cards = []
        for membership in owed:
            price, paid = float(membership["plan_price"]), float(membership["paid"])
            cards.append(
                make_card(
                    ft.Column(
                        [
                            self.styled_text(name, 15, True),
                            member_line,
                            ft.Row(
                                [
                                    self.styled_text(
                                        f"{membership['plan_name']} ({membership['start_date']} to {membership['end_date']})  •  "
                                        f"Paid ₱{paid:,.2f} of ₱{price:,.2f}",
                                        12,
                                        color=self.TEXT_MUTED,
                                    ),
                                    self.styled_text(
                                        f"Balance ₱{max(0.0, price - paid):,.2f}",
                                        12,
                                        True,
                                        self.ORANGE,
                                    ),
                                ],
                                spacing=12,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    self.button(
                        "Select",
                        lambda membership_id=membership["id"]: self.select_payment_membership(
                            membership_id
                        ),
                        110,
                    ),
                )
            )
        return cards
    def refresh_payable_results(self):
        query = (self.payment_search_field.value or "").strip()
        self.payment_results.controls.clear()
        if not query:
            self.payment_results.controls.append(
                self.styled_text(
                    "Start typing to find a member. Press Enter to select when only one membership matches.",
                    12,
                    color=self.TEXT_MUTED,
                )
            )
        else:
            members = self.manager.find_members(query, limit=9)
            if not members:
                self.payment_results.controls.append(
                    self.styled_text(f'No member found for "{query}".', color=self.TEXT_MUTED)
                )
            for member in members[:8]:
                self.payment_results.controls.extend(self._payable_cards(member))
            if len(members) > 8:
                self.payment_results.controls.append(
                    self.styled_text(
                        "More members match. Keep typing to narrow the list.",
                        12,
                        color=self.TEXT_MUTED,
                    )
                )
        self.page.update()
    def payable_search_enter(self):
        """Enter selects the membership when the search points at exactly one unpaid membership.
        A member ID typed (or scanned) that matches exactly always wins."""
        query = (self.payment_search_field.value or "").strip()
        if not query:
            return
        members = self.manager.find_members(query, limit=9)
        if query.isdigit() and members and members[0]["id"] == int(query):
            members = members[:1]
        owed = [
            membership
            for member in members
            for membership in self.manager.payable_memberships(member["id"])
        ]
        if len(owed) == 1:
            return self.select_payment_membership(owed[0]["id"])
        if not members:
            return self.toast("No member found.")
        if not owed:
            return self.toast("Nothing owed: no unpaid membership for that search.")
        self.toast("Several memberships match. Pick one from the list.")
    def select_payment_membership(self, membership_id):
        membership = self.manager.membership_summary(membership_id)
        if not membership or float(membership["plan_price"]) - float(membership["paid"]) <= 0.005:
            return self.show_warning(
                "Nothing to pay",
                "This membership has no balance left. Search again to refresh the list.",
            )
        self.selected_payment_membership_id = membership_id
        self.draw_payment_form()
        self.page.update()
        self.focus_control(self.amount_field)
    def draw_payment_form(self):
        self.payment_form.controls.clear()
        membership_id = self.selected_payment_membership_id
        membership = (
            self.manager.membership_summary(membership_id) if membership_id is not None else None
        )
        if not membership:
            self.payment_form.controls.append(
                self.styled_text(
                    "Select a membership above to enter the payment.", 12, color=self.TEXT_MUTED
                )
            )
            return
 
        def make_field(label, width, value=None):
            return ft.TextField(
                label=label,
                width=width,
                value=value,
                label_style=ft.TextStyle(size=13),
                **field_style(),
            )
 
        price, paid = float(membership["plan_price"]), float(membership["paid"])
        self.payment_form.controls.append(
            ft.Container(
                bgcolor=self.ORANGE_TINT,
                border_radius=10,
                padding=pad_all(12),
                content=ft.Column(
                    [
                        self.styled_text(f"Paying: {row_full_name(membership)}", 14, True),
                        self.styled_text(
                            f"{membership['plan_name']} ({membership['start_date']} to {membership['end_date']})  •  "
                            f"Paid ₱{paid:,.2f} of ₱{price:,.2f}  •  Balance ₱{max(0.0, price - paid):,.2f}",
                            12,
                            color=self.TEXT_MUTED,
                        ),
                    ],
                    spacing=2,
                ),
            )
        )
        self.amount_field = make_field("Amount ₱", 160)
        self.method_dropdown = ft.Dropdown(
            options=[DropdownItem(option) for option in PAYMENT_METHODS],
            value="Cash",
            width=160,
            **field_style(),
        )
        self.payment_date_field = self.date_field(
            "Date YYYY-MM-DD", 200, date.today().isoformat(), title="Payment date"
        )
        self.note_field = make_field("Note optional", 260)
        center_alignment = ft.CrossAxisAlignment.CENTER
        self.payment_form.controls.append(
            ft.Row(
                [
                    self.amount_field,
                    self.method_dropdown,
                    self.button("Pay Full Balance", self.fill_full_balance, 150, self.ORANGE_DEEP),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=center_alignment,
            )
        )
        self.payment_form.controls.append(
            ft.Row(
                [
                    self.payment_date_field,
                    self.note_field,
                    self.button("Save Payment", self.save_payment, 125),
                    self.button("Cancel", self.cancel_payment_selection, 100, self.GRAY),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=center_alignment,
            )
        )
    def cancel_payment_selection(self):
        self.selected_payment_membership_id = None
        self.draw_payment_form()
        self.payment_search_field.value = ""
        self.refresh_payable_results()
        self.focus_control(self.payment_search_field)
    def build_outstanding_balance_page(self):
        self.outstanding_section = self.add_section(
            self.payment_panel, "Outstanding Balances", "Oldest membership start date first"
        )
        self.refresh_outstanding_balances()
    def build_payment_history_page(self):
        panel = self.payment_panel
        self.payment_summary = ft.Row(spacing=8, wrap=True)
        panel.controls.append(self.payment_summary)
 
        style = field_style(width=FIELD_WIDTH)
        label_style = ft.TextStyle(size=13)
 
        self.history_from_field = self.date_field(
            "From date", FIELD_WIDTH, title="From date", hint_text="YYYY-MM-DD"
        )
        self.history_to_field = self.date_field(
            "To date", FIELD_WIDTH, title="To date", hint_text="YYYY-MM-DD"
        )
        self.history_customer_field = ft.TextField(
            label="Customer name", label_style=label_style, **style
        )
        self.history_method_dropdown = ft.Dropdown(
            options=[DropdownItem(option) for option in (["All Methods"] + PAYMENT_METHODS)],
            value="All Methods",
            **style,
        )
        self.history_status_dropdown = ft.Dropdown(
            options=[DropdownItem(option) for option in ("All Payments", "Voided Only")],
            value="All Payments",
            **style,
        )
 
        apply_button = self.button("Apply Filters", self.refresh_payments, FIELD_WIDTH)
        show_all_button = self.button(
            "Show All", self.clear_payment_filters, FIELD_WIDTH, self.GRAY
        )
        for control in (apply_button, show_all_button):
            control.width = FIELD_WIDTH
            control.height = FIELD_HEIGHT
 
        panel.controls.append(
            ft.Row(
                [
                    self.history_from_field,
                    self.history_to_field,
                    self.history_customer_field,
                    self.history_method_dropdown,
                    self.history_status_dropdown,
                    apply_button,
                    show_all_button,
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.payment_table = self.add_section(panel, "Payment History", "Newest first")
        self.refresh_payments()
    def fill_full_balance(self):
        if self.selected_payment_membership_id is None:
            return self.show_warning(
                "Select membership", "Find the member and select a membership first."
            )
        self.amount_field.value = (
            f"{self.manager.membership_balance(self.selected_payment_membership_id):.2f}"
        )
        self.page.update()
    def clear_payment_filters(self):
        for filter_field in (
            self.history_from_field,
            self.history_to_field,
            self.history_customer_field,
        ):
            filter_field.value = ""
        self.history_method_dropdown.value = "All Methods"
        self.history_status_dropdown.value = "All Payments"
        self.refresh_payments()
    def select_outstanding_membership(self, membership_id):
        # The Record Payment widgets are rebuilt when the subpage is shown.
        self.show_payment_subpage("Record Payment")
        self.select_payment_membership(membership_id)
    def refresh_outstanding_balances(self):
        customers={c["id"]:c for c in self.db.rows("customers")}; payments=self.db.rows("payments")
        memberships=[]
        for m in self.db.rows("memberships"):
            if m["customer_id"] not in customers: continue
            paid=sum(float(p["amount"] or 0) for p in payments if p.get("membership_id")==m["id"] and not p.get("voided"))
            balance=max(0,float(m["plan_price"])-paid)
            if balance>0: memberships.append({**m,"full_name":customers[m["customer_id"]]["full_name"],"paid":paid,"balance":balance})
        memberships.sort(key=lambda m:(m["start_date"],m["id"]))
        table_rows = [
            [
                membership["full_name"],
                membership["plan_name"],
                f"₱{membership['plan_price']:,.2f}",
                f"₱{membership['paid']:,.2f}",
                f"₱{membership['balance']:,.2f}",
                membership["start_date"],
                self.small_button(
                    "Pay",
                    lambda membership_id=int(membership["id"]): self.select_outstanding_membership(
                        membership_id
                    ),
                    60,
                ),
            ]
            for membership in memberships
        ]
        self.outstanding_section.controls.append(
            self.table(
                ["Customer", "Plan", "Price", "Paid", "Balance", "Start Date", "Action"],
                table_rows,
                "No outstanding balances.",
            )
        )
    def refresh_payment_summary(self, where_sql, params):
        self.payment_summary.controls.clear()
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=7)
        month_start = today.replace(day=1)
        month_end = (
            date(today.year + 1, 1, 1)
            if today.month == 12
            else date(today.year, today.month + 1, 1)
        )
        periods = [
            ("Income Today", today.isoformat(), (today + timedelta(days=1)).isoformat()),
            ("Income This Week", week_start.isoformat(), week_end.isoformat()),
            ("Income This Month", month_start.isoformat(), month_end.isoformat()),
        ]
        summary_cards = []
        user=self.manager.current_user
        for label, period_start, period_end in periods:
            total=sum(float(p["amount"] or 0) for p in self.db.rows("payments") if period_start<=p["payment_date"]<period_end and not p.get("voided") and user and (user["role"]=="owner" or p.get("recorded_by")==user["id"]))
            summary_cards.append((label, float(total)))
        # The summary uses the same visible payment set as the history table.
        totals={}
        for row in getattr(self,"filtered_payment_rows",[]):
            if row.get("voided"): continue
            totals[row["method"]]=totals.get(row["method"],0.0)+float(row["amount"] or 0)
        # GCash, Maya, and Bank Transfer remain separate methods in records and
        # filters, but their totals share one compact E-Wallet card.
        summary_cards.extend(summarize_payment_methods(totals))
        label_prefix = (
            "" if self.is_owner else "My "
        )  # method totals are already limited to the person's own payments
        for label, value in summary_cards:
            label = label_prefix + label
            self.payment_summary.controls.append(
                ft.Container(
                    width=CARD_WIDTH,
                    bgcolor=self.SURFACE,
                    border_radius=8,
                    padding=pad_all(9),
                    content=ft.Column(
                        [
                            self.styled_text(label, 10, True, self.TEXT_MUTED),
                            self.styled_text(f"₱{value:,.2f}", 15, True),
                        ],
                        spacing=4,
                    ),
                )
            )
    def save_payment(self):
        try:
            membership_id = self.selected_payment_membership_id
            if membership_id is None:
                raise ValueError("Find the member and select a membership first.")
            membership = self.db.get("memberships",id=membership_id)
            if not membership:
                raise ValueError("Select a valid membership.")
            try:
                amount = float(self.amount_field.value)
            except (TypeError, ValueError):
                raise ValueError("Enter a valid amount.")
            if amount <= 0:
                raise ValueError("Payment amount must be greater than zero.")
            date.fromisoformat((self.payment_date_field.value or "").strip())
            amount_text, date_text, note_text, method_text = (
                self.amount_field.value,
                self.payment_date_field.value,
                self.note_field.value or "",
                self.method_dropdown.value,
            )
            summary = (
                f"Member: {self.db.get('customers',id=membership['customer_id'])['full_name']}\n"
                f"Membership: {membership['plan_name']} (ID {membership_id})\nAmount: ₱{amount:,.2f}\n"
                f"Date: {date_text.strip()}\nMethod: {method_text}\n\nEnter your password to save this payment."
            )
 
            def authorized_save():
                try:
                    payment_id = self.manager.record_payment(
                        membership["customer_id"],
                        membership_id,
                        amount_text,
                        date_text,
                        note_text,
                        method=method_text,
                        authorized=True,
                    )
                    self.payment_page()
                    self.page.update()
                    self.show_receipt(payment_id)
                except (ValueError, DataError) as error:
                    self.show_error("Unable to save payment", str(error))
 
            self._confirm_with_password(
                "Confirm Payment", authorized_save, summary, "Authenticate & Save"
            )
        except (ValueError, DataError, AttributeError, TypeError) as error:
            self.show_error("Unable to save payment", str(error))
    def refresh_payments(self):
        if not hasattr(self, "payment_table"):
            return
        from_text = (self.history_from_field.value or "").strip()
        to_text = (self.history_to_field.value or "").strip()
        for date_text in (from_text, to_text):
            if date_text:
                try:
                    date.fromisoformat(date_text)
                except ValueError:
                    return self.show_error("Invalid date", "Use YYYY-MM-DD.")
        if from_text and to_text and from_text > to_text:
            return self.show_error("Invalid date range", "From date must be on or before To date.")
        customer = (self.history_customer_field.value or "").strip()
        method = (self.history_method_dropdown.value or "").strip()
        customer_rows={c["id"]:c for c in self.db.rows("customers")}; membership_rows={m["id"]:m for m in self.db.rows("memberships")}; user_rows={u["id"]:u for u in self.db.rows("users")}
        all_payments=sorted(self.db.rows("payments"),key=lambda p:(p["payment_date"],p["id"]))
        rows=[]
        user=self.manager.current_user
        for p in all_payments:
            c=customer_rows.get(p["customer_id"])
            if not c: continue
            if from_text and p["payment_date"]<from_text: continue
            if to_text and p["payment_date"]>to_text: continue
            customer_name = " ".join(
                str(c.get(field) or "")
                for field in ("full_name", "first_name", "last_name")
            )
            if customer and customer.casefold() not in customer_name.casefold(): continue
            if method and method!="All Methods" and p.get("method")!=method: continue
            if (self.history_status_dropdown.value or "") == "Voided Only" and not p.get("voided"): continue
            if not user or (user["role"]!="owner" and p.get("recorded_by")!=user["id"]): continue
            m=membership_rows.get(p.get("membership_id"))
            prior=sum(float(old["amount"] or 0) for old in all_payments if old.get("membership_id")==p.get("membership_id") and not old.get("voided") and (old["payment_date"],old["id"])<=(p["payment_date"],p["id"])) if p.get("membership_id") is not None else 0
            rows.append({**p,"staff_name":(user_rows.get(p.get("recorded_by")) or {}).get("display_name"),"voided_by_name":(user_rows.get(p.get("voided_by")) or {}).get("display_name"),"full_name":c["full_name"],"plan_name":(m or {}).get("plan_name"),"plan_price":(m or {}).get("plan_price"),"paid_at_payment":prior})
        rows.sort(key=lambda p:p["id"],reverse=True)
        self.filtered_payment_rows = rows
        self.payment_table.controls.clear()
        self.refresh_payment_summary("", ())
        self.payment_records_table(rows)
        self.page.update()
    def payment_records_table(self, rows):
        is_owner = self.is_owner
        table_rows = []
        for payment in rows:
            payment_id = int(payment["id"])
            voided = bool(payment["voided"])
            balance = max(
                0.0, float(payment["plan_price"] or 0) - float(payment["paid_at_payment"])
            )
            amount = f"₱{payment['amount']:,.2f}"
            # Voided payments stay visible: struck-through amount, red VOID note, no balance.
            if voided:
                voided_by_text = (
                    f" by {payment['voided_by_name']}"
                    if is_owner and payment["voided_by_name"]
                    else ""
                )
                note = ft.Text(
                    f"VOID{voided_by_text}: {payment['void_reason']}",
                    size=12,
                    color=self.RED,
                    text_align=ft.TextAlign.CENTER,
                )
                amount_cell = ft.Text(
                    amount,
                    size=12,
                    color=self.TEXT_MUTED,
                    text_align=ft.TextAlign.CENTER,
                    style=ft.TextStyle(decoration=ft.TextDecoration.LINE_THROUGH),
                )
            else:
                note, amount_cell = payment["note"], amount
            cells = [
                payment["id"],
                payment["full_name"],
                payment["plan_name"] or payment["note"] or "—",
                amount_cell,
                payment["payment_date"],
                payment["method"],
                payment["receipt_no"],
                "—" if voided else f"₱{balance:,.2f}",
            ]
            if is_owner:  # who took the payment is for the owner's eyes only
                cells.append(payment["staff_name"] or "—")
            cells += [
                note,
                self.small_button(
                    "View Receipt", lambda payment_id=payment_id: self.show_receipt(payment_id), 100
                ),
            ]
            if voided:
                cells.append(ft.Text("Voided", size=12, color=self.TEXT_MUTED))
            elif self.manager.can_void(payment):
                cells.append(
                    self.small_button(
                        "Void",
                        lambda payment_id=payment_id: self.void_payment(payment_id),
                        62,
                        self.RED,
                    )
                )
            else:
                cells.append(ft.Text("—", size=12, color=self.TEXT_MUTED))
            table_rows.append(cells)
        self.payment_table.controls.append(
            self.table(
                [
                    "ID",
                    "Customer",
                    "Plan",
                    "Amount",
                    "Date",
                    "Method",
                    "Receipt No",
                    "Balance After",
                ]
                + (["Recorded By"] if is_owner else [])
                + ["Note", "Receipt", "Void"],
                table_rows,
                "No payment records found.",
                weights=[1, 3, 3, 3, 3, 2, 4, 3] + ([3] if is_owner else []) + [3, 4, 3],
            )
        )
    def _payment_row(self, payment_id):
        payment=self.db.get("payments",id=payment_id)
        if not payment:return None
        user=self.manager.current_user
        if not user or (user["role"]!="owner" and payment.get("recorded_by")!=user["id"]):return None
        customer=self.db.get("customers",id=payment["customer_id"]) or {}
        membership=self.db.get("memberships",id=payment.get("membership_id")) if payment.get("membership_id") else {}
        users={u["id"]:u for u in self.db.rows("users")}
        prior=sum(float(p["amount"] or 0) for p in self.db.rows("payments") if payment.get("membership_id") is not None and p.get("membership_id")==payment.get("membership_id") and not p.get("voided") and (p["payment_date"],p["id"])<=(payment["payment_date"],payment["id"]))
        return {**payment,"full_name":customer.get("full_name"),"plan_name":membership.get("plan_name"),"plan_price":membership.get("plan_price"),"staff_name":(users.get(payment.get("recorded_by")) or {}).get("display_name"),"voided_by_name":(users.get(payment.get("voided_by")) or {}).get("display_name"),"paid_at_payment":prior}

    def show_receipt(self, payment_id):
        payment=self._payment_row(payment_id)
        if not payment:
            return self.show_error("Receipt unavailable", "Payment record not found.")
        balance = max(0.0, float(payment["plan_price"] or 0) - float(payment["paid_at_payment"]))
        details = {
            "Customer": payment["full_name"],
            "Plan": payment["plan_name"] or payment["note"] or "—",
            "Receipt No": payment["receipt_no"],
            "Date": payment["payment_date"],
            "Method": payment["method"],
            "Amount Paid": f"₱{payment['amount']:,.2f}",
            "Balance After Payment": f"₱{balance:,.2f}",
            "Recorded By": payment["staff_name"] or "—",
        }
        if payment["voided"]:
            details["Status"] = "VOIDED"
            details["Void Reason"] = payment["void_reason"]
            details["Voided By"] = payment["voided_by_name"] or "—"
 
        def save_receipt():
            # Native save dialog (tkinter is used only for the file chooser).
            try:
                import tkinter as tk
                from tkinter import filedialog
 
                root = tk.Tk()
                root.withdraw()
                try:
                    root.attributes("-topmost", True)
                except Exception:
                    pass
                path = filedialog.asksaveasfilename(
                    parent=root,
                    defaultextension=".txt",
                    filetypes=[("Text files", "*.txt")],
                    initialfile=f"{payment['receipt_no']}.txt",
                )
                root.destroy()
            except Exception as error:
                return self.show_error("Unable to save receipt", str(error))
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as receipt_file:
                    receipt_file.write("BSIT-2B Gym\nPayment Receipt\n\n")
                    receipt_file.writelines(
                        f"{label}: {value}\n" for label, value in details.items()
                    )
                self.show_info("Receipt saved", "Receipt saved successfully.")
            except OSError as error:
                self.show_error("Unable to save receipt", str(error))
 
        lines = [
            ft.Row(
                [
                    self.styled_text(label, color=self.TEXT_MUTED),
                    self.styled_text(value, bold=True),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            for label, value in details.items()
        ]
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Payment Receipt", weight=ft.FontWeight.BOLD),
            content=ft.Container(
                ft.Column(lines, spacing=10, tight=True),
                width=400,
                bgcolor=self.SURFACE,
                border_radius=8,
                padding=14,
            ),
            actions=[
                self.button("Save as .txt", save_receipt, 145),
                self.button("Close", lambda: self.close_dialog(dialog), 100, self.GRAY),
            ],
        )
        self.open_dialog(dialog)
    def void_payment(self, payment_id):
        payment=self._payment_row(payment_id)
        if not payment:
            return self.show_error("Payment not found", "This payment record no longer exists.")
        if payment["voided"]:
            return self.show_warning("Already voided", "This payment has already been voided.")
        if not self.manager.can_void(payment):
            return self.show_warning(
                "Can't void this payment",
                "Staff can only void payments they recorded themselves, on the day they recorded them. "
                "Ask the owner to void this one.",
            )
        summary = (
            f"Void payment ID {payment_id}?\nMember: {payment['full_name']}\nAmount: ₱{payment['amount']:,.2f}\n"
            f"Date: {payment['payment_date']}\nMethod: {payment['method']}\nReceipt: {payment['receipt_no']}\n\n"
            "The payment is NOT deleted: it stays in the history marked VOID with your name and the reason. "
            "The membership balance and status are recalculated."
        )
        reason_field = ft.TextField(
            label="Reason for voiding (required)",
            width=450,
            label_style=ft.TextStyle(size=13),
            **field_style(),
        )
 
        def continue_to_password():
            reason_text = " ".join((reason_field.value or "").split())
            if len(reason_text) < 3:
                return self.show_error(
                    "Reason required", "Enter a short reason (at least 3 characters)."
                )
            self.close_dialog(dialog)
 
            def do_void():
                try:
                    self.manager.void_payment(payment_id, reason_text, authorized=True)
                    self.payment_page()
                    self.show_payment_subpage("Payment History")
                    self.show_info(
                        "Payment voided",
                        "The payment was voided. The membership balance and status were recalculated.",
                    )
                except (ValueError, DataError) as error:
                    self.show_error("Unable to void payment", str(error))
 
            self._confirm_with_password("Authorize Void", do_void, summary, "Authenticate & Void")
 
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Void Payment", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Container(
                        ft.Text(summary, color=self.TEXT_PRIMARY),
                        bgcolor=self.ORANGE_TINT,
                        border_radius=8,
                        padding=10,
                        width=450,
                    ),
                    reason_field,
                ],
                tight=True,
                width=470,
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
            actions=[
                self.button("Continue", continue_to_password, 130),
                self.button("Cancel", lambda: self.close_dialog(dialog), 100, self.GRAY),
            ],
        )
        self.open_dialog(dialog)
        self.focus_control(reason_field)

