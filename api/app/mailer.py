"""Sending email through a Mail Server connection (Admin > Connections, kind "smtp").

A connection's config (validated by `validate_config`):

    {"host": "smtp.gmail.com", "port": 587, "security": "starttls" | "tls" | "none",
     "from_address": "reports@example.com.kh", "from_name": "Aksor Khmer BI" | None,
     "auth": {"type": "basic", "username": ..., "password_secret" | "password_env": ...} | None}

The password is a Secret's name (or an environment variable's), never a value -- the same rule every connection
follows; `resolve` turns it into the password for one sending session.

Everything a person can type ends up in headers that are checked: addresses must look like addresses, and a
subject never carries a line break (which could otherwise add headers). Khmer in the subject, the sender's name or
an attachment's file name is encoded the standard way (RFC 2047 / RFC 2231), so it arrives readable.

Failures are sorted the way a job needs them: `MailError.retryable` is True for what may pass on its own (the
server unreachable, a 4xx "try later"), False for what won't (bad password, a refused address, a 5xx).
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .report_data import DataConfigError

_log = logging.getLogger("aksor_khmer_bi.mailer")

SECURITY = ("starttls", "tls", "none")
TIMEOUT_SECONDS = 30
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
MAX_RECIPIENTS = 50


def max_attachment_bytes() -> int:
    """MAIL_MAX_ATTACHMENT_MB (default 10): bigger reports fail with a clear message instead of bouncing."""
    raw = os.environ.get("MAIL_MAX_ATTACHMENT_MB", "").strip()
    megabytes = int(raw) if raw.isdigit() and int(raw) > 0 else 10
    return megabytes * 1024 * 1024


class MailError(RuntimeError):
    """A message safe to show an administrator (no password, no server banner with internals)."""

    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


# --- the connection's config ------------------------------------------------------------------------------------


def validate_address(value: object, where: str) -> str:
    if not isinstance(value, str) or not EMAIL_RE.match(value.strip()) or len(value.strip()) > 254:
        raise DataConfigError(f"{where}: {value!r} doesn't look like an email address (name@example.com)")
    return value.strip()


def validate_addresses(values: object, where: str, *, required: bool = False) -> list[str]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise DataConfigError(f"{where} must be a list of email addresses")
    cleaned: list[str] = []
    for value in values:
        address = validate_address(value, where)
        if address.lower() not in (a.lower() for a in cleaned):
            cleaned.append(address)
    if required and not cleaned:
        raise DataConfigError(f"{where}: add at least one email address")
    if len(cleaned) > MAX_RECIPIENTS:
        raise DataConfigError(f"{where}: at most {MAX_RECIPIENTS} addresses")
    return cleaned


def validate_config(config: dict, secret_names: set[str] | None) -> dict:
    """A Mail Server connection's config, normalized. Raises DataConfigError with a message for the form."""
    from . import report_data

    host = (config.get("host") or "").strip()
    if not host or not re.match(r"^[A-Za-z0-9.-]+$", host):
        raise DataConfigError("Enter the mail server's host name, e.g. smtp.gmail.com")
    port = config.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise DataConfigError("Enter the mail server's port (587 for STARTTLS, 465 for TLS)")
    security = config.get("security") or "starttls"
    if security not in SECURITY:
        raise DataConfigError("Security is STARTTLS, TLS or none")
    from_address = validate_address(config.get("from_address"), "From address")
    from_name = (config.get("from_name") or "").strip() or None
    if from_name and (len(from_name) > 100 or any(ch in from_name for ch in "\r\n")):
        raise DataConfigError("The From name must be one line of at most 100 characters")
    auth = config.get("auth") or None
    if auth is not None:
        if auth.get("type") != "basic" or not (auth.get("username") or "").strip():
            raise DataConfigError("Signing in to the mail server needs a username and a password")
        _, auth = report_data._validate_headers_and_auth({"auth": auth}, "mail server", secret_names)
    if security == "none" and auth is not None:
        # A password sent in the clear can be read by anyone on the network path.
        raise DataConfigError("Signing in needs STARTTLS or TLS, so the password isn't sent in the clear")
    return {"host": host, "port": port, "security": security, "from_address": from_address, "from_name": from_name, "auth": auth}


def display(config: dict) -> str:
    """Where a Mail Server connection points, for lists and the audit trail."""
    return f"smtp://{config.get('host', '')}:{config.get('port', '')} · {config.get('from_address', '')}"


