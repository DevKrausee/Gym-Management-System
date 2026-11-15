"""Attendance search, check-in/check-out, and history screens."""

from datetime import date

import flet as ft

from ..database import DataError

from ..config import (
    build_list_name,
    field_style,
    format_clock_time,
    pad_symmetric,
    row_full_name,
)



class AttendanceMixin:
    def attendance_page(self):
        page_content = self.new_page("Attendance")
        self.manager.close_stale_checkins()
        search_body = self.add_section(
            page_content,
            "Check In / Check Out",
            "Type a name, phone number or member ID. Only active membership dates are checked; "
            "unpaid or partial active memberships are allowed.",
        )
        self.attendance_search_field = ft.TextField(
            label="Search name, phone or member ID",
            width=520,
            label_style=ft.TextStyle(size=13),
            on_change=lambda event: self.refresh_member_results(),
            on_submit=lambda event: self.search_enter(),
            **field_style(),
        )
        self.attendance_results = ft.Column(
            spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH
        )
        search_body.controls.append(self.attendance_search_field)
        search_body.controls.append(self.attendance_results)
        self.refresh_member_results()
 
        inside_members = self.manager.inside_now()
        inside_body = self.add_section(
            page_content, f"Inside Now ({len(inside_members)})", "Members currently checked in."
        )
        inside_rows = []
        for member in inside_members:
            list_name_text = build_list_name(
                member["first_name"],
                member["middle_name"],
                member["last_name"],
                member["extension"],
            )
            inside_rows.append(
                [
                    list_name_text,
                    f"since {format_clock_time(member['check_in'])}",
                    self.small_button(
                        "Check Out",
                        lambda customer_id=member["id"], full_name=row_full_name(member): (
                            self.check_out_member(customer_id, full_name)
                        ),
                        85,
                        self.ORANGE_DEEP,
                    ),
                ]
            )
        inside_body.controls.append(
            self.table(
                ["Member", "Checked In", "Check Out"],
                inside_rows,
                "Nobody is checked in right now.",
                weights=[3, 2, 2],
            )
        )
 
        self.attendance_date_field = self.date_field(
            "YYYY-MM-DD or blank", 240, title="Attendance date"
        )
        self.attendance_history_search_field = ft.TextField(
            label="Search name, phone or member ID",
            width=360,
            label_style=ft.TextStyle(size=13),
            on_change=lambda event: self.refresh_attendance(),
            on_submit=lambda event: self.refresh_attendance(),
            **field_style(),
        )
        page_content.controls.append(
            ft.Row(
                [
                    self.styled_text("Search visits:"),
                    self.attendance_history_search_field,
                    self.styled_text("Date:"),
                    self.attendance_date_field,
                    self.button("Apply Filter", self.refresh_attendance, 105),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.attendance_table = self.add_section(page_content, "Attendance History", "Newest first")
        self.refresh_attendance()
    def _member_card(self, member):
        name = build_list_name(
            member["first_name"], member["middle_name"], member["last_name"], member["extension"]
        )
        is_inside, has_active_membership = bool(member["inside_since"]), bool(
            member["active_until"]
        )
        title_row = [self.styled_text(name, 15, True)]
        if is_inside:
            title_row.append(
                ft.Container(
                    self.styled_text(
                        f"INSIDE since {format_clock_time(member['inside_since'])}",
                        11,
                        True,
                        self.ORANGE,
                    ),
                    bgcolor=self.ORANGE_TINT,
                    border_radius=6,
                    padding=pad_symmetric(horizontal=8, vertical=3),
                )
            )
        membership_text = (
            self.styled_text(
                f"{member['plan']} - active until {member['active_until']}",
                12,
                color=self.TEXT_MUTED,
            )
            if has_active_membership
            else self.styled_text("No active membership", 12, color=self.RED)
        )
        if is_inside:
            action = self.button(
                "Check Out",
                lambda customer_id=member["id"], full_name=row_full_name(
                    member
                ): self.check_out_member(customer_id, full_name),
                130,
                self.ORANGE_DEEP,
            )
        else:
            action = self.button(
                "Check In",
                lambda customer_id=member["id"], full_name=row_full_name(
                    member
                ): self.check_in_member(customer_id, full_name),
                130,
                None if has_active_membership else self.GRAY,
            )
            action.disabled = not has_active_membership
        return ft.Container(
            bgcolor=self.SURFACE_ALT,
            border_radius=10,
            padding=pad_symmetric(horizontal=14, vertical=10),
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                title_row,
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            self.styled_text(
                                f"Member ID {member['id']}  •  {member['phone'] or 'no phone'}",
                                12,
                                color=self.TEXT_MUTED,
                            ),
                            membership_text,
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    action,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
    def refresh_member_results(self):
        query = (self.attendance_search_field.value or "").strip()
        self.attendance_results.controls.clear()
        if not query:
            self.attendance_results.controls.append(
                self.styled_text(
                    "Start typing to find a member. Press Enter to check in/out "
                    "when exactly one member matches.",
                    12,
                    color=self.TEXT_MUTED,
                )
            )
        else:
            members = self.manager.find_members(query, limit=9)
            if not members:
                self.attendance_results.controls.append(
                    self.styled_text(f'No member found for "{query}".', color=self.TEXT_MUTED)
                )
            for member in members[:8]:
                self.attendance_results.controls.append(self._member_card(member))
            if len(members) > 8:
                self.attendance_results.controls.append(
                    self.styled_text(
                        "More members match. Keep typing to narrow the list.",
                        12,
                        color=self.TEXT_MUTED,
                    )
                )
        self.page.update()
    def search_enter(self):
        """Enter checks the member in or out when the search points at exactly one person.
        A member ID typed (or scanned) that matches exactly always wins."""
        query = (self.attendance_search_field.value or "").strip()
        if not query:
            return
        members = self.manager.find_members(query, limit=9)
        if query.isdigit() and members and members[0]["id"] == int(query):
            target = members[0]
        elif len(members) == 1:
            target = members[0]
        else:
            return self.toast(
                "No member found."
                if not members
                else "Several members match. Pick one from the list."
            )
        name = row_full_name(target)
        if target["inside_since"]:
            self.check_out_member(target["id"], name)
        elif target["active_until"]:
            self.check_in_member(target["id"], name)
        else:
            self.show_warning(
                "No active membership",
                f"{name} has no active membership today. Add or renew a membership first.",
            )
    def check_in_member(self, customer_id, name):
        try:
            self.manager.check_in(customer_id)
        except (ValueError, DataError) as error:
            return self.show_error("Check-in failed", str(error))
        self.attendance_page()
        self.page.update()  # clears the search box for the next person
        self.toast(f"{name} checked in.")
        self.focus_control(self.attendance_search_field)
    def check_out_member(self, customer_id, name):
        try:
            self.manager.check_out(customer_id)
        except (ValueError, DataError) as error:
            return self.show_error("Check-out failed", str(error))
        self.attendance_page()
        self.page.update()
        self.toast(f"{name} checked out.")
        self.focus_control(self.attendance_search_field)
    def refresh_attendance(self):
        if not hasattr(self, "attendance_table"):
            return
        self.manager.close_stale_checkins()
        date_text = (
            (self.attendance_date_field.value or "").strip()
            if hasattr(self, "attendance_date_field")
            else ""
        )
        search_text=(self.attendance_history_search_field.value or "").strip() if hasattr(self,"attendance_history_search_field") else ""
        if date_text:
            try:
                date.fromisoformat(date_text)
            except ValueError:
                return self.show_error("Invalid date", "Use YYYY-MM-DD.")
        customers={c["id"]:c for c in self.db.rows("customers")}
        users={u["id"]:u for u in self.db.rows("users")}
        visits=[]
        for visit in self.db.rows("attendance"):
            customer=customers.get(visit["customer_id"])
            if not customer: continue
            if date_text and visit["check_in"][:10]!=date_text: continue
            if search_text and search_text.casefold() not in " ".join(str(customer.get(k) or "") for k in ("full_name","phone","id")).casefold(): continue
            visits.append({**visit,"full_name":customer["full_name"],"staff_name":(users.get(visit.get("recorded_by")) or {}).get("display_name")})
        visits.sort(key=lambda v:v["id"],reverse=True)
        if not date_text and not search_text: visits=visits[:250]
        self.attendance_table.controls.clear()
        is_owner = self.is_owner
        table_rows = []
        for visit in visits:
            attendance_id = int(visit["id"])
            table_row = [
                visit["id"],
                visit["full_name"],
                visit["check_in"].replace("T", " "),
                self.check_out_text(visit),
                visit["staff_name"] or "—",
            ]
            if is_owner:
                table_row.append(
                    self.small_button(
                        "Delete",
                        lambda attendance_id=attendance_id: self.delete_attendance(attendance_id),
                        62,
                        self.RED,
                    )
                )
            table_rows.append(table_row)
        self.attendance_table.controls.append(
            self.table(
                ["ID", "Customer", "Check-in", "Check-out", "Checked In By"]
                + (["Delete"] if is_owner else []),
                table_rows,
                "No attendance records found.",
            )
        )
        self.page.update()
    def delete_attendance(self, attendance_id):
        def do_delete():
            try:
                self.manager.delete_attendance(attendance_id)
                self.attendance_page()
                self.page.update()
                self.show_info("Deleted", "Attendance record deleted successfully.")
            except DataError as error:
                self.show_error("Unable to delete attendance", str(error))
 
        self.ask_yes_no(
            "Confirm attendance deletion",
            f"Delete attendance record ID {attendance_id}? This cannot be undone.",
            do_delete,
        )

