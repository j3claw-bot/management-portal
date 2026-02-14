import re
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from models import (
    Absence,
    ChildAttendance,
    Employee,
    Group,
    KitaSettings,
    Schedule,
    Shift,
    get_session,
)
from engine.scheduler import generate_schedule, apply_schedule
from engine.scoring import score_color, score_label
from engine.constraints import validate_schedule, shift_duration_hours

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _time_slots(open_time: str, close_time: str):
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


def _valid_time(t: str) -> bool:
    return bool(TIME_RE.match(t.strip()))


def _required_staff(session, group: Group, weekday: int) -> int:
    att = session.query(ChildAttendance).filter_by(
        group_id=group.id, weekday=weekday
    ).first()
    if not att or att.expected_children <= 0:
        return 0
    import math
    return math.ceil(att.expected_children * group.ratio_num / group.ratio_den)


def _absent_employee_ids(session, week_monday: date) -> dict[int, set[int]]:
    week_friday = week_monday + timedelta(days=4)
    absences = (
        session.query(Absence)
        .filter(Absence.start_date <= week_friday, Absence.end_date >= week_monday)
        .all()
    )
    result = {d: set() for d in range(5)}
    for a in absences:
        for day_offset in range(5):
            day_date = week_monday + timedelta(days=day_offset)
            if a.start_date <= day_date <= a.end_date:
                result[day_offset].add(a.employee_id)
    return result


def _coverage_info(session, schedule_id: int, group: Group, weekday: int):
    required = _required_staff(session, group, weekday)
    assigned = session.query(Shift).filter_by(
        schedule_id=schedule_id, group_id=group.id, weekday=weekday
    ).count()
    return assigned, required


