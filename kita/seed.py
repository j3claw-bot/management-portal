"""
Seed file for kita.db - NO LONGER USED.

All initial setup is now done through the Setup Wizard in the Kita app.
This file is kept for reference only.
"""

from models import (
    ChildAttendance,
    Employee,
    EmployeeRestriction,
    Group,
    KitaSettings,
    get_session,
)


def seed():
    """
    DEPRECATED: This function is no longer used.
    Use the Setup Wizard in the Kita app instead.
    """
    print("⚠️  Seed function is deprecated.")
    print("Please use the Setup Wizard in the Kita app to initialize your database.")
    print("The wizard will guide you through:")
    print("  1. Kita settings (name, times)")
    print("  2. Adding groups")
    print("  3. Adding employees with preferences")
    return


if __name__ == "__main__":
    seed()