# --- building and sending -----------------------------------------------------------------------------------------


@dataclass
class Attachment:
    file_name: str
    content: bytes


@dataclass
class Message:
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    attachment: Attachment | None = None


def _one_line(text: str) -> str:
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def build(server: dict, message: Message) -> EmailMessage:
    email = EmailMessage()
    email["From"] = formataddr((server.get("from_name") or "", server["from_address"]))
    email["To"] = ", ".join(message.to)
    if message.cc:
        email["Cc"] = ", ".join(message.cc)
    email["Subject"] = _one_line(message.subject)[:300]
    email["Message-ID"] = make_msgid(domain=server["from_address"].split("@", 1)[1])
    email.set_content(message.body or "")
    if message.attachment is not None:
        kind, _ = mimetypes.guess_type(message.attachment.file_name)
        maintype, subtype = (kind or "application/octet-stream").split("/", 1)
        email.add_attachment(message.attachment.content, maintype=maintype, subtype=subtype, filename=message.attachment.file_name)
    return email


def _open(server: dict) -> smtplib.SMTP:
    from . import jdbc

    try:
        jdbc.assert_resolves_safely(server["host"])  # never a link-local / metadata address, whatever DNS says today
    except Exception as exc:
        raise MailError("The mail server's address isn't allowed or doesn't resolve", retryable=False) from exc
    context = ssl.create_default_context()
    try:
        if server["security"] == "tls":
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(server["host"], server["port"], timeout=TIMEOUT_SECONDS, context=context)
        else:
            smtp = smtplib.SMTP(server["host"], server["port"], timeout=TIMEOUT_SECONDS)
            if server["security"] == "starttls":
                smtp.starttls(context=context)
        if server.get("password") is not None:
            smtp.login(server["username"], server["password"])
        return smtp
    except smtplib.SMTPAuthenticationError as exc:
        _log.warning("Mail server %s refused the sign-in: %s", server["host"], exc)
        raise MailError("The mail server refused the username or password", retryable=False) from exc
    except (smtplib.SMTPException, OSError) as exc:
        _log.warning("Couldn't reach mail server %s:%s: %s", server["host"], server["port"], exc)
        raise MailError("Couldn't reach the mail server", retryable=True) from exc


class Session:
    """One sign-in to the mail server for several messages -- a bursting run sends one per branch."""

    def __init__(self, server: dict):
        self.server = server
        self.smtp: smtplib.SMTP | None = None

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        if self.smtp is not None:
            try:
                self.smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def send(self, message: Message) -> str | None:
        """Sends one message. Returns None, or -- when the server took it for some recipients and refused others --
        which addresses were refused (it *was* delivered, so it isn't a failure to re-send to everyone). Raises
        MailError when nobody got it; the session stays usable for the next message when it can."""
        if message.attachment is not None and len(message.attachment.content) > max_attachment_bytes():
            limit = max_attachment_bytes() // (1024 * 1024)
            raise MailError(f"The report is larger than {limit} MB, too big to attach (MAIL_MAX_ATTACHMENT_MB)", retryable=False)
        if self.smtp is None:
            self.smtp = _open(self.server)
        email = build(self.server, message)
        try:
            refused = self.smtp.send_message(email, from_addr=self.server["from_address"], to_addrs=message.to + message.cc)
        except smtplib.SMTPRecipientsRefused as exc:
            raise MailError(_refused(exc.recipients), retryable=False) from exc
        except smtplib.SMTPResponseException as exc:
            self._drop()
            reason = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
            raise MailError(f"The mail server refused it: {reason[:200]} ({exc.smtp_code})", retryable=400 <= exc.smtp_code < 500) from exc
        except (smtplib.SMTPException, OSError) as exc:
            self._drop()
            _log.warning("Sending through %s failed: %s", self.server["host"], exc)
            raise MailError("The connection to the mail server broke while sending", retryable=True) from exc
        return _refused(refused) if refused else None

    def _drop(self) -> None:
        try:
            if self.smtp is not None:
                self.smtp.close()
        finally:
            self.smtp = None


def _refused(recipients: dict) -> str:
    parts = []
    for address, (code, reason) in list(recipients.items())[:5]:
        text = reason.decode(errors="replace") if isinstance(reason, bytes) else str(reason)
        parts.append(f"{address}: {text[:120]} ({code})")
    return "The mail server refused " + "; ".join(parts)