def _build_grid_html(session, schedule: Schedule, kita: KitaSettings, groups):
    slots = _time_slots(kita.open_time, kita.close_time)
    core_start = _time_to_min(kita.core_start)
    core_end = _time_to_min(kita.core_end)

    all_shifts = session.query(Shift).filter_by(schedule_id=schedule.id).all()

    shifts_by_day = {}
    for s in all_shifts:
        shifts_by_day.setdefault(s.weekday, []).append(s)

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

                if s_start == slot_min:
                    emp = emp_map.get(s.employee_id)
                    grp = grp_map.get(s.group_id) if s.group_id else None
                    area_cls = "shift-krippe" if (grp and grp.area == "krippe") else "shift-elementar"
                    emp_name = emp.full_name if emp else "?"
                    grp_name = grp.name if grp else "—"
                    role_badge = "[E]" if emp and emp.role == "erstkraft" else "[Z]"
                    manual_tag = " *" if s.is_manual else ""

                    cell_content += (
                        f'<div class="shift-block {area_cls}" '
                        f'title="{emp_name} | {grp_name} | {s.start_time}-{s.end_time}{manual_tag}">'
                        f"<small style='opacity:0.7'>{role_badge}</small> {emp_name[:15]}<br>"
                        f"<small>{grp_name} {s.start_time}-{s.end_time}</small>"
                        f"</div>"
                    )

                if s.break_start:
                    b_start = _time_to_min(s.break_start)
                    if b_start == slot_min:
                        cell_content += (
                            f'<div class="shift-block shift-break">'
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
    html += "</tr></tbody></table>"
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
                st.session_state["week_offset"] = st.session_state.get("week_offset", 0) - 1
                st.rerun()
        with c3:
            if st.button("Nächste Woche >"):
                st.session_state["week_offset"] = st.session_state.get("week_offset", 0) + 1
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

        # --- Absences ---
        absent_by_day = _absent_employee_ids(session, view_monday)
        all_absent_this_week = set()
        for ids in absent_by_day.values():
            all_absent_this_week |= ids

        # --- Grid ---
        grid_html = _build_grid_html(session, schedule, kita, groups)
        st.markdown(grid_html, unsafe_allow_html=True)

        # Absent employees banner
        if all_absent_this_week:
            absent_emps = session.query(Employee).filter(Employee.id.in_(all_absent_this_week)).all()
            absent_names = []
            for emp in absent_emps:
                days = [WEEKDAYS_DE[d][:2] for d in range(5) if emp.id in absent_by_day[d]]
                abs_record = (
                    session.query(Absence)
                    .filter(
                        Absence.employee_id == emp.id,
                        Absence.start_date <= view_friday,
                        Absence.end_date >= view_monday,
                    )
                    .first()
                )
                abs_type = {"urlaub": "Urlaub", "krank": "Krank", "fortbildung": "Fortb.", "sonstig": "Sonst."}.get(
                    abs_record.absence_type, "?"
                ) if abs_record else "?"
                absent_names.append(f"{emp.full_name} ({abs_type}, {', '.join(days)})")

            st.markdown(
                '<div style="background:#78350F;border-radius:6px;padding:8px 12px;margin:8px 0;'
                'color:#FCD34D;font-size:0.85rem;">'
                f'<strong>Abwesend:</strong> {" | ".join(absent_names)}'
                '</div>',
                unsafe_allow_html=True,
            )

        # --- Score cards (4 columns) ---
        has_scores = schedule.score_coverage > 0 or schedule.score_fairness > 0
        if has_scores:
            sc1, sc2, sc3, sc4 = st.columns(4)
            for col, label, val in [
                (sc1, "Abdeckung", schedule.score_coverage),
                (sc2, "Fairness", schedule.score_fairness),
                (sc3, "Präferenzen", schedule.score_preference),
                (sc4, "Compliance", schedule.score_compliance),
            ]:
                with col:
                    color = score_color(val)
                    st.markdown(
                        f'<div style="background:#1E293B;border-radius:8px;padding:8px 12px;text-align:center;">'
                        f'<div style="color:#94A3B8;font-size:0.7rem;text-transform:uppercase;">{label}</div>'
                        f'<div style="color:{color};font-size:1.4rem;font-weight:700;">{val}%</div>'
                        f'<div style="color:#64748B;font-size:0.7rem;">{score_label(val)}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        # --- Constraint validation panel ---
        shifts_exist = session.query(Shift).filter_by(schedule_id=schedule.id).count() > 0
        if shifts_exist:
            violations = validate_schedule(session, schedule.id, view_monday, groups, kita)
            if violations:
                v_html = "".join(f"<li>{v}</li>" for v in violations)
                st.markdown(
                    f'<div style="background:#7F1D1D;border-radius:8px;padding:0.8rem 1rem;'
                    f'margin:0.5rem 0;color:#FCA5A5;">'
                    f'<div style="font-weight:600;margin-bottom:4px;">&#9888; {len(violations)} Regelverletzung(en)</div>'
                    f'<ul style="margin:0;padding-left:1.2rem;font-size:0.85rem;">{v_html}</ul>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div style="background:#14532D;border-radius:8px;padding:0.6rem 1rem;'
                    'margin:0.5rem 0;color:#86EFAC;font-size:0.9rem;">'
                    '&#10003; Alle Regeln eingehalten — keine Verletzungen.</div>',
                    unsafe_allow_html=True,
                )

        # --- Auto-generate (admin only, draft only) ---
        if editable and schedule.status == "draft":
            st.markdown('<div class="section-hdr">Automatische Planung</div>',
                        unsafe_allow_html=True)

            gen_c1, gen_c2, gen_c3 = st.columns([3, 1, 1])
            with gen_c1:
                st.caption(
                    "Erstellt einen Dienstplan basierend auf verfügbaren Mitarbeitern, "
                    "Betreuungsschlüsseln, Abwesenheiten und Präferenzen. "
                    "Manuell erstellte Schichten bleiben erhalten."
                )

            # Preview mode: generate without applying
            with gen_c2:
                if st.button("Vorschau", use_container_width=True):
                    with st.spinner("Berechne..."):
                        preview = generate_schedule(session, view_monday)
                    st.session_state["schedule_preview"] = preview

            with gen_c3:
                if st.button("Generieren & Anwenden", use_container_width=True, type="primary"):
                    with st.spinner("Plane Schichten..."):
                        result = generate_schedule(session, view_monday)
                        apply_schedule(session, schedule, result)
                    if result["warnings"]:
                        for w in result["warnings"]:
                            st.warning(w)
                    else:
                        st.success("Dienstplan erfolgreich generiert.")
                    st.session_state.pop("schedule_preview", None)
                    st.rerun()

            # Show preview if available
            preview = st.session_state.get("schedule_preview")
            if preview:
                st.markdown(
                    '<div style="background:#1E293B;border-radius:8px;padding:1rem;margin:0.5rem 0;">',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div style="font-weight:600;color:#A5B4FC;margin-bottom:8px;">'
                    f'Vorschau: {len(preview["shifts"])} Schichten</div>',
                    unsafe_allow_html=True,
                )

                # Preview scores
                pv1, pv2, pv3, pv4 = st.columns(4)
                for col, label, val in [
                    (pv1, "Abdeckung", preview["scores"]["coverage"]),
                    (pv2, "Fairness", preview["scores"]["fairness"]),
                    (pv3, "Präferenzen", preview["scores"]["preference"]),
                    (pv4, "Compliance", preview["scores"]["compliance"]),
                ]:
                    with col:
                        color = score_color(val)
                        st.markdown(
                            f'<div style="text-align:center;">'
                            f'<span style="color:#94A3B8;font-size:0.7rem;">{label}</span><br>'
                            f'<span style="color:{color};font-size:1.2rem;font-weight:700;">{val}%</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                if preview["warnings"]:
                    for w in preview["warnings"]:
                        st.warning(w)
                else:
                    st.success("Keine Warnungen — alle Gruppen sind besetzbar.")

                st.markdown('</div>', unsafe_allow_html=True)

            # --- Copy from previous week ---
            prev_monday = view_monday - timedelta(weeks=1)
            prev_schedule = session.query(Schedule).filter_by(week_start=prev_monday).first()
            if prev_schedule:
                prev_shift_count = session.query(Shift).filter_by(schedule_id=prev_schedule.id).count()
                if prev_shift_count > 0:
                    if st.button(
                        f"Vorwoche kopieren (KW {prev_monday.isocalendar()[1]}, {prev_shift_count} Schichten)",
                        use_container_width=True,
                    ):
                        # Delete existing auto shifts
                        session.query(Shift).filter_by(
                            schedule_id=schedule.id, is_manual=False
                        ).delete()
                        # Copy shifts from previous week
                        prev_shifts = session.query(Shift).filter_by(schedule_id=prev_schedule.id).all()
                        for ps in prev_shifts:
                            session.add(Shift(
                                schedule_id=schedule.id,
                                employee_id=ps.employee_id,
                                group_id=ps.group_id,
                                weekday=ps.weekday,
                                start_time=ps.start_time,
                                end_time=ps.end_time,
                                break_start=ps.break_start,
                                break_minutes=ps.break_minutes,
                                is_manual=ps.is_manual,
                            ))
                        # Copy scores
                        schedule.score_coverage = prev_schedule.score_coverage
                        schedule.score_fairness = prev_schedule.score_fairness
                        schedule.score_preference = prev_schedule.score_preference
                        schedule.score_compliance = prev_schedule.score_compliance
                        session.commit()
                        st.success(f"{prev_shift_count} Schichten aus KW {prev_monday.isocalendar()[1]} kopiert.")
                        st.rerun()

        # --- Shift list ---
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
        available_emp_options = {
            e.id: e.full_name for e in employees
            if e.id not in all_absent_this_week
        }
        grp_options = {g.id: g.name for g in groups}

        if shifts:
            st.markdown('<div class="section-hdr">Schichtübersicht</div>', unsafe_allow_html=True)
            shift_rows = []
            for s in shifts:
                emp_name = emp_options.get(s.employee_id, "?")
                grp_name = grp_options.get(s.group_id, "—") if s.group_id else "—"
                hours = shift_duration_hours(s.start_time, s.end_time, s.break_minutes)
                shift_rows.append({
                    "Tag": WEEKDAYS_DE[s.weekday],
                    "Mitarbeiter": emp_name,
                    "Gruppe": grp_name,
                    "Von": s.start_time,
                    "Bis": s.end_time,
                    "Pause": f"{s.break_minutes} min" if s.break_minutes else "—",
                    "Stunden": f"{hours:.1f}h",
                    "Typ": "Manuell" if s.is_manual else "Auto",
                })
            st.dataframe(shift_rows, use_container_width=True, hide_index=True)

        # --- Admin editing ---
        if not editable:
            st.caption("Nur Administratoren können Schichten bearbeiten.")
        else:
            # --- Edit shift ---
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
                            edit_start = st.text_input("Beginn (HH:MM)", value=shift.start_time)
                            edit_end = st.text_input("Ende (HH:MM)", value=shift.end_time)
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
                            if not _valid_time(edit_start) or not _valid_time(edit_end):
                                st.error("Ungültiges Zeitformat. Bitte HH:MM verwenden (z.B. 08:00).")
                            elif _time_to_min(edit_start.strip()) >= _time_to_min(edit_end.strip()):
                                st.error("Beginn muss vor Ende liegen.")
                            else:
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
                        "Mitarbeiter", list(available_emp_options.keys()),
                        format_func=lambda k: available_emp_options[k],
                        key="new_shift_emp",
                    )
                with c2:
                    new_start = st.text_input("Beginn (HH:MM)", value="08:00", key="new_shift_start")
                    new_end = st.text_input("Ende (HH:MM)", value="16:00", key="new_shift_end")
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
                    if not available_emp_options:
                        st.error("Keine verfügbaren Mitarbeiter.")
                    elif not _valid_time(new_start) or not _valid_time(new_end):
                        st.error("Ungültiges Zeitformat. Bitte HH:MM verwenden (z.B. 08:00).")
                    elif _time_to_min(new_start.strip()) >= _time_to_min(new_end.strip()):
                        st.error("Beginn muss vor Ende liegen.")
                    else:
                        s_min = _time_to_min(new_start.strip())
                        e_min = _time_to_min(new_end.strip())
                        mid = (s_min + e_min) // 2
                        mid_h, mid_m = divmod(mid, 60)
                        mid_m = (mid_m // 30) * 30
                        break_start = f"{mid_h:02d}:{mid_m:02d}" if new_break > 0 else None

                        session.add(Shift(
                            schedule_id=schedule.id,
                            employee_id=new_emp,
                            group_id=new_grp,
                            weekday=new_day,
                            start_time=new_start.strip(),
                            end_time=new_end.strip(),
                            break_start=break_start,
                            break_minutes=new_break,
                            is_manual=True,
                        ))
                        session.commit()
                        st.success("Schicht angelegt.")
                        st.rerun()

            # --- Status actions ---
            st.markdown('<div class="section-hdr">Status</div>', unsafe_allow_html=True)

            sc1, sc2, sc3 = st.columns(3)
            with sc1:
                if schedule.status != "published":
                    if st.button("Veröffentlichen", use_container_width=True):
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
