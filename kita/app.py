import os

import bcrypt
import streamlit as st
from sqlalchemy import Column, Integer, String, Boolean, DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from models import get_session as get_kita_session, KitaSettings
from seed import seed

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

    /* Hide Streamlit default elements */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { display: none; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Auto-seed on first run
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_db():
    seed()
    return True

_init_db()


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
                ["Dienstplan", "Mitarbeiter", "Gruppen"],
                horizontal=True,
                label_visibility="collapsed",
            )
        else:
            page = "Dienstplan"
            st.radio(
                "Navigation",
                ["Dienstplan"],
                horizontal=True,
                label_visibility="collapsed",
            )
    with out_col:
        if st.button("Abmelden", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    # Route to page
    if page == "Dienstplan":
        from pages.schedule import show_schedule
        show_schedule(user, editable=is_admin)
    elif page == "Mitarbeiter" and is_admin:
        from pages.employees import show_employees
        show_employees(user)
    elif page == "Gruppen" and is_admin:
        from pages.groups import show_groups
        show_groups(user)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if st.session_state.get("auth"):
        show_portal()
    else:
        show_login()


main()
