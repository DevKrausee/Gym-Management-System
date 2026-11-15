"""Membership list, renewals, membership creation, and balance displays."""

from datetime import date, timedelta

import flet as ft

from ..database import DataError

from ..config import (
    DropdownItem,
    PLANS,
    build_list_name,
    field_style,
    pad_all,
    pad_symmetric,
    row_full_name,
)



class MembershipsMixin:
    def membership_page(self):
        page_content = self.new_page("Memberships")
        self.selected_renewal_member_id = None
        if self.is_owner:
            pricing = self.add_section(
                page_content,
                "Regular Membership Pricing",
                "Set rates for new sales. Existing memberships keep their recorded price.",
            )
            price_fields = [
                (name, ft.TextField(
                    label=f"{name} (₱)",
                    value=f"{self.manager.regular_price(name):.2f}",
                    width=190,
                    **field_style(),
                ))
                for name in PLANS
            ]
            pricing.controls.append(ft.Row(
                [*(field for _, field in price_fields), self.button("Save Prices", lambda: self._save_regular_prices(price_fields), 130)],
                wrap=True,
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ))

        # Quick lookup lets staff verify a customer's current gym access without
        # selecting the customer for a new membership or renewal.
        checker_body = self.add_section(
            page_content,
            "Check Membership Access",
            "Search by customer name, phone number, or member ID to verify their subscription status.",
        )
        self.access_search_field = ft.TextField(
            label="Customer name, phone or member ID",
            width=420,
            label_style=ft.TextStyle(size=13),
            on_submit=lambda event: self.check_membership_access(),
            **field_style(),
        )
        self.access_search_results = ft.Column(
            spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
        checker_body.controls.append(
            ft.Row(
                [
                    self.access_search_field,
                    self.button("Search", self.check_membership_access, 105),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        checker_body.controls.append(self.access_search_results)

        form_body = self.add_section(
            page_content,
            "Create / Renew Membership",
            "Find the member, then choose the plan and start date. The end date is calculated automatically.",
        )
        if not self.db.rows("customers"):
            form_body.controls.append(
                self.styled_text("Add a customer first.", color=self.TEXT_MUTED)
            )
        else:
            self.membership_search_field = ft.TextField(
                label="Search name, phone or member ID",
                width=520,
                label_style=ft.TextStyle(size=13),
                on_change=lambda event: self.refresh_renewal_results(),
                on_submit=lambda event: self.renewal_search_enter(),
                **field_style(),
            )
            self.membership_results = ft.Column(
                spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
            )
            self.membership_form = ft.Column(
                spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
            )
            form_body.controls.extend(
                [self.membership_search_field, self.membership_results, self.membership_form]
            )
            self.refresh_renewal_results()
            self.draw_membership_form()
        records_body = self.add_section(
            page_content,
            "Membership Records",
            "Access depends on valid membership dates. Outstanding balances must be settled before another membership can be created.",
        )
        customers={c["id"]:c for c in self.db.rows("customers")}
        payments=self.db.rows("payments")
        memberships=[]
        for m in sorted(self.db.rows("memberships"),key=lambda m:m["id"],reverse=True):
            customer=customers.get(m["customer_id"])
            if customer: memberships.append({**m,"full_name":customer["full_name"],"paid":sum(float(p["amount"] or 0) for p in payments if p.get("membership_id")==m["id"] and not p.get("voided"))})
        today = date.today().isoformat()
        if not hasattr(self, "membership_status_filter"):
            self.membership_status_filter = "All"
        filters = ft.Row(spacing=8, wrap=True)
        for status_filter in ("All", "Active", "Expired"):
            filters.controls.append(self.button(
                status_filter,
                lambda value=status_filter: self._set_membership_status_filter(value),
                100,
                self.ORANGE if self.membership_status_filter == status_filter else self.GRAY,
            ))
        records_body.controls.append(filters)
        table_rows = []
        is_owner = self.is_owner
        for membership in memberships:
            balance = max(0, membership["plan_price"] - membership["paid"])
            if today < membership["start_date"]:
                access_status = "Upcoming"
            elif today > membership["end_date"]:
                access_status = "Expired"
            else:
                # Active dates grant access even when the balance is unpaid.
                access_status = "Active"
            if self.membership_status_filter in ("Active", "Expired") and access_status != self.membership_status_filter:
                continue
            # Color-coded access badge: access is still determined by membership dates.
            access_colors = {
                "Upcoming": ("#431407", "#FDBA74"),  # Orange
                "Active": ("#14532D", "#86EFAC"),    # Green
                "Expired": ("#7F1D1D", "#FCA5A5"),   # Red
            }
            badge_background, badge_text = access_colors[access_status]
            access_badge = ft.Container(
                content=ft.Text(
                    access_status,
                    size=11,
                    weight=ft.FontWeight.BOLD,
                    color=badge_text,
                ),
                bgcolor=badge_background,
                border_radius=20,
                padding=pad_symmetric(horizontal=10, vertical=5),
            )
            membership_id = int(membership["id"])
            table_row = [
                membership["id"],
                membership["full_name"],
                membership["plan_name"],
                membership["start_date"],
                membership["end_date"],
                f"₱{membership['plan_price']:,.2f}",
                membership["payment_status"],
                f"₱{balance:,.2f}",
                access_badge,
            ]
            if is_owner:
                table_row.append(
                    self.small_button(
                        "Delete",
                        lambda membership_id=membership_id: self.delete_membership(membership_id),
                        62,
                        self.RED,
                    )
                )
            table_rows.append(table_row)
        records_body.controls.append(
            self.table(
                ["ID", "Customer", "Plan", "Start", "End", "Price", "Payment", "Balance", "Access"]
                + (["Delete"] if is_owner else []),
                table_rows,
                "No membership records found.",
            )
        )
        self.page.update()

    def _set_membership_status_filter(self, status):
        self.membership_status_filter = status
        self.membership_page()
    def check_membership_access(self, customer_id=None):
        """Find a customer and show whether any membership grants access today."""
        query = (self.access_search_field.value or "").strip()
        self.access_search_results.controls.clear()

        if customer_id is None:
            if not query:
                self.access_search_results.controls.append(
                    self.styled_text("Enter a customer name, phone number, or member ID.", color=self.TEXT_MUTED)
                )
                self.page.update()
                return
            matches = self.manager.find_members(query, limit=10)
            if query.isdigit() and matches and matches[0]["id"] == int(query):
                matches = matches[:1]
            if not matches:
                self.access_search_results.controls.append(
                    self.styled_text(f'No customer found for "{query}".', color=self.TEXT_MUTED)
                )
            elif len(matches) > 1:
                self.access_search_results.controls.append(
                    self.styled_text("Multiple customers found. Select the correct customer:", 12, color=self.TEXT_MUTED)
                )
                for member in matches:
                    self.access_search_results.controls.append(
                        self.button(
                            f"{row_full_name(member)}  •  ID {member['id']}",
                            lambda selected_id=member["id"]: self.check_membership_access(selected_id),
                            260,
                            self.GRAY,
                        )
                    )
            else:
                customer_id = matches[0]["id"]

        if customer_id is not None:
            customer = self.db.get("customers",id=customer_id)
            if not customer:
                self.access_search_results.controls.append(
                    self.styled_text("Customer not found. Please search again.", color=self.RED)
                )
            else:
                today = date.today().isoformat()
                memberships=sorted((m for m in self.db.rows("memberships") if m["customer_id"]==customer_id),key=lambda m:(m["start_date"],m["id"]),reverse=True)
                current = next(
                    (item for item in memberships if item["start_date"] <= today <= item["end_date"]),
                    None,
                )
                upcoming = next(
                    (item for item in reversed(memberships) if item["start_date"] > today),
                    None,
                )
                latest = memberships[0] if memberships else None
                if current:
                    status, background, foreground = "Active", "#14532D", "#86EFAC"
                    detail = f"{current['plan_name']} • Valid until {current['end_date']}"
                elif upcoming:
                    status, background, foreground = "Upcoming", "#431407", "#FDBA74"
                    detail = f"{upcoming['plan_name']} • Starts {upcoming['start_date']}"
                elif latest:
                    status, background, foreground = "Expired", "#7F1D1D", "#FCA5A5"
                    detail = f"{latest['plan_name']} • Expired {latest['end_date']}"
                else:
                    status, background, foreground = "No Membership", self.SURFACE_ALT, self.TEXT_MUTED
                    detail = "This customer has no membership record."

                status_badge = ft.Container(
                    content=ft.Text(status, size=12, weight=ft.FontWeight.BOLD, color=foreground),
                    bgcolor=background,
                    border_radius=20,
                    padding=pad_symmetric(horizontal=12, vertical=6),
                )
                self.access_search_results.controls.append(
                    ft.Container(
                        bgcolor=self.SURFACE_ALT,
                        border_radius=10,
                        padding=pad_all(12),
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Column(
                                            [
                                                self.styled_text(row_full_name(customer), 15, True),
                                                self.styled_text(
                                                    f"Member ID {customer['id']} • {customer['phone'] or 'No phone number'}",
                                                    12,
                                                    color=self.TEXT_MUTED,
                                                ),
                                            ],
                                            spacing=2,
                                            expand=True,
                                        ),
                                        status_badge,
                                    ],
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                self.styled_text(detail, 12, color=self.TEXT_MUTED),
                                self.styled_text(
                                    "Access allowed today." if status == "Active" else "Gym access is not allowed today.",
                                    12,
                                    bold=True,
                                    color="#86EFAC" if status == "Active" else self.RED,
                                ),
                            ],
                            spacing=5,
                        ),
                    )
                )

        self.page.update()

    @staticmethod
    def _standing_text(standing):
        latest, today = standing["latest"], date.today().isoformat()
        if not latest:
            return "No membership yet"
        if latest["start_date"] > today:
            return f"{latest['plan_name']} starts {latest['start_date']}"
        if latest["end_date"] >= today:
            return f"{latest['plan_name']} active until {latest['end_date']}"
        return f"Last membership ended {latest['end_date']} ({latest['plan_name']})"
    def _renewal_card(self, member):
        name = build_list_name(
            member["first_name"], member["middle_name"], member["last_name"], member["extension"]
        )
        standing = self.manager.membership_standing(member["id"])
        lines = [
            self.styled_text(name, 15, True),
            self.styled_text(
                f"Member ID {member['id']}  •  {member['phone'] or 'no phone'}",
                12,
                color=self.TEXT_MUTED,
            ),
            self.styled_text(self._standing_text(standing), 12, color=self.TEXT_MUTED),
        ]
        if standing["owed"] > 0.005:  # the renewal rule: nothing new until the old balance is paid
            lines.append(
                self.styled_text(
                    f"Owes ₱{standing['owed']:,.2f}. A new membership can't be created until it is paid.",
                    12,
                    color=self.RED,
                )
            )
            action = self.button(
                "Pay Balance",
                lambda membership_id=standing["owed_membership_id"]: self.pay_from_membership(
                    membership_id
                ),
                140,
                self.ORANGE_DEEP,
            )
        else:
            action = self.button(
                "Select",
                lambda customer_id=member["id"]: self.select_membership_member(customer_id),
                110,
            )
        return ft.Container(
            bgcolor=self.SURFACE_ALT,
            border_radius=10,
            padding=pad_symmetric(horizontal=14, vertical=10),
            content=ft.Row(
                [ft.Column(lines, spacing=2, expand=True), action],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
    def refresh_renewal_results(self):
        query = (self.membership_search_field.value or "").strip()
        self.membership_results.controls.clear()
        if not query:
            self.membership_results.controls.append(
                self.styled_text(
                    "Start typing to find a member. Press Enter to select when only one member matches.",
                    12,
                    color=self.TEXT_MUTED,
                )
            )
        else:
            members = self.manager.find_members(query, limit=9)
            if not members:
                self.membership_results.controls.append(
                    self.styled_text(f'No member found for "{query}".', color=self.TEXT_MUTED)
                )
            for member in members[:8]:
                self.membership_results.controls.append(self._renewal_card(member))
            if len(members) > 8:
                self.membership_results.controls.append(
                    self.styled_text(
                        "More members match. Keep typing to narrow the list.",
                        12,
                        color=self.TEXT_MUTED,
                    )
                )
        self.page.update()
    def renewal_search_enter(self):
        """Enter selects the member when exactly one person matches (an exact ID always wins)."""
        query = (self.membership_search_field.value or "").strip()
        if not query:
            return
        members = self.manager.find_members(query, limit=9)
        if query.isdigit() and members and members[0]["id"] == int(query):
            members = members[:1]
        if len(members) != 1:
            return self.toast(
                "No member found."
                if not members
                else "Several members match. Pick one from the list."
            )
        member = members[0]
        standing = self.manager.membership_standing(member["id"])
        if standing["owed"] > 0.005:
            return self.show_warning(
                "Balance owed",
                f"{row_full_name(member)} owes ₱{standing['owed']:,.2f}. A new membership can't be created until it is paid.",
            )
        self.select_membership_member(member["id"])
    def pay_from_membership(self, membership_id):
        self.navigate("Payments", self.payment_page)
        self.select_outstanding_membership(membership_id)
    def select_membership_member(self, customer_id):
        if not self.db.get("customers",id=customer_id):
            return self.show_warning(
                "Member not found", "That member no longer exists. Search again."
            )
        self.selected_renewal_member_id = customer_id
        self.draw_membership_form()
        self.page.update()
    def draw_membership_form(self):
        self.membership_form.controls.clear()
        customer_id = self.selected_renewal_member_id
        customer_row = (
            self.db.get("customers",id=customer_id)
            if customer_id is not None
            else None
        )
        if not customer_row:
            self.membership_form.controls.append(
                self.styled_text(
                    "Select a member above to choose their plan.", 12, color=self.TEXT_MUTED
                )
            )
            return
        self.membership_form.controls.append(
            ft.Container(
                bgcolor=self.ORANGE_TINT,
                border_radius=10,
                padding=pad_all(12),
                content=ft.Column(
                    [
                        self.styled_text(
                            f"Membership for: {row_full_name(customer_row)}", 14, True
                        ),
                        self.styled_text(
                            self._standing_text(self.manager.membership_standing(customer_id)),
                            12,
                            color=self.TEXT_MUTED,
                        ),
                    ],
                    spacing=2,
                ),
            )
        )
        self.plan_dropdown = ft.Dropdown(
            options=[DropdownItem(option) for option in PLANS],
            value="Monthly",
            width=220,
            **field_style(),
        )
        self.start_date_field = self.date_field(
            "Start YYYY-MM-DD", 220, date.today().isoformat(), title="Membership start date"
        )
        self.membership_preview = self.styled_text("", 12, color=self.TEXT_MUTED)
        self.plan_dropdown.on_change = lambda event: self.update_membership_preview()
        self.plan_dropdown.on_select = (
            lambda event: self.update_membership_preview()
        )  # newer Flet versions fire on_select
        self.start_date_field.on_change = lambda event: self.update_membership_preview()
        self.update_membership_preview(refresh=False)
        self.membership_form.controls.append(
            ft.Row(
                [
                    self.plan_dropdown,
                    self.start_date_field,
                    self.button("Create Membership", self.create_membership, 160),
                    self.button("Cancel", self.cancel_membership_selection, 100, self.GRAY),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.membership_form.controls.append(self.membership_preview)
    def _save_regular_prices(self, fields):
        try:
            updates = [(name, round(float(field.value), 2)) for name, field in fields]
            if any(price < 0 for _, price in updates):
                raise ValueError("Membership prices cannot be negative.")
            changed = [(name, price) for name, price in updates if round(self.manager.regular_price(name), 2) != price]
            if not changed:
                return self.toast("No regular membership price changes to save.")
            summary = "Save these regular membership prices?\n\n" + "\n".join(f"{name}: ₱{price:,.2f}" for name, price in changed)
            def save():
                try:
                    for name, price in changed:
                        self.manager.set_regular_price(name, price)
                    self.membership_page()
                    self.toast("Regular membership prices saved.")
                except Exception as error:
                    self.show_error("Unable to save prices", str(error))
            self.ask_yes_no("Confirm Regular Price Changes", summary, save)
        except (TypeError, ValueError) as error:
            self.show_error("Unable to save prices", str(error))

    def update_membership_preview(self, refresh=True):
        plan_info = PLANS.get(self.plan_dropdown.value)
        try:
            start_date = date.fromisoformat((self.start_date_field.value or "").strip())
        except ValueError:
            start_date = None
        if not plan_info:
            preview_text = "Choose a plan."
        elif start_date is None:
            preview_text = "Enter the start date as YYYY-MM-DD."
        else:
            end_date = start_date + timedelta(days=plan_info["days"] - 1)
            preview_text = (
                f"{self.plan_dropdown.value}: ₱{self.manager.regular_price(self.plan_dropdown.value):,.2f}  •  {start_date.isoformat()} to {end_date.isoformat()} "
                f"({plan_info['days']} day{'' if plan_info['days'] == 1 else 's'})"
            )
        self.membership_preview.value = preview_text
        if refresh:
            self.page.update()
    def cancel_membership_selection(self):
        self.selected_renewal_member_id = None
        self.draw_membership_form()
        self.membership_search_field.value = ""
        self.refresh_renewal_results()
        self.focus_control(self.membership_search_field)
    def delete_membership(self, membership_id):
        def do_delete():
            try:
                self.manager.delete_membership(membership_id)
                self.membership_page()
                self.show_info("Deleted", "Membership deleted successfully.")
            except (ValueError, DataError) as error:
                self.show_error("Unable to delete membership", str(error))
 
        self.ask_yes_no(
            "Confirm membership deletion",
            f"Delete membership ID {membership_id}? Any linked payments must be deleted first. This cannot be undone.",
            do_delete,
        )
    def create_membership(self):
        # Guard against rapid double-clicks while the handler is running.
        if self.is_creating_membership:
            return
        self.is_creating_membership = True
        waiting_for_dialog = False
        try:
            customer_id = self.selected_renewal_member_id
            if customer_id is None:
                raise ValueError("Find the member and select them first.")
            plan_name = self.plan_dropdown.value
            start_text = (self.start_date_field.value or "").strip()
            if plan_name not in PLANS:
                raise ValueError("Choose a valid membership plan.")
            try:
                start_date = date.fromisoformat(start_text)
            except ValueError:
                raise ValueError("Start date must use YYYY-MM-DD.")
            proposed_end_date = start_date + timedelta(days=PLANS[plan_name]["days"] - 1)
 
            # Warn about date overlap, but let the user continue if intentional.
            overlapping_memberships=sorted((m for m in self.db.rows("memberships") if m["customer_id"]==customer_id and m["start_date"]<=proposed_end_date.isoformat() and m["end_date"]>=start_date.isoformat()),key=lambda m:m["start_date"])
 
            def create_after_password():
                try:
                    self.manager.add_membership(customer_id, plan_name, start_date.isoformat())
                    self.membership_page()
                    self.toast("Membership created.")
                except (ValueError, DataError) as error:
                    self.show_error("Unable to create membership", str(error))
                finally:
                    self.is_creating_membership = False

            def do_create():
                customer = self.db.get("customers",id=customer_id)
                summary = (
                    f"Member: {customer['full_name']}\nPlan: {plan_name}\n"
                    f"Price: ₱{self.manager.regular_price(plan_name):,.2f}\n"
                    f"Dates: {start_date.isoformat()} through {proposed_end_date.isoformat()}\n\n"
                    "Enter your password to authorize membership creation."
                )
                opened = self._confirm_with_password(
                    "Confirm Membership Creation",
                    create_after_password,
                    summary,
                    "Authenticate & Create",
                    on_cancel=lambda: setattr(self, "is_creating_membership", False),
                )
                if not opened:
                    self.is_creating_membership = False
 
            if overlapping_memberships:
                customer = self.db.get("customers",id=customer_id)
                existing_text = "\n".join(
                    f"• {overlap['plan_name']} ({overlap['start_date']} to {overlap['end_date']})"
                    for overlap in overlapping_memberships
                )
                waiting_for_dialog = True
                self.ask_yes_no(
                    "Overlapping Membership",
                    f"{customer['full_name']} already has membership dates that overlap with this plan.\n\n"
                    f"Existing membership(s):\n{existing_text}\n\n"
                    f"New membership: {plan_name} ({start_date.isoformat()} to {proposed_end_date.isoformat()})\n\n"
                    "Do you want to create it anyway?",
                    do_create,
                    lambda: setattr(self, "is_creating_membership", False),
                )
                return
            waiting_for_dialog = True
            do_create()
        except (ValueError, DataError, AttributeError) as error:
            self.show_error("Unable to create membership", str(error))
        finally:
            if not waiting_for_dialog:
                self.is_creating_membership = False

