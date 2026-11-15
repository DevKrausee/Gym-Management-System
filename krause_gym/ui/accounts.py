"""Owner/staff account management screens."""


import flet as ft

from ..database import DataError

from ..config import field_style



class AccountsMixin:
    def accounts_page(self):
        page_content = self.new_page("Accounts")
        if not self.is_owner:
            self.add_section(page_content, "Accounts", "Only the owner can manage accounts.")
            return
 
        def make_field(label, width, password=False):
            return ft.TextField(
                label=label,
                width=width,
                label_style=ft.TextStyle(size=13),
                password=password,
                can_reveal_password=password,
                **field_style(),
            )
 
        form_body = self.add_section(
            page_content,
            "Add Staff Account",
            "Staff can check members in, add customers, create memberships and record payments. "
            "Only the owner can delete records, void payments and manage accounts.",
        )
        self.staff_name_field = make_field("Staff name", 180)
        self.staff_username_field = make_field("Username", 150)
        self.staff_password_field = make_field("Password (8+ characters)", 200, True)
        self.staff_confirm_field = make_field("Confirm password", 180, True)
        form_body.controls.append(
            ft.Row(
                [
                    self.staff_name_field,
                    self.staff_username_field,
                    self.staff_password_field,
                    self.staff_confirm_field,
                    self.button("Add Staff", self.add_staff, 130),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.accounts_table = self.add_section(
            page_content, "Accounts", "Deactivated accounts cannot sign in but keep their history."
        )
        self.refresh_accounts()
    def add_staff(self):
        if (self.staff_password_field.value or "") != (self.staff_confirm_field.value or ""):
            return self.show_error(
                "Passwords do not match", "Type the same password in both password fields."
            )
        try:
            self.manager.create_staff(
                self.staff_name_field.value or "",
                self.staff_username_field.value or "",
                self.staff_password_field.value or "",
            )
        except (ValueError, DataError) as error:
            return self.show_error("Unable to add staff", str(error))
        for field in (
            self.staff_name_field,
            self.staff_username_field,
            self.staff_password_field,
            self.staff_confirm_field,
        ):
            field.value = ""
        self.refresh_accounts()
        self.show_info(
            "Staff added", "The account is ready. Give the person their username and password."
        )
    def refresh_accounts(self):
        self.accounts_table.controls.clear()
        table_rows = []
        for account in self.manager.list_users():
            is_active = bool(account["active"])
            table_rows.append(
                [
                    account["display_name"],
                    account["username"],
                    account["role"].title(),
                    "Active" if is_active else "Deactivated",
                    (
                        self.small_button(
                            "Edit name",
                            lambda user_id=account["id"], display_name=account["display_name"]: self.edit_staff_name(user_id, display_name),
                            90,
                            self.GRAY,
                        )
                        if account["role"] == "staff"
                        else ft.Text("—", color=self.TEXT_MUTED)
                    ),
                    self.small_button(
                        "Reset",
                        lambda user_id=account["id"], display_name=account[
                            "display_name"
                        ]: self.reset_password(user_id, display_name),
                        70,
                    ),
                    (
                        ft.Text("—", color=self.TEXT_MUTED)
                        if account["role"] == "owner"
                        else self.small_button(
                            "Deactivate" if is_active else "Activate",
                            lambda user_id=account["id"], display_name=account[
                                "display_name"
                            ], was_active=is_active: self.toggle_account(
                                user_id, display_name, was_active
                            ),
                            112,
                            self.RED if is_active else None,
                        )
                    ),
                ]
            )
        self.accounts_table.controls.append(
            self.table(
                ["Name", "Username", "Role", "Status", "Profile", "Password", "Access"],
                table_rows,
                "No accounts.",
            )
        )
        self.page.update()
    def edit_staff_name(self, user_id, current_name):
        name_field = ft.TextField(
            label="Staff name",
            value=current_name,
            width=420,
            label_style=ft.TextStyle(size=13),
            **field_style(),
        )

        def authorize_change():
            new_name = " ".join((name_field.value or "").split())
            if len(new_name) < 2:
                name_field.error_text = "Enter at least 2 characters."
                self.page.update()
                return
            if new_name == current_name:
                self.close_dialog(dialog)
                return self.show_info("No changes", "The staff name is already up to date.")

            def save_name():
                try:
                    self.manager.update_staff_name(user_id, new_name)
                except (ValueError, DataError) as error:
                    return self.show_error("Unable to update staff name", str(error))
                self.refresh_accounts()
                self.show_info("Staff name updated", f"The account name is now {new_name}.")

            self.close_dialog(dialog)
            self._confirm_with_password(
                "Authorize Staff Name Change",
                save_name,
                f"Change staff name from {current_name} to {new_name}. Username and account history will be kept.",
                "Authenticate & Save",
            )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit Staff Name", weight=ft.FontWeight.BOLD),
            content=ft.Column([name_field], tight=True, width=440, spacing=10),
            actions=[
                self.button("Continue", authorize_change, 100),
                self.button("Cancel", lambda: self.close_dialog(dialog), 100, self.GRAY),
            ],
        )
        name_field.on_change = lambda event: setattr(name_field, "error_text", None)
        self.open_dialog(dialog)
        self.focus_control(name_field)
    def reset_password(self, user_id, name):
        def ask_new_password():
            new_password_field = ft.TextField(
                label="New password (8+ characters)",
                width=420,
                label_style=ft.TextStyle(size=13),
                password=True,
                can_reveal_password=True,
                **field_style(),
            )
            confirm_field = ft.TextField(
                label="Confirm new password",
                width=420,
                label_style=ft.TextStyle(size=13),
                password=True,
                can_reveal_password=True,
                **field_style(),
            )
 
            def save_password():
                if (new_password_field.value or "") != (confirm_field.value or ""):
                    return self.show_error(
                        "Passwords do not match", "Type the same password in both fields."
                    )
                try:
                    self.manager.reset_password(user_id, new_password_field.value or "")
                except (ValueError, DataError) as error:
                    return self.show_error("Unable to reset password", str(error))
                self.close_dialog(dialog)
                self.show_info("Password changed", f"{name}'s password was changed.")
 
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(f"New password for {name}", weight=ft.FontWeight.BOLD),
                content=ft.Column(
                    [new_password_field, confirm_field], tight=True, width=440, spacing=10
                ),
                actions=[
                    self.button("Save Password", save_password, 150),
                    self.button("Cancel", lambda: self.close_dialog(dialog), 100, self.GRAY),
                ],
            )
            self.open_dialog(dialog)
            self.focus_control(new_password_field)
 
        self._confirm_with_password(
            "Authorize Password Reset",
            ask_new_password,
            f"Change the password for {name}.",
            "Authenticate & Continue",
        )
    def toggle_account(self, user_id, name, is_active):
        verb = "Deactivate" if is_active else "Activate"
 
        def apply_change():
            try:
                self.manager.set_user_active(user_id, not is_active)
            except (ValueError, DataError) as error:
                return self.show_error(f"Unable to {verb.lower()} account", str(error))
            self.refresh_accounts()
 
        self.ask_yes_no(
            f"{verb} account",
            f"{verb} the account for {name}?"
            + (" They will no longer be able to sign in." if is_active else ""),
            apply_change,
        )

