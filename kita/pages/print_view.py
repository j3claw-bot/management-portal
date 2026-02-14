"""Print-friendly schedule view — optimized for A4 landscape printing."""

import math
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
from engine.constraints import get_required_staff, shift_duration_hours

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def show_print_view(user: dict):
    session = get_session()
    try:
        kita = session.query(KitaSettings).first()
        if not kita:
            st.warning("Keine Kita-Einstellungen vorhanden.")
            return

        groups = session.query(Group).filter_by(is_active=True).order_by(Group.area, Group.name).all()

        # Week picker
        today = date.today()
        current_monday = _monday_of(today)
        week_offset = st.session_state.get("print_week_offset", 0)
        view_monday = current_monday + timedelta(weeks=week_offset)
        view_friday = view_monday + timedelta(days=4)

        c1, c2, c3 = st.columns([1, 4, 1])
        with c1:
            if st.button("< Woche", key="print_prev"):
                st.session_state["print_week_offset"] = week_offset - 1
                st.rerun()
        with c3:
            if st.button("Woche >", key="print_next"):
                st.session_state["print_week_offset"] = week_offset + 1
                st.rerun()
        with c2:
            st.markdown(
                f"<div style='text-align:center;font-size:1.1rem;font-weight:600;'>"
                f"KW {view_monday.isocalendar()[1]} — "
                f"{view_monday.strftime('%d.%m.%Y')} bis {view_friday.strftime('%d.%m.%Y')}"
                f"</div>",
                unsafe_allow_html=True,
            )

        schedule = session.query(Schedule).filter_by(week_start=view_monday).first()
        if not schedule:
            st.info("Kein Dienstplan für diese Woche vorhanden.")
            return

        shifts = session.query(Shift).filter_by(schedule_id=schedule.id).all()
        if not shifts:
            st.info("Keine Schichten in diesem Dienstplan.")
            return

        # Print button
        st.markdown(
            '<div style="text-align:right;margin-bottom:1rem;">'
            '<button onclick="window.print()" style="background:#4F46E5;color:white;'
            'border:none;padding:8px 24px;border-radius:6px;cursor:pointer;font-size:0.9rem;'
            'font-weight:600;">Drucken</button></div>',
            unsafe_allow_html=True,
        )

        # Build print-optimized schedule
        # Load employee and group maps
        emp_map = {}
        for s in shifts:
            if s.employee_id not in emp_map:
                emp = session.query(Employee).get(s.employee_id)
                if emp:
                    emp_map[s.employee_id] = emp
        grp_map = {g.id: g for g in groups}

        # --- Main schedule table: one row per employee per day ---
        html = f"""
        <style>
            @media print {{
                header[data-testid="stHeader"] {{ display: none !important; }}
                .stApp > div:first-child {{ padding: 0 !important; }}
                .block-container {{ padding: 0.5rem !important; max-width: 100% !important; }}
                [data-testid="stSidebar"] {{ display: none !important; }}
                button, .stButton, [data-testid="stRadio"] {{ display: none !important; }}
                .no-print {{ display: none !important; }}
            }}
            .print-table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 0.82rem;
                font-family: 'Segoe UI', system-ui, sans-serif;
            }}
            .print-table th {{
                background: #1E293B;
                color: #E2E8F0;
                padding: 8px 10px;
                text-align: center;
                border: 1px solid #475569;
                font-weight: 600;
            }}
            .print-table td {{
                padding: 5px 8px;
                border: 1px solid #334155;
                vertical-align: top;
            }}
            .print-table .group-header {{
                background: #1E293B;
                color: #94A3B8;
                font-weight: 600;
                font-size: 0.9rem;
                padding: 6px 10px;
            }}
            .print-table .emp-name {{
                font-weight: 600;
                color: #E2E8F0;
                white-space: nowrap;
            }}
            .print-table .shift-cell {{
                text-align: center;
                font-size: 0.8rem;
            }}
            .print-table .shift-active {{
                background: #1a2744;
                color: #93C5FD;
            }}
            .print-table .shift-empty {{
                color: #475569;
            }}
            .print-table .coverage-row td {{
                background: #0F172A;
                font-weight: 600;
                text-align: center;
                font-size: 0.8rem;
                border-top: 2px solid #475569;
            }}
            @media print {{
                .print-table th {{ background: #f0f0f0 !important; color: #111 !important; border-color: #999 !important; }}
                .print-table td {{ border-color: #ccc !important; color: #111 !important; }}
                .print-table .group-header {{ background: #e0e0e0 !important; color: #333 !important; }}
                .print-table .shift-active {{ background: #e8f0fe !important; color: #1a3a6b !important; }}
                .print-table .shift-empty {{ color: #999 !important; }}
                .print-table .coverage-row td {{ background: #f5f5f5 !important; color: #111 !important; }}
                .print-table .emp-name {{ color: #111 !important; }}
                body {{ background: white !important; }}
            }}
        </style>
        """

        # Title
        html += (
            f'<div style="text-align:center;margin-bottom:1rem;">'
            f'<div style="font-size:1.3rem;font-weight:700;color:#E2E8F0;">{kita.name} — Dienstplan</div>'
            f'<div style="color:#94A3B8;">KW {view_monday.isocalendar()[1]} · '
            f'{view_monday.strftime("%d.%m.%Y")} – {view_friday.strftime("%d.%m.%Y")}</div>'
            f'</div>'
        )

        # Table
        html += '<table class="print-table"><thead><tr>'
        html += '<th style="text-align:left;min-width:150px;">Mitarbeiter</th>'
        for day_name in WEEKDAYS_DE:
            html += f'<th>{day_name}<br><small>{(view_monday + timedelta(days=WEEKDAYS_DE.index(day_name))).strftime("%d.%m.")}</small></th>'
        html += '<th>Stunden</th></tr></thead><tbody>'

        # Group by group
        for g in groups:
            area_label = "Krippe" if g.area == "krippe" else "Elementar"
            area_dot = "&#9679;" if g.area == "krippe" else "&#9670;"
            html += (
                f'<tr><td class="group-header" colspan="7">'
                f'{area_dot} {g.name} <small>({area_label})</small></td></tr>'
            )

            # Find all employees assigned to this group this week
            group_shifts = [s for s in shifts if s.group_id == g.id]
            group_emp_ids = sorted(set(s.employee_id for s in group_shifts))

            if not group_emp_ids:
                html += '<tr><td colspan="7" style="color:#475569;text-align:center;font-size:0.8rem;">Keine Schichten</td></tr>'
                continue

            for emp_id in group_emp_ids:
                emp = emp_map.get(emp_id)
                if not emp:
                    continue

                role_badge = "E" if emp.role == "erstkraft" else "Z"
                role_color = "#22C55E" if emp.role == "erstkraft" else "#94A3B8"

                html += (
                    f'<tr><td class="emp-name">'
                    f'<span style="color:{role_color};font-size:0.7rem;margin-right:4px;">[{role_badge}]</span>'
                    f'{emp.full_name}</td>'
                )

                week_hours = 0.0
                for d in range(5):
                    day_shift = next(
                        (s for s in group_shifts if s.employee_id == emp_id and s.weekday == d),
                        None,
                    )
                    if day_shift:
                        hours = shift_duration_hours(day_shift.start_time, day_shift.end_time, day_shift.break_minutes)
                        week_hours += hours
                        break_info = f" ({day_shift.break_minutes}min)" if day_shift.break_minutes else ""
                        html += (
                            f'<td class="shift-cell shift-active">'
                            f'{day_shift.start_time}–{day_shift.end_time}'
                            f'<br><small style="color:#64748B;">{hours:.1f}h{break_info}</small></td>'
                        )
                    else:
                        html += '<td class="shift-cell shift-empty">—</td>'

                html += f'<td class="shift-cell" style="font-weight:600;">{week_hours:.1f}h</td></tr>'

            # Coverage row for this group
            html += '<tr class="coverage-row"><td style="text-align:right;">Besetzung:</td>'
            for d in range(5):
                required = get_required_staff(session, g, d)
                assigned = sum(1 for s in group_shifts if s.weekday == d)
                if required == 0:
                    html += '<td style="color:#475569;">—</td>'
                elif assigned >= required:
                    html += f'<td style="color:#22C55E;">{assigned}/{required} &#10003;</td>'
                else:
                    html += f'<td style="color:#EF4444;">{assigned}/{required} &#9888;</td>'
            html += '<td></td></tr>'

        html += '</tbody></table>'

        # Footer with generation info
        html += (
            f'<div style="margin-top:1rem;color:#64748B;font-size:0.75rem;text-align:center;">'
            f'Erstellt am {today.strftime("%d.%m.%Y")} · {kita.name} · J3Claw Management'
            f'</div>'
        )

        st.markdown(html, unsafe_allow_html=True)

    finally:
        session.close()
