from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from ..settings import settings

logger = logging.getLogger("cbc-notifications")


class NotificationService:
    def send_milestone_email(self, event_data: dict[str, Any]) -> bool:
        """Sends an HTML milestone progress email via SMTP if configured, or logs to console."""
        target_date = event_data.get("date", "Today")
        tier = event_data.get("milestone_tier", "100%")
        completed = event_data.get("completed_count", 0)
        target = event_data.get("target_count", 0)
        approved = event_data.get("approved_count", 0)

        subject = f"[CBC Generation Milestone] {tier} Reached for {target_date} ({completed}/{target} items)"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
                <h2 style="color: #2563eb; margin-top: 0;">CBC Content Production Milestone Reached</h2>
                <p>The automated generation pipeline has achieved the <strong>{tier}</strong> milestone for <strong>{target_date}</strong>.</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px; border: 1px solid #cbd5e1;"><strong>Milestone Tier:</strong></td>
                        <td style="padding: 10px; border: 1px solid #cbd5e1; color: #16a34a; font-weight: bold;">{tier}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #cbd5e1;"><strong>Completed Items:</strong></td>
                        <td style="padding: 10px; border: 1px solid #cbd5e1;">{completed} of {target}</td>
                    </tr>
                    <tr style="background: #f8fafc;">
                        <td style="padding: 10px; border: 1px solid #cbd5e1;"><strong>Approved by Quality Gates:</strong></td>
                        <td style="padding: 10px; border: 1px solid #cbd5e1;">{approved}</td>
                    </tr>
                </table>

                <p style="font-size: 12px; color: #64748b; margin-top: 30px;">
                    This is an automated notification from the CBC API Platform.
                </p>
            </div>
        </body>
        </html>
        """

        if not settings.smtp_host or not settings.smtp_user:
            logger.info("SMTP not configured. Milestone alert: %s", subject)
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from
            msg["To"] = ", ".join(settings.email_recipients)
            msg.attach(MIMEText(html_body, "html"))

            if settings.smtp_secure:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10.0)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10.0)
                server.starttls()

            if settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)

            server.sendmail(settings.smtp_from, settings.email_recipients, msg.as_string())
            server.quit()
            logger.info("Milestone email for tier %s sent successfully to %s", tier, settings.email_recipients)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send milestone email via SMTP: %s", exc)
            return False


notification_service = NotificationService()
