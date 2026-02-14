from datetime import date, timedelta

import streamlit as st

from models import (
    ChildAttendance,
    Employee,
    Group,
    KitaSettings,
    Schedule,
    Shift,
    get_session,
)

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _time_slots(open_time: str, close_time: str):
    """Generate 30-minute time slot labels from open to close."""
    oh, om = map(int, open_time.split(":"))
    ch, cm = map(int, close_time.split(":"))
    start = oh * 60 + om
    end = ch * 60 + cm
    slots = []
    t = start
    while t < end:
        h, m = divmod(t, 60)
        slots.append(f"{h:02d}:{m:02d}")
        t += 30
    return slots


def _time_to_min(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _required_staff(session, group: Group, weekday: int) -> int:
    """Calculate required staff for a group on a given weekday based on child attendance and ratio."""
    att = session.query(ChildAttendance).filter_by(
        group_id=group.id, weekday=weekday
    ).first()
    if not att:
        return 0
    children = att.expected_children
    if children <= 0:
        return 0
    import math
    return math.ceil(children * group.ratio_num / group.ratio_den)


def _coverage_info(session, schedule_id: int, group: Group, weekday: int):
    """Return (assigned_count, required_count) for a group on a weekday."""
    required = _required_staff(session, group, weekday)
    assigned = session.query(Shift).filter_by(
        schedule_id=schedule_id, group_id=group.id, weekday=weekday
    ).count()
    return assigned, required


def _build_grid_html(session, schedule: Schedule, kita: KitaSettings, groups):
    """Build the HTML schedule grid table."""
    slots = _time_slots(kita.open_time, kita.close_time)
    core_start = _time_to_min(kita.core_start)
    core_end = _time_to_min(kita.core_end)

    # Load all shifts for this schedule, organized by (weekday, slot)
    all_shifts = session.query(Shift).filter_by(schedule_id=schedule.id).all()

    # Map: (weekday) -> list of shifts
    shifts_by_day = {}
    for s in all_shifts:
        shifts_by_day.setdefault(s.weekday, []).append(s)

    # Load employees and groups for display
    emp_map = {}
    for s in all_shifts:
        if s.employee_id not in emp_map:
            emp = session.query(Employee).get(s.employee_id)
            if emp:
                emp_map[s.employee_id] = emp

    grp_map = {g.id: g for g in groups}

    html = '<table class="schedule-grid"><thead><tr><th>Zeit</th>'
    for day_name in WEEKDAYS_DE:
        html += f"<th>{day_name}</th>"
    html += "</tr></thead><tbody>"

    for slot_time in slots:
        slot_min = _time_to_min(slot_time)
        is_core = core_start <= slot_min < core_end
        row_bg = "background:#1a2744;" if is_core else ""

        html += f'<tr style="{row_bg}">'
        html += f'<td class="time-col">{slot_time}</td>'

        for weekday in range(5):
            day_shifts = shifts_by_day.get(weekday, [])
            cell_content = ""

            for s in day_shifts:
                s_start = _time_to_min(s.start_time)
                s_end = _time_to_min(s.end_time)

                # Show shift block in the starting slot
                if s_start == slot_min:
                    emp = emp_map.get(s.employee_id)
                    grp = grp_map.get(s.group_id) if s.group_id else None
                    area_cls = "shift-krippe" if (grp and grp.area == "krippe") else "shift-elementar"
                    emp_name = emp.full_name if emp else "?"
                    grp_name = grp.name if grp else "—"
                    span_slots = max(1, (s_end - s_start) // 30)

                    cell_content += (
                        f'<div class="shift-block {area_cls}" '
                        f'title="{emp_name} | {grp_name} | {s.start_time}-{s.end_time}">'
                        f"{emp_name[:15]}<br>"
                        f"<small>{grp_name} {s.start_time}-{s.end_time}</small>"
                        f"</div>"
                    )

                # Show break indicator
                if s.break_start:
                    b_start = _time_to_min(s.break_start)
                    if b_start == slot_min:
                        emp = emp_map.get(s.employee_id)
                        emp_name = emp.full_name if emp else "?"
                        cell_content += (
                            f'<div class="shift-block shift-break" '
                            f'title="Pause: {emp_name}">'
                            f"<small>Pause {s.break_minutes}min</small></div>"
                        )

            html += f"<td>{cell_content}</td>"
        html += "</tr>"

    # Coverage summary row
    html += '<tr><td class="time-col" style="font-weight:600">Personal</td>'
    for weekday in range(5):
        coverage_parts = []
        for g in groups:
            if not g.is_active:
                continue
            assigned, required = _coverage_info(session, schedule.id, g, weekday)
            if required == 0:
                continue
            pct = (assigned / required * 100) if required > 0 else 100
            color_cls = "coverage-ok" if pct >= 100 else ("coverage-warn" if pct >= 75 else "coverage-bad")
            coverage_parts.append(
                f'<div style="margin:2px 0">'
                f'<small>{g.name}: {assigned}/{required}</small>'
                f'<div class="coverage-bar">'
                f'<div class="coverage-fill {color_cls}" style="width:{min(pct, 100):.0f}%"></div>'
                f"</div></div>"
            )
        html += f'<td>{"".join(coverage_parts)}</td>'
    html += "</tr>"

    html += "</tbody></table>"
    return html


def show_schedule(user: dict, editable: bool = True):
    session = get_session()
    try:
        kita = session.query(KitaSettings).first()
        if not kita:
            st.warning("Bitte zuerst Kita-Einstellungen anlegen.")
            return

        groups = session.query(Group).filter_by(is_active=True).order_by(Group.area, Group.name).all()
        if not groups:
            st.warning("Bitte zuerst Gruppen anlegen.")
            return

        # --- Week picker ---
        st.markdown('<div class="section-hdr">Wochendienstplan</div>', unsafe_allow_html=True)

        today = date.today()
        current_monday = _monday_of(today)

        c1, c2, c3 = st.columns([1, 3, 1])
        with c1:
            if st.button("< Vorherige Woche"):
                week_offset = st.session_state.get("week_offset", 0) - 1
                st.session_state["week_offset"] = week_offset
                st.rerun()
        with c3:
            if st.button("Nächste Woche >"):
                week_offset = st.session_state.get("week_offset", 0) + 1
                st.session_state["week_offset"] = week_offset
                st.rerun()

        week_offset = st.session_state.get("week_offset", 0)
        view_monday = current_monday + timedelta(weeks=week_offset)
        view_friday = view_monday + timedelta(days=4)

        with c2:
            st.markdown(
                f"<div style='text-align:center; font-size:1.2rem; font-weight:600;'>"
                f"KW {view_monday.isocalendar()[1]} — "
                f"{view_monday.strftime('%d.%m.%Y')} bis {view_friday.strftime('%d.%m.%Y')}"
                f"</div>",
                unsafe_allow_html=True,
            )

        # Get or create schedule for this week
        schedule = session.query(Schedule).filter_by(week_start=view_monday).first()
        if not schedule:
            schedule = Schedule(week_start=view_monday, status="draft")
            session.add(schedule)
            session.commit()

        # Status badge
        status_colors = {"draft": "#EAB308", "published": "#22C55E", "archived": "#6B7280"}
        status_labels = {"draft": "Entwurf", "published": "Veröffentlicht", "archived": "Archiviert"}
        status_color = status_colors.get(schedule.status, "#6B7280")
        status_label = status_labels.get(schedule.status, schedule.status)
        st.markdown(
            f'<span style="background:{status_color};color:#0F172A;padding:2px 10px;'
            f'border-radius:4px;font-size:0.85rem;font-weight:600;">{status_label}</span>',
            unsafe_allow_html=True,
        )

        # --- Grid ---
        grid_html = _build_grid_html(session, schedule, kita, groups)
        st.markdown(grid_html, unsafe_allow_html=True)

        # --- Shift list (visible to all) ---
        shifts = (
            session.query(Shift)
            .filter_by(schedule_id=schedule.id)
            .order_by(Shift.weekday, Shift.start_time)
            .all()
        )

        employees = session.query(Employee).filter_by(is_active=True).order_by(
            Employee.last_name
        ).all()
        emp_options = {e.id: e.full_name for e in employees}
        grp_options = {g.id: g.name for g in groups}

        if shifts:
            st.markdown('<div class="section-hdr">Schichtübersicht</div>', unsafe_allow_html=True)
            shift_rows = []
            for s in shifts:
                emp = emp_options.get(s.employee_id, "?")
                grp = grp_options.get(s.group_id, "—") if s.group_id else "—"
                shift_rows.append({
                    "Tag": WEEKDAYS_DE[s.weekday],
                    "Mitarbeiter": emp,
                    "Gruppe": grp,
                    "Von": s.start_time,
                    "Bis": s.end_time,
                    "Pause": f"{s.break_minutes} min" if s.break_minutes else "—",
                })
            st.dataframe(shift_rows, use_container_width=True, hide_index=True)

        # --- Admin-only: Shift editing ---
        if not editable:
            st.caption("Nur Administratoren können Schichten bearbeiten.")
        else:
            # --- Edit existing shift ---
            if shifts:
                st.markdown('<div class="section-hdr">Schicht bearbeiten</div>',
                            unsafe_allow_html=True)
                shift_options = {
                    s.id: f"{WEEKDAYS_DE[s.weekday]} | {emp_options.get(s.employee_id, '?')} | {s.start_time}-{s.end_time}"
                    for s in shifts
                }
                selected_shift_id = st.selectbox(
                    "Schicht auswählen",
                    list(shift_options.keys()),
                    format_func=lambda k: shift_options[k],
                    key="edit_shift_select",
                )

                shift = session.query(Shift).get(selected_shift_id)
                if shift:
                    with st.form("edit_shift"):
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            edit_day = st.selectbox(
                                "Tag", list(range(5)),
                                index=shift.weekday,
                                format_func=lambda i: WEEKDAYS_DE[i],
                            )
                            edit_emp = st.selectbox(
                                "Mitarbeiter", list(emp_options.keys()),
                                index=list(emp_options.keys()).index(shift.employee_id)
                                if shift.employee_id in emp_options else 0,
                                format_func=lambda k: emp_options[k],
                            )
                        with c2:
                            edit_start = st.text_input("Beginn", value=shift.start_time)
                            edit_end = st.text_input("Ende", value=shift.end_time)
                        with c3:
                            edit_grp = st.selectbox(
                                "Gruppe",
                                [None] + list(grp_options.keys()),
                                index=([None] + list(grp_options.keys())).index(shift.group_id)
                                if shift.group_id in grp_options else 0,
                                format_func=lambda k: grp_options.get(k, "Keine Zuordnung") if k else "Keine Zuordnung",
                            )
                            edit_break = st.number_input(
                                "Pause (min)", min_value=0, max_value=60,
                                value=shift.break_minutes or 0, step=15,
                            )

                        fc1, fc2 = st.columns(2)
                        with fc1:
                            save = st.form_submit_button("Speichern", use_container_width=True)
                        with fc2:
                            delete = st.form_submit_button("Schicht löschen", use_container_width=True)

                        if save:
                            shift.weekday = edit_day
                            shift.employee_id = edit_emp
                            shift.group_id = edit_grp
                            shift.start_time = edit_start.strip()
                            shift.end_time = edit_end.strip()
                            shift.break_minutes = edit_break
                            shift.is_manual = True
                            session.commit()
                            st.success("Schicht aktualisiert.")
                            st.rerun()
                        elif delete:
                            session.delete(shift)
                            session.commit()
                            st.success("Schicht gelöscht.")
                            st.rerun()

            # --- Create new shift ---
            st.markdown('<div class="section-hdr">Neue Schicht anlegen</div>',
                        unsafe_allow_html=True)

            with st.form("create_shift", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    new_day = st.selectbox(
                        "Tag", list(range(5)),
                        format_func=lambda i: WEEKDAYS_DE[i],
                        key="new_shift_day",
                    )
                    new_emp = st.selectbox(
                        "Mitarbeiter", list(emp_options.keys()),
                        format_func=lambda k: emp_options[k],
                        key="new_shift_emp",
                    )
                with c2:
                    new_start = st.text_input("Beginn", value="08:00", key="new_shift_start")
                    new_end = st.text_input("Ende", value="16:00", key="new_shift_end")
                with c3:
                    new_grp = st.selectbox(
                        "Gruppe",
                        [None] + list(grp_options.keys()),
                        format_func=lambda k: grp_options.get(k, "Keine Zuordnung") if k else "Keine Zuordnung",
                        key="new_shift_grp",
                    )
                    new_break = st.number_input(
                        "Pause (min)", min_value=0, max_value=60, value=30, step=15,
                        key="new_shift_break",
                    )

                if st.form_submit_button("Schicht anlegen", use_container_width=True):
                    if not emp_options:
                        st.error("Keine aktiven Mitarbeiter vorhanden.")
                    else:
                        s_min = _time_to_min(new_start.strip())
                        e_min = _time_to_min(new_end.strip())
                        mid = (s_min + e_min) // 2
                        mid_h, mid_m = divmod(mid, 60)
                        mid_m = (mid_m // 30) * 30
                        break_start = f"{mid_h:02d}:{mid_m:02d}" if new_break > 0 else None

                        new_shift = Shift(
                            schedule_id=schedule.id,
                            employee_id=new_emp,
                            group_id=new_grp,
                            weekday=new_day,
                            start_time=new_start.strip(),
                            end_time=new_end.strip(),
                            break_start=break_start,
                            break_minutes=new_break,
                            is_manual=True,
                        )
                        session.add(new_shift)
                        session.commit()
                        st.success("Schicht angelegt.")
                        st.rerun()

            # --- Schedule status actions ---
            st.markdown('<div class="section-hdr">Status</div>', unsafe_allow_html=True)

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                if schedule.status != "published":
                    if st.button("Veröffentlichen", use_container_width=True):
                        from datetime import datetime, timezone
                        schedule.status = "published"
                        schedule.published_at = datetime.now(timezone.utc)
                        session.commit()
                        st.success("Dienstplan veröffentlicht.")
                        st.rerun()
            with sc2:
                if schedule.status == "published":
                    if st.button("Zurück zu Entwurf", use_container_width=True):
                        schedule.status = "draft"
                        schedule.published_at = None
                        session.commit()
                        st.success("Status auf Entwurf zurückgesetzt.")
                        st.rerun()
            with sc3:
                if schedule.status != "archived":
                    if st.button("Archivieren", use_container_width=True):
                        schedule.status = "archived"
                        session.commit()
                        st.success("Dienstplan archiviert.")
                        st.rerun()

    finally:
        session.close()
