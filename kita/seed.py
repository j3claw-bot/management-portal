"""Seed the kita.db with realistic test data. Run once."""

import json

from models import (
    ChildAttendance,
    Employee,
    EmployeeRestriction,
    Group,
    KitaSettings,
    get_session,
)


def seed():
    session = get_session()
    try:
        if session.query(KitaSettings).count() > 0:
            print("Datenbank bereits befüllt – überspringe Seed.")
            return

        # Kita settings
        kita = KitaSettings(
            name="Kita Sonnenschein",
            open_time="07:00",
            close_time="17:00",
            core_start="09:00",
            core_end="15:00",
        )
        session.add(kita)

        # Groups
        groups_data = [
            ("Marienkäfer", "krippe", 6, 12, 1, 4),
            ("Schmetterlinge", "krippe", 6, 12, 1, 4),
            ("Bären", "elementar", 10, 22, 1, 10),
            ("Füchse", "elementar", 10, 22, 1, 10),
        ]
        groups = []
        for name, area, min_c, max_c, r_num, r_den in groups_data:
            g = Group(
                name=name,
                area=area,
                min_children=min_c,
                max_children=max_c,
                ratio_num=r_num,
                ratio_den=r_den,
            )
            session.add(g)
            groups.append(g)

        session.flush()  # get group IDs

        # Child attendance per weekday (Mon-Fri)
        # Krippe groups: slightly fewer on Mon/Fri
        krippe_counts = [10, 12, 12, 11, 9]
        elementar_counts = [18, 22, 22, 20, 17]

        for g in groups:
            counts = krippe_counts if g.area == "krippe" else elementar_counts
            for day in range(5):
                session.add(ChildAttendance(
                    group_id=g.id,
                    weekday=day,
                    expected_children=counts[day],
                    arrival_time="07:00",
                    departure_time="17:00",
                ))

        # Employees (14 total)
        employees_data = [
            # (first, last, role, area, hours, days, restrictions)
            ("Anna", "Müller", "erstkraft", "krippe", 39.0, 5, []),
            ("Sabine", "Schmidt", "erstkraft", "krippe", 39.0, 5, [("no_early_shift", "true")]),
            ("Laura", "Weber", "zweitkraft", "krippe", 30.0, 5, []),
            ("Petra", "Fischer", "zweitkraft", "krippe", 20.0, 4, [("fixed_day_off", "Freitag")]),
            ("Thomas", "Becker", "erstkraft", "elementar", 39.0, 5, []),
            ("Claudia", "Wagner", "erstkraft", "elementar", 39.0, 5, []),
            ("Michael", "Hoffmann", "zweitkraft", "elementar", 35.0, 5, [("no_late_shift", "true")]),
            ("Sandra", "Koch", "zweitkraft", "elementar", 30.0, 5, []),
            ("Julia", "Richter", "zweitkraft", "both", 25.0, 5, []),
            ("Katrin", "Wolf", "erstkraft", "both", 39.0, 5, [("max_consecutive_days", "4")]),
            ("Monika", "Braun", "zweitkraft", "krippe", 20.0, 4, [("fixed_day_off", "Montag")]),
            ("Stefan", "Schäfer", "zweitkraft", "elementar", 30.0, 5, []),
            ("Nicole", "Lehmann", "erstkraft", "elementar", 35.0, 5, [("no_early_shift", "true")]),
            ("Frank", "Krause", "zweitkraft", "both", 25.0, 5, []),
        ]

        for first, last, role, area, hours, days, restrictions in employees_data:
            emp = Employee(
                first_name=first,
                last_name=last,
                role=role,
                area=area,
                contract_hours=hours,
                days_per_week=days,
            )
            session.add(emp)
            session.flush()

            for rtype, rval in restrictions:
                session.add(EmployeeRestriction(
                    employee_id=emp.id,
                    restriction_type=rtype,
                    value=rval,
                ))

        session.commit()
        print("Seed-Daten erfolgreich eingefügt.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
