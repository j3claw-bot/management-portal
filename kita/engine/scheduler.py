"""
Auto-schedule generation engine.

Greedy constraint-based scheduler that assigns employees to groups
for each weekday, respecting hard constraints and optimizing for preferences.
"""

import math
from datetime import date, timedelta

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
from engine.constraints import (
    get_absent_employees,
    get_required_staff,
    get_restrictions,
    is_available,
    can_work_in_group,
    shift_duration_hours,
    validate_schedule,
)


# Shift templates
EARLY_SHIFT = ("07:00", "15:30", "11:30", 30)   # start, end, break_start, break_min
MID_SHIFT   = ("08:00", "16:00", "12:00", 30)
LATE_SHIFT  = ("08:30", "17:00", "12:30", 30)
SHORT_SHIFT = ("08:00", "14:00", None, 0)        # part-time, no break needed under 6h

SHIFT_TEMPLATES = {
    "early": EARLY_SHIFT,
    "mid": MID_SHIFT,
    "late": LATE_SHIFT,
    "short": SHORT_SHIFT,
}


def _pick_shift_template(employee: Employee, restrictions: list[EmployeeRestriction],
                         needs_early: bool, needs_late: bool) -> tuple[str, str, str | None, int]:
    """Pick the best shift template for an employee based on restrictions and preferences."""
    no_early = any(r.restriction_type == "no_early_shift" for r in restrictions)
    no_late = any(r.restriction_type == "no_late_shift" for r in restrictions)
    prefers_early = any(r.restriction_type == "prefers_early" for r in restrictions)
    prefers_late = any(r.restriction_type == "prefers_late" for r in restrictions)

    # Part-time employees (< 30h/week → ~6h/day) get short shifts
    daily_target = employee.contract_hours / employee.days_per_week
    if daily_target < 6.5:
        return SHORT_SHIFT

    # Apply hard constraints first
    if no_early and needs_late:
        return LATE_SHIFT
    if no_late and needs_early:
        return EARLY_SHIFT
    if no_early:
        return MID_SHIFT if not needs_late else LATE_SHIFT
    if no_late:
        return MID_SHIFT if not needs_early else EARLY_SHIFT

    # Apply preferences
    if prefers_early and needs_early:
        return EARLY_SHIFT
    if prefers_late and needs_late:
        return LATE_SHIFT

    # Fill coverage needs
    if needs_early:
        return EARLY_SHIFT
    if needs_late:
        return LATE_SHIFT

    return MID_SHIFT


def _get_max_consecutive(restrictions: list[EmployeeRestriction]) -> int | None:
    """Extract max_consecutive_days restriction value, or None if not set."""
    for r in restrictions:
        if r.restriction_type == "max_consecutive_days":
            try:
                return int(r.value)
            except (ValueError, TypeError):
                pass
    return None


def _would_exceed_consecutive(emp_id: int, weekday: int,
                               days_assigned: dict[int, list[int]],
                               max_consecutive: int) -> bool:
    """Check if assigning emp to weekday would exceed max consecutive days."""
    assigned_days = set(days_assigned.get(emp_id, []))
    assigned_days.add(weekday)

    # Find the longest run of consecutive days in the assigned set
    if not assigned_days:
        return False

    sorted_days = sorted(assigned_days)
    max_run = 1
    current_run = 1
    for i in range(1, len(sorted_days)):
        if sorted_days[i] == sorted_days[i - 1] + 1:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 1

    return max_run > max_consecutive


def _score_employee_for_group(employee: Employee, group: Group,
                               restrictions: list[EmployeeRestriction],
                               hours_so_far: float,
                               group_assigned: set[int],
                               colleague_prefs: dict[int, set[int]]) -> float:
    """Score how suitable an employee is for a group assignment. Higher = better."""
    score = 0.0

    # Prefer employees who are specific to this area (not "both")
    if employee.area == group.area:
        score += 10
    elif employee.area == "both":
        score += 5

    # Prefer Erstkraft if group doesn't have one yet
    if employee.role == "erstkraft":
        score += 3

    # Fairness: prefer employees with fewer hours scheduled so far
    target_hours = employee.contract_hours
    utilization = hours_so_far / target_hours if target_hours > 0 else 1.0
    score += max(0, 5 * (1 - utilization))

    # Colleague preference bonus — check if preferred colleagues are in THIS GROUP
    if employee.id in colleague_prefs:
        preferred = colleague_prefs[employee.id]
        overlap = preferred & group_assigned
        score += 5 * len(overlap)

    return score


