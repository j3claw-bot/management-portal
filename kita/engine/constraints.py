"""Hard constraint validation for schedule generation."""

import math
from datetime import date, timedelta

from models import (
    Absence,
    ChildAttendance,
    Employee,
    EmployeeRestriction,
    Group,
    KitaSettings,
    Shift,
    get_session,
)

WEEKDAYS_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"]


def get_required_staff(session, group: Group, weekday: int) -> int:
    """Minimum staff required for a group on a given weekday."""
    att = session.query(ChildAttendance).filter_by(
        group_id=group.id, weekday=weekday
    ).first()
    if not att or att.expected_children <= 0:
        return 0
    return math.ceil(att.expected_children * group.ratio_num / group.ratio_den)


def get_absent_employees(session, week_monday: date) -> dict[int, set[int]]:
    """Return {weekday: set(employee_ids)} who are absent each day."""
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


def get_restrictions(session, employee_id: int) -> list[EmployeeRestriction]:
    return session.query(EmployeeRestriction).filter_by(employee_id=employee_id).all()


def is_available(employee: Employee, weekday: int, restrictions: list[EmployeeRestriction],
                 absent_ids: set[int]) -> bool:
    """Check if employee is available on a given weekday."""
    if not employee.is_active:
        return False
    if employee.id in absent_ids:
        return False
    for r in restrictions:
        if r.restriction_type == "fixed_day_off":
            if r.value == WEEKDAYS_DE[weekday]:
                return False
    return True


def can_work_in_group(employee: Employee, group: Group) -> bool:
    """Check if employee can work in the given group's area."""
    if employee.area == "both":
        return True
    return employee.area == group.area


def shift_duration_hours(start: str, end: str, break_min: int = 0) -> float:
    """Calculate shift duration in hours."""
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    return max(0, ((eh * 60 + em) - (sh * 60 + sm) - break_min) / 60)


def validate_schedule(session, schedule_id: int, week_monday: date,
                      groups: list[Group], kita: KitaSettings) -> list[str]:
    """Validate a schedule and return a list of constraint violations."""
    violations = []
    shifts = session.query(Shift).filter_by(schedule_id=schedule_id).all()

    # Check required staff per group per day
    for weekday in range(5):
        for group in groups:
            required = get_required_staff(session, group, weekday)
            assigned = sum(1 for s in shifts if s.weekday == weekday and s.group_id == group.id)
            if assigned < required:
                violations.append(
                    f"{WEEKDAYS_DE[weekday]}: {group.name} braucht {required} "
                    f"Fachkräfte, nur {assigned} eingeteilt."
                )

        # Check each group has at least one Erstkraft
        for group in groups:
            required = get_required_staff(session, group, weekday)
            if required == 0:
                continue
            group_shifts = [s for s in shifts if s.weekday == weekday and s.group_id == group.id]
            erstkraft_count = 0
            for s in group_shifts:
                emp = session.query(Employee).get(s.employee_id)
                if emp and emp.role == "erstkraft":
                    erstkraft_count += 1
            if erstkraft_count == 0:
                violations.append(
                    f"{WEEKDAYS_DE[weekday]}: {group.name} hat keine Erstkraft."
                )

    # Check no double-booking
    for weekday in range(5):
        day_shifts = [s for s in shifts if s.weekday == weekday]
        emp_ids = [s.employee_id for s in day_shifts]
        seen = set()
        for eid in emp_ids:
            if eid in seen:
                emp = session.query(Employee).get(eid)
                name = emp.full_name if emp else f"ID {eid}"
                violations.append(
                    f"{WEEKDAYS_DE[weekday]}: {name} ist doppelt eingeteilt."
                )
            seen.add(eid)

    # Check contract hours
    employees = session.query(Employee).filter_by(is_active=True).all()
    for emp in employees:
        emp_shifts = [s for s in shifts if s.employee_id == emp.id]
        total_hours = sum(
            shift_duration_hours(s.start_time, s.end_time, s.break_minutes)
            for s in emp_shifts
        )
        if total_hours > emp.contract_hours + 0.5:  # small tolerance
            violations.append(
                f"{emp.full_name}: {total_hours:.1f}h geplant, "
                f"nur {emp.contract_hours:.1f}h Vertrag."
            )

    return violations
