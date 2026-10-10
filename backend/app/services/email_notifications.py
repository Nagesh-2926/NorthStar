"""Optional SMTP notifications. Delivery failures never roll back saved workflows."""
from email.message import EmailMessage
import logging
import smtplib

from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class EmailNotificationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_from_email)

    def send(self, recipient: str | None, subject: str, body: str, *, event: str) -> bool:
        if not self.configured or not recipient:
            return False
        message = EmailMessage()
        message["From"] = self.settings.smtp_from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port,
                              timeout=self.settings.smtp_timeout_seconds) as client:
                if self.settings.smtp_starttls:
                    client.starttls()
                if self.settings.smtp_username:
                    password = (self.settings.smtp_password.get_secret_value()
                                if self.settings.smtp_password else "")
                    client.login(self.settings.smtp_username, password)
                client.send_message(message)
            return True
        except Exception as exc:
            # Do not leak SMTP credentials, recipient addresses, or message contents to logs.
            logger.warning("SMTP notification failed for event %s (%s)", event, type(exc).__name__)
            return False
