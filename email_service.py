import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from database import LocalMail, get_session, get_setting

log = logging.getLogger(__name__)

# Legacy SMTP config from environment (still supported as fallback)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@jan-miller.de")


def _smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


def _mailgun_configured() -> bool:
    api_key = get_setting("mailgun_api_key")
    domain = get_setting("mailgun_domain")
    return bool(api_key and domain)


def _get_mailgun_config() -> dict:
    return {
        "api_key": get_setting("mailgun_api_key"),
        "domain": get_setting("mailgun_domain"),
        "from_address": get_setting("mailgun_from", "J3Claw Portal <noreply@jan-miller.de>"),
    }


def _store_locally(to_email: str, subject: str, body_text: str, sent_via_smtp: bool):
    session = get_session()
    try:
        session.add(
            LocalMail(
                to_email=to_email,
                subject=subject,
                body_text=body_text,
                sent_via_smtp=sent_via_smtp,
            )
        )
        session.commit()
    finally:
        session.close()


def send_via_mailgun(to_email: str, subject: str, text: str, html: str | None = None) -> tuple[bool, str]:
    """Send email via Mailgun HTTP API. Returns (success, message)."""
    cfg = _get_mailgun_config()
    if not cfg["api_key"] or not cfg["domain"]:
        return False, "Mailgun not configured"

    url = f"https://api.mailgun.net/v3/{cfg['domain']}/messages"
    data = {
        "from": cfg["from_address"],
        "to": [to_email],
        "subject": subject,
        "text": text,
    }
    if html:
        data["html"] = html

    try:
        resp = requests.post(
            url,
            auth=("api", cfg["api_key"]),
            data=data,
            timeout=10,
        )
        if resp.status_code == 200:
            msg_id = resp.json().get("id", "")
            log.info("Mailgun sent to %s: %s", to_email, msg_id)
            return True, f"Sent (ID: {msg_id})"
        else:
            error = resp.json().get("message", resp.text)
            log.warning("Mailgun error %d: %s", resp.status_code, error)
            return False, f"Mailgun error {resp.status_code}: {error}"
    except Exception as e:
        log.exception("Mailgun request failed for %s", to_email)
        return False, f"Request failed: {e}"


def send_test_email(to_email: str) -> tuple[bool, str]:
    """Send a test email via Mailgun. Returns (success, message)."""
    subject = "J3Claw Portal — Test Email"
    text = (
        "This is a test email from the J3Claw Management Portal.\n\n"
        "If you received this, your Mailgun integration is working correctly.\n\n"
        "— J3Claw Portal"
    )
    html = """\
<html>
<body style="margin:0;padding:0;background:#0F172A;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:520px;margin:40px auto;background:#1E293B;border-radius:12px;border:1px solid #334155;overflow:hidden;">
    <div style="background:#4F46E5;padding:28px 32px;text-align:center;">
      <span style="font-size:32px;">&#129408;</span>
      <h1 style="color:#fff;margin:8px 0 0;font-size:22px;">J3Claw Management Portal</h1>
    </div>
    <div style="padding:32px;">
      <p style="color:#E2E8F0;font-size:16px;margin-top:0;">Test Email</p>
      <p style="color:#CBD5E1;font-size:15px;line-height:1.6;">
        If you received this, your Mailgun integration is working correctly.
      </p>
      <div style="background:#065F46;border-radius:8px;padding:16px 20px;margin:20px 0;text-align:center;">
        <span style="color:#6EE7B7;font-size:14px;font-weight:600;">&#10003; Mailgun Connected</span>
      </div>
    </div>
  </div>
</body>
</html>"""

    success, message = send_via_mailgun(to_email, subject, text, html)
    _store_locally(to_email, subject, text, success)
    return success, message


def _build_welcome_email(name: str, username: str) -> tuple[str, str]:
    """Return (text, html) for the welcome email."""
    text = (
        f"Hi {name},\n\n"
        f"Welcome to the J3Claw Management Portal!\n\n"
        f"Your account has been created with the username: {username}\n\n"
        f"You can sign in at https://jan-miller.de\n\n"
        f"If you did not expect this email, please ignore it.\n\n"
        f"— J3Claw Portal"
    )

    html = f"""\
<html>
<body style="margin:0;padding:0;background:#0F172A;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:520px;margin:40px auto;background:#1E293B;border-radius:12px;border:1px solid #334155;overflow:hidden;">
    <div style="background:#4F46E5;padding:28px 32px;text-align:center;">
      <span style="font-size:32px;">&#129408;</span>
      <h1 style="color:#fff;margin:8px 0 0;font-size:22px;">J3Claw Management Portal</h1>
    </div>
    <div style="padding:32px;">
      <p style="color:#E2E8F0;font-size:16px;margin-top:0;">Hi {name},</p>
      <p style="color:#CBD5E1;font-size:15px;line-height:1.6;">
        Welcome! Your account has been created successfully.
      </p>
      <table style="background:#0F172A;border-radius:8px;padding:16px 20px;margin:20px 0;width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:10px 20px;color:#94A3B8;font-size:13px;">Username</td>
          <td style="padding:10px 20px;color:#E2E8F0;font-size:14px;font-weight:600;">{username}</td>
        </tr>
      </table>
      <div style="text-align:center;margin:28px 0 12px;">
        <a href="https://jan-miller.de" style="background:#4F46E5;color:#fff;text-decoration:none;padding:12px 32px;border-radius:8px;font-weight:600;font-size:15px;display:inline-block;">
          Sign In
        </a>
      </div>
      <p style="color:#64748B;font-size:12px;text-align:center;margin-top:24px;">
        If you did not expect this email, please ignore it.
      </p>
    </div>
  </div>
</body>
</html>"""

    return text, html


def send_welcome_email(to_email: str, name: str, username: str) -> bool:
    subject = "Welcome to J3Claw Management Portal"
    text, html = _build_welcome_email(name, username)

    sent = False

    # Try Mailgun first
    if _mailgun_configured():
        sent, msg = send_via_mailgun(to_email, subject, text, html)
        if sent:
            _store_locally(to_email, subject, text, sent)
            return True
        log.warning("Mailgun failed, falling back: %s", msg)

    # Fallback to SMTP
    if _smtp_configured():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_email, msg.as_string())
            sent = True
            log.info("Welcome email sent via SMTP to %s", to_email)
        except Exception:
            log.exception("SMTP send failed for %s", to_email)

    _store_locally(to_email, subject, text, sent)

    if not sent:
        log.info("Welcome email stored locally for %s (no send method available)", to_email)

    return sent
