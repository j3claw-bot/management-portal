"""Kita Dashboard — today's staffing, alerts, week overview."""

import math
from datetime import date, timedelta

import streamlit as st

from models import (
    Absence,
    ChildAttendance,
    Employee,
    EmployeeRestriction,
    Group,
    KitaSettings,
    Schedule,
    Shift,
    get_session,
)
from engine.constraints import get_required_staff, shift_duration_hours

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr"]
ABSENCE_LABELS = {"urlaub": "Urlaub", "krank": "Krank", "fortbildung": "Fortb.", "sonstig": "Sonst."}
AREA_COLORS = {"krippe": "#F59E0B", "elementar": "#3B82F6"}


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def show_dashboard(user: dict):
    session = get_session()
    try:
        kita = session.query(KitaSettings).first()
        if not kita:
            st.warning("Bitte zuerst Kita-Einstellungen anlegen.")
            return

        today = date.today()
        weekday = today.weekday()  # 0=Mon..6=Sun
        monday = _monday_of(today)
        is_workday = weekday < 5

        groups = session.query(Group).filter_by(is_active=True).order_by(Group.area, Group.name).all()
        employees = session.query(Employee).filter_by(is_active=True).all()
        schedule = session.query(Schedule).filter_by(week_start=monday).first()

        # --- Header ---
        st.markdown(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:1.6rem;font-weight:700;color:#E2E8F0;">{kita.name}</div>'
            f'<div style="color:#94A3B8;font-size:0.95rem;">'
            f'{today.strftime("%A, %d. %B %Y")} · KW {today.isocalendar()[1]}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

        # --- Stat cards ---
        total_emp = len(employees)
        total_groups = len(groups)
        total_children = 0
        for g in groups:
            att = session.query(ChildAttendance).filter_by(
                group_id=g.id, weekday=weekday if is_workday else 0
            ).first()
            if att:
                total_children += att.expected_children

        # Today's absences
        today_absent = (
            session.query(Absence)
            .filter(Absence.start_date <= today, Absence.end_date >= today)
            .all()
        )
        absent_ids = {a.employee_id for a in today_absent}
        available_today = total_emp - len(absent_ids)

        # Schedule status
        sched_status = "—"
        sched_color = "#6B7280"
        if schedule:
            sched_map = {
                "draft": ("Entwurf", "#EAB308"),
                "published": ("Veröffentlicht", "#22C55E"),
                "archived": ("Archiviert", "#6B7280"),
            }
            sched_status, sched_color = sched_map.get(schedule.status, ("?", "#6B7280"))

        cards = [
            ("Mitarbeiter", str(available_today) + f"/{total_emp}", "verfügbar heute", "#4F46E5"),
            ("Gruppen", str(total_groups), "aktiv", "#8B5CF6"),
            ("Kinder heute", str(total_children), "erwartet", "#EC4899"),
            ("Dienstplan", sched_status, f"KW {today.isocalendar()[1]}", sched_color),
        ]

        cols = st.columns(4)
        for col, (label, value, sub, color) in zip(cols, cards):
            with col:
                st.markdown(
                    f'<div style="background:#1E293B;border-radius:10px;padding:1.2rem;'
                    f'border-left:4px solid {color};">'
                    f'<div style="color:#94A3B8;font-size:0.75rem;text-transform:uppercase;'
                    f'letter-spacing:0.05em;">{label}</div>'
                    f'<div style="font-size:1.8rem;font-weight:700;color:#E2E8F0;margin:0.3rem 0;">'
                    f'{value}</div>'
                    f'<div style="color:#64748B;font-size:0.8rem;">{sub}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # --- Today's staffing per group ---
        if is_workday:
            st.markdown(
                '<div class="section-hdr">Heutige Besetzung</div>',
                unsafe_allow_html=True,
            )

            alerts = []

            for g in groups:
                required = get_required_staff(session, g, weekday)
                if required == 0:
                    continue

                assigned = 0
                has_erstkraft = False
                assigned_names = []

                if schedule:
                    day_shifts = (
                        session.query(Shift)
                        .filter_by(schedule_id=schedule.id, group_id=g.id, weekday=weekday)
                        .all()
                    )
                    assigned = len(day_shifts)
                    for s in day_shifts:
                        emp = session.query(Employee).get(s.employee_id)
                        if emp:
                            assigned_names.append(emp.full_name)
                            if emp.role == "erstkraft":
                                has_erstkraft = True

                pct = min(assigned / required, 1.0) if required > 0 else 0
                area_color = AREA_COLORS.get(g.area, "#6B7280")
                area_label = "Krippe" if g.area == "krippe" else "Elementar"

                if assigned < required:
                    status_icon = "&#9888;"  # warning
                    status_color = "#EF4444"
                    alerts.append(f"{g.name}: {assigned}/{required} Fachkräfte")
                elif not has_erstkraft:
                    status_icon = "&#9888;"
                    status_color = "#EAB308"
                    alerts.append(f"{g.name}: Keine Erstkraft eingeteilt")
                else:
                    status_icon = "&#10003;"
                    status_color = "#22C55E"

                bar_color = "#22C55E" if pct >= 1.0 else ("#EAB308" if pct >= 0.75 else "#EF4444")
                names_str = ", ".join(assigned_names) if assigned_names else "Keine Schichten"

                # Get expected children
                att = session.query(ChildAttendance).filter_by(group_id=g.id, weekday=weekday).first()
                child_count = att.expected_children if att else 0

                st.markdown(
                    f'<div style="background:#1E293B;border-radius:8px;padding:0.8rem 1rem;'
                    f'margin-bottom:0.5rem;border-left:3px solid {area_color};">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                    f'<div>'
                    f'<span style="font-weight:600;color:#E2E8F0;">{g.name}</span>'
                    f'<span style="color:#64748B;font-size:0.8rem;margin-left:8px;">{area_label}</span>'
                    f'</div>'
                    f'<div style="display:flex;align-items:center;gap:12px;">'
                    f'<span style="color:#94A3B8;font-size:0.8rem;">{child_count} Kinder</span>'
                    f'<span style="color:{status_color};font-weight:600;">'
                    f'{status_icon} {assigned}/{required}</span>'
                    f'</div></div>'
                    f'<div style="background:#334155;border-radius:3px;height:6px;margin:6px 0;">'
                    f'<div style="background:{bar_color};height:100%;border-radius:3px;'
                    f'width:{pct*100:.0f}%;transition:width 0.3s;"></div></div>'
                    f'<div style="color:#64748B;font-size:0.8rem;">{names_str}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # --- Alerts panel ---
            if alerts:
                alert_html = "".join(f"<li>{a}</li>" for a in alerts)
                st.markdown(
                    f'<div style="background:#7F1D1D;border-radius:8px;padding:0.8rem 1rem;'
                    f'margin-top:0.5rem;color:#FCA5A5;">'
                    f'<div style="font-weight:600;margin-bottom:4px;">Warnungen</div>'
                    f'<ul style="margin:0;padding-left:1.2rem;font-size:0.85rem;">{alert_html}</ul>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            elif schedule and schedule.shifts:
                st.markdown(
                    '<div style="background:#14532D;border-radius:8px;padding:0.8rem 1rem;'
                    'margin-top:0.5rem;color:#86EFAC;">'
                    '&#10003; Alle Gruppen sind heute vollständig besetzt.</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Wochenende — keine Dienstplanung.")

        # --- Absences this week ---
        friday = monday + timedelta(days=4)
        week_absences = (
            session.query(Absence)
            .filter(Absence.start_date <= friday, Absence.end_date >= monday)
            .order_by(Absence.start_date)
            .all()
        )

        st.markdown(
            '<div class="section-hdr">Abwesenheiten diese Woche</div>',
            unsafe_allow_html=True,
        )

        if week_absences:
            abs_html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;">'
            for a in week_absences:
                emp = session.query(Employee).get(a.employee_id)
                if not emp:
                    continue
                type_label = ABSENCE_LABELS.get(a.absence_type, a.absence_type)
                # Which days this week
                days = []
                for d in range(5):
                    day_date = monday + timedelta(days=d)
                    if a.start_date <= day_date <= a.end_date:
                        days.append(WEEKDAYS_SHORT[d])
                is_today = a.start_date <= today <= a.end_date

                type_colors = {
                    "urlaub": "#1E3A5F",
                    "krank": "#7F1D1D",
                    "fortbildung": "#4C1D95",
                    "sonstig": "#374151",
                }
                bg = type_colors.get(a.absence_type, "#374151")
                border = "#EF4444" if is_today else "#475569"

                abs_html += (
                    f'<div style="background:{bg};border-radius:8px;padding:0.6rem 0.8rem;'
                    f'border:1px solid {border};">'
                    f'<div style="font-weight:600;color:#E2E8F0;font-size:0.9rem;">{emp.full_name}</div>'
                    f'<div style="color:#94A3B8;font-size:0.8rem;">'
                    f'{type_label} · {", ".join(days)}'
                    f'</div></div>'
                )
            abs_html += '</div>'
            st.markdown(abs_html, unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="color:#64748B;font-size:0.9rem;padding:0.5rem;">Keine Abwesenheiten diese Woche.</div>',
                unsafe_allow_html=True,
            )

        # --- Week at a glance: mini coverage heatmap ---
        if schedule:
            st.markdown(
                '<div class="section-hdr">Wochenübersicht — Besetzung</div>',
                unsafe_allow_html=True,
            )

            # Build a heatmap: groups × weekdays
            heat_html = '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
            heat_html += '<tr><th style="text-align:left;padding:6px 8px;color:#94A3B8;border-bottom:1px solid #334155;">Gruppe</th>'
            for d in range(5):
                is_today_col = (d == weekday) if is_workday else False
                bg = "background:#1a2744;" if is_today_col else ""
                heat_html += (
                    f'<th style="text-align:center;padding:6px 8px;color:#94A3B8;'
                    f'border-bottom:1px solid #334155;{bg}">{WEEKDAYS_SHORT[d]}</th>'
                )
            heat_html += '</tr>'

            for g in groups:
                area_dot = f'<span style="color:{AREA_COLORS.get(g.area, "#6B7280")};">&#9679;</span>'
                heat_html += f'<tr><td style="padding:6px 8px;color:#E2E8F0;border-bottom:1px solid #1E293B;">{area_dot} {g.name}</td>'

                for d in range(5):
                    required = get_required_staff(session, g, d)
                    assigned = session.query(Shift).filter_by(
                        schedule_id=schedule.id, group_id=g.id, weekday=d
                    ).count()

                    if required == 0:
                        cell_bg = "#1E293B"
                        cell_text = "—"
                        cell_color = "#475569"
                    elif assigned >= required:
                        cell_bg = "#14532D"
                        cell_text = f"{assigned}/{required}"
                        cell_color = "#86EFAC"
                    elif assigned >= required - 1:
                        cell_bg = "#78350F"
                        cell_text = f"{assigned}/{required}"
                        cell_color = "#FCD34D"
                    else:
                        cell_bg = "#7F1D1D"
                        cell_text = f"{assigned}/{required}"
                        cell_color = "#FCA5A5"

                    is_today_col = (d == weekday) if is_workday else False
                    border = "border:2px solid #4F46E5;" if is_today_col else ""

                    heat_html += (
                        f'<td style="text-align:center;padding:6px 8px;background:{cell_bg};'
                        f'color:{cell_color};font-weight:600;border-bottom:1px solid #1E293B;{border}">'
                        f'{cell_text}</td>'
                    )
                heat_html += '</tr>'

            heat_html += '</table>'
            st.markdown(heat_html, unsafe_allow_html=True)

        # --- Hours utilization ---
        st.markdown(
            '<div class="section-hdr">Stundenauslastung (diese Woche)</div>',
            unsafe_allow_html=True,
        )

        if schedule:
            emp_hours = []
            for emp in employees:
                emp_shifts = session.query(Shift).filter_by(
                    schedule_id=schedule.id, employee_id=emp.id
                ).all()
                total = sum(
                    shift_duration_hours(s.start_time, s.end_time, s.break_minutes)
                    for s in emp_shifts
                )
                pct = min(total / emp.contract_hours, 1.0) if emp.contract_hours > 0 else 0
                emp_hours.append((emp, total, pct))

            # Sort: most utilized first
            emp_hours.sort(key=lambda x: x[2], reverse=True)

            hours_html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:6px;">'
            for emp, total, pct in emp_hours:
                bar_color = "#22C55E" if pct >= 0.9 else ("#EAB308" if pct >= 0.5 else "#94A3B8")
                is_absent = emp.id in absent_ids
                absent_badge = (
                    ' <span style="background:#7F1D1D;color:#FCA5A5;padding:1px 6px;'
                    'border-radius:3px;font-size:0.7rem;">abwesend</span>'
                    if is_absent else ""
                )

                hours_html += (
                    f'<div style="background:#1E293B;border-radius:6px;padding:0.5rem 0.8rem;">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center;'
                    f'margin-bottom:4px;">'
                    f'<span style="color:#E2E8F0;font-size:0.85rem;">{emp.full_name}{absent_badge}</span>'
                    f'<span style="color:#94A3B8;font-size:0.8rem;">{total:.1f}/{emp.contract_hours:.0f}h</span>'
                    f'</div>'
                    f'<div style="background:#334155;border-radius:3px;height:5px;">'
                    f'<div style="background:{bar_color};height:100%;border-radius:3px;'
                    f'width:{pct*100:.0f}%;"></div></div>'
                    f'</div>'
                )
            hours_html += '</div>'
            st.markdown(hours_html, unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="color:#64748B;font-size:0.9rem;padding:0.5rem;">'
                'Kein Dienstplan für diese Woche vorhanden.</div>',
                unsafe_allow_html=True,
            )

    finally:
        session.close()
