"""Customer list, customer forms, and new-member setup."""

from datetime import date

import flet as ft

from ..database import DataError

from ..config import (
    DropdownItem,
    EXTENSIONS,
    PAYMENT_METHODS,
    PLANS,
    VIP_PLANS,
    build_list_name,
    field_style,
)



class CustomersMixin:
    def customer_page(self):
        page_content = self.new_page("Customers")
        self.selected_customer_id = None  # fields are rebuilt blank, so drop any old selection
 
        def make_field(label, width):
            return ft.TextField(
                label=label, width=width, label_style=ft.TextStyle(size=13), **field_style()
            )
 
        form_body = self.add_section(
            page_content, "Customer Details", "Add a customer or select a row to edit"
        )
        self.first_name_field = make_field("First name", 190)
        self.middle_name_field = make_field("Middle name (optional)", 190)
        self.last_name_field = make_field("Last name", 190)
        self.extension_dropdown = ft.Dropdown(
            options=[DropdownItem(option) for option in EXTENSIONS],
            value="None",
            width=130,
            label="Extension",
            label_style=ft.TextStyle(size=13),
            **field_style(),
        )
        self.phone_field = make_field("Phone", 160)
        self.email_field = make_field("Email (optional)", 220)
        form_body.controls.append(
            ft.Row(
                [
                    self.first_name_field,
                    self.middle_name_field,
                    self.last_name_field,
                    self.extension_dropdown,
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        form_body.controls.append(
            ft.Row(
                [
                    self.phone_field,
                    self.email_field,
                    self.button("Add Customer", self.add_customer, 150),
                    self.button("Update Selected", self.update_customer, 190, self.ORANGE_DEEP),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.customer_search_field = make_field("Search name, phone, or email", 320)
        page_content.controls.append(
            ft.Row(
                [
                    self.customer_search_field,
                    self.button("Search", self.refresh_customers, 125),
                    self.button(
                        "Show All",
                        lambda: (
                            setattr(self.customer_search_field, "value", ""),
                            self.refresh_customers(),
                        ),
                        140,
                        self.GRAY,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        self.customer_table = self.add_section(
            page_content, "Customer List", "Select a customer to load their details"
        )
        self.refresh_customers()
    def clear_customer_form(self):
        for field in (
            self.first_name_field,
            self.middle_name_field,
            self.last_name_field,
            self.phone_field,
            self.email_field,
        ):
            field.value = ""
        self.extension_dropdown.value = "None"
    def add_customer(self):
        try:
            customer_id = self.manager.add_customer(
                self.first_name_field.value or "",
                self.middle_name_field.value or "",
                self.last_name_field.value or "",
                self.extension_dropdown.value or "",
                self.phone_field.value or "",
                self.email_field.value or "",
            )
            full_name = self.db.get("customers", id=customer_id)["full_name"]
            self.selected_customer_id = None
            self.clear_customer_form()
            self.page.update()
            self.refresh_customers()
            self.open_new_member_dialog(customer_id, full_name)
        except (ValueError, DataError) as error:
            self.show_error("Unable to add customer", str(error))
    def open_new_member_dialog(self, customer_id, customer_name):
        """After adding a customer, offer a modal membership and initial-payment workflow."""
        plan_options = list(PLANS.keys()) + [f"VIP {name}" for name in VIP_PLANS]
        plan_dropdown = self.dropdown(plan_options, "Monthly", 450)
        start_date_field = self.date_field(
            "Start date (YYYY-MM-DD)", 450, date.today().isoformat(), title="Membership start date"
        )
        price_label = self.styled_text("Plan price: ₱800.00", 15, True, self.ORANGE_DARK)
        initial_payment_field = self.text_field(
            "Initial payment (₱)", 450, "0", hint_text="Enter 0 for no payment yet"
        )
        method_dropdown = self.dropdown(PAYMENT_METHODS, "Cash", 450)
        balance_label = self.styled_text("Balance after payment: ₱800.00", color=self.TEXT_MUTED)
 
        def update_price(_event=None):
            selection = plan_dropdown.value or "Monthly"
            current_price = (
                self.manager.vip_price(selection.removeprefix("VIP "))
                if selection.startswith("VIP ")
                else self.manager.regular_price(selection) if selection in PLANS else 0
            ) or 0
            price_label.value = f"Plan price: ₱{current_price:,.2f}"
            try:
                entered_amount = max(0.0, float(initial_payment_field.value or 0))
            except ValueError:
                entered_amount = 0.0
            balance_label.value = (
                f"Balance after payment: ₱{max(0, current_price-entered_amount):,.2f}"
            )
            self.page.update()
 
        plan_dropdown.on_change = update_price
        plan_dropdown.on_select = update_price  # newer Flet versions fire on_select
        initial_payment_field.on_change = update_price
 
        def close():
            self.close_dialog(dialog)
 
        def save_setup_authorized(start_text, selected_plan, payment_amount, payment_method):
            try:
                is_vip = selected_plan.startswith("VIP ")
                plan_name = selected_plan.removeprefix("VIP ") if is_vip else selected_plan
                if is_vip:
                    membership_id, _ = self.manager.add_vip_membership(customer_id, plan_name, start_text)
                else:
                    membership_id = self.manager.add_membership(customer_id, selected_plan, start_text)
                payment_id = None
                if payment_amount > 0:
                    payment_id = self.manager.record_payment(
                        customer_id,
                        membership_id,
                        payment_amount,
                        date.today().isoformat(),
                        "VIP membership registration" if is_vip else "Initial payment",
                        method=payment_method,
                        authorized=True,
                    )
                close()
                self.refresh_customers()
                if payment_id is not None:
                    self.show_receipt(payment_id)
                else:
                    self.show_info(
                        "Setup saved",
                        "Customer and membership saved. No initial payment was recorded.",
                    )
            except (ValueError, KeyError, DataError) as error:
                self.show_error("Unable to save setup", str(error))
 
        def save_setup():
            try:
                start_text = (start_date_field.value or "").strip()
                selected_plan = plan_dropdown.value
                try:
                    payment_amount = float((initial_payment_field.value or "").strip() or 0)
                except ValueError:
                    raise ValueError("Enter a valid amount.")
                is_vip = selected_plan.startswith("VIP ")
                plan_price = (
                    self.manager.vip_price(selected_plan.removeprefix("VIP "))
                    if is_vip else self.manager.regular_price(selected_plan)
                )
                if payment_amount < 0:
                    raise ValueError("Payment cannot be negative.")
                if payment_amount > plan_price:
                    raise ValueError(f"Payment cannot exceed the plan price of ₱{plan_price:,.2f}.")
                payment_method = method_dropdown.value
                summary = (
                    f"New membership for {customer_name}\nPlan: {selected_plan}\n"
                    f"Membership price: ₱{plan_price:,.2f}\n"
                    f"Initial payment: ₱{payment_amount:,.2f}\nMethod: {payment_method}\n\n"
                    "Enter your password to authorize membership creation"
                    + (" and the initial payment." if payment_amount > 0 else ".")
                )
                self._confirm_with_password(
                    "Confirm Membership Creation",
                    lambda: save_setup_authorized(
                        start_text, selected_plan, payment_amount, payment_method
                    ),
                    summary,
                    "Authenticate & Create",
                )
            except (ValueError, KeyError, DataError) as error:
                self.show_error("Unable to save setup", str(error))
 
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Customer Added Successfully", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                [
                    ft.Text(
                        f"Set up a membership and record the first payment for {customer_name}.",
                        color=self.TEXT_MUTED,
                        width=450,
                    ),
                    self.styled_text("Membership plan"),
                    plan_dropdown,
                    start_date_field,
                    price_label,
                    initial_payment_field,
                    self.styled_text("Payment method"),
                    method_dropdown,
                    balance_label,
                    ft.Text(
                        "Membership dates determine check-in access, regardless of payment status. "
                        "Outstanding balances must be settled before another membership can be created.",
                        color=self.TEXT_MUTED,
                        width=450,
                    ),
                ],
                tight=True,
                width=470,
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
            actions=[
                self.button("Save Membership & Payment", save_setup, 235),
                self.button("Skip for Now", close, 120, self.GRAY),
            ],
        )
        self.open_dialog(dialog)
    def update_customer(self):
        if not self.selected_customer_id:
            return self.show_warning("Select customer", "Select a customer first.")
        try:
            self.manager.update_customer(
                self.selected_customer_id,
                self.first_name_field.value or "",
                self.middle_name_field.value or "",
                self.last_name_field.value or "",
                self.extension_dropdown.value or "",
                self.phone_field.value or "",
                self.email_field.value or "",
            )
            self.refresh_customers()
            self.show_info("Updated", "Customer details updated.")
        except (ValueError, DataError) as error:
            self.show_error("Unable to update", str(error))
    def refresh_customers(self):
        if not hasattr(self, "customer_table"):
            return
        self.customer_table.controls.clear()
        customers = self.manager.search_customers(
            self.customer_search_field.value or "" if hasattr(self, "customer_search_field") else ""
        )
        is_owner = self.is_owner
        table_rows = []
        for customer in customers:
            table_row = [
                customer["id"],
                build_list_name(
                    customer["first_name"],
                    customer["middle_name"],
                    customer["last_name"],
                    customer["extension"],
                ),
                customer["phone"],
                customer["email"],
                customer["plan"] or "—",
                customer["end_date"] or "—",
                self.small_button(
                    "Select",
                    lambda current_customer=customer: self.select_customer(current_customer),
                    65,
                ),
            ]
            if is_owner:
                table_row.append(
                    self.small_button(
                        "Delete",
                        lambda current_customer=customer: self.delete_customer(
                            current_customer["id"], current_customer["full_name"]
                        ),
                        65,
                        self.RED,
                    )
                )
            table_rows.append(table_row)
        self.customer_table.controls.append(
            self.table(
                ["ID", "Name", "Phone", "Email", "Latest Plan", "End Date", "Select"]
                + (["Delete"] if is_owner else []),
                table_rows,
                "No customers found.",
            )
        )
        self.page.update()
    def delete_customer(self, customer_id, name):
        def do_delete():
            try:
                self.manager.delete_customer(customer_id)
                if self.selected_customer_id == customer_id:
                    self.selected_customer_id = None
                    self.clear_customer_form()
                self.refresh_customers()
                self.show_info("Deleted", "Customer deleted successfully.")
            except (ValueError, DataError) as error:
                self.show_error("Unable to delete customer", str(error))
 
        self.ask_yes_no(
            "Confirm customer deletion",
            f"Delete customer {name}? Customers with membership, payment, or attendance history cannot be deleted.",
            do_delete,
        )
    def select_customer(self, customer):
        self.selected_customer_id = customer["id"]
        self.first_name_field.value = customer["first_name"] or ""
        self.middle_name_field.value = customer["middle_name"] or ""
        self.last_name_field.value = customer["last_name"] or ""
        self.extension_dropdown.value = customer["extension"] or "None"
        self.phone_field.value = customer["phone"] or ""
        self.email_field.value = customer["email"] or ""
        self.page.update()

