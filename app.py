import logging
import sys
from datetime import datetime, timezone

import streamlit as st

from auth import authenticate, generate_password, hash_password, init_admin
from database import LoginEvent, User, get_session
from email_service import is_configured as smtp_configured
from email_service import send_welcome_email

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

st.set_page_config(
    page_title="J3Claw Portal",
    page_icon="🦀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Initialise admin on first run ──────────────────────────────────────
admin_pw = init_admin()
if admin_pw:
    logging.info("Initial admin password: %s", admin_pw)

# ── CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
#MainMenu,footer,header{visibility:hidden}
.login-wrap{max-width:400px;margin:5rem auto;padding:2.5rem;background:#1E293B;
  border-radius:16px;border:1px solid #334155;box-shadow:0 25px 50px -12px rgba(0,0,0,.5)}
.brand{text-align:center;margin-bottom:1.5rem}
.brand .icon{font-size:3rem}
.brand h1{font-size:1.6rem;font-weight:700;color:#F1F5F9;margin:.25rem 0 0}
.brand p{color:#94A3B8;font-size:.9rem}
.topbar{display:flex;justify-content:space-between;align-items:center;padding:1rem 0;
  border-bottom:1px solid #334155;margin-bottom:.5rem}
.topbar-brand{font-size:1.1rem;font-weight:700;color:#A5B4FC}
.topbar-user{color:#94A3B8;font-size:.85rem}
.stat-card{background:#1E293B;border:1px solid #334155;border-radius:12px;padding:1.25rem;text-align:center}
.stat-val{font-size:1.8rem;font-weight:700;color:#F1F5F9}
.stat-lbl{color:#94A3B8;font-size:.8rem;margin-top:.25rem}
.section-hdr{font-size:1.15rem;font-weight:600;color:#F1F5F9;margin:1.5rem 0 .75rem;
  padding-bottom:.5rem;border-bottom:1px solid #334155}
</style>
""",
    unsafe_allow_html=True,
)


# ── Helpers ────────────────────────────────────────────────────────────
def _ago(dt: datetime | None) -> str:
    if dt is None:
        return "Never"
    now = datetime.now(timezone.utc)
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    delta = now - dt_utc
    secs = int(delta.total_seconds())
    if secs < 60:
        return "Just now"
    if secs < 3600:
        m = secs // 60
        return f"{m}m ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h}h ago"
    d = secs // 86400
    return f"{d}d ago"


# ══════════════════════════════════════════════════════════════════════
#  LOGIN
# ══════════════════════════════════════════════════════════════════════
def show_login():
    st.markdown(
        '<div class="login-wrap"><div class="brand">'
        '<div class="icon">🦀</div>'
        "<h1>J3Claw Portal</h1>"
        "<p>Management Portal</p>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login"):
            user = st.text_input("Username", placeholder="Username")
            pw = st.text_input("Password", type="password", placeholder="Password")
            go = st.form_submit_button("Sign In")
            if go:
                if not user or not pw:
                    st.error("Enter username and password.")
                else:
                    result = authenticate(user, pw)
                    if result:
                        st.session_state["auth"] = True
                        st.session_state["user"] = result
                        st.rerun()
                    else:
                        st.error("Invalid credentials.")


# ══════════════════════════════════════════════════════════════════════
#  PORTAL  (after login)
# ══════════════════════════════════════════════════════════════════════
def show_portal():
    user = st.session_state["user"]

    # ── top bar ──
    st.markdown(
        f'<div class="topbar">'
        f'<span class="topbar-brand">🦀 J3Claw Portal</span>'
        f'<span class="topbar-user">Signed in as <strong>{user["name"]}</strong> ({user["role"]})</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # Navigation
    col_nav, _, col_out = st.columns([6, 2, 1])
    with col_nav:
        if user["role"] == "admin":
            page = st.radio(
                "Navigation",
                ["Dashboard", "User Management"],
                horizontal=True,
                label_visibility="collapsed",
            )
        else:
            page = "Dashboard"
    with col_out:
        if st.button("Sign Out"):
            st.session_state.clear()
            st.rerun()

    if page == "Dashboard":
        show_dashboard(user)
    elif page == "User Management":
        show_user_management()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════
def show_dashboard(user: dict):
    session = get_session()
    try:
        db_user = session.query(User).get(user["id"])
        total_users = session.query(User).filter_by(is_active=True).count()
        total_logins = session.query(LoginEvent).count()
        recent_events = (
            session.query(LoginEvent)
            .order_by(LoginEvent.logged_in_at.desc())
            .limit(10)
            .all()
        )

        st.markdown('<div class="section-hdr">Overview</div>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{total_users}</div>'
                f'<div class="stat-lbl">Active Users</div></div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{total_logins}</div>'
                f'<div class="stat-lbl">Total Logins</div></div>',
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{db_user.login_count if db_user else 0}</div>'
                f'<div class="stat-lbl">Your Logins</div></div>',
                unsafe_allow_html=True,
            )
        with c4:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{_ago(db_user.last_login) if db_user else "N/A"}</div>'
                f'<div class="stat-lbl">Last Login</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div class="section-hdr">Recent Activity</div>', unsafe_allow_html=True
        )
        if recent_events:
            rows = []
            for ev in recent_events:
                ev_user = session.query(User).get(ev.user_id)
                ts = ev.logged_in_at.replace(tzinfo=timezone.utc) if ev.logged_in_at.tzinfo is None else ev.logged_in_at
                rows.append(
                    {
                        "User": ev_user.username if ev_user else "?",
                        "Name": ev_user.name if ev_user else "?",
                        "Time": ts.strftime("%Y-%m-%d %H:%M UTC"),
                        "IP": ev.ip_address or "—",
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No login events yet.")

        # ── Your profile summary ──
        if db_user:
            st.markdown(
                '<div class="section-hdr">Your Profile</div>', unsafe_allow_html=True
            )
            pc1, pc2 = st.columns(2)
            with pc1:
                st.text_input("Username", db_user.username, disabled=True)
                st.text_input("Name", db_user.name, disabled=True)
            with pc2:
                st.text_input("Email", db_user.email, disabled=True)
                st.text_input("Role", db_user.role, disabled=True)
                created = db_user.created_at.replace(tzinfo=timezone.utc) if db_user.created_at.tzinfo is None else db_user.created_at
                st.text_input(
                    "Member since",
                    created.strftime("%Y-%m-%d"),
                    disabled=True,
                )
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  USER MANAGEMENT  (admin only)
# ══════════════════════════════════════════════════════════════════════
def show_user_management():
    session = get_session()
    try:
        users = session.query(User).order_by(User.id).all()

        st.markdown(
            '<div class="section-hdr">Users</div>', unsafe_allow_html=True
        )

        rows = []
        for u in users:
            last = u.last_login
            if last:
                last = last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last
                last_str = last.strftime("%Y-%m-%d %H:%M UTC")
            else:
                last_str = "Never"
            rows.append(
                {
                    "ID": u.id,
                    "Username": u.username,
                    "Name": u.name,
                    "Email": u.email,
                    "Role": u.role,
                    "Active": "Yes" if u.is_active else "No",
                    "Logins": u.login_count,
                    "Last Login": last_str,
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        # ── Create user ──
        st.markdown(
            '<div class="section-hdr">Create User</div>', unsafe_allow_html=True
        )
        with st.form("create_user", clear_on_submit=True):
            cc1, cc2 = st.columns(2)
            with cc1:
                new_username = st.text_input("Username *")
                new_name = st.text_input("Full Name *")
                new_role = st.selectbox("Role", ["user", "admin"])
            with cc2:
                new_email = st.text_input("Email *")
                new_password = st.text_input(
                    "Password (leave blank to auto-generate)", type="password"
                )
            create = st.form_submit_button("Create User")

            if create:
                if not new_username or not new_name or not new_email:
                    st.error("Username, name, and email are required.")
                elif session.query(User).filter_by(username=new_username).first():
                    st.error(f"Username '{new_username}' already exists.")
                elif session.query(User).filter_by(email=new_email).first():
                    st.error(f"Email '{new_email}' already in use.")
                else:
                    pw = new_password or generate_password()
                    u = User(
                        username=new_username,
                        email=new_email,
                        password_hash=hash_password(pw),
                        name=new_name,
                        role=new_role,
                    )
                    session.add(u)
                    session.commit()

                    email_sent = send_welcome_email(new_email, new_name, new_username)
                    email_msg = " Welcome email sent." if email_sent else ""

                    if not new_password:
                        st.success(
                            f"User **{new_username}** created. "
                            f"Generated password: `{pw}`{email_msg}"
                        )
                    else:
                        st.success(
                            f"User **{new_username}** created.{email_msg}"
                        )
                    st.rerun()

        # ── Edit / deactivate ──
        st.markdown(
            '<div class="section-hdr">Edit User</div>', unsafe_allow_html=True
        )
        usernames = [u.username for u in users]
        if usernames:
            sel = st.selectbox("Select user", usernames, key="edit_sel")
            sel_user = session.query(User).filter_by(username=sel).first()
            if sel_user:
                with st.form("edit_user"):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        edit_name = st.text_input("Name", sel_user.name)
                        edit_email = st.text_input("Email", sel_user.email)
                    with ec2:
                        edit_role = st.selectbox(
                            "Role",
                            ["user", "admin"],
                            index=0 if sel_user.role == "user" else 1,
                        )
                        edit_active = st.checkbox("Active", sel_user.is_active)
                        reset_pw = st.text_input(
                            "Reset password (leave blank to keep)", type="password"
                        )
                    save = st.form_submit_button("Save Changes")

                    if save:
                        sel_user.name = edit_name
                        sel_user.email = edit_email
                        sel_user.role = edit_role
                        sel_user.is_active = edit_active
                        if reset_pw:
                            sel_user.password_hash = hash_password(reset_pw)
                        session.commit()
                        st.success(f"User **{sel}** updated.")
                        st.rerun()
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════
if st.session_state.get("auth"):
    show_portal()
else:
    show_login()
