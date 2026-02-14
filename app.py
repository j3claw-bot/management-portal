import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import streamlit as st

from auth import authenticate, generate_password, hash_password, init_admin
from database import AuditLog, LocalMail, LoginEvent, User, audit, get_session, get_setting, set_setting
from email_service import send_test_email, send_welcome_email

SESSION_SECRET = os.environ.get("SESSION_SECRET", "j3claw-default-session-key-change-me").encode()


def _make_sso_token(user: dict) -> str:
    """Generate a short-lived HMAC-signed token for SSO handoff."""
    payload = json.dumps({
        "id": user["id"], "u": user["username"], "n": user["name"],
        "e": user["email"], "r": user["role"], "exp": int(time.time()) + 60,
    }, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(SESSION_SECRET, payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"

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
    # Store it so the very first page load shows it
    st.session_state.setdefault("_init_admin_pw", admin_pw)

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
.pw-box{background:#1a1a2e;border:1px solid #4F46E5;border-radius:8px;padding:1rem 1.25rem;
  margin:.75rem 0;font-family:monospace;font-size:1.1rem;color:#A5B4FC;letter-spacing:.5px}
.mail-card{background:#1E293B;border:1px solid #334155;border-radius:8px;padding:1rem;margin:.5rem 0}
.mail-to{color:#A5B4FC;font-size:.85rem;font-weight:600}
.mail-subj{color:#E2E8F0;font-size:.95rem;margin:.25rem 0}
.mail-time{color:#64748B;font-size:.75rem}
.mail-badge-smtp{background:#065F46;color:#6EE7B7;font-size:.7rem;padding:.15rem .5rem;border-radius:999px}
.mail-badge-local{background:#78350F;color:#FCD34D;font-size:.7rem;padding:.15rem .5rem;border-radius:999px}
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


def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    dt_utc = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return dt_utc.strftime("%Y-%m-%d %H:%M UTC")


# ══════════════════════════════════════════════════════════════════════
#  LOGIN
# ══════════════════════════════════════════════════════════════════════
def show_login():
    # Show initial admin password on very first run
    if "_init_admin_pw" in st.session_state:
        st.warning(
            f"**First run — initial admin credentials:**  \n"
            f"Username: `admin`  \n"
            f"Password: `{st.session_state['_init_admin_pw']}`  \n"
            f"Change this immediately after logging in."
        )

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
                        st.session_state.pop("_init_admin_pw", None)
                        audit(user, "login", detail="Successful login")
                        st.rerun()
                    else:
                        audit(user, "login_failed", detail="Invalid credentials")
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
                ["Dashboard", "User Management", "Mailbox", "Email Settings", "Audit Log"],
                horizontal=True,
                label_visibility="collapsed",
            )
        else:
            page = st.radio(
                "Navigation",
                ["Dashboard"],
                horizontal=True,
                label_visibility="collapsed",
            )
    with col_out:
        if st.button("Sign Out"):
            audit(user["username"], "logout")
            st.session_state.clear()
            st.rerun()

    # Kita link with SSO token
    sso_token = _make_sso_token(user)
    st.markdown(
        f'<div style="margin:-0.5rem 0 1rem;"><a href="/kita/?sso={sso_token}" target="_self" '
        f'style="color:#A5B4FC;text-decoration:none;font-size:0.9rem;">'
        f'&#127968; Kita Dienstplan &rarr;</a></div>',
        unsafe_allow_html=True,
    )

    if page == "Dashboard":
        show_dashboard(user)
    elif page == "User Management":
        show_user_management(user)
    elif page == "Mailbox":
        show_mailbox()
    elif page == "Email Settings":
        show_email_settings(user)
    elif page == "Audit Log":
        show_audit_log()


# ══════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════════════
def show_dashboard(user: dict):
    session = get_session()
    try:
        db_user = session.query(User).get(user["id"])
        total_users = session.query(User).filter_by(is_active=True).count()
        total_logins = session.query(LoginEvent).count()
        total_mails = session.query(LocalMail).count()
        total_audit = session.query(AuditLog).count()

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

        if user["role"] == "admin":
            st.markdown("")
            c5, c6, c7, c8 = st.columns(4)
            with c5:
                st.markdown(
                    f'<div class="stat-card"><div class="stat-val">{total_mails}</div>'
                    f'<div class="stat-lbl">Emails Sent</div></div>',
                    unsafe_allow_html=True,
                )
            with c6:
                st.markdown(
                    f'<div class="stat-card"><div class="stat-val">{total_audit}</div>'
                    f'<div class="stat-lbl">Audit Events</div></div>',
                    unsafe_allow_html=True,
                )
            with c7:
                inactive = session.query(User).filter_by(is_active=False).count()
                st.markdown(
                    f'<div class="stat-card"><div class="stat-val">{inactive}</div>'
                    f'<div class="stat-lbl">Inactive Users</div></div>',
                    unsafe_allow_html=True,
                )
            with c8:
                never_logged = (
                    session.query(User)
                    .filter_by(is_active=True)
                    .filter(User.last_login.is_(None))
                    .count()
                )
                st.markdown(
                    f'<div class="stat-card"><div class="stat-val">{never_logged}</div>'
                    f'<div class="stat-lbl">Never Logged In</div></div>',
                    unsafe_allow_html=True,
                )

        if user["role"] == "admin":
            st.markdown(
                '<div class="section-hdr">Recent Activity</div>', unsafe_allow_html=True
            )
            recent_events = (
                session.query(LoginEvent)
                .order_by(LoginEvent.logged_in_at.desc())
                .limit(10)
                .all()
            )
            if recent_events:
                rows = []
                for ev in recent_events:
                    ev_user = session.query(User).get(ev.user_id)
                    rows.append(
                        {
                            "User": ev_user.username if ev_user else "?",
                            "Name": ev_user.name if ev_user else "?",
                            "Time": _ts(ev.logged_in_at),
                            "IP": ev.ip_address or "—",
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)
            else:
                st.info("No login events yet.")

        # ── Your profile ──
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
                st.text_input(
                    "Member since",
                    _ts(db_user.created_at).split(" ")[0] if db_user.created_at else "—",
                    disabled=True,
                )
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  USER MANAGEMENT  (admin only)
# ══════════════════════════════════════════════════════════════════════
def show_user_management(current_user: dict):
    session = get_session()
    try:
        users = session.query(User).order_by(User.id).all()

        st.markdown('<div class="section-hdr">Users</div>', unsafe_allow_html=True)

        rows = []
        for u in users:
            rows.append(
                {
                    "ID": u.id,
                    "Username": u.username,
                    "Name": u.name,
                    "Email": u.email,
                    "Role": u.role,
                    "Active": "Yes" if u.is_active else "No",
                    "Logins": u.login_count,
                    "Last Login": _ts(u.last_login) if u.last_login else "Never",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        # ── Show pending generated password ──
        if "created_user_info" in st.session_state:
            info = st.session_state["created_user_info"]
            st.success(f"User **{info['username']}** created successfully.")
            if info.get("generated_pw"):
                st.markdown(
                    f"**Generated password — copy it now, it won't be shown again:**"
                )
                st.markdown(
                    f'<div class="pw-box">{info["generated_pw"]}</div>',
                    unsafe_allow_html=True,
                )
            if info.get("email_smtp"):
                st.info("Welcome email sent via SMTP.")
            else:
                st.info("Welcome email saved to local mailbox (SMTP not configured).")
            if st.button("Dismiss", key="dismiss_pw"):
                del st.session_state["created_user_info"]
                st.rerun()

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
                    audit(
                        current_user["username"],
                        "user_created",
                        target=new_username,
                        detail=f"Role: {new_role}, Email: {new_email}",
                    )

                    # Persist the result in session state so it survives rerun
                    st.session_state["created_user_info"] = {
                        "username": new_username,
                        "generated_pw": pw if not new_password else None,
                        "email_smtp": email_sent,
                    }
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
                        changes = []
                        if sel_user.name != edit_name:
                            changes.append(f"name: {sel_user.name} -> {edit_name}")
                        if sel_user.email != edit_email:
                            changes.append(f"email: {sel_user.email} -> {edit_email}")
                        if sel_user.role != edit_role:
                            changes.append(f"role: {sel_user.role} -> {edit_role}")
                        if sel_user.is_active != edit_active:
                            changes.append(f"active: {sel_user.is_active} -> {edit_active}")
                        if reset_pw:
                            changes.append("password reset")

                        sel_user.name = edit_name
                        sel_user.email = edit_email
                        sel_user.role = edit_role
                        sel_user.is_active = edit_active
                        if reset_pw:
                            sel_user.password_hash = hash_password(reset_pw)
                        session.commit()

                        audit(
                            current_user["username"],
                            "user_edited",
                            target=sel,
                            detail="; ".join(changes) if changes else "no changes",
                        )
                        st.success(f"User **{sel}** updated.")
                        st.rerun()
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  MAILBOX  (admin only)
# ══════════════════════════════════════════════════════════════════════
def show_mailbox():
    session = get_session()
    try:
        mails = (
            session.query(LocalMail)
            .order_by(LocalMail.created_at.desc())
            .limit(50)
            .all()
        )

        smtp_count = sum(1 for m in mails if m.sent_via_smtp)
        local_count = len(mails) - smtp_count

        st.markdown('<div class="section-hdr">Local Mailbox</div>', unsafe_allow_html=True)
        st.caption(
            f"All outgoing emails are stored here. "
            f"{smtp_count} sent via SMTP, {local_count} local only."
        )

        if not mails:
            st.info("No emails yet.")
            return

        for m in mails:
            badge = (
                '<span class="mail-badge-smtp">SMTP</span>'
                if m.sent_via_smtp
                else '<span class="mail-badge-local">Local Only</span>'
            )
            st.markdown(
                f'<div class="mail-card">'
                f'<div class="mail-to">To: {m.to_email} {badge}</div>'
                f'<div class="mail-subj">{m.subject}</div>'
                f'<div class="mail-time">{_ts(m.created_at)}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
            with st.expander("View content"):
                st.text(m.body_text)
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  EMAIL SETTINGS  (admin only)
# ══════════════════════════════════════════════════════════════════════
def show_email_settings(user: dict):
    st.markdown('<div class="section-hdr">Mailgun Configuration</div>', unsafe_allow_html=True)

    # Current values
    current_key = get_setting("mailgun_api_key")
    current_domain = get_setting("mailgun_domain")
    current_from = get_setting("mailgun_from", "J3Claw Portal <noreply@jan-miller.de>")

    # Status indicator
    if current_key and current_domain:
        st.markdown(
            '<span style="background:#065F46;color:#6EE7B7;padding:4px 12px;'
            'border-radius:4px;font-size:0.85rem;font-weight:600;">Configured</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span style="background:#78350F;color:#FCD34D;padding:4px 12px;'
            'border-radius:4px;font-size:0.85rem;font-weight:600;">Not Configured</span>',
            unsafe_allow_html=True,
        )

    st.caption(
        "Mailgun is used to send emails (welcome messages, notifications). "
        "Emails are always stored in the local mailbox regardless of send status."
    )

    with st.form("mailgun_settings"):
        mg_key = st.text_input(
            "API Key",
            value=current_key,
            type="password",
            help="Your Mailgun API key (starts with a hex string)",
        )
        mg_domain = st.text_input(
            "Domain",
            value=current_domain,
            help="e.g. sandbox433c19c564e6454198ed913dd9375da2.mailgun.org",
        )
        mg_from = st.text_input(
            "From Address",
            value=current_from,
            help='e.g. J3Claw Portal <postmaster@yourdomain.mailgun.org>',
        )

        if st.form_submit_button("Save Settings", use_container_width=True):
            set_setting("mailgun_api_key", mg_key.strip())
            set_setting("mailgun_domain", mg_domain.strip())
            set_setting("mailgun_from", mg_from.strip())
            audit(user["username"], "mailgun_configured", detail=f"Domain: {mg_domain.strip()}")
            st.success("Mailgun settings saved.")
            st.rerun()

    # Test email
    st.markdown('<div class="section-hdr">Send Test Email</div>', unsafe_allow_html=True)

    if not current_key or not current_domain:
        st.info("Save your Mailgun settings above first.")
    else:
        with st.form("test_email"):
            test_to = st.text_input("Recipient", value=user.get("email", ""))
            if st.form_submit_button("Send Test Email", use_container_width=True):
                if not test_to:
                    st.error("Please enter a recipient email address.")
                else:
                    with st.spinner("Sending..."):
                        success, message = send_test_email(test_to.strip())
                    if success:
                        st.success(f"Test email sent to {test_to}.")
                        audit(user["username"], "test_email_sent", target=test_to)
                    else:
                        st.error(f"Failed: {message}")
                        audit(user["username"], "test_email_failed", target=test_to, detail=message)


# ══════════════════════════════════════════════════════════════════════
#  AUDIT LOG  (admin only)
# ══════════════════════════════════════════════════════════════════════
def show_audit_log():
    session = get_session()
    try:
        st.markdown('<div class="section-hdr">Audit Log</div>', unsafe_allow_html=True)

        # Filters
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            actions = [r[0] for r in session.query(AuditLog.action).distinct().all()]
            sel_action = st.selectbox("Filter by action", ["All"] + sorted(actions))
        with fc2:
            actors = [r[0] for r in session.query(AuditLog.actor).distinct().all()]
            sel_actor = st.selectbox("Filter by user", ["All"] + sorted(actors))
        with fc3:
            limit = st.selectbox("Show last", [50, 100, 250, 500], index=0)

        q = session.query(AuditLog)
        if sel_action != "All":
            q = q.filter(AuditLog.action == sel_action)
        if sel_actor != "All":
            q = q.filter(AuditLog.actor == sel_actor)
        logs = q.order_by(AuditLog.timestamp.desc()).limit(limit).all()

        # Stats row
        total = session.query(AuditLog).count()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_count = (
            session.query(AuditLog)
            .filter(AuditLog.timestamp >= today_start)
            .count()
        )
        failed_logins = (
            session.query(AuditLog)
            .filter(AuditLog.action == "login_failed")
            .count()
        )

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{total}</div>'
                f'<div class="stat-lbl">Total Events</div></div>',
                unsafe_allow_html=True,
            )
        with sc2:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{today_count}</div>'
                f'<div class="stat-lbl">Events Today</div></div>',
                unsafe_allow_html=True,
            )
        with sc3:
            st.markdown(
                f'<div class="stat-card"><div class="stat-val">{failed_logins}</div>'
                f'<div class="stat-lbl">Failed Logins (all time)</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("")
        if logs:
            rows = []
            for entry in logs:
                rows.append(
                    {
                        "Time": _ts(entry.timestamp),
                        "User": entry.actor,
                        "Action": entry.action,
                        "Target": entry.target or "—",
                        "Detail": entry.detail or "—",
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No audit events match your filters.")
    finally:
        session.close()


# ══════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════
if st.session_state.get("auth"):
    show_portal()
else:
    show_login()
