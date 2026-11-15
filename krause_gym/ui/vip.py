"""VIP membership dashboard and front-desk service workflows."""

from datetime import date, datetime, timedelta

import flet as ft

from ..config import LEFT_ALIGNMENT, PAYMENT_METHODS, VIP_PLANS, field_style, pad_all, pad_symmetric


class VipMixin:
    def vip_page(self):
        body=self.new_page("VIP Membership")
        tab_names=("Overview","Memberships","Facilities","Training")
        views={name:ft.Column(spacing=15,horizontal_alignment=ft.CrossAxisAlignment.STRETCH) for name in tab_names}
        buttons={}
        selected_tab=getattr(self,"vip_current_tab","Overview")
        if selected_tab not in tab_names:selected_tab="Overview"

        def select_tab(name):
            self.vip_current_tab=name
            for tab,view in views.items():
                view.visible=tab==name
                buttons[tab].bgcolor=self.ORANGE if tab==name else self.GRAY
            self.record_activity()
            self.page.update()

        nav=ft.Row(spacing=7,wrap=True)
        for name in tab_names:
            buttons[name]=ft.Container(
                content=self.styled_text(name,13,True),width=150,alignment=LEFT_ALIGNMENT,
                padding=pad_symmetric(horizontal=12,vertical=10),border_radius=9,
                bgcolor=self.ORANGE if name==selected_tab else self.SURFACE_ALT,ink=True,
                on_click=lambda event,tab=name:select_tab(tab))
            nav.controls.append(buttons[name])
        self.vip_tab_bar.content=ft.Container(nav,padding=pad_symmetric(horizontal=18,vertical=6),bgcolor=self.BACKGROUND)
        self.vip_tab_bar.visible=True
        body.controls.extend(views.values())
        self.vip_current_tab=selected_tab
        for tab,view in views.items():view.visible=tab==selected_tab

        stats=self.manager.vip_summary()
        cards=ft.Row(spacing=8,wrap=True)
        revenue_label="VIP Revenue This Month" if self.is_owner else "My VIP Revenue This Month"
        for label,value in (("VIP Members",stats['total']),("Active VIP",stats['active']),("Expired VIP",stats['expired']),
                            ("Lockers Occupied",f"{stats['occupied']} / {stats['lockers']}"),
                            ("Training Today",stats['training']),
                            (revenue_label,f"₱{stats['revenue']:,.2f}")):
            cards.controls.append(ft.Container(width=175,bgcolor=self.SURFACE,border=ft.Border.all(1,self.BORDER_COLOR),border_radius=10,padding=pad_all(12),
                content=ft.Column([self.styled_text(label,11,True,self.TEXT_MUTED),self.styled_text(value,18,True)])))
        views["Overview"].controls.append(cards)
        members=self.manager.vip_members()
        sec=self.add_section(views["Overview"],"VIP Members","Membership-date eligibility controls access; service and payment history remain traceable.")
        sec.controls.append(self.table(["Member","Plan","Dates","Status","Locker"],[(r['full_name'],r['plan_name'],f"{r['start_date']} – {r['end_date']}",r['status'],r['locker'] or "—") for r in members]))
        today=date.today().isoformat()
        people={c["id"]:c for c in self.db.rows("customers")}; trainers={t["id"]:t for t in self.db.rows("vip_trainers")}
        daily=[]
        for s in sorted(self.db.rows("vip_training_sessions"),key=lambda s:s["starts_at"]):
            if s["starts_at"][:10]==today and s["status"]=="Scheduled" and s["customer_id"] in people and s["trainer_id"] in trainers:
                daily.append({"starts_at":s["starts_at"],"full_name":people[s["customer_id"]]["full_name"],"trainer":trainers[s["trainer_id"]]["name"]})
        daily_section=self.add_section(views["Overview"],"Today's VIP Activity","Scheduled VIP training")
        daily_section.controls.append(self.table(["Training time","Member","Trainer"],[(r['starts_at'],r['full_name'],r['trainer']) for r in daily]))
        expiring=[member for member in self.manager.vip_expiring_soon(30) if member['end_date']>=today]
        expiring_section=self.add_section(views["Overview"],"VIP Memberships Expiring in 30 Days")
        expiring_section.controls.append(self.table(["Member","Plan","Expires"],[(r['full_name'],r['plan_name'],r['end_date']) for r in expiring]))
        history_section=self.add_section(views["Overview"],"Member History","Search any member to review their VIP activity and membership timeline.")
        history_member=self._vip_member_picker(history_section,"Search member history","history")
        history_body=ft.Column(spacing=8,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        history_section.controls.append(ft.Row([self.button("Load History",lambda:self._vip_show_member_history(history_member,history_body),120)],wrap=True))
        history_section.controls.append(history_body)
        if self.is_owner:
            auditsec=self.add_section(views["Overview"],"VIP Audit History","Latest owner-visible changes")
            record_labels={"locker_assignment":"Locker Assignment","training_session":"Training Session","membership":"VIP Membership","locker":"Locker","trainer":"Trainer","locker_waitlist":"Locker Waitlist"}
            audit_search=ft.TextField(label="Search action, record type, details, staff, or date",width=520,
                label_style=ft.TextStyle(size=13),on_change=lambda event:load_audit(),**field_style())
            audit_result=self.styled_text("Showing the latest 20 records",11,color=self.TEXT_MUTED)
            audit_body=ft.Column(spacing=6,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
            auditsec.controls.extend([audit_search,audit_result,audit_body])
            def load_audit(_event=None):
                query=(audit_search.value or "").strip()
                users={u["id"]:u for u in self.db.rows("users")}; audit=[]
                for record in sorted(self.db.rows("vip_audit"),key=lambda a:a["id"],reverse=True):
                    entity=(record.get("entity") or "").lower(); action=(record.get("action") or "").lower()
                    if entity=="lounge_visit" or "lounge" in action: continue
                    person=users.get(record.get("performed_by")); display=(person or {}).get("display_name")
                    view={**record,"display_name":display}
                    label=record_labels.get(entity,entity.replace("_"," ").title() or "—")
                    haystack=" ".join(str(x or "") for x in (action,label,record.get("details"),display,record.get("performed_at"))).lower()
                    if query and query.lower() not in haystack: continue
                    audit.append(view)
                if not query:audit=audit[:20]
                audit_rows=[(r['performed_at'],r['action'],record_labels.get(r['entity'],(r['entity'] or "").replace("_"," ").title() or "—"),r['details'] or "—",r['display_name'] or "—") for r in audit]
                audit_result.value=f"Found {len(audit_rows)} matching records" if query else "Showing the latest 20 records"
                audit_body.controls.clear()
                audit_body.controls.append(self.table(["When","Action","Record Type","Details","Staff"],audit_rows,"No matching audit records."))
                self.page.update()
            load_audit()

        duration_opts=[ft.dropdown.Option(key=k,text=k) for k in VIP_PLANS]
        vip_plan=ft.Dropdown(label="VIP duration",options=duration_opts,width=210,value="Monthly")
        register=self.add_section(views["Memberships"],"Register VIP","Search by member name, phone, email, or member ID. The payment is confirmed with the signed-in user's password.")
        vip_customer=self._vip_member_picker(register,"Search existing customer","any")
        reg_method=ft.Dropdown(label="Payment method",options=[ft.dropdown.Option(k) for k in PAYMENT_METHODS],value="Cash",width=165)
        start=self.date_field("Start date (YYYY-MM-DD)",210,date.today().isoformat())
        price_display=self.styled_text(f"VIP price: ₱{self.manager.vip_price(vip_plan.value):,.2f}",13,True,self.ORANGE_LIGHT)
        def refresh_vip_price(_event=None):
            price=self.manager.vip_price(vip_plan.value)
            price_display.value=f"VIP price: ₱{price:,.2f}" if price is not None else "VIP price is not configured."
            self.page.update()
        vip_plan.on_change=refresh_vip_price
        vip_plan.on_select=refresh_vip_price
        register.controls.append(ft.Row([vip_plan,price_display,start,reg_method,self.button("Register & Pay",lambda:self._vip_register(vip_customer,vip_plan,start,reg_method),140)],wrap=True))
        upgrade=self.add_section(views["Memberships"],"Upgrade Regular to VIP","Search for an active Regular member. Outstanding balances must be settled first; original dates are retained.")
        upgrade_dd=self._vip_member_picker(upgrade,"Search active Regular member","Regular")
        upgrade_quote_preview=ft.Column(spacing=3)
        upgrade.controls.append(upgrade_quote_preview)
        def show_upgrade_quote(member):
            upgrade_quote_preview.controls.clear()
            try:
                quote=self.manager.vip_upgrade_quote(int(member["membership_id"]))
                upgrade_quote_preview.controls.extend([
                    self.styled_text(f"Upgrade quote for {member['name']} · {quote['days']} of {quote['membership_days']} days remaining",13,True,self.ORANGE_LIGHT),
                    self.styled_text(f"VIP value for remaining days: ₱{quote['vip_remaining_value']:,.2f}  ·  Regular value already paid: −₱{quote['regular_remaining_value']:,.2f}",12,color=self.TEXT_MUTED),
                    self.styled_text(f"Amount due: ₱{quote['amount']:,.2f}",15,True),
                ])
            except Exception as error:
                upgrade_quote_preview.controls.append(self.styled_text(str(error),12,color=self.RED))
            self.page.update()
        def clear_upgrade_quote():
            upgrade_quote_preview.controls.clear()
            self.page.update()
        upgrade_dd["on_select"]=show_upgrade_quote
        upgrade_dd["on_clear"]=clear_upgrade_quote
        method=ft.Dropdown(label="Payment method",options=[ft.dropdown.Option(k) for k in PAYMENT_METHODS],value="Cash",width=180)
        upgrade.controls.append(ft.Row([method,self.button("Quote & Upgrade",lambda:self._vip_upgrade(upgrade_dd,method),150)],wrap=True))
        if self.is_owner:
            prices=self.add_section(views["Memberships"],"VIP Pricing & Benefits","Owner settings")
            price_fields=[]
            for name in VIP_PLANS:
                val=self.manager.vip_price(name)
                field=self.text_field(f"{name} VIP price",145,f"{val:.2f}")
                price_fields.append((name,field))
            prices.controls.append(ft.Row([*([f for _,f in price_fields]),self.button("Save Prices",lambda:self._vip_save_prices(price_fields),115)],wrap=True))
            training_rate=self.manager.vip_training_rate()
            training_rate_field=self.text_field("Non-VIP training session price (₱)",230,f"{training_rate:.2f}" if training_rate>0 else "")
            prices.controls.append(ft.Row([training_rate_field,self.button("Save Training Rate",lambda:self._vip_save_training_rate(training_rate_field),155)],wrap=True))
            benefit_fields=[]
            for benefit in self.manager.vip_benefits():
                checkbox=ft.Checkbox(label=benefit['label'],value=bool(benefit['enabled']))
                benefit_fields.append((benefit['benefit_key'],benefit['label'],checkbox))
            prices.controls.append(ft.Row([*([item[2] for item in benefit_fields]),self.button("Save Benefits",lambda:self._vip_save_benefits(benefit_fields),120)],wrap=True))
        renewals=self.manager.vip_expiring_soon(30)
        renewal_section=self.add_section(views["Memberships"],"VIP Renewals","Active memberships extend from the current expiry; expired memberships restart today. Each action preserves membership history.")
        renewal_search=ft.TextField(label="Search name, phone or member ID",width=420,label_style=ft.TextStyle(size=13))
        renewal_results=ft.Column(spacing=5,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        def refresh_renewals(_event=None,update=True):
            query=(renewal_search.value or "").strip().casefold()
            filtered=[r for r in renewals if not query or query in (r['full_name'] or "").casefold() or query in (r['phone'] or "").casefold() or query in str(r['customer_id'])]
            renewal_results.controls.clear()
            renewal_results.controls.append(self.table(["Member","Plan","Start","Expires","Action"],[(r['full_name'],r['plan_name'],r['start_date'],r['end_date'],self.small_button("Extend VIP" if r['end_date']>=date.today().isoformat() else "Renew VIP",lambda item=r:self._vip_start_renewal(item),95)) for r in filtered],"No matching VIP renewals."))
            if update:self.page.update()
        renewal_search.on_change=refresh_renewals
        renewal_search.on_submit=refresh_renewals
        renewal_section.controls.extend([renewal_search,renewal_results])
        refresh_renewals(update=False)

        people={c["id"]:c for c in self.db.rows("customers")}
        lockers=[]
        for locker in sorted(self.db.rows("vip_lockers"),key=lambda l:l["locker_no"]):
            assignment=next((a for a in self.db.rows("vip_locker_assignments") if a["locker_id"]==locker["id"] and not a.get("released_at")),None)
            lockers.append({**locker,"assignment_id":assignment["id"] if assignment else None,"full_name":(people.get(assignment["customer_id"]) or {}).get("full_name") if assignment else None})
        free_lockers=[locker for locker in lockers if locker['active'] and not locker['assignment_id']]
        waitlist=[]
        for w in sorted(self.db.rows("vip_locker_waitlist"),key=lambda w:(w["requested_at"],w["id"])):
            if w["status"]=="Waiting" and w["customer_id"] in people: waitlist.append({**w,"full_name":people[w["customer_id"]]["full_name"]})
        wait_section=self.add_section(views["Facilities"],"Locker Waitlist","When lockers are full, add an active VIP member to the queue and assign the next available locker.")
        wait_member=self._vip_member_picker(wait_section,"Search active VIP member","VIP")
        wait_note=self.text_field("Optional note",220)
        wait_section.controls.append(ft.Row([wait_note,self.button("Add to Waitlist",lambda:self._vip_waitlist_add(wait_member,wait_note),120)],wrap=True))
        wait_rows=[]
        for item in waitlist:
            available=ft.Dropdown(label="Available locker",options=[ft.dropdown.Option(key=str(locker['id']),text=locker['locker_no']) for locker in free_lockers],width=145)
            actions=ft.Row([self.small_button("Assign",lambda wid=item['id'],dd=available:self._vip_waitlist_assign(wid,dd),58),self.small_button("Remove",lambda wid=item['id']:self._vip_waitlist_cancel(wid),65,self.GRAY)],wrap=True,spacing=3)
            wait_rows.append((item['full_name'],item['requested_at'],item['note'] or "—",ft.Row([available,actions],wrap=True,spacing=4)))
        wait_section.controls.append(self.table(["Member","Requested","Note","Next action"],wait_rows))

        locker_dd=ft.Dropdown(label="Available locker",options=[ft.dropdown.Option(key=str(l['id']),text=l['locker_no']) for l in lockers if not l['assignment_id']],width=180)
        locker_sec=self.add_section(views["Facilities"],"Locker Assignments")
        if self.is_owner:
            new_locker=self.text_field("Locker label (e.g. A-12)",190)
            locker_sec.controls.append(ft.Row([new_locker,self.button("Add Locker",lambda:self._vip_add_locker(new_locker),100)],wrap=True))
        lock_member=self._vip_member_picker(locker_sec,"Search active VIP member","VIP")
        locker_sec.controls.append(ft.Row([locker_dd,self.button("Assign",lambda:self._vip_assign(lock_member,locker_dd),90)],wrap=True))
        locker_rows=[]
        for locker in lockers:
            state="Assigned" if locker['assignment_id'] else ("Available" if locker['active'] else "Unavailable")
            actions=[]
            if self.is_owner:
                actions.append(self.small_button("Edit",lambda lid=locker['id'],label=locker['locker_no']:self._vip_edit_locker(lid,label),55,self.GRAY))
            if locker['assignment_id']:
                actions.append(self.small_button("Release",lambda aid=locker['assignment_id'],no=locker['locker_no'],member=locker['full_name']:self._vip_release(aid,no,member),65,self.RED))
            elif self.is_owner:
                actions.append(self.small_button("Disable" if locker['active'] else "Enable",lambda lid=locker['id'],active=not bool(locker['active']):self._vip_toggle_locker(lid,active),72,self.GRAY))
            action=ft.Row(actions,wrap=True,spacing=4) if actions else "—"
            locker_rows.append((locker['locker_no'],locker['full_name'] or "—",state,action))
        locker_sec.controls.append(self.table(["Locker","Assigned member","Status","Action"],locker_rows))
        trainers=sorted(self.db.rows("vip_trainers"),key=lambda t:(not bool(t["active"]),t["name"].casefold()))
        active_trainers=[trainer for trainer in trainers if trainer['active']]
        trainer_dd=ft.Dropdown(label="Trainer",options=[ft.dropdown.Option(key=str(t['id']),text=t['name']) for t in active_trainers],width=240)
        when=self.date_field("Session date (YYYY-MM-DD)",220,date.today().isoformat(),title="Select training date")
        session_time=self.text_field("Start time (HH:MM)",150,"18:00")
        tnotes=self.text_field("Workout notes",210)
        ts=self.add_section(views["Training"],"Personal Training","Active VIP members receive included sessions; other customers can book at the paid rate. A member may hold at most three scheduled sessions.")
        training_member=self._vip_member_picker(ts,"Search customer for training","training")
        training_price=ft.Column(spacing=3)
        def refresh_training_price(member=None):
            training_price.controls.clear()
            if not member:
                training_price.controls.append(self.styled_text("Select a customer to see whether training is included or the paid session rate.",11,color=self.TEXT_MUTED))
                training_method.visible=True
            elif self.manager.vip_training_included(int(member['id'])):
                training_price.controls.append(self.styled_text("VIP personal training · Included",12,True,self.ORANGE_LIGHT))
                training_method.visible=False
            else:
                fee=self.manager.vip_training_rate()
                message=f"Paid personal training · ₱{fee:,.2f} per session" if fee>0 else "Paid training is unavailable until the owner sets a session price."
                training_price.controls.append(self.styled_text(message,12,True,self.ORANGE_LIGHT if fee>0 else self.RED))
                training_method.visible=True
            self.page.update()
        training_member["on_select"]=refresh_training_price
        training_member["on_clear"]=lambda:refresh_training_price()
        training_price.controls.append(self.styled_text("Select a customer to see whether training is included or the paid session rate.",11,color=self.TEXT_MUTED))
        training_method=ft.Dropdown(label="Payment method for paid session",options=[ft.dropdown.Option(k) for k in PAYMENT_METHODS],value="Cash",width=230)
        ts.controls.append(training_price)
        ts.controls.append(ft.Row([trainer_dd,when,session_time,tnotes,training_method,self.button("Book Session",lambda:self._vip_schedule(training_member,trainer_dd,when,session_time,tnotes,training_method),125)],wrap=True))
        booked_preview=ft.Column(spacing=4,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        ts.controls.append(booked_preview)

        def refresh_booked_preview(_event=None,update=True):
            booked_preview.controls.clear()
            if not trainer_dd.value or not when.value:
                booked_preview.controls.append(self.styled_text("Select a trainer and date to see that day's bookings.",11,color=self.TEXT_MUTED))
            else:
                customers={c["id"]:c for c in self.db.rows("customers")}; payment_rows={p["id"]:p for p in self.db.rows("payments")}
                bookings=[]
                for s in sorted(self.db.rows("vip_training_sessions"),key=lambda s:s["starts_at"]):
                    if s["trainer_id"]==int(trainer_dd.value) and s["starts_at"][:10]==when.value.strip() and s["status"]=="Scheduled" and s["customer_id"] in customers:
                        bookings.append({**s,"full_name":customers[s["customer_id"]]["full_name"],"payment_voided":(payment_rows.get(s.get("payment_id")) or {}).get("voided",0)})
                if bookings:
                    booked_preview.controls.append(self.styled_text("Already booked for this trainer and date:",11,True,self.ORANGE_LIGHT))
                    booked_preview.controls.append(self.table(["Time","Member","Status","Type / Fee"],[(b['starts_at'][11:16],b['full_name'],b['status'],"VIP Included" if b['booking_type']=="VIP Included" else f"{'Voided' if b['payment_voided'] else 'Paid'} · ₱{b['session_fee']:,.2f}") for b in bookings]))
                else:
                    booked_preview.controls.append(self.styled_text("No scheduled sessions for this trainer on this date.",11,color=self.TEXT_MUTED))
            if update:self.page.update()

        trainer_dd.on_change=refresh_booked_preview
        trainer_dd.on_select=refresh_booked_preview
        when.on_change=refresh_booked_preview
        refresh_booked_preview(update=False)

        if self.is_owner:
            draft=getattr(self,"vip_trainer_draft",{})
            trainer_form=self.add_section(views["Training"],"Trainer Records","Owner-managed contact and availability; phone numbers are for staff use.")
            day_order=("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
            selected_days=set((draft.get("working_days") or "Mon,Tue,Wed,Thu,Fri,Sat").split(","))
            day_fields={}
            def refresh_day_buttons(update=True):
                for day,button in day_fields.items():
                    button.style=ft.ButtonStyle(bgcolor=self.ORANGE if day in selected_days else self.GRAY,color="white",padding=pad_symmetric(horizontal=4),shape=ft.RoundedRectangleBorder(radius=8))
                if update:self.page.update()
            def set_working_days(days):
                selected_days.clear()
                selected_days.update(days)
                refresh_day_buttons()
            def toggle_working_day(day):
                if day in selected_days:selected_days.remove(day)
                else:selected_days.add(day)
                refresh_day_buttons()
            for day in day_order:
                day_fields[day]=self.small_button(day,lambda item=day:toggle_working_day(item),66,self.ORANGE if day in selected_days else self.GRAY)
            fields={
                "name":self.text_field("Trainer name",190,draft.get("name","")),
                "phone":self.text_field("Phone (optional)",180,draft.get("phone","")),
                "days":selected_days,
                "from":self.text_field("Available from (HH:MM)",175,draft.get("available_from","08:00")),
                "to":self.text_field("Available to (HH:MM)",175,draft.get("available_to","21:00")),
            }
            trainer_form.controls.append(ft.Row([fields["name"],fields["phone"],fields["from"],fields["to"],self.button("Save Trainer",lambda:self._vip_save_trainer(fields),120),*([self.button("Cancel Edit",self._vip_cancel_trainer_edit,100,self.GRAY)] if getattr(self,"vip_trainer_edit_id",None) else [])],wrap=True))
            trainer_form.controls.append(ft.Row([self.styled_text("Working days:",12,True),self.small_button("Weekdays",lambda:set_working_days(day_order[:5]),78,self.GRAY),self.small_button("Every day",lambda:set_working_days(day_order),82,self.GRAY),self.small_button("Clear",lambda:set_working_days(()),60,self.GRAY),*day_fields.values()],wrap=True,spacing=7,vertical_alignment=ft.CrossAxisAlignment.CENTER))
            trainer_rows=[]
            for trainer in trainers:
                actions=ft.Row([self.small_button("Edit",lambda item=trainer:self._vip_edit_trainer(item),55),self.small_button("Deactivate" if trainer['active'] else "Activate",lambda tid=trainer['id'],active=not bool(trainer['active']):self._vip_toggle_trainer(tid,active),86,self.GRAY)],wrap=True,spacing=4)
                trainer_rows.append((trainer['name'],trainer['phone'] or "—",trainer['working_days'],f"{trainer['available_from']}–{trainer['available_to']}","Active" if trainer['active'] else "Inactive",actions))
            trainer_form.controls.append(self.table(["Trainer","Phone","Days","Hours","Status","Actions"],trainer_rows))
        else:
            trainer_view=self.add_section(views["Training"],"Trainer Availability","Trainer contact details are visible to gym staff only.")
            trainer_view.controls.append(self.table(["Trainer","Phone","Days","Hours","Status"],[(t['name'],t['phone'] or "—",t['working_days'],f"{t['available_from']}–{t['available_to']}","Active" if t['active'] else "Inactive") for t in trainers]))

        schedule_filter=self.add_section(views["Training"],"Training Schedule","Search by member and filter appointments by date or trainer.")
        trainer_filter_options=[ft.dropdown.Option(key="all",text="All trainers")]+[ft.dropdown.Option(key=str(t['id']),text=t['name']) for t in trainers]
        schedule_trainer=ft.Dropdown(label="Trainer",options=trainer_filter_options,value=getattr(self,"vip_schedule_filter_trainer","all"),width=220)
        schedule_date=self.date_field("Date filter (optional)",220,getattr(self,"vip_schedule_filter_date",""),title="Filter training by date")
        schedule_member=ft.TextField(label="Search member name, phone or ID",width=320,label_style=ft.TextStyle(size=13),value=getattr(self,"vip_schedule_filter_member",""))
        session_table=ft.Column(spacing=0,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        schedule_filter.controls.append(ft.Row([schedule_member,schedule_trainer,schedule_date,self.button("Apply Filter",lambda:refresh_training_schedule(),100),self.button("Clear",lambda:clear_training_filter(),75,self.GRAY)],wrap=True))
        schedule_filter.controls.append(session_table)

        def refresh_training_schedule():
            self.vip_schedule_filter_trainer=schedule_trainer.value or "all"
            self.vip_schedule_filter_date=(schedule_date.value or "").strip()
            self.vip_schedule_filter_member=(schedule_member.value or "").strip()
            customers={c["id"]:c for c in self.db.rows("customers")}; trainer_map={t["id"]:t for t in trainers}; payments_map={p["id"]:p for p in self.db.rows("payments")}
            sessions=[]
            for s in self.db.rows("vip_training_sessions"):
                c=customers.get(s["customer_id"]); t=trainer_map.get(s["trainer_id"])
                if not c or not t: continue
                if self.vip_schedule_filter_trainer!="all" and s["trainer_id"]!=int(self.vip_schedule_filter_trainer): continue
                if self.vip_schedule_filter_date and s["starts_at"][:10]!=self.vip_schedule_filter_date: continue
                search=self.vip_schedule_filter_member.casefold()
                if search and search not in (str(c["id"])+" "+c["full_name"]+" "+str(c.get("phone") or "")).casefold():continue
                sessions.append({**s,"full_name":c["full_name"],"trainer":t["name"],"payment_voided":(payments_map.get(s.get("payment_id")) or {}).get("voided",0)})
            sessions.sort(key=lambda s:s["starts_at"],reverse=True)
            if not self.vip_schedule_filter_trainer=="all" or self.vip_schedule_filter_date or self.vip_schedule_filter_member: pass
            else: sessions=sessions[:100]
            rows=[]
            for session in sessions:
                if session['status']=='Scheduled':
                    actions=ft.Row([self.small_button("Done",lambda sid=session['id']:self._vip_training_status(sid,'Completed'),55),self.small_button("Cancel",lambda sid=session['id']:self._vip_training_status(sid,'Cancelled'),58,self.GRAY),self.small_button("Missed",lambda sid=session['id']:self._vip_training_status(sid,'Missed'),58,self.RED)],wrap=True,spacing=3)
                elif self.is_owner:
                    actions=self.small_button("Correct",lambda sid=session['id']:self._vip_correct_training(sid),65,self.GRAY)
                else:actions="—"
                booking_label="VIP Included" if session['booking_type']=="VIP Included" else f"{'Voided' if session['payment_voided'] else 'Paid'} · ₱{session['session_fee']:,.2f}"
                rows.append((session['full_name'],session['trainer'],session['starts_at'],session['status'],booking_label,session['notes'],actions))
            session_table.controls.clear()
            session_table.controls.append(self.table(["Member","Trainer","Start","Status","Type / Fee","Notes","Actions"],rows))
            self.page.update()

        def clear_training_filter():
            schedule_trainer.value="all"; schedule_date.value=""; schedule_member.value=""
            refresh_training_schedule()

        schedule_trainer.on_change=lambda event:refresh_training_schedule()
        schedule_trainer.on_select=lambda event:refresh_training_schedule()
        schedule_member.on_change=lambda event:refresh_training_schedule()
        schedule_member.on_submit=lambda event:refresh_training_schedule()
        refresh_training_schedule()
        self.page.update()

    def _vip_error(self,title,error): self.show_error(title,str(error))
    def _vip_show_member_history(self,picker,target):
        try:
            selected=picker["selected"]
            if not selected:raise ValueError("Search for and select a member first.")
            customer_id=int(selected['id'])
            target.controls.clear()
            memberships=sorted((m for m in self.db.rows("memberships") if m["customer_id"]==customer_id),key=lambda m:(m["start_date"],m["id"]),reverse=True)
            target.controls.append(self.table(["Membership","Type","Start","End","Price","Payment status"],[(r['plan_name'],r['membership_type'],r['start_date'],r['end_date'],f"₱{r['plan_price']:,.2f}",r['payment_status']) for r in memberships]))
            user=self.manager.current_user
            payments=[p for p in self.db.rows("payments") if p["customer_id"]==customer_id and user and (user["role"]=="owner" or p.get("recorded_by")==user["id"])]
            payments.sort(key=lambda p:p["id"],reverse=True); payments=payments[:50]
            target.controls.append(self.styled_text("Payments",14,True))
            target.controls.append(self.table(["Date","Amount","Method","Receipt","Note","Status"],[(r['payment_date'],f"₱{r['amount']:,.2f}",r['method'],r['receipt_no'],r['note'] or "—","Voided" if r['voided'] else "Recorded") for r in payments]))
            locker_map={l["id"]:l for l in self.db.rows("vip_lockers")}
            lockers=[{**a,"locker_no":locker_map[a["locker_id"]]["locker_no"]} for a in sorted(self.db.rows("vip_locker_assignments"),key=lambda a:a["id"],reverse=True) if a["customer_id"]==customer_id and a["locker_id"] in locker_map]
            target.controls.append(self.styled_text("Locker history",14,True))
            target.controls.append(self.table(["Locker","Assigned","Released"],[(r['locker_no'],r['assigned_at'],r['released_at'] or "Current") for r in lockers]))
            trainer_map={t["id"]:t for t in self.db.rows("vip_trainers")}; payment_map={p["id"]:p for p in self.db.rows("payments")}
            sessions=[{**s,"trainer":trainer_map[s["trainer_id"]]["name"],"payment_voided":(payment_map.get(s.get("payment_id")) or {}).get("voided",0)} for s in sorted(self.db.rows("vip_training_sessions"),key=lambda s:s["starts_at"],reverse=True) if s["customer_id"]==customer_id and s["trainer_id"] in trainer_map]
            target.controls.append(self.styled_text("Personal training",14,True))
            target.controls.append(self.table(["Start","Trainer","Status","Type / Fee","Notes"],[(r['starts_at'],r['trainer'],r['status'],"VIP Included" if r['booking_type']=="VIP Included" else f"{'Voided' if r['payment_voided'] else 'Paid'} · ₱{r['session_fee']:,.2f}",r['notes']) for r in sessions]))
            self.page.update()
        except Exception as e:self._vip_error("Unable to load member history",e)

    def _vip_start_renewal(self,member):
        try:
            balance=self.manager.vip_outstanding_balance(member['customer_id'])
            if balance>0.005:raise ValueError(f"Settle the outstanding balance of ₱{balance:,.2f} before renewing.")
            plan=ft.Dropdown(label="Renewal duration",options=[ft.dropdown.Option(k) for k in VIP_PLANS],value="Monthly",width=220)
            method=ft.Dropdown(label="Payment method",options=[ft.dropdown.Option(k) for k in PAYMENT_METHODS],value="Cash",width=220)
            is_active=member['end_date']>=date.today().isoformat()
            action="Extend" if is_active else "Renew"
            dialog=ft.AlertDialog(modal=True,title=ft.Text(f"{action} VIP Membership"),content=ft.Column([
                ft.Text(f"Member: {member['full_name']}\nCurrent expiry: {member['end_date']}\nThe new membership starts {'the day after the current expiry' if is_active else 'today'} and preserves the existing history."),plan,method],tight=True,width=450,spacing=10))
            def continue_to_password(_event=None):
                self.close_dialog(dialog)
                price=self.manager.vip_price(plan.value)
                last=max((m for m in self.db.rows("memberships") if m["customer_id"]==member['customer_id'] and m.get("membership_type")=="VIP"),key=lambda m:(m["end_date"],m["id"]),default=None)
                start=max(date.today(),date.fromisoformat(last['end_date'])+timedelta(days=1))
                end=start+timedelta(days=VIP_PLANS[plan.value]['days']-1)
                summary=f"VIP {action.lower()}\nMember: {member['full_name']}\nPlan: VIP {plan.value}\nPrice: ₱{price:,.2f}\nDates: {start.isoformat()} through {end.isoformat()}\nPayment method: {method.value}\n\nEnter your password to authorize this membership and payment."
                def save():
                    try:
                        membership_id,amount=self.manager.vip_renew(member['customer_id'],plan.value)
                        payment_id=self.manager.record_payment(member['customer_id'],membership_id,amount,date.today().isoformat(),"VIP membership renewal",method=method.value,authorized=True)
                        self.vip_current_tab="Memberships"; self.vip_page(); self.show_receipt(payment_id)
                    except Exception as e:self._vip_error("Unable to renew VIP membership",e)
                self._confirm_with_password(f"Confirm VIP {action}",save,summary,f"Authenticate & {action}")
            dialog.actions=[self.button("Continue",continue_to_password,100),self.button("Cancel",lambda:self.close_dialog(dialog),90,self.GRAY)]
            self.open_dialog(dialog)
        except Exception as e:self._vip_error("Unable to prepare renewal",e)

    def _vip_waitlist_add(self,picker,note):
        try:
            if not picker['selected']:raise ValueError("Search for and select an active VIP member.")
            self.manager.vip_waitlist_add(picker['selected']['id'],note.value or '')
            self.vip_current_tab="Facilities"; self.vip_page()
        except Exception as e:self._vip_error("Unable to add to locker waitlist",e)
    def _vip_waitlist_assign(self,waitlist_id,locker):
        try:
            if not locker.value:raise ValueError("No available locker is selected.")
            self.manager.vip_waitlist_assign(waitlist_id,int(locker.value))
            self.vip_current_tab="Facilities"; self.vip_page()
        except Exception as e:self._vip_error("Unable to assign locker",e)
    def _vip_waitlist_cancel(self,waitlist_id):
        try:self.manager.vip_waitlist_cancel(waitlist_id); self.vip_current_tab="Facilities"; self.vip_page()
        except Exception as e:self._vip_error("Unable to remove from waitlist",e)
    def _vip_toggle_locker(self,locker_id,active):
        try:self.manager.vip_set_locker_active(locker_id,active); self.vip_current_tab="Facilities"; self.vip_page()
        except Exception as e:self._vip_error("Unable to update locker",e)

    def _vip_reason_prompt(self,title,prompt,on_save,confirm_label="Save Correction"):
        reason=ft.TextField(label="Reason (required)",width=420,multiline=True,min_lines=2,max_lines=4)
        dialog=ft.AlertDialog(modal=True,title=ft.Text(title),content=ft.Column([ft.Text(prompt),reason],tight=True,width=440,spacing=10))
        def save(_event=None):
            value=(reason.value or '').strip()
            if len(value)<3:return self.show_error("Reason required","Enter a short reason so the correction is auditable.")
            self.close_dialog(dialog); on_save(value)
        dialog.actions=[self.button(confirm_label,save,175),self.button("Cancel",lambda:self.close_dialog(dialog),90,self.GRAY)]
        self.open_dialog(dialog)

    def _vip_correct_training(self,session_id):
        record=self.db.get("vip_training_sessions",id=session_id)
        customer=self.db.get("customers",id=record["customer_id"]) if record else None
        trainer=self.db.get("vip_trainers",id=record["trainer_id"]) if record else None
        session={**record,"full_name":customer["full_name"],"trainer":trainer["name"]} if record and customer and trainer else None
        if not session:return self._vip_error("Unable to correct training session","This training session could not be found.")
        booking_type="VIP Included" if session['booking_type']=="VIP Included" else f"Paid · ₱{session['session_fee']:,.2f}"
        prompt=f"Member: {session['full_name']}\nTrainer: {session['trainer']}\nStart: {session['starts_at']}\nCurrent status: {session['status']}\nBooking: {booking_type}\n\nThis will reopen the session as Scheduled. Enter a reason for the audit history."
        def correct(reason):
            try:self.manager.vip_reopen_training(session_id,reason); self.vip_current_tab="Training"; self.vip_page()
            except Exception as e:self._vip_error("Unable to correct training session",e)
        self._vip_reason_prompt("Reopen Training Session",prompt,correct,"Reopen as Scheduled")

    def _vip_member_picker(self,parent,label,kind="any"):
        field=ft.TextField(label=label,width=520,label_style=ft.TextStyle(size=13),
            on_change=lambda event:self._vip_search_members(picker,kind),
            on_submit=lambda event:self._vip_search_members(picker,kind))
        results=ft.Column(spacing=5,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        picker={"field":field,"results":results,"selected":None,"kind":kind}
        parent.controls.extend([field,results])
        results.controls.append(self.styled_text("Start typing a name, phone, email, or member ID.",12,color=self.TEXT_MUTED))
        return picker

    def _vip_search_members(self,picker,kind):
        query=(picker["field"].value or "").strip()
        results=picker["results"]
        picker["selected"]=None
        if picker.get("on_clear"):
            picker["on_clear"]()
        results.controls.clear()
        if not query:
            results.controls.append(self.styled_text("Start typing a name, phone, email, or member ID.",12,color=self.TEXT_MUTED))
            self.page.update(); return
        if kind in ("any","history","training"):
            rows=self.manager.find_members(query,limit=9)
        else:
            today=date.today().isoformat()
            member_id=int(query) if query.isdigit() else -1
            customers=self.db.rows("customers"); words=query.replace(","," ").split(); rows=[]
            for c in customers:
                haystack=" ".join(str(c.get(k) or "") for k in ("full_name","first_name","middle_name","last_name","phone","email")).casefold()
                if c["id"]!=member_id and not all(word.casefold() in haystack for word in words):continue
                active=[m for m in self.db.rows("memberships") if m["customer_id"]==c["id"] and m.get("membership_type")==kind and m["start_date"]<=today<=m["end_date"]]
                latest=max(active,key=lambda m:(m["end_date"],m["id"]),default=None)
                if latest:rows.append({"id":c["id"],"full_name":c["full_name"],"name":c["full_name"],"membership_id":latest["id"],"plan_name":latest["plan_name"],"end_date":latest["end_date"]})
            rows.sort(key=lambda r:(r["id"]!=member_id,r["full_name"].casefold())); rows=rows[:9]
        if not rows:
            results.controls.append(self.styled_text(f'No matching {"member" if kind != "any" else "customer"} found.',12,color=self.TEXT_MUTED))
        for member in rows[:8]:
            keys=member.keys()
            plan_name=member['plan_name'] if 'plan_name' in keys else None
            end_date=member['end_date'] if 'end_date' in keys else None
            membership_id=member['membership_id'] if 'membership_id' in keys else None
            balance=self.manager.vip_outstanding_balance(member['id'])
            can_upgrade_plan=kind!="Regular" or plan_name in VIP_PLANS
            eligible=kind in ("history","training") or (balance<=0.005 and can_upgrade_plan)
            membership=(f"{plan_name} · expires {end_date}" if plan_name else "Customer record")
            if kind=="history":
                eligibility="Member history available"; eligibility_color=self.TEXT_MUTED
            elif kind=="training":
                eligibility="VIP training included" if self.manager.vip_training_included(member['id']) else "Paid training booking"
                eligibility_color=self.ORANGE_LIGHT
            else:
                if eligible:
                    eligibility="Eligible for VIP upgrade" if kind=="Regular" else "Eligible for VIP registration"
                elif balance>0.005:
                    eligibility=f"Not eligible — ₱{balance:,.2f} outstanding; settle the balance first"
                else:
                    eligibility="Day Pass memberships cannot be upgraded to VIP; choose a weekly, monthly, or quarterly VIP plan"
                eligibility_color="#22C55E" if eligible else self.RED
            info={"id":member['id'],"name":member['full_name'],"membership_id":membership_id,"plan_name":plan_name,"end_date":end_date,"eligible":eligible,"balance":balance}
            results.controls.append(ft.Container(
                content=ft.Column([self.styled_text(f"{member['full_name']}  ·  Member ID {member['id']}",13,True),self.styled_text(membership,11,color=self.TEXT_MUTED),self.styled_text(eligibility,11,color=eligibility_color)],spacing=2),
                bgcolor=self.SURFACE_ALT,border=ft.Border.all(1,self.BORDER_COLOR),border_radius=8,
                padding=pad_symmetric(horizontal=12,vertical=7),ink=True,
                on_click=(lambda event,selected=info:self._vip_select_member(picker,selected)) if eligible else None))
        if len(rows)>8:
            results.controls.append(self.styled_text("More matches found. Keep typing to narrow the list.",12,color=self.TEXT_MUTED))
        self.page.update()

    def _vip_select_member(self,picker,member):
        picker["selected"]=member
        picker["results"].controls.clear()
        picker["results"].controls.append(ft.Row([
            self.styled_text(f"Selected: {member['name']}  ·  Member ID {member['id']}",13,True),
            self.small_button("Change",lambda:self._vip_clear_member(picker),70,self.GRAY)],wrap=True))
        if picker.get("on_select"):
            picker["on_select"](member)
        self.page.update()

    def _vip_clear_member(self,picker):
        picker["field"].value=""
        picker["selected"]=None
        self._vip_search_members(picker,picker["kind"])
        self.focus_control(picker["field"])

    def _vip_register(self,customer,plan,start,method):
        try:
            if not customer["selected"]: raise ValueError("Search for and select a customer.")
            customer_id=int(customer["selected"]["id"])
            price=self.manager.vip_price(plan.value)
            summary=f"VIP Registration\nMember: {customer['selected']['name']}\nPlan: VIP {plan.value}\nPrice: ₱{price:,.2f}\nStart: {start.value}\nMethod: {method.value}\n\nEnter your password to confirm payment and registration."
            def save():
                try:
                    mid,amount=self.manager.add_vip_membership(customer_id,plan.value,start.value)
                    pid=self.manager.record_payment(customer_id,mid,amount,date.today().isoformat(),"VIP membership registration",method=method.value,authorized=True)
                    self.vip_page(); self.show_receipt(pid)
                except Exception as e:self._vip_error("Unable to register VIP",e)
            self._confirm_with_password("Confirm VIP Registration",save,summary,"Authenticate & Register")
        except Exception as e:self._vip_error("Unable to register VIP",e)

    def _vip_upgrade(self,dd,method):
        try:
            if not dd["selected"]: raise ValueError("Search for and select an active Regular member.")
            membership_id=int(dd["selected"]["membership_id"])
            q=self.manager.vip_upgrade_quote(membership_id)
            m=q['membership']; name=self.db.get("customers",id=m['customer_id'])['full_name']
            summary=f"VIP Upgrade\nMember: {name}\nPlan: {q['plan']}\nRemaining days: {q['days']} of {q['membership_days']}\nVIP value for remaining days: ₱{q['vip_remaining_value']:,.2f}\nRegular value already paid: −₱{q['regular_remaining_value']:,.2f}\nAmount due: ₱{q['amount']:,.2f}\nMethod: {method.value}\n\nEnter your password to confirm."
            def save():
                try:
                    pid,_=self.manager.vip_upgrade(membership_id,date.today().isoformat(),method.value,authorized=True)
                    self.vip_page()
                    if pid:self.show_receipt(pid)
                    else:self.toast("Membership upgraded to VIP with no payment due.")
                except Exception as e:self._vip_error("Unable to upgrade membership",e)
            self._confirm_with_password("Confirm VIP Upgrade",save,summary,"Authenticate & Upgrade")
        except Exception as e:self._vip_error("Unable to upgrade membership",e)

    def _vip_save_prices(self,fields):
        try:
            values=[(name,float(field.value)) for name,field in fields]
            if any(value<0 for _,value in values):raise ValueError("Price cannot be negative.")
            current={name:self.manager.vip_price(name) for name in VIP_PLANS}
            changes=[(name,value) for name,value in values if current.get(name) is None or round(current[name],2)!=round(value,2)]
            if not changes:return self.toast("No VIP price changes to save.")
            summary="Save these VIP price changes?\n\n"+"\n".join(f"{name}: ₱{value:,.2f}" for name,value in changes)
            self.ask_yes_no("Confirm VIP Price Changes",summary,lambda:self._vip_apply_prices(changes))
        except Exception as e:self._vip_error("Unable to save prices",e)
    def _vip_save_training_rate(self,field):
        try:
            value=round(float(field.value),2)
            if value<=0:raise ValueError("The paid training rate must be greater than zero.")
            current=self.manager.vip_training_rate()
            if round(current,2)==value:return self.toast("No training rate changes to save.")
            self.ask_yes_no("Confirm Training Rate Change",f"Set the non-VIP personal-training price to ₱{value:,.2f} per session?",lambda:self._vip_apply_training_rate(value))
        except Exception as e:self._vip_error("Unable to save training rate",e)
    def _vip_apply_training_rate(self,value):
        try:
            self.manager.vip_set_training_rate(value)
            self.vip_page(); self.toast("Paid training rate saved.")
        except Exception as e:self._vip_error("Unable to save training rate",e)
    def _vip_apply_prices(self,values):
        try:
            for name,value in values:self.manager.vip_set_price(name,value)
            self.vip_page(); self.toast("VIP prices saved.")
        except Exception as e:self._vip_error("Unable to save prices",e)
    def _vip_save_benefits(self,fields):
        try:
            current={row['benefit_key']:bool(row['enabled']) for row in self.manager.vip_benefits()}
            changes=[(key,label,bool(cb.value)) for key,label,cb in fields if current.get(key)!=bool(cb.value)]
            if not changes:return self.toast("No VIP benefit changes to save.")
            summary="Apply these VIP benefit changes?\n\n"+"\n".join(f"{label}: {'Available' if enabled else 'Unavailable'}" for _,label,enabled in changes)
            self.ask_yes_no("Confirm VIP Benefit Changes",summary,lambda:self._vip_apply_benefits(changes))
        except Exception as e:self._vip_error("Unable to save benefits",e)
    def _vip_apply_benefits(self,changes):
        try:
            for key,_label,enabled in changes:self.manager.vip_set_benefit(key,enabled)
            self.vip_page(); self.toast("VIP benefit availability saved.")
        except Exception as e:self._vip_error("Unable to save benefits",e)
    def _vip_add_locker(self,f):
        try:self.manager.vip_add_locker(f.value); self.vip_page()
        except Exception as e:self._vip_error("Unable to add locker",e)
    def _vip_edit_locker(self,locker_id,current_label):
        field=ft.TextField(label="Locker label",value=current_label,width=300)
        dialog=ft.AlertDialog(modal=True,title=ft.Text("Edit Locker Label"),content=field)
        def continue_edit(_event=None):
            new_label=(field.value or "").strip()
            if not new_label:return self.show_error("Locker label required","Enter a locker label before saving.")
            self.close_dialog(dialog)
            self.ask_yes_no("Confirm Locker Label Change",f"Change locker label {current_label} to {new_label}? Any current assignment will remain attached to this locker.",lambda:self._vip_apply_locker_label(locker_id,new_label))
        dialog.actions=[self.button("Continue",continue_edit,100),self.button("Cancel",lambda:self.close_dialog(dialog),90,self.GRAY)]
        self.open_dialog(dialog)
    def _vip_apply_locker_label(self,locker_id,new_label):
        try:
            self.manager.vip_rename_locker(locker_id,new_label)
            self.vip_current_tab="Facilities"; self.vip_page(); self.toast("Locker label updated.")
        except Exception as e:self._vip_error("Unable to update locker label",e)
    def _vip_save_trainer(self,fields):
        try:
            day_order=("Mon","Tue","Wed","Thu","Fri","Sat","Sun")
            working_days=",".join(day for day in day_order if day in fields['days'])
            if not working_days:raise ValueError("Select at least one working day.")
            values=(fields['name'].value,fields['phone'].value,working_days,fields['from'].value,fields['to'].value)
            edit_id=getattr(self,"vip_trainer_edit_id",None)
            if edit_id:
                active=bool(self.db.get("vip_trainers",id=edit_id)["active"])
                self.manager.vip_update_trainer(edit_id,*values,active=active)
            else:
                self.manager.vip_add_trainer(*values[:5])
            self.vip_trainer_edit_id=None
            self.vip_trainer_draft={}
            self.vip_current_tab="Training"
            self.vip_page()
            self.toast("Trainer saved.")
        except Exception as e:self._vip_error("Unable to save trainer",e)
    def _vip_edit_trainer(self,trainer):
        self.vip_trainer_edit_id=trainer['id']
        self.vip_trainer_draft={key:trainer[key] for key in ("name","phone","working_days","available_from","available_to")}
        self.vip_current_tab="Training"
        self.vip_page()
    def _vip_cancel_trainer_edit(self):
        self.vip_trainer_edit_id=None
        self.vip_trainer_draft={}
        self.vip_current_tab="Training"
        self.vip_page()
    def _vip_toggle_trainer(self,trainer_id,active):
        def save():
            try:
                self.manager.vip_set_trainer_active(trainer_id,active)
                self.vip_current_tab="Training"
                self.vip_page()
            except Exception as e:self._vip_error("Unable to update trainer",e)
        if active:
            save()
        else:
            self.ask_yes_no("Deactivate Trainer","This trainer will no longer be available for new appointments. Existing sessions will remain in the schedule.",save)
    def _vip_assign(self,m,l):
        try:
            if not m["selected"] or not l.value:raise ValueError("Search for a member and choose an available locker.")
            self.manager.vip_assign_locker(int(m["selected"]["id"]),int(l.value)); self.vip_page()
        except Exception as e:self._vip_error("Unable to assign locker",e)
    def _vip_release(self,aid,locker_no,member_name):
        def release():
            try:self.manager.vip_release_locker(int(aid)); self.vip_current_tab="Facilities"; self.vip_page()
            except Exception as e:self._vip_error("Unable to release locker",e)
        self.ask_yes_no("Confirm Locker Release",f"Release locker {locker_no} from {member_name}? The locker will become available for reassignment.",release)
    def _vip_schedule(self,m,t,session_date,session_time,n,method):
        try:
            if not m["selected"] or not t.value:raise ValueError("Search for a member and choose a trainer.")
            start=datetime.strptime(f"{session_date.value.strip()} {session_time.value.strip()}",'%Y-%m-%d %H:%M').isoformat(timespec='minutes')
            customer_id=int(m["selected"]["id"]); trainer_id=int(t.value)
            if self.manager.vip_training_included(customer_id):
                self.manager.vip_schedule_training(customer_id,trainer_id,start,n.value or '')
                self.vip_current_tab="Training"; self.vip_page()
            else:
                fee=self.manager.vip_training_rate()
                if fee<=0:raise ValueError("The owner must set a paid training rate before non-VIP bookings can be made.")
                trainer=self.db.get("vip_trainers",id=trainer_id)
                summary=f"Paid Personal Training Booking\nMember: {m['selected']['name']}\nTrainer: {trainer['name']}\nStart: {start.replace('T',' ')}\nSession price: ₱{fee:,.2f}\nPayment method: {method.value}\n\nEnter your password to confirm the booking and payment."
                def save_paid_booking():
                    try:
                        _session_id,payment_id=self.manager.vip_schedule_paid_training(customer_id,trainer_id,start,n.value or '',method.value,authorized=True,expected_fee=fee)
                    except Exception as e:
                        return self._vip_error("Unable to book paid training",e)
                    try:
                        self.vip_current_tab="Training"; self.vip_page(); self.show_receipt(payment_id)
                    except Exception as e:self._vip_error("Booking saved, but unable to display the receipt",e)
                self._confirm_with_password("Confirm Paid Training",save_paid_booking,summary,"Authenticate & Book")
        except Exception as e:self._vip_error("Unable to book training",e)
    def _vip_training_status(self,sid,status):
        if status=="Cancelled":
            session=self.db.get("vip_training_sessions",id=sid)
            prompt="Cancel this scheduled personal training session?"
            if session and session['booking_type']=="Paid" and session['payment_id']:
                prompt+=" Its payment will remain recorded; void or refund it separately if appropriate."
            self.ask_yes_no("Confirm Session Cancellation",prompt,lambda:self._vip_apply_training_status(sid,status))
        else:
            self._vip_apply_training_status(sid,status)
    def _vip_apply_training_status(self,sid,status):
        try:self.manager.vip_training_status(int(sid),status); self.vip_current_tab="Training"; self.vip_page()
        except Exception as e:self._vip_error("Unable to update session",e)

