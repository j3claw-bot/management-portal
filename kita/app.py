import base64
import hashlib
import hmac
import json
import os
import time

import bcrypt
import streamlit as st
from sqlalchemy import Column, Integer, String, Boolean, DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from models import get_session as get_kita_session, KitaSettings, Employee, Group, EmployeeRestriction

SESSION_SECRET = os.environ.get("SESSION_SECRET", "j3claw-default-session-key-change-me").encode()

# ---------------------------------------------------------------------------
# Portal auth DB (read-only for authentication)
# ---------------------------------------------------------------------------

PORTAL_DB_PATH = os.environ.get("PORTAL_DB_PATH", "/app/portal_data/portal.db")

_portal_engine = None
_PortalSession = None


class PortalBase(DeclarativeBase):
    pass


class PortalUser(PortalBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(120), nullable=False)
    email = Column(String(255))
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, default=True)


def _get_portal_session():
    global _portal_engine, _PortalSession
    if _portal_engine is None:
        _portal_engine = create_engine(f"sqlite:///{PORTAL_DB_PATH}", echo=False)
    if _PortalSession is None:
        _PortalSession = sessionmaker(bind=_portal_engine)
    return _PortalSession()


def authenticate(username: str, password: str) -> dict | None:
    session = _get_portal_session()
    try:
        user = session.query(PortalUser).filter_by(username=username, is_active=True).first()
        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "email": user.email,
                "role": user.role,
            }
        return None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Page config & custom CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Kita Dienstplan",
    page_icon="\U0001F3E0",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    /* Login */
    .login-wrap {
        max-width: 420px;
        margin: 4rem auto;
        padding: 2rem;
        border-radius: 12px;
        background: #1E293B;
    }
    .brand {
        text-align: center;
        margin-bottom: 1.5rem;
    }
    .brand h1 { font-size: 1.8rem; margin: 0; }
    .brand p { color: #94A3B8; font-size: 0.9rem; }

    /* Topbar */
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.6rem 1rem;
        background: #1E293B;
        border-radius: 8px;
        margin-bottom: 0.5rem;
    }
    .topbar .user-info { color: #94A3B8; font-size: 0.9rem; }

    /* Stat cards */
    .stat-card {
        background: #1E293B;
        padding: 1rem 1.2rem;
        border-radius: 8px;
        text-align: center;
    }
    .stat-card .label { color: #94A3B8; font-size: 0.8rem; text-transform: uppercase; }
    .stat-card .value { font-size: 1.6rem; font-weight: 700; color: #E2E8F0; }

    /* Section headers */
    .section-hdr {
        font-size: 1.1rem;
        font-weight: 600;
        border-bottom: 2px solid #4F46E5;
        padding-bottom: 0.4rem;
        margin: 1.5rem 0 1rem;
    }

    /* Schedule grid */
    .schedule-grid {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }
    .schedule-grid th {
        background: #1E293B;
        color: #94A3B8;
        padding: 6px 8px;
        text-align: center;
        border: 1px solid #334155;
        position: sticky;
        top: 0;
        z-index: 10;
    }
    .schedule-grid td {
        padding: 4px 6px;
        border: 1px solid #334155;
        vertical-align: top;
        min-width: 140px;
        height: 28px;
    }
    .schedule-grid .time-col {
        background: #1E293B;
        color: #94A3B8;
        text-align: right;
        font-size: 0.8rem;
        min-width: 50px;
        width: 60px;
    }
    .shift-block {
        border-radius: 4px;
        padding: 2px 6px;
        margin: 1px 0;
        font-size: 0.8rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .shift-krippe { background: #92400E; color: #FDE68A; }
    .shift-elementar { background: #1E3A5F; color: #93C5FD; }
    .shift-break { background: repeating-linear-gradient(45deg, #334155, #334155 4px, #475569 4px, #475569 8px); }

    /* Coverage bar */
    .coverage-bar {
        height: 6px;
        border-radius: 3px;
        background: #334155;
        margin-top: 4px;
    }
    .coverage-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.3s;
    }
    .coverage-ok { background: #22C55E; }
    .coverage-warn { background: #EAB308; }
    .coverage-bad { background: #EF4444; }

    /* Hide Streamlit default elements and sidebar */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { display: none; }
    section[data-testid="stSidebar"] { display: none; }
    button[kind="header"] { display: none; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# SSO token validation
# ---------------------------------------------------------------------------

def _validate_sso_token(token: str) -> dict | None:
    """Validate an HMAC-signed SSO token. Returns user dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected = hmac.new(SESSION_SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return {
            "id": payload["id"], "username": payload["u"],
            "name": payload["n"], "email": payload["e"], "role": payload["r"],
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Setup wizard (first-time configuration)
# ---------------------------------------------------------------------------

def _needs_setup() -> bool:
    session = get_kita_session()
    try:
        has_groups = session.query(Group).count() > 0
        has_employees = session.query(Employee).count() > 0
        return not (has_groups and has_employees)
    finally:
        session.close()


def show_setup_wizard(user: dict):
    from models import KitaSettings, ChildAttendance
    st.markdown(
        '<div style="max-width:700px;margin:2rem auto;">'
        '<div class="brand"><h1>Kita Dienstplan — Ersteinrichtung</h1>'
        '<p style="color:#94A3B8;">Schritt für Schritt einrichten</p></div></div>',
        unsafe_allow_html=True,
    )

    session = get_kita_session()
    try:
        step = st.session_state.get("setup_step", 1)

        # Step 1: Kita settings
        if step == 1:
            st.markdown('<div class="section-hdr">Schritt 1: Kita-Einstellungen</div>',
                        unsafe_allow_html=True)
            with st.form("setup_kita"):
                kita_name = st.text_input("Name der Kita", value="Kita Sonnenschein")
                c1, c2 = st.columns(2)
                with c1:
                    open_time = st.text_input("Öffnungszeit", value="07:00")
                    core_start = st.text_input("Kernzeit Beginn", value="09:00")
                with c2:
                    close_time = st.text_input("Schließzeit", value="17:00")
                    core_end = st.text_input("Kernzeit Ende", value="15:00")

                if st.form_submit_button("Weiter", use_container_width=True):
                    kita = session.query(KitaSettings).first()
                    if kita:
                        kita.name = kita_name.strip()
                        kita.open_time = open_time.strip()
                        kita.close_time = close_time.strip()
                        kita.core_start = core_start.strip()
                        kita.core_end = core_end.strip()
                    else:
                        session.add(KitaSettings(
                            name=kita_name.strip(), open_time=open_time.strip(),
                            close_time=close_time.strip(), core_start=core_start.strip(),
                            core_end=core_end.strip(),
                        ))
                    session.commit()
                    st.session_state["setup_step"] = 2
                    st.rerun()

        # Step 2: Groups
        elif step == 2:
            st.markdown('<div class="section-hdr">Schritt 2: Gruppen anlegen</div>',
                        unsafe_allow_html=True)

            groups = session.query(Group).all()
            if groups:
                st.dataframe([{
                    "Name": g.name,
                    "Bereich": "Krippe" if g.area == "krippe" else "Elementar",
                    "Max. Kinder": g.max_children,
                    "Schlüssel": f"{g.ratio_num}:{g.ratio_den}",
                } for g in groups], use_container_width=True, hide_index=True)

            with st.form("setup_group", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    g_name = st.text_input("Gruppenname", placeholder="z.B. Marienkäfer")
                    g_area = st.selectbox("Bereich", ["krippe", "elementar"],
                                          format_func=lambda k: "Krippe" if k == "krippe" else "Elementar")
                with c2:
                    g_max = st.number_input("Max. Kinder", min_value=1, max_value=30, value=12)
                    g_ratio = st.number_input("Betreuungsschlüssel (Kinder pro Fachkraft)",
                                              min_value=1, max_value=15,
                                              value=4 if g_area == "krippe" else 10)

                fc1, fc2 = st.columns(2)
                with fc1:
                    add_group = st.form_submit_button("Gruppe hinzufügen", use_container_width=True)
                with fc2:
                    next_step = st.form_submit_button("Weiter zu Mitarbeitern", use_container_width=True)

                if add_group and g_name:
                    kita = session.query(KitaSettings).first()
                    g = Group(name=g_name.strip(), area=g_area, min_children=0,
                              max_children=g_max, ratio_num=1, ratio_den=g_ratio)
                    session.add(g)
                    session.flush()
                    for day in range(5):
                        session.add(ChildAttendance(
                            group_id=g.id, weekday=day, expected_children=g_max - 2,
                            arrival_time=kita.open_time if kita else "07:00",
                            departure_time=kita.close_time if kita else "17:00",
                        ))
                    session.commit()
                    st.success(f"Gruppe '{g_name}' angelegt.")
                    st.rerun()
                elif next_step:
                    if not groups:
                        st.error("Bitte mindestens eine Gruppe anlegen.")
                    else:
                        st.session_state["setup_step"] = 3
                        st.rerun()

        # Step 3: Employees
        elif step == 3:
            st.markdown('<div class="section-hdr">Schritt 3: Mitarbeiter anlegen</div>',
                        unsafe_allow_html=True)

            employees = session.query(Employee).all()
            if employees:
                emp_list = []
                for e in employees:
                    prefs = session.query(EmployeeRestriction).filter_by(employee_id=e.id).all()
                    pref_str = ", ".join([r.restriction_type.replace("_", " ").title() for r in prefs]) if prefs else "—"
                    emp_list.append({
                        "Name": f"{e.first_name} {e.last_name}",
                        "Rolle": "Erstkraft" if e.role == "erstkraft" else "Zweitkraft",
                        "Bereich": {"krippe": "Krippe", "elementar": "Elementar", "both": "Beide"}.get(e.area, e.area),
                        "Stunden/Wo": e.contract_hours,
                        "Präferenzen": pref_str,
                    })
                st.dataframe(emp_list, use_container_width=True, hide_index=True)

            with st.form("setup_employee", clear_on_submit=True):
                st.markdown("**Mitarbeiterdaten**")
                c1, c2 = st.columns(2)
                with c1:
                    e_first = st.text_input("Vorname")
                    e_role = st.selectbox("Rolle", ["erstkraft", "zweitkraft"],
                                          format_func=lambda k: "Erstkraft" if k == "erstkraft" else "Zweitkraft")
                    e_hours = st.number_input("Vertragsstunden/Woche", min_value=5.0, max_value=42.0,
                                              value=39.0, step=0.5)
                with c2:
                    e_last = st.text_input("Nachname")
                    e_area = st.selectbox("Bereich", ["krippe", "elementar", "both"],
                                          format_func=lambda k: {"krippe": "Krippe", "elementar": "Elementar", "both": "Beide"}[k])
                    e_days = st.number_input("Tage/Woche", min_value=1, max_value=5, value=5)

                st.markdown("**Präferenzen & Einschränkungen** (optional)")
                p1, p2 = st.columns(2)
                with p1:
                    no_early = st.checkbox("Kein Frühdienst")
                    prefers_early = st.checkbox("Bevorzugt Frühdienst")
                    fixed_day_off = st.selectbox("Fester freier Tag",
                                                  ["Keiner", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag"])
                with p2:
                    no_late = st.checkbox("Kein Spätdienst")
                    prefers_late = st.checkbox("Bevorzugt Spätdienst")
                    max_consecutive = st.number_input("Max. aufeinanderfolgende Tage",
                                                      min_value=0, max_value=5, value=0,
                                                      help="0 = keine Einschränkung")

                fc1, fc2 = st.columns(2)
                with fc1:
                    add_emp = st.form_submit_button("Mitarbeiter hinzufügen", use_container_width=True)
                with fc2:
                    finish = st.form_submit_button("Einrichtung abschließen", use_container_width=True)

                if add_emp and e_first and e_last:
                    emp = Employee(
                        first_name=e_first.strip(), last_name=e_last.strip(),
                        role=e_role, area=e_area, contract_hours=e_hours, days_per_week=e_days,
                    )
                    session.add(emp)
                    session.flush()  # Get employee ID

                    # Add restrictions/preferences
                    if no_early:
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="no_early_shift", value="true"
                        ))
                    if no_late:
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="no_late_shift", value="true"
                        ))
                    if prefers_early:
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="prefers_early", value="true"
                        ))
                    if prefers_late:
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="prefers_late", value="true"
                        ))
                    if fixed_day_off != "Keiner":
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="fixed_day_off", value=fixed_day_off
                        ))
                    if max_consecutive > 0:
                        session.add(EmployeeRestriction(
                            employee_id=emp.id, restriction_type="max_consecutive_days", value=str(max_consecutive)
                        ))

                    session.commit()
                    st.success(f"{e_first} {e_last} angelegt.")
                    st.rerun()
                elif finish:
                    if not employees:
                        st.error("Bitte mindestens einen Mitarbeiter anlegen.")
                    else:
                        st.session_state.pop("setup_step", None)
                        st.rerun()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Navigation & routing
# ---------------------------------------------------------------------------

def show_login():
    st.markdown('<div class="login-wrap">', unsafe_allow_html=True)
    st.markdown("""
    <div class="brand">
        <h1>Kita Dienstplan</h1>
        <p>J3Claw Management</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("Benutzername")
        password = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Anmelden", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("Bitte Benutzername und Passwort eingeben.")
            else:
                user = authenticate(username, password)
                if user:
                    st.session_state["auth"] = True
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Anmeldung fehlgeschlagen.")

    st.markdown("</div>", unsafe_allow_html=True)


def show_portal():
    user = st.session_state["user"]
    is_admin = user["role"] == "admin"

    # Check if setup wizard is needed
    if is_admin and _needs_setup():
        show_setup_wizard(user)
        return

    # Top bar with branding + user info + sign out
    role_badge = "Admin" if is_admin else "Benutzer"
    st.markdown(
        f'<div class="topbar">'
        f'<span style="color:#A5B4FC;font-weight:700;">Kita Dienstplan</span>'
        f'<span class="user-info">{user["name"]} <small>({role_badge})</small></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Navigation via st.radio (preserves session state)
    nav_col, _, out_col = st.columns([6, 2, 1])
    with nav_col:
        if is_admin:
            page = st.radio(
                "Navigation",
                ["Dashboard", "Dienstplan", "Mitarbeiter", "Gruppen", "Druckansicht"],
                horizontal=True,
                label_visibility="collapsed",
            )
        else:
            page = st.radio(
                "Navigation",
                ["Dashboard", "Dienstplan"],
                horizontal=True,
                label_visibility="collapsed",
            )
    with out_col:
        if st.button("Abmelden", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # Route to page
    if page == "Dashboard":
        from pages.dashboard import show_dashboard
        show_dashboard(user)
    elif page == "Dienstplan":
        from pages.schedule import show_schedule
        show_schedule(user, editable=is_admin)
    elif page == "Mitarbeiter" and is_admin:
        from pages.employees import show_employees
        show_employees(user)
    elif page == "Gruppen" and is_admin:
        from pages.groups import show_groups
        show_groups(user)
    elif page == "Druckansicht":
        from pages.print_view import show_print_view
        show_print_view(user)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Check for SSO token in query params
    sso_token = st.query_params.get("sso")
    if sso_token and not st.session_state.get("auth"):
        user = _validate_sso_token(sso_token)
        if user:
            st.session_state["auth"] = True
            st.session_state["user"] = user
            st.query_params.clear()
            st.rerun()

    if st.session_state.get("auth"):
        show_portal()
    else:
        show_login()


main()
