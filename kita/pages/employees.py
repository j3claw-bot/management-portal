from datetime import date

import streamlit as st

from models import Absence, Employee, EmployeeRestriction, Shift, Schedule, get_session

ROLES = {"erstkraft": "Erstkraft", "zweitkraft": "Zweitkraft"}
AREAS = {"krippe": "Krippe", "elementar": "Elementar", "both": "Krippe & Elementar"}

RESTRICTION_TYPES = {
    "no_early_shift": "Kein Frühdienst",
    "no_late_shift": "Kein Spätdienst",
    "fixed_day_off": "Fester freier Tag",
    "max_consecutive_days": "Max. aufeinanderfolgende Tage",
    "only_area": "Nur bestimmter Bereich",
    "fixed_schedule": "Fester Dienstplan",
    "prefers_early": "Bevorzugt Frühdienst",
    "prefers_late": "Bevorzugt Spätdienst",
    "prefers_colleague": "Bevorzugt Zusammenarbeit mit",
}

ABSENCE_TYPES = {
    "urlaub": "Urlaub",
    "krank": "Krank",
    "fortbildung": "Fortbildung",
    "sonstig": "Sonstig",
}

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


def _calc_weekly_hours(session, employee_id):
    """Calculate total scheduled hours for the current/latest week."""
    latest = session.query(Schedule).order_by(Schedule.week_start.desc()).first()
    if not latest:
        return 0.0
    shifts = session.query(Shift).filter_by(
        schedule_id=latest.id, employee_id=employee_id
    ).all()
    total = 0.0
    for s in shifts:
        start_h, start_m = map(int, s.start_time.split(":"))
        end_h, end_m = map(int, s.end_time.split(":"))
        hours = (end_h * 60 + end_m - start_h * 60 - start_m - s.break_minutes) / 60
        total += max(0, hours)
    return total


