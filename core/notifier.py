"""
Notification system for JobApplierBot.
Sends alerts via email on key events (application submitted, errors, daily summary).
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class NotificationEvent:
    """Represents a notification event."""
    event_type: str  # "application_submitted", "error", "daily_summary", "info"
    title: str
    message: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class EmailNotifier:
    """Send notifications via SMTP email."""

    def __init__(self, smtp_server: str, smtp_port: int,
                 sender_email: str, sender_password: str,
                 recipient_email: Optional[str] = None):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.recipient_email = recipient_email or sender_email

    def send(self, event: NotificationEvent) -> bool:
        """Send an email notification."""
        if not self.sender_email or not self.sender_password:
            logger.warning("Email not configured. Skipping notification.")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = self.recipient_email
            msg["Subject"] = f"[JobBot] {event.title}"

            body = f"""
{event.title}
{'=' * len(event.title)}

Time: {event.timestamp}
Type: {event.event_type}

{event.message}

---
JobApplierBot Automated Notification
            """

            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            logger.info(f"Email notification sent: {event.title}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.warning("SMTP Authentication failed: Invalid SENDER_EMAIL or SENDER_PASSWORD (App Password required for Gmail). Skipping email notification.")
            return False
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False


class Notifier:
    """Multi-channel notification dispatcher."""

    def __init__(self, email_notifier: Optional[EmailNotifier] = None):
        self.email_notifier = email_notifier
        self._event_log: List[NotificationEvent] = []

    def notify(self, event_type: str, title: str, message: str) -> None:
        """Send a notification through all configured channels."""
        event = NotificationEvent(
            event_type=event_type,
            title=title,
            message=message,
        )
        self._event_log.append(event)

        # Console
        icon = {
            "application_submitted": "[OK]",
            "error": "[ERROR]",
            "daily_summary": "[STATS]",
            "info": "[INFO]",
            "warning": "[WARN]",
        }.get(event_type, "[NOTE]")
        logger.info(f"{icon} [{event_type}] {title}: {message[:100]}")

        # Email
        if self.email_notifier:
            self.email_notifier.send(event)

    def application_submitted(self, job_title: str, company: str,
                               ats_score: float = 0) -> None:
        """Notify that an application was submitted."""
        self.notify(
            "application_submitted",
            f"Applied: {job_title} at {company}",
            f"Successfully applied to {job_title} at {company}.\nATS Score: {ats_score:.1f}",
        )

    def application_failed(self, job_title: str, company: str, reason: str) -> None:
        """Notify that an application failed."""
        self.notify(
            "error",
            f"Failed: {job_title} at {company}",
            f"Application failed for {job_title} at {company}.\nReason: {reason}",
        )

    def daily_summary(self, total_applied: int, successful: int, failed: int,
                      avg_ats: float) -> None:
        """Send daily summary notification."""
        self.notify(
            "daily_summary",
            f"Daily Summary - {datetime.now().strftime('%Y-%m-%d')}",
            f"Applications: {total_applied}\n"
            f"Successful: {successful}\n"
            f"Failed: {failed}\n"
            f"Avg ATS Score: {avg_ats:.1f}",
        )

    def get_event_log(self) -> List[NotificationEvent]:
        """Get all notification events from this session."""
        return self._event_log.copy()
