import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.audit import AuditLog
from app.core.config import get_settings
from app.core.errors import Conflict

log = logging.getLogger(__name__)
STATUSES = ("sent", "failed", "skipped")


@dataclass
class Letter:
    to: str | None
    subject: str
    body: str
    # shown when there is no address to send to, e.g. "Buyer has no email address"
    missing: str


# blank SMTP_HOST in .env: mail is off and nothing is sent
def enabled() -> bool:
    return bool(get_settings().smtp_host)


# per step: some wifi takes 5 s just to connect; sends run after the response, so nobody waits
TIMEOUT_S = 30


# STARTTLS on 587 (gmail)
def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.mail_from, to, subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=TIMEOUT_S) as smtp:
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
    if isinstance(e, TimeoutError):
        return "The mail server did not answer in time. Check the internet, then press Resend."
    return "Cannot reach the mail server. Is the internet on?"


def require_on() -> None:
    if not enabled():
        raise Conflict("Email is not set up on the server (SMTP_HOST in .env)", code="mail_off")


# one try, kept as an audit row "<kind>_email_<status>". A mail error never raises, so it can
# never undo the caller's work. Caller commits.
def attempt(
    db: Session, user_id: int | None, kind: str, entity: tuple[str, int], letter: Letter
) -> str:
    if not letter.to:
        status, data = "skipped", {"error": letter.missing}
    else:
        try:
            send(letter.to, letter.subject, letter.body)
            status, data = "sent", {"to": letter.to}
        except OSError as e:
            log.warning("%s email for %s %s failed: %s", kind, *entity, type(e).__name__)
            status, data = "failed", {"to": letter.to, "error": reason(e)}
    audit.record(db, user_id, f"{kind}_email_{status}", entity[0], entity[1], data=data)
    return status


# newest try of one kind, for the screen
def last_attempt(db: Session, kind: str, entity: tuple[str, int]) -> dict | None:
    actions = {f"{kind}_email_{s}": s for s in STATUSES}
    row = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_type == entity[0],
            AuditLog.entity_id == entity[1],
            AuditLog.action.in_(actions),
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    if not row:
        return None
    data = row.data or {}
    return {
        "status": actions[row.action],
        "at": row.created_at,
        "to": data.get("to"),
        "error": data.get("error"),
    }