def show_employees(user: dict):
    st.markdown('<div class="section-hdr">Mitarbeiterverwaltung</div>', unsafe_allow_html=True)

    session = get_session()
    try:
        # --- Employee list ---
        show_inactive = st.checkbox("Archivierte anzeigen", value=False)
        query = session.query(Employee)
        if not show_inactive:
            query = query.filter_by(is_active=True)
        employees = query.order_by(Employee.last_name, Employee.first_name).all()

        if employees:
            # Check current absences for badge
            today = date.today()
            absent_ids = set()
            current_absences = (
                session.query(Absence)
                .filter(Absence.start_date <= today, Absence.end_date >= today)
                .all()
            )
            for a in current_absences:
                absent_ids.add(a.employee_id)

            rows = []
            for emp in employees:
                scheduled = _calc_weekly_hours(session, emp.id)
                restrictions = [RESTRICTION_TYPES.get(r.restriction_type, r.restriction_type)
                                for r in emp.restrictions]
                status = "Abwesend" if emp.id in absent_ids else ("Aktiv" if emp.is_active else "Archiviert")
                rows.append({
                    "ID": emp.id,
                    "Name": emp.full_name,
                    "Rolle": ROLES.get(emp.role, emp.role),
                    "Bereich": AREAS.get(emp.area, emp.area),
                    "Vertrag (h/Wo)": emp.contract_hours,
                    "Tage/Wo": emp.days_per_week,
                    "Geplant (h)": round(scheduled, 1),
                    "Einschränkungen": ", ".join(restrictions) if restrictions else "—",
                    "Status": status,
                })

            st.dataframe(rows, use_container_width=True, hide_index=True)

            # Hours progress bars
            st.markdown('<div class="section-hdr">Stundenübersicht (aktuelle Woche)</div>',
                        unsafe_allow_html=True)
            for emp in employees:
                if not emp.is_active:
                    continue
                scheduled = _calc_weekly_hours(session, emp.id)
                pct = min(scheduled / emp.contract_hours, 1.0) if emp.contract_hours > 0 else 0
                col_name, col_bar = st.columns([2, 5])
                with col_name:
                    absent_tag = " (abwesend)" if emp.id in absent_ids else ""
                    st.text(f"{emp.full_name}{absent_tag}")
                with col_bar:
                    st.progress(pct, text=f"{scheduled:.1f} / {emp.contract_hours:.1f} h")
        else:
            st.info("Keine Mitarbeiter vorhanden.")

        # --- Create employee ---
        st.markdown('<div class="section-hdr">Neuen Mitarbeiter anlegen</div>', unsafe_allow_html=True)

        with st.form("create_employee", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                new_first = st.text_input("Vorname")
                new_role = st.selectbox("Rolle", list(ROLES.keys()), format_func=lambda k: ROLES[k])
                new_hours = st.number_input("Vertragsstunden/Woche", min_value=5.0, max_value=42.0,
                                            value=39.0, step=0.5)
            with c2:
                new_last = st.text_input("Nachname")
                new_area = st.selectbox("Bereich", list(AREAS.keys()), format_func=lambda k: AREAS[k])
                new_days = st.number_input("Tage/Woche", min_value=1, max_value=5, value=5)

            if st.form_submit_button("Anlegen", use_container_width=True):
                if not new_first or not new_last:
                    st.error("Vor- und Nachname sind Pflichtfelder.")
                else:
                    emp = Employee(
                        first_name=new_first.strip(),
                        last_name=new_last.strip(),
                        role=new_role,
                        area=new_area,
                        contract_hours=new_hours,
                        days_per_week=new_days,
                    )
                    session.add(emp)
                    session.commit()
                    st.success(f"{emp.full_name} wurde angelegt.")
                    st.rerun()

        # --- Edit employee ---
        if employees:
            st.markdown('<div class="section-hdr">Mitarbeiter bearbeiten</div>', unsafe_allow_html=True)

            emp_options = {emp.id: emp.full_name for emp in employees}
            selected_id = st.selectbox(
                "Mitarbeiter auswählen",
                list(emp_options.keys()),
                format_func=lambda k: emp_options[k],
                key="edit_emp_select",
            )

            emp = session.query(Employee).get(selected_id)
            if emp:
                with st.form("edit_employee"):
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_first = st.text_input("Vorname", value=emp.first_name)
                        edit_role = st.selectbox(
                            "Rolle", list(ROLES.keys()),
                            index=list(ROLES.keys()).index(emp.role),
                            format_func=lambda k: ROLES[k],
                        )
                        edit_hours = st.number_input(
                            "Vertragsstunden/Woche", min_value=5.0, max_value=42.0,
                            value=emp.contract_hours, step=0.5,
                        )
                    with c2:
                        edit_last = st.text_input("Nachname", value=emp.last_name)
                        edit_area = st.selectbox(
                            "Bereich", list(AREAS.keys()),
                            index=list(AREAS.keys()).index(emp.area),
                            format_func=lambda k: AREAS[k],
                        )
                        edit_days = st.number_input(
                            "Tage/Woche", min_value=1, max_value=5, value=emp.days_per_week,
                        )

                    edit_active = st.checkbox("Aktiv", value=emp.is_active)

                    if st.form_submit_button("Speichern", use_container_width=True):
                        emp.first_name = edit_first.strip()
                        emp.last_name = edit_last.strip()
                        emp.role = edit_role
                        emp.area = edit_area
                        emp.contract_hours = edit_hours
                        emp.days_per_week = edit_days
                        emp.is_active = edit_active
                        session.commit()
                        st.success(f"{emp.full_name} wurde aktualisiert.")
                        st.rerun()

                # --- Absences for selected employee ---
                st.markdown(f'<div class="section-hdr">Abwesenheiten — {emp.full_name}</div>',
                            unsafe_allow_html=True)

                absences = (
                    session.query(Absence)
                    .filter_by(employee_id=emp.id)
                    .order_by(Absence.start_date.desc())
                    .all()
                )

                if absences:
                    abs_rows = []
                    for a in absences:
                        is_current = a.start_date <= today <= a.end_date
                        abs_rows.append({
                            "Typ": ABSENCE_TYPES.get(a.absence_type, a.absence_type),
                            "Von": a.start_date.strftime("%d.%m.%Y"),
                            "Bis": a.end_date.strftime("%d.%m.%Y"),
                            "Notiz": a.note or "—",
                            "Status": "Aktiv" if is_current else ("Vergangen" if a.end_date < today else "Geplant"),
                        })
                    st.dataframe(abs_rows, use_container_width=True, hide_index=True)

                    # Delete buttons
                    for a in absences:
                        label = (
                            f"{ABSENCE_TYPES.get(a.absence_type, a.absence_type)} "
                            f"{a.start_date.strftime('%d.%m.')}–{a.end_date.strftime('%d.%m.%Y')}"
                        )
                        if st.button(f"Löschen: {label}", key=f"del_abs_{a.id}"):
                            session.delete(a)
                            session.commit()
                            st.rerun()
                else:
                    st.caption("Keine Abwesenheiten eingetragen.")

                with st.form("add_absence", clear_on_submit=True):
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        abs_type = st.selectbox(
                            "Typ", list(ABSENCE_TYPES.keys()),
                            format_func=lambda k: ABSENCE_TYPES[k],
                        )
                        abs_start = st.date_input("Von", value=today)
                    with ac2:
                        abs_note = st.text_input("Notiz (optional)")
                        abs_end = st.date_input("Bis", value=today)

                    if st.form_submit_button("Abwesenheit eintragen", use_container_width=True):
                        if abs_end < abs_start:
                            st.error("Das Enddatum muss nach dem Startdatum liegen.")
                        else:
                            session.add(Absence(
                                employee_id=emp.id,
                                start_date=abs_start,
                                end_date=abs_end,
                                absence_type=abs_type,
                                note=abs_note.strip() or None,
                            ))
                            session.commit()
                            st.success(
                                f"Abwesenheit eingetragen: {ABSENCE_TYPES[abs_type]} "
                                f"{abs_start.strftime('%d.%m.')}–{abs_end.strftime('%d.%m.%Y')}"
                            )
                            st.rerun()

                # --- Restrictions for selected employee ---
                st.markdown(f'<div class="section-hdr">Einschränkungen — {emp.full_name}</div>',
                            unsafe_allow_html=True)

                restrictions = session.query(EmployeeRestriction).filter_by(
                    employee_id=emp.id
                ).all()

                if restrictions:
                    for r in restrictions:
                        rc1, rc2, rc3 = st.columns([3, 3, 1])
                        with rc1:
                            st.text(RESTRICTION_TYPES.get(r.restriction_type, r.restriction_type))
                        with rc2:
                            st.text(r.value)
                        with rc3:
                            if st.button("Entfernen", key=f"del_r_{r.id}"):
                                session.delete(r)
                                session.commit()
                                st.rerun()
                else:
                    st.caption("Keine Einschränkungen vorhanden.")

                with st.form("add_restriction", clear_on_submit=True):
                    r_c1, r_c2 = st.columns(2)
                    with r_c1:
                        r_type = st.selectbox(
                            "Typ", list(RESTRICTION_TYPES.keys()),
                            format_func=lambda k: RESTRICTION_TYPES[k],
                        )
                    with r_c2:
                        if r_type == "fixed_day_off":
                            r_value = st.selectbox("Wert", WEEKDAYS_DE)
                        elif r_type == "max_consecutive_days":
                            r_value = str(st.number_input("Wert", min_value=1, max_value=5, value=4))
                        elif r_type == "only_area":
                            r_value = st.selectbox("Wert", ["krippe", "elementar"],
                                                   format_func=lambda k: AREAS.get(k, k))
                        elif r_type == "prefers_colleague":
                            other_emps = [e for e in employees if e.id != emp.id]
                            if other_emps:
                                r_value = st.selectbox(
                                    "Kolleg/in",
                                    [e.id for e in other_emps],
                                    format_func=lambda eid: next(
                                        (e.full_name for e in other_emps if e.id == eid), "?"),
                                )
                                r_value = str(r_value)
                            else:
                                r_value = st.text_input("Mitarbeiter-ID")
                        elif r_type in ("prefers_early", "prefers_late"):
                            r_value = "true"
                            st.caption("Wird beim Auto-Dienstplan berücksichtigt.")
                        else:
                            r_value = st.text_input("Wert", value="true")

                    if st.form_submit_button("Einschränkung hinzufügen", use_container_width=True):
                        session.add(EmployeeRestriction(
                            employee_id=emp.id,
                            restriction_type=r_type,
                            value=str(r_value),
                        ))
                        session.commit()
                        st.success("Einschränkung hinzugefügt.")
                        st.rerun()
    finally:
        session.close()
