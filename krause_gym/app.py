"""Flet application class and composition of the UI screen modules."""

import threading
import time

import flet as ft

from .config import APP_NAME, Button, LEFT_ALIGNMENT, pad_only, pad_symmetric
from .database import CsvDatabase
from .manager import GymManager
from .ui.accounts import AccountsMixin
from .ui.attendance import AttendanceMixin
from .ui.base import BaseUIMixin
from .ui.customers import CustomersMixin
from .ui.dashboard import DashboardMixin
from .ui.memberships import MembershipsMixin
from .ui.payments import PaymentsMixin
from .ui.vip import VipMixin


class GymApp(
    BaseUIMixin,
    DashboardMixin,
    CustomersMixin,
    MembershipsMixin,
    PaymentsMixin,
    AccountsMixin,
    AttendanceMixin,
    VipMixin,
):
    # Colors
    ORANGE = "#F97316"
    ORANGE_DARK = "#EA580C"
    ORANGE_DEEP = "#C2410C"
    ORANGE_LIGHT = "#FDBA74"
    ORANGE_TINT = "#431407"
    RED = "#EF4444"
    GRAY = "#52525B"
    BACKGROUND = "#111113"
    SIDEBAR_BG = "#18181B"
    SURFACE = "#202124"
    SURFACE_ALT = "#27272A"
    ROW_ALT_BG = "#252529"
    BORDER_COLOR = "#3F3F46"
    TEXT_PRIMARY = "#F4F4F5"
    TEXT_MUTED = "#A1A1AA"

    def __init__(self, page: ft.Page):
        self.page = page
        page.title = APP_NAME
        try:
            page.window.width = 1240
            page.window.height = 780
            page.window.min_width = 1050
            page.window.min_height = 680
        except Exception:
            pass
        page.padding = 0
        page.spacing = 0
        page.bgcolor = self.BACKGROUND
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=self.ORANGE)
 
        self.db = CsvDatabase()
        self.manager = GymManager(self.db)
        self.selected_customer_id = None
        self.current_user = None
        self.last_activity = time.monotonic()
        self.failed_password_attempts = 0
        self.password_locked_until = 0.0
        self.password_lockout_seconds = 30
        self.is_creating_membership = False
        self.selected_payment_membership_id = None
        self.selected_renewal_member_id = None
        self.shell_visible = False
        page.on_keyboard_event = lambda event: self.record_activity()
 
        # --- Sidebar ---
        self.nav_buttons = {}
        nav_items = []
        for label, page_builder in [
            ("Dashboard", self.dashboard),
            ("Customers", self.customer_page),
            ("Memberships", self.membership_page),
            ("Payments History", self.payment_page),
            ("Attendance", self.attendance_page),
            ("VIP Membership", self.vip_page),
            ("Accounts", self.accounts_page),
        ]:
            item = ft.Container(
                content=ft.Text(label, color="white", size=14, text_align=ft.TextAlign.LEFT),
                width=199,
                alignment=LEFT_ALIGNMENT,
                padding=pad_symmetric(vertical=12, horizontal=16),
                border_radius=9,
                ink=True,
                bgcolor=ft.Colors.TRANSPARENT,
                on_click=lambda event, page_name=label, page_builder=page_builder: self.navigate(
                    page_name, page_builder
                ),
            )
            self.nav_buttons[label] = item
            nav_items.append(item)
        self.nav_buttons["Accounts"].visible = False  # shown only while the owner is signed in
        self.sidebar = ft.Container(
            width=225,
            bgcolor=self.SIDEBAR_BG,
            padding=pad_symmetric(horizontal=13),
            content=ft.Column(
                [
                    ft.Container(height=24),
                    ft.Container(
                        ft.Text("🏋  BSIT-2B GYM", size=20, weight=ft.FontWeight.BOLD, color="white"),
                        padding=pad_only(left=7),
                    ),
                    ft.Container(
                        ft.Text(
                            "MANAGEMENT SYSTEM",
                            size=10,
                            weight=ft.FontWeight.BOLD,
                            color=self.ORANGE_LIGHT,
                        ),
                        padding=pad_only(left=9, bottom=22),
                    ),
                    *nav_items,
                ],
                spacing=4,
            ),
        )
 
        # --- Header + content ---
        self.title_label = ft.Text(
            "Dashboard", size=25, weight=ft.FontWeight.BOLD, color=self.TEXT_PRIMARY
        )
        self.clock = ft.Text("", color=self.TEXT_MUTED)
        self.user_label = ft.Text("", size=12, color=self.TEXT_MUTED)
        self.logout_button = Button(
            "Logout",
            on_click=lambda event: self.logout(),
            width=150,
            height=52,
            style=ft.ButtonStyle(
                bgcolor=self.RED,
                color="white",
                padding=pad_symmetric(horizontal=20, vertical=12),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self.header = ft.Container(
            bgcolor=self.SURFACE,
            padding=pad_symmetric(horizontal=26, vertical=16),
            content=ft.Row(
                [
                    ft.Column([self.title_label, self.user_label], spacing=0),
                    ft.Row([self.clock, self.logout_button], spacing=14),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        )
        self.page_body = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.vip_tab_bar = ft.Container(visible=False)
        self.main_column = ft.Column(
            [self.header, self.vip_tab_bar, ft.Container(self.page_body, padding=18, expand=True)],
            expand=True,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.shell = ft.Row(
            [self.sidebar, self.main_column],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
 
        threading.Thread(target=self._background_loop, daemon=True).start()
        self.show_login_page()
