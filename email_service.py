import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database import LocalMail, get_session

log = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@jan-miller.de")


def _smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS)


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


def send_welcome_email(to_email: str, name: str, username: str) -> bool:
    subject = "Welcome to J3Claw Management Portal"

    body_text = (
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

    sent_smtp = False
    if _smtp_configured():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(html, "html"))
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_FROM, to_email, msg.as_string())
            sent_smtp = True
            log.info("Welcome email sent via SMTP to %s", to_email)
        except Exception:
            log.exception("SMTP send failed for %s", to_email)

    _store_locally(to_email, subject, body_text, sent_smtp)

    if not sent_smtp:
        log.info("Welcome email stored locally for %s (SMTP %s)",
                 to_email, "failed" if _smtp_configured() else "not configured")

    return sent_smtp
