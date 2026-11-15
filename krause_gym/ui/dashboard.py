"""Dashboard screen and summary widgets."""

import flet as ft

from ..config import PLANS, pad_all, pad_symmetric



class DashboardMixin:
    def dashboard(self):
        self.manager.close_stale_checkins()
        page_content = self.new_page("Dashboard")
        stats = self.manager.dashboard_stats()
        is_owner = self.is_owner
        stat_cards = [
            ("Total Customers", stats["customers"]),
            ("Active Memberships", stats["active"]),
            ("Today's Income" if is_owner else "My Income Today", f"₱{stats['income']:,.2f}"),
            ("Outstanding Balance", f"₱{stats['outstanding']:,.2f}"),
            ("Today's Check-ins", stats["checkins"]),
        ]
        if is_owner:
            stat_cards.append(
                (
                    "Voided Today",
                    (
                        f"{stats['voids_today']} (₱{stats['voids_amount']:,.2f})"
                        if stats["voids_today"]
                        else "None"
                    ),
                )
            )
        cards = ft.Row(spacing=7)
        for label, value in stat_cards:
            cards.controls.append(
                ft.Container(
                    expand=1,
                    bgcolor=self.SURFACE,
                    border=ft.Border.all(1, self.BORDER_COLOR),
                    border_radius=12,
                    padding=pad_all(10),
                    content=ft.Column(
                        [
                            self.styled_text(label, 11, True, self.TEXT_MUTED),
                            self.styled_text(value, 18, True),
                            self.styled_text("Overview", 10, color=self.TEXT_MUTED),
                        ],
                        spacing=5,
                    ),
                )
            )
        page_content.controls.append(cards)
 
        attendance_body = self.add_section(page_content, "Recent Attendance", "Latest visits")
        customers = {c["id"]: c for c in self.db.rows("customers")}
        recent_visits = [{**a, "full_name": customers[a["customer_id"]]["full_name"]} for a in sorted(self.db.rows("attendance"), key=lambda a:a["id"], reverse=True) if a["customer_id"] in customers][:8]
        attendance_body.controls.append(
            self.table(
                ["Member", "Check-in", "Check-out"],
                [
                    (
                        visit["full_name"],
                        visit["check_in"].replace("T", " "),
                        self.check_out_text(visit),
                    )
                    for visit in recent_visits
                ],
            )
        )
 
        plans_body = self.add_section(page_content, "Membership Plans", "Current standard rates")
        plan_row = ft.Row(spacing=8)
        for plan_name, plan in PLANS.items():
            plan_row.controls.append(
                ft.Container(
                    expand=1,
                    bgcolor=self.SURFACE_ALT,
                    border_radius=9,
                    padding=pad_symmetric(vertical=10, horizontal=8),
                    content=ft.Column(
                        [
                            self.styled_text(plan_name, 14, True, self.ORANGE_DARK),
                            self.styled_text(f"₱{self.manager.regular_price(plan_name):,.2f}", 18, True),
                            self.styled_text(f"{plan['days']} day(s)", color=self.TEXT_MUTED),
                        ],
                        spacing=3,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )
        plans_body.controls.append(plan_row)
        self.page.update()

