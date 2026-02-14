# J3Claw Management Portal & Kita Scheduler

A self-hosted management platform and German daycare staff scheduling system, built with Streamlit and deployed via Docker at [jan-miller.de](https://jan-miller.de).

---

## Overview

| App | URL | Port | Purpose |
|-----|-----|------|---------|
| **Management Portal** | `jan-miller.de/` | 8501 | User management, audit logging, email |
| **Kita Dienstplan** | `jan-miller.de/kita` | 8502 | Staff scheduling for daycare facilities |

Both apps share a dark indigo theme, SSO authentication, and run as separate Docker containers behind nginx.

---

## Management Portal

The portal provides admin tooling for the J3Claw platform.

### Features

- **Dashboard** — Stats overview (active users, logins, emails sent, audit events)
- **User Management** — Create, edit, and deactivate user accounts with role-based access (admin/user)
- **Mailbox** — View all outgoing emails (SMTP and locally stored)
- **Email Settings** — Configure Mailgun API integration with test email support
- **Audit Log** — Full action trail with filtering, timestamps, and actor tracking
- **SSO** — Seamless token-based handoff to the Kita app (HMAC-SHA256 signed, 60s expiry)

Regular users see only the Dashboard. Admin features are restricted by role.

### Tech Stack

- Python 3.12 / Streamlit 1.41.1
- SQLAlchemy 2.0 + SQLite (`portal.db`)
- bcrypt password hashing
- Mailgun HTTP API (optional) with SMTP fallback

---

## Kita Dienstplan (Scheduler)

A constraint-based staff scheduling system for German daycare centers (Kindertagesstätten). Manages employees, groups, absences, and auto-generates weekly schedules that comply with legal staffing ratios.

### Features

#### Schedule Management
- **Weekly grid view** — Visual HTML table with 30-minute time slots (07:00-17:00)
- **Color-coded shifts** — Warm tones for Krippe (infant care), cool tones for Elementar (preschool)
- **Coverage indicators** — Per-group staffing bars showing assigned vs. required staff
- **Core hours highlighting** — Visual emphasis on mandatory staffing periods (Kernzeit)
- **Shift CRUD** — Create, edit, and delete individual shifts with group assignment
- **Schedule lifecycle** — Draft, Published, and Archived statuses
- **Absence banner** — Shows who is out this week and why (vacation, sick, training)

#### Auto-Schedule Engine
- **Greedy constraint solver** — Assigns employees to groups per weekday respecting all hard constraints
- **Shift templates** — Early (07:00-15:30), Mid (08:00-16:00), Late (08:30-17:00), Short (08:00-14:00)
- **Hard constraints** — No early/late shift, fixed days off, contract hour limits, area restrictions
- **Soft preferences** — Preferred shift times, colleague pairings
- **Erstkraft priority** — Ensures each group has a qualified lead educator
- **Fairness optimization** — Balances hours across employees relative to contracts
- **Quality scores** — Coverage %, Fairness %, and Preference satisfaction %

#### Employee Management
- Full CRUD with role (Erstkraft/Zweitkraft) and area (Krippe/Elementar/Both)
- Contract hours and days-per-week tracking
- Weekly hours progress bars (scheduled vs. contracted)
- Restriction system: no early/late shift, fixed days off, max consecutive days, area-only, colleague preferences
- Absence management with types: Urlaub, Krank, Fortbildung, Sonstig

#### Group & Kita Settings
- Kita operating hours and core hours (Kernzeit)
- Group management with child capacity and staffing ratios
- Per-weekday expected child attendance (drives ratio calculations)
- Legal ratios: 1:4 Krippe, 1:10 Elementar (configurable)

#### Setup Wizard
First-time admin users are guided through a 3-step setup:
1. Kita settings (name, hours)
2. Groups (name, area, capacity, ratios)
3. Employees (name, role, area, contract)

### Staffing Ratio Logic

Required staff is calculated per group per weekday:

```
required = ceil(expected_children * ratio_num / ratio_den)
```

For example, a Krippe group with 12 children and a 1:4 ratio needs `ceil(12 * 1/4) = 3` staff.

---

## Architecture

```
nginx (jan-miller.de)
  |
  +-- / ---------> portal (8501)     portal.db
  |                    |                  ^
  |                    | SSO token        | read-only
  |                    v                  |
  +-- /kita -----> kita (8502)       kita.db
```

- **Separate databases** — Portal uses `portal.db`, Kita uses `kita.db`
- **Shared auth** — Kita mounts `portal.db` read-only for login validation
- **SSO tokens** — HMAC-SHA256 signed payloads with 60-second expiry, shared `SESSION_SECRET`
- **Docker volumes** — `portal_data` (shared) and `kita_data` (Kita-only)

### Database Schema

**Portal** (`portal.db`): Users, LoginEvents, LocalMail, AuditLog, Settings

**Kita** (`kita.db`):
| Table | Purpose |
|-------|---------|
| `kita_settings` | Facility name, operating hours, core hours |
| `groups` | Group name, area, child capacity, staffing ratio |
| `employees` | Staff with role, area, contract hours, days/week |
| `employee_restrictions` | Hard constraints and soft preferences per employee |
| `child_attendance` | Expected children per group per weekday |
| `schedules` | One row per week with status and quality scores |
| `shifts` | Individual shift assignments (employee, group, day, times) |
| `absences` | PTO, sick leave, training with date ranges |

---

## Project Structure

```
management-portal/
|-- app.py                        # Portal entry point
|-- database.py                   # Portal models (User, AuditLog, etc.)
|-- email_service.py              # Mailgun + SMTP + local email
|-- requirements.txt
|-- Dockerfile
|-- docker-compose.yml
|-- .streamlit/config.toml
|
|-- kita/
    |-- app.py                    # Kita entry point, SSO, setup wizard
    |-- models.py                 # Kita models (Employee, Schedule, etc.)
    |-- seed.py                   # Demo data generator
    |-- Dockerfile
    |-- requirements.txt
    |-- .streamlit/config.toml
    |-- pages/
    |   |-- schedule.py           # Week view grid, shift CRUD, auto-generate
    |   |-- employees.py          # Employee CRUD, absences, restrictions
    |   |-- groups.py             # Group settings, child attendance
    |-- engine/
        |-- constraints.py        # Validation rules, availability checks
        |-- scheduler.py          # Auto-schedule generation algorithm
        |-- scoring.py            # Quality score labels and colors
```

---

## Deployment

### Prerequisites

- Docker & Docker Compose
- nginx (reverse proxy)
- Domain with SSL (e.g. via Let's Encrypt)

### Quick Start

```bash
git clone https://github.com/j3claw-bot/management-portal.git
cd management-portal

# Set a secure shared secret for SSO
export SESSION_SECRET=$(openssl rand -hex 32)

# Build and run
docker compose up -d --build
```

The portal will be available at `localhost:8501` and the Kita app at `localhost:8502/kita`.

On first launch, log in with the default admin credentials shown on screen, then change the password.

### Nginx Configuration

```nginx
server {
    server_name jan-miller.de;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /kita/ {
        proxy_pass http://127.0.0.1:8502/kita/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
    }

    location /kita/_stcore/stream {
        proxy_pass http://127.0.0.1:8502/kita/_stcore/stream;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/app/data/portal.db` | Portal database path |
| `KITA_DB_PATH` | `/app/data/kita.db` | Kita database path |
| `PORTAL_DB_PATH` | `/app/portal_data/portal.db` | Portal DB path (read by Kita for auth) |
| `SESSION_SECRET` | generated | Shared HMAC key for SSO tokens |
| `SMTP_HOST` | — | SMTP server (optional) |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP username |
| `SMTP_PASS` | — | SMTP password |
| `SMTP_FROM` | `noreply@jan-miller.de` | Sender address |

### Seed Demo Data

To populate the Kita app with sample data (1 facility, 4 groups, 14 employees):

```bash
docker exec -it kita-scheduler python seed.py
```

Alternatively, use the built-in Setup Wizard on first admin login.

---

## License

Private repository. All rights reserved.
