"""Shared controls, dialogs, login/session handling, and navigation."""

import inspect
import time
from datetime import date, datetime

import flet as ft

from ..database import DataError

from ..config import (
    Button,
    DropdownItem,
    FIELD_HEIGHT,
    IDLE_LOGOUT_SECONDS,
    date_from_picker,
    field_style,
    pad_all,
    pad_symmetric,
)



class BaseUIMixin:
    def styled_text(self, value, size=13, bold=False, color=None, **text_options):
        return ft.Text(
            str(value),
            size=size,
            weight=ft.FontWeight.BOLD if bold else None,
            color=color or self.TEXT_PRIMARY,
            **text_options,
        )
    def open_dialog(self, dialog):
        if hasattr(self.page, "show_dialog"):
            self.page.show_dialog(dialog)
        else:
            self.page.open(dialog)
    def close_dialog(self, dialog):
        if hasattr(self.page, "pop_dialog"):
            self.page.pop_dialog()
        else:
            self.page.close(dialog)
    def _message(self, title, message, on_ok=None):
        def ok(event):
            self.close_dialog(dialog)
            if on_ok:
                on_ok()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Container(ft.Text(str(message)), width=420),
            actions=[self.button("OK", lambda: ok(None), 90)],
        )
        self.open_dialog(dialog)
    def show_info(self, title, message, on_ok=None):
        self._message(title, message, on_ok)
    def show_warning(self, title, message, on_ok=None):
        self._message(title, message, on_ok)
    def show_error(self, title, message, on_ok=None):
        self._message(title, message, on_ok)
    def toast(self, message):
        """A short message that disappears by itself (no OK button), for routine successes."""
        self.open_dialog(ft.SnackBar(content=ft.Text(str(message)), duration=2500))
    def ask_yes_no(self, title, message, on_yes, on_no=None):
        def yes():
            self.close_dialog(dialog)
            on_yes()
 
        def no():
            self.close_dialog(dialog)
            if on_no:
                on_no()
 
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Container(ft.Text(str(message)), width=440),
            actions=[self.button("Yes", yes, 90), self.button("No", no, 90, self.GRAY)],
        )
        self.open_dialog(dialog)
    def new_page(self, title):
        self.title_label.value = title
        self.page_body.controls.clear()
        if hasattr(self, "vip_tab_bar"):
            self.vip_tab_bar.content = None
            self.vip_tab_bar.visible = False
        return self.page_body
    def add_section(self, parent, title, subtitle=""):
        body = ft.Column(spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        heading_controls = [self.styled_text(title, 17, True)]
        if subtitle:
            heading_controls.append(self.styled_text(subtitle, 12, color=self.TEXT_MUTED))
        card = ft.Container(
            bgcolor=self.SURFACE,
            border=ft.Border.all(1, self.BORDER_COLOR),
            border_radius=13,
            padding=pad_all(17),
            content=ft.Column(
                heading_controls + [body],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )
        parent.controls.append(card)
        return body
    def text_field(self, placeholder, width=180, value=None, **field_options):
        height = field_options.pop("height", FIELD_HEIGHT)
        return ft.TextField(
            label=placeholder,
            width=width,
            value=value,
            label_style=ft.TextStyle(size=13),
            **field_style(height=height, **field_options),
        )
    def dropdown(self, options, value=None, width=200):
        return ft.Dropdown(
            options=[DropdownItem(option) for option in options],
            value=value,
            width=width,
            **field_style(),
        )
    def date_field(self, label, width, value=None, title="Select date", **field_options):
        """A date box with a calendar button inside it; typing a date still works."""
        date_box = ft.TextField(
            label=label,
            width=width,
            value=value,
            label_style=ft.TextStyle(size=13),
            **field_style(**field_options),
        )
        date_box.suffix = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            icon_size=20,
            tooltip="Pick a date",
            on_click=lambda event: self.open_calendar(date_box, title),
        )
        return date_box
    def open_calendar(self, date_box, title):
        earliest_date, latest_date = date(2000, 1, 1), date(2100, 12, 31)
        try:
            initial_date = date.fromisoformat((date_box.value or "").strip())
        except ValueError:
            initial_date = date.today()
        initial_date = min(max(initial_date, earliest_date), latest_date)
        picker = ft.DatePicker(
            value=datetime(initial_date.year, initial_date.month, initial_date.day),
            first_date=datetime(earliest_date.year, 1, 1),
            last_date=datetime(latest_date.year, 12, 31),
            help_text=title,
            confirm_text="OK",
            cancel_text="Cancel",
        )
 
        def on_date_picked(event):
            if picker.value is None:
                return
            date_box.value = date_from_picker(picker.value).isoformat()
            self.record_activity()
            if date_box.on_change:
                date_box.on_change(None)  # lets live previews (e.g. membership end date) update
            self.page.update()
 
        picker.on_change = on_date_picked
        self.open_dialog(picker)
    @staticmethod
    def check_out_text(visit):
        if not visit["check_out"]:
            return "Still inside"
        return visit["check_out"].replace("T", " ") + (" (auto)" if visit["auto_closed"] else "")
    def button(self, text, command, width=130, color=None):
        """Standard action button; the width grows to fit long labels."""
 
        def handler(event):
            self.record_activity()
            command()
 
        # A separate no-wrap Text keeps newer Flet versions from wrapping long labels.
        label = ft.Text(text, no_wrap=True, text_align=ft.TextAlign.CENTER, size=13)
        return Button(
            label,
            on_click=handler,
            width=max(width, len(text) * 10 + 38),
            height=48,
            style=ft.ButtonStyle(
                bgcolor=color or self.ORANGE,
                color="white",
                padding=pad_symmetric(horizontal=16, vertical=10),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
    def small_button(self, text, command, width=70, color=None):
        def handler(event):
            self.record_activity()
            command()
 
        return Button(
            text,
            on_click=handler,
            width=width,
            height=31,
            style=ft.ButtonStyle(
                bgcolor=color or self.ORANGE,
                color="white",
                padding=pad_symmetric(horizontal=4),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
    def table(self, headers, rows, empty="No records found.", weights=None):
        """Columns share the width equally unless `weights` (one whole number per column) is given.
        Any cell that is a Flet control is shown as-is (buttons, styled text)."""
        weights = weights or [1] * len(headers)
        table_column = ft.Column(spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        table_column.controls.append(
            ft.Container(
                bgcolor=self.SURFACE_ALT,
                padding=pad_symmetric(vertical=9, horizontal=5),
                content=ft.Row(
                    [
                        ft.Text(
                            header,
                            expand=weight,
                            text_align=ft.TextAlign.CENTER,
                            size=11,
                            weight=ft.FontWeight.BOLD,
                            color=self.ORANGE_LIGHT,
                        )
                        for header, weight in zip(headers, weights)
                    ],
                    spacing=4,
                ),
            )
        )
        for row_index, row in enumerate(rows):
            cells = []
            for cell, weight in zip(row, weights):
                if isinstance(cell, ft.Control):
                    cells.append(
                        ft.Row([cell], alignment=ft.MainAxisAlignment.CENTER, expand=weight)
                    )
                else:
                    cells.append(
                        ft.Text(
                            str(cell),
                            expand=weight,
                            text_align=ft.TextAlign.CENTER,
                            color=self.TEXT_PRIMARY,
                            size=12,
                        )
                    )
            table_column.controls.append(
                ft.Container(
                    bgcolor=self.SURFACE if row_index % 2 == 0 else self.ROW_ALT_BG,
                    padding=pad_symmetric(vertical=6, horizontal=5),
                    content=ft.Row(
                        cells, spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER
                    ),
                )
            )
        if not rows:
            table_column.controls.append(
                ft.Container(
                    padding=14,
                    content=ft.Row(
                        [self.styled_text(empty, color=self.TEXT_MUTED)],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                )
            )
        return table_column
    def focus_control(self, control):
        """Focus a control (focus() is async on current Flet, plain on older versions)."""
        try:
            if inspect.iscoroutinefunction(control.focus):
                self.page.run_task(control.focus)
            else:
                control.focus()
        except Exception:
            pass
    @property
    def is_owner(self):
        return bool(self.current_user and self.current_user["role"] == "owner")
    def record_activity(self, _event=None):
        self.last_activity = time.monotonic()
    def _centered_card(self, *controls):
        card = ft.Container(
            bgcolor=self.SURFACE,
            border_radius=18,
            width=440,
            padding=pad_all(26),
            content=ft.Column(
                [
                    ft.Text("🏋  BSIT-2B GYM", size=25, weight=ft.FontWeight.BOLD, color=self.ORANGE),
                    *controls,
                ],
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )
        # Size the card to its content instead of stretching it to the window height.
        alignment_class = getattr(ft, "Alignment", None)
        centered_alignment = alignment_class(0, 0) if alignment_class else ft.alignment.center
        self.page.controls.clear()
        self.page.add(
            ft.Container(
                content=card, expand=True, alignment=centered_alignment, padding=pad_all(20)
            )
        )
        self.page.update()
    def _login_field(self, label, password=False):
        return ft.TextField(
            label=label,
            width=340,
            label_style=ft.TextStyle(size=13),
            password=password,
            can_reveal_password=password,
            **field_style(),
        )
    def show_login_page(self, notice=""):
        self.shell_visible = False
        self.current_user = None
        self.manager.current_user = None
        is_first_run_setup = not self.manager.has_users()
        name_entry = self._login_field("Your name") if is_first_run_setup else None
        user_entry = self._login_field("Choose a username" if is_first_run_setup else "Username")
        password_entry = self._login_field(
            "Create password (8+ characters)" if is_first_run_setup else "Password", password=True
        )
        confirm_entry = (
            self._login_field("Confirm password", password=True) if is_first_run_setup else None
        )
        info_label = ft.Text(notice, color=self.TEXT_MUTED, width=340)
        error_label = ft.Text("", color=self.RED, width=340)
 
        def set_error(text):
            error_label.value = text
            self.page.update()
 
        def submit(_event=None):
            current_time = time.monotonic()
            if not is_first_run_setup and current_time < self.password_locked_until:
                return set_error(
                    f"Too many attempts. Try again in {max(1, int(self.password_locked_until - current_time))} seconds."
                )
            try:
                if is_first_run_setup:
                    if (password_entry.value or "") != (confirm_entry.value or ""):
                        return set_error("Passwords do not match.")
                    user = self.manager.create_owner(
                        name_entry.value, user_entry.value, password_entry.value or ""
                    )
                else:
                    user = self.manager.authenticate(
                        user_entry.value or "", password_entry.value or ""
                    )
                    if not user:
                        self.failed_password_attempts += 1
                        password_entry.value = ""
                        if self.failed_password_attempts >= 5:
                            self.password_locked_until = (
                                time.monotonic() + self.password_lockout_seconds
                            )
                            self.failed_password_attempts = 0
                            return set_error(
                                f"Too many incorrect attempts. Try again in {self.password_lockout_seconds} seconds."
                            )
                        return set_error(
                            "Incorrect username or password, or the account is disabled."
                        )
            except (ValueError, DataError) as error:
                return set_error(str(error))
            self.failed_password_attempts = 0
            self._sign_in(user)
 
        fields = [
            field for field in (name_entry, user_entry, password_entry, confirm_entry) if field
        ]
        for field in fields:
            field.on_submit = submit
        controls = [
            self.styled_text(
                "Create the owner account" if is_first_run_setup else "Sign In", 19, True
            ),
            ft.Text(
                (
                    "The owner adds the staff accounts and is the only one who can delete records or void payments."
                    if is_first_run_setup
                    else "Sign in with your own username and password."
                ),
                color=self.TEXT_MUTED,
                width=340,
            ),
            info_label,
            *fields,
            error_label,
            self.button("Create Owner Account" if is_first_run_setup else "Sign In", submit, 340),
        ]
        if not is_first_run_setup:
            controls.append(
                ft.TextButton(
                    "Forgot owner password?", on_click=lambda event: self.show_recovery_page()
                )
            )
        self._centered_card(*controls)
        self.focus_control(name_entry or user_entry)
    def show_recovery_page(self):
        code_entry = self._login_field("Recovery code")
        new_entry = self._login_field("New owner password (8+ characters)", password=True)
        confirm_entry = self._login_field("Confirm new password", password=True)
        error_label = ft.Text("", color=self.RED, width=340)
 
        def set_error(text):
            error_label.value = text
            self.page.update()
 
        def submit(_event=None):
            current_time = time.monotonic()
            if current_time < self.password_locked_until:
                return set_error(
                    f"Too many attempts. Try again in {max(1, int(self.password_locked_until - current_time))} seconds."
                )
            if (new_entry.value or "") != (confirm_entry.value or ""):
                return set_error("Passwords do not match.")
            try:
                new_code = self.manager.recover_owner_password(
                    code_entry.value or "", new_entry.value or ""
                )
            except (ValueError, DataError) as error:
                if str(error) == "Incorrect recovery code.":
                    self.failed_password_attempts += 1
                    if self.failed_password_attempts >= 5:
                        self.password_locked_until = (
                            time.monotonic() + self.password_lockout_seconds
                        )
                        self.failed_password_attempts = 0
                return set_error(str(error))
            self.failed_password_attempts = 0
            self._show_recovery_code(
                new_code,
                "Password reset - save your new recovery code",
                on_ok=lambda: self.show_login_page(
                    "Owner password reset. Sign in with your new password."
                ),
            )
 
        for field in (code_entry, new_entry, confirm_entry):
            field.on_submit = submit
        self._centered_card(
            self.styled_text("Reset owner password", 19, True),
            ft.Text(
                "Enter the recovery code you saved when the owner account was set up.",
                color=self.TEXT_MUTED,
                width=340,
            ),
            code_entry,
            new_entry,
            confirm_entry,
            error_label,
            self.button("Reset Password", submit, 340),
            ft.TextButton("Back to sign in", on_click=lambda event: self.show_login_page()),
        )
        self.focus_control(code_entry)
    def _show_recovery_code(self, code, title, on_ok=None):
        def ok():
            self.close_dialog(dialog)
            if on_ok:
                on_ok()
 
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text(
                        "Write this code down and keep it somewhere safe, away from this computer. "
                        "If the owner forgets the password, this code is the only way to reset it. "
                        "It is shown only once.",
                        width=420,
                    ),
                    ft.Container(
                        ft.Row(
                            [
                                ft.Text(
                                    code,
                                    size=24,
                                    weight=ft.FontWeight.BOLD,
                                    color=self.ORANGE,
                                    selectable=True,
                                )
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                        ),
                        bgcolor=self.ORANGE_TINT,
                        border_radius=8,
                        padding=14,
                        width=420,
                    ),
                ],
                tight=True,
                width=440,
                spacing=12,
            ),
            actions=[self.button("I saved it", ok, 140)],
        )
        self.open_dialog(dialog)
    def _sign_in(self, user):
        self.current_user = user
        self.manager.current_user = user
        self.user_label.value = f"Signed in as {user['display_name']} ({user['role'].title()})"
        self.nav_buttons["Accounts"].visible = user["role"] == "owner"
        self.record_activity()
        self._show_main_system()
        if user["role"] == "owner" and not self.manager.has_recovery_code():
            self._show_recovery_code(self.manager.new_recovery_code(), "Save your recovery code")
    def _show_main_system(self):
        self.page.controls.clear()
        self.page.add(self.shell)
        self.shell_visible = True
        self.navigate("Dashboard", self.dashboard)
    def logout(self, notice=""):
        for _ in range(
            5
        ):  # close any dialog still open so it doesn't sit on top of the sign-in screen
            try:
                if not self.page.pop_dialog():
                    break
            except Exception:
                break
        self.show_login_page(notice)
    def _background_loop(self):
        ticks = 0
        while True:
            time.sleep(1)
            ticks += 1
            try:
                if self.shell_visible:
                    self.clock.value = datetime.now().strftime("%a, %d %b %Y  •  %I:%M:%S %p")
                    self.clock.update()
                if ticks % 15 == 0:
                    self._check_idle_logout()
            except Exception:
                pass
    def _check_idle_logout(self):
        if self.shell_visible and time.monotonic() - self.last_activity >= IDLE_LOGOUT_SECONDS:
            self.logout(
                f"You were signed out after {IDLE_LOGOUT_SECONDS // 60} minutes of inactivity."
            )
    def navigate(self, name, show_page):
        if name == "Accounts" and not self.is_owner:
            return
        self.record_activity()
        for page_name, nav_item in self.nav_buttons.items():
            nav_item.bgcolor = self.ORANGE_DARK if page_name == name else ft.Colors.TRANSPARENT
        show_page()
        self.page.update()
    def _confirm_with_password(self, title, on_success, summary=None, confirm_label="Continue", on_cancel=None):
        """Ask the signed-in person to re-enter THEIR OWN password before a sensitive action."""
        if not self.current_user:
            self.show_warning("Not signed in", "Sign in first.")
            if on_cancel:
                on_cancel()
            return False
        current_time = time.monotonic()
        if current_time < self.password_locked_until:
            remaining = max(1, int(self.password_locked_until - current_time))
            self.show_warning(
                "Please wait", f"Too many incorrect passwords. Try again in {remaining} seconds."
            )
            if on_cancel:
                on_cancel()
            return False
        password_field = ft.TextField(
            label="Your password",
            width=450,
            label_style=ft.TextStyle(size=13),
            password=True,
            can_reveal_password=True,
            **field_style(),
        )
        dialog_body = [
            ft.Text("Enter your password to authorize this action.", width=450),
            password_field,
        ]
        if summary:
            dialog_body.append(
                ft.Container(
                    ft.Text(summary, color=self.TEXT_PRIMARY),
                    bgcolor=self.ORANGE_TINT,
                    border_radius=8,
                    padding=10,
                    width=450,
                )
            )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                dialog_body, tight=True, width=470, scroll=ft.ScrollMode.AUTO, spacing=10
            ),
        )
 
        def close():
            self.close_dialog(dialog)

        def cancel():
            close()
            if on_cancel:
                on_cancel()
 
        def submit(_event=None):
            if not self.manager.verify_password(
                self.current_user["id"], password_field.value or ""
            ):
                self.failed_password_attempts += 1
                if self.failed_password_attempts >= 5:
                    self.password_locked_until = time.monotonic() + self.password_lockout_seconds
                    self.failed_password_attempts = 0
                    self.show_error(
                        "Temporarily locked",
                        f"Five incorrect attempts. Try again in {self.password_lockout_seconds} seconds.",
                    )
                else:
                    self.show_error(
                        "Incorrect password",
                        f"Password incorrect. Attempts remaining: {5-self.failed_password_attempts}.",
                    )
                password_field.value = ""
                self.page.update()
                return
            self.failed_password_attempts = 0
            close()
            self.record_activity()
            on_success()
 
        password_field.on_submit = submit
        dialog.actions = [
            self.button(confirm_label, submit, 190),
            self.button("Cancel", cancel, 100, self.GRAY),
        ]
        self.open_dialog(dialog)
        self.focus_control(password_field)
        return True

