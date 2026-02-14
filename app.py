import streamlit as st
from auth import authenticate

st.set_page_config(
    page_title="Management Portal | jan-miller.de",
    page_icon="🔒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Custom CSS ---
st.markdown(
    """
<style>
    /* Hide default streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Login card */
    .login-container {
        max-width: 420px;
        margin: 6rem auto;
        padding: 2.5rem;
        background: #1E293B;
        border-radius: 16px;
        border: 1px solid #334155;
        box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
    }
    .login-title {
        text-align: center;
        font-size: 1.8rem;
        font-weight: 700;
        color: #F1F5F9;
        margin-bottom: 0.25rem;
    }
    .login-subtitle {
        text-align: center;
        color: #94A3B8;
        font-size: 0.95rem;
        margin-bottom: 2rem;
    }

    /* Portal header */
    .portal-header {
        text-align: center;
        padding: 2rem 0 1rem;
    }
    .portal-header h1 {
        font-size: 2rem;
        font-weight: 700;
        color: #F1F5F9;
        margin-bottom: 0.25rem;
    }
    .portal-header p {
        color: #94A3B8;
        font-size: 1.05rem;
    }

    /* App cards */
    .app-card {
        background: #1E293B;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 1.75rem;
        text-align: center;
        transition: all 0.2s ease;
        height: 100%;
        min-height: 200px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .app-card:hover {
        border-color: #4F46E5;
        box-shadow: 0 0 20px rgba(79,70,229,0.15);
        transform: translateY(-2px);
    }
    .app-icon {
        font-size: 2.5rem;
        margin-bottom: 0.75rem;
    }
    .app-name {
        font-size: 1.15rem;
        font-weight: 600;
        color: #F1F5F9;
        margin-bottom: 0.35rem;
    }
    .app-desc {
        color: #94A3B8;
        font-size: 0.85rem;
        line-height: 1.4;
    }
    .app-badge {
        display: inline-block;
        background: #312E81;
        color: #A5B4FC;
        font-size: 0.7rem;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        margin-top: 0.75rem;
        font-weight: 600;
    }

    /* Top bar */
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem 0;
        border-bottom: 1px solid #334155;
        margin-bottom: 1rem;
    }
    .topbar-brand {
        font-size: 1.1rem;
        font-weight: 700;
        color: #A5B4FC;
    }
    .topbar-user {
        color: #94A3B8;
        font-size: 0.9rem;
    }

    /* Streamlit overrides for inputs */
    .stTextInput > div > div > input {
        background: #0F172A;
        border: 1px solid #334155;
        border-radius: 8px;
        color: #E2E8F0;
        padding: 0.6rem 0.75rem;
    }
    .stTextInput > div > div > input:focus {
        border-color: #4F46E5;
        box-shadow: 0 0 0 2px rgba(79,70,229,0.3);
    }
    div.stButton > button {
        width: 100%;
        background: #4F46E5;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.5rem;
        font-weight: 600;
        font-size: 0.95rem;
    }
    div.stButton > button:hover {
        background: #4338CA;
        border: none;
        color: white;
    }
</style>
""",
    unsafe_allow_html=True,
)

# --- Sub-apps registry ---
APPS = [
    {
        "name": "Analytics Dashboard",
        "icon": "📊",
        "desc": "Real-time metrics and business intelligence",
        "status": "Coming Soon",
    },
    {
        "name": "User Management",
        "icon": "👥",
        "desc": "Manage users, roles, and permissions",
        "status": "Coming Soon",
    },
    {
        "name": "File Manager",
        "icon": "📁",
        "desc": "Upload, organize, and share files",
        "status": "Coming Soon",
    },
    {
        "name": "API Gateway",
        "icon": "🔗",
        "desc": "Monitor and manage API endpoints",
        "status": "Coming Soon",
    },
    {
        "name": "Notifications",
        "icon": "🔔",
        "desc": "Configure alerts and notification channels",
        "status": "Coming Soon",
    },
    {
        "name": "Settings",
        "icon": "⚙️",
        "desc": "System configuration and preferences",
        "status": "Coming Soon",
    },
]


def show_login():
    st.markdown(
        '<div class="login-container">'
        '<div class="login-title">Management Portal</div>'
        '<div class="login-subtitle">jan-miller.de</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input(
                "Password", type="password", placeholder="Enter your password"
            )
            submitted = st.form_submit_button("Sign In")

            if submitted:
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    user = authenticate(username, password)
                    if user:
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = user
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")


def show_portal():
    user = st.session_state["user"]

    # Top bar
    st.markdown(
        f'<div class="topbar">'
        f'<span class="topbar-brand">🔒 Management Portal</span>'
        f'<span class="topbar-user">Signed in as <strong>{user["name"]}</strong> ({user["role"]})</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # Logout button
    col1, col2 = st.columns([9, 1])
    with col2:
        if st.button("Sign Out"):
            st.session_state.clear()
            st.rerun()

    # Header
    st.markdown(
        '<div class="portal-header">'
        "<h1>Your Applications</h1>"
        "<p>Select an application to get started</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    # App grid
    cols = st.columns(3)
    for i, app in enumerate(APPS):
        with cols[i % 3]:
            st.markdown(
                f'<div class="app-card">'
                f'<div class="app-icon">{app["icon"]}</div>'
                f'<div class="app-name">{app["name"]}</div>'
                f'<div class="app-desc">{app["desc"]}</div>'
                f'<span class="app-badge">{app["status"]}</span>'
                f"</div>",
                unsafe_allow_html=True,
            )
            st.write("")  # spacing


# --- Main ---
if st.session_state.get("authenticated"):
    show_portal()
else:
    show_login()