def generate_schedule(session, week_monday: date) -> dict:
    """
    Generate a schedule for the given week.

    Returns {
        "shifts": [(employee_id, group_id, weekday, start, end, break_start, break_min), ...],
        "warnings": [str, ...],
        "scores": {"coverage": int, "fairness": int, "preference": int, "compliance": int},
    }
    """
    kita = session.query(KitaSettings).first()
    groups = session.query(Group).filter_by(is_active=True).order_by(Group.area, Group.name).all()
    employees = session.query(Employee).filter_by(is_active=True).all()
    absent_by_day = get_absent_employees(session, week_monday)

    # Load all restrictions
    emp_restrictions = {}
    colleague_prefs = {}  # emp_id -> set of preferred colleague ids
    max_consecutive = {}  # emp_id -> max consecutive days (or None)
    for emp in employees:
        restrictions = get_restrictions(session, emp.id)
        emp_restrictions[emp.id] = restrictions
        max_consecutive[emp.id] = _get_max_consecutive(restrictions)
        for r in restrictions:
            if r.restriction_type == "prefers_colleague":
                try:
                    colleague_id = int(r.value)
                    colleague_prefs.setdefault(emp.id, set()).add(colleague_id)
                except (ValueError, TypeError):
                    pass

    shifts = []
    warnings = []
    hours_tracker = {emp.id: 0.0 for emp in employees}
    days_tracker = {emp.id: 0 for emp in employees}
    days_assigned = {emp.id: [] for emp in employees}  # emp_id -> list of weekdays

    # Track which group each employee is assigned to each day
    group_assignments = {}  # (weekday, group_id) -> set of emp_ids

    for weekday in range(5):
        absent_ids = absent_by_day[weekday]
        assigned_today = set()

        # Calculate what each group needs
        group_needs = []
        for group in groups:
            required = get_required_staff(session, group, weekday)
            if required > 0:
                group_needs.append((group, required))

        # Sort groups by need (highest ratio first = hardest to fill)
        group_needs.sort(key=lambda x: x[1], reverse=True)

        # Track early/late coverage needs
        early_assigned = 0
        late_assigned = 0
        total_needed = sum(n for _, n in group_needs)
        early_target = max(1, total_needed // 3)  # ~1/3 should be early
        late_target = max(1, total_needed // 3)    # ~1/3 should be late

        for group, required in group_needs:
            group_key = (weekday, group.id)
            group_assignments.setdefault(group_key, set())

            # Get available employees for this group
            candidates = []
            for emp in employees:
                if emp.id in assigned_today:
                    continue
                if not is_available(emp, weekday, emp_restrictions[emp.id], absent_ids):
                    continue
                if not can_work_in_group(emp, group):
                    continue
                # Check max days per week
                if days_tracker[emp.id] >= emp.days_per_week:
                    continue
                # Check contract hours (rough check: would adding ~8h exceed?)
                daily_target = emp.contract_hours / emp.days_per_week
                if hours_tracker[emp.id] + daily_target > emp.contract_hours + 1:
                    continue
                # Check max consecutive days
                mc = max_consecutive[emp.id]
                if mc is not None and _would_exceed_consecutive(
                    emp.id, weekday, days_assigned, mc
                ):
                    continue
                candidates.append(emp)

            # Score and sort candidates
            scored = []
            for emp in candidates:
                score = _score_employee_for_group(
                    emp, group, emp_restrictions[emp.id],
                    hours_tracker[emp.id],
                    group_assignments[group_key],
                    colleague_prefs,
                )
                scored.append((score, emp))
            scored.sort(key=lambda x: x[0], reverse=True)

            # Ensure at least one Erstkraft
            erstkraft_candidates = [(s, e) for s, e in scored if e.role == "erstkraft"]

            assigned_to_group = []

            # First assign an Erstkraft
            if erstkraft_candidates:
                _, emp = erstkraft_candidates[0]
                assigned_to_group.append(emp)
                scored = [(s, e) for s, e in scored if e.id != emp.id]

            # Fill remaining slots
            remaining = required - len(assigned_to_group)
            for _, emp in scored[:remaining]:
                assigned_to_group.append(emp)

            if len(assigned_to_group) < required:
                warnings.append(
                    f"{['Mo', 'Di', 'Mi', 'Do', 'Fr'][weekday]}: {group.name} braucht "
                    f"{required} Fachkräfte, nur {len(assigned_to_group)} verfügbar."
                )

            # Assign shifts
            for emp in assigned_to_group:
                needs_early = early_assigned < early_target
                needs_late = late_assigned < late_target

                start, end, break_start, break_min = _pick_shift_template(
                    emp, emp_restrictions[emp.id], needs_early, needs_late,
                )

                # Track early/late
                if start == "07:00":
                    early_assigned += 1
                elif end == "17:00":
                    late_assigned += 1

                hours = shift_duration_hours(start, end, break_min)
                hours_tracker[emp.id] += hours
                days_tracker[emp.id] += 1
                days_assigned[emp.id].append(weekday)
                assigned_today.add(emp.id)
                group_assignments[group_key].add(emp.id)

                shifts.append((emp.id, group.id, weekday, start, end, break_start, break_min))

    # Calculate scores
    total_required = 0
    total_filled = 0
    for weekday in range(5):
        for group in groups:
            req = get_required_staff(session, group, weekday)
            total_required += req
            filled = sum(1 for s in shifts if s[2] == weekday and s[1] == group.id)
            total_filled += min(filled, req)

    coverage_score = int((total_filled / total_required * 100)) if total_required > 0 else 100

    # Fairness: how evenly distributed are hours relative to contracts
    fairness_deltas = []
    for emp in employees:
        if emp.contract_hours > 0:
            utilization = hours_tracker[emp.id] / emp.contract_hours
            fairness_deltas.append(abs(1.0 - utilization))
    avg_delta = sum(fairness_deltas) / len(fairness_deltas) if fairness_deltas else 0
    fairness_score = max(0, int((1 - avg_delta) * 100))

    # Preference score: how many preferences were satisfied
    pref_total = 0
    pref_satisfied = 0
    for emp in employees:
        for r in emp_restrictions.get(emp.id, []):
            if r.restriction_type == "prefers_early":
                pref_total += 1
                emp_shifts = [s for s in shifts if s[0] == emp.id]
                if any(s[3] == "07:00" for s in emp_shifts):
                    pref_satisfied += 1
            elif r.restriction_type == "prefers_late":
                pref_total += 1
                emp_shifts = [s for s in shifts if s[0] == emp.id]
                if any(s[4] == "17:00" for s in emp_shifts):
                    pref_satisfied += 1
            elif r.restriction_type == "prefers_colleague":
                pref_total += 1
                try:
                    colleague_id = int(r.value)
                    # Check if they're in the SAME GROUP on any day
                    for wd in range(5):
                        emp_groups = {s[1] for s in shifts if s[0] == emp.id and s[2] == wd}
                        col_groups = {s[1] for s in shifts if s[0] == colleague_id and s[2] == wd}
                        if emp_groups & col_groups:  # same group on same day
                            pref_satisfied += 1
                            break
                except (ValueError, TypeError):
                    pass
    preference_score = int((pref_satisfied / pref_total * 100)) if pref_total > 0 else 100

    # Compliance score: percentage of constraint checks passed
    total_checks = max(1, total_required + len(employees))  # groups + employees
    violation_count = len(warnings)
    compliance_score = max(0, int((1 - violation_count / total_checks) * 100))

    return {
        "shifts": shifts,
        "warnings": warnings,
        "scores": {
            "coverage": coverage_score,
            "fairness": fairness_score,
            "preference": preference_score,
            "compliance": compliance_score,
        },
    }


def apply_schedule(session, schedule: Schedule, result: dict):
    """Apply generated shifts to a schedule, replacing any existing auto-generated shifts."""
    # Remove existing auto-generated shifts
    session.query(Shift).filter_by(
        schedule_id=schedule.id, is_manual=False
    ).delete()

    # Add new shifts
    for emp_id, group_id, weekday, start, end, break_start, break_min in result["shifts"]:
        session.add(Shift(
            schedule_id=schedule.id,
            employee_id=emp_id,
            group_id=group_id,
            weekday=weekday,
            start_time=start,
            end_time=end,
            break_start=break_start,
            break_minutes=break_min,
            is_manual=False,
        ))

    # Update scores
    schedule.score_coverage = result["scores"]["coverage"]
    schedule.score_fairness = result["scores"]["fairness"]
    schedule.score_preference = result["scores"]["preference"]
    schedule.score_compliance = result["scores"]["compliance"]

    session.commit()
