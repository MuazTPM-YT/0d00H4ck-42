import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


# blank SMTP_HOST in .env: mail is off and nothing is sent
def enabled() -> bool:
    return bool(get_settings().smtp_host)


# STARTTLS on 587 (gmail); 10 s timeout so a dead network fails fast instead of hanging
def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.mail_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


# plain words for the order page; never the password, never a stack trace
def reason(e: OSError) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "Mail login refused: check SMTP_USER and the app password in .env"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "The mail server refused this address"
    if isinstance(e, smtplib.SMTPException):
        return f"Mail server said no: {e}"[:300]
    return "Cannot reach the mail server. Is the internet on?"
