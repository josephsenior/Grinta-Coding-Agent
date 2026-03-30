"""Email service for sending transactional emails."""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

from backend.core.logger import app_logger as logger


class EmailService:
    """Service for sending emails via SMTP."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        smtp_use_tls: bool = True,
        from_email: str | None = None,
        from_name: str = "App",
    ):
        """Initialize email service.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_password: SMTP password
            smtp_use_tls: Whether to use TLS
            from_email: Sender email address
            from_name: Sender name
        """
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.getenv("SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
        self.smtp_use_tls = smtp_use_tls
        self.from_email = from_email or os.getenv("SMTP_FROM_EMAIL") or self.smtp_user
        self.from_name = from_name
        self.enabled = bool(self.smtp_host and self.smtp_user and self.smtp_password)

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML email body
            text_body: Plain text email body (optional)

        Returns:
            True if email was sent successfully, False otherwise
        """
        if not self.enabled:
            logger.warning(
                "Email service is not configured. Set SMTP_HOST, SMTP_USER, and SMTP_PASSWORD environment variables."
            )
            return False

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email

            # Add text and HTML parts
            if text_body:
                text_part = MIMEText(text_body, "plain")
                msg.attach(text_part)

            html_part = MIMEText(html_body, "html")
            msg.attach(html_part)

            # Send email
            # Type narrowing: self.enabled ensures these are not None
            assert self.smtp_host is not None, "SMTP host must be set"
            assert self.smtp_user is not None, "SMTP user must be set"
            assert self.smtp_password is not None, "SMTP password must be set"

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.smtp_use_tls:
                    server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("Password reset email sent to %s", to_email)
            return True

        except Exception as e:
            logger.error("Failed to send email to %s: %s", to_email, e, exc_info=True)
            return False

    def send_password_reset_email(
        self,
        to_email: str,
        reset_token: str,
        reset_url: str | None = None,
    ) -> bool:
        """Send password reset email.

        Args:
            to_email: Recipient email address
            reset_token: Password reset token
            reset_url: Full reset URL (if not provided, will be constructed from base URL)

        Returns:
            True if email was sent successfully, False otherwise
        """
        # Construct reset URL if not provided
        if not reset_url:
            base_url = os.getenv("APP_BASE_URL", "http://localhost:3000")
            params = urlencode({"token": reset_token, "email": to_email})
            reset_url = f"{base_url}/auth/reset-password?{params}"

        subject = "Reset Your App Password"

        # HTML email body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset Your Password</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
            <div style="background-color: #000000; padding: 30px; border-radius: 8px; margin-bottom: 20px;">
                <h1 style="color: #ffffff; margin: 0; font-size: 24px;">Reset Your Password</h1>
            </div>
            <div style="background-color: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <p style="color: #333; font-size: 16px; margin-bottom: 20px;">
                    Hello,
                </p>
                <p style="color: #333; font-size: 16px; margin-bottom: 20px;">
                    We received a request to reset your password for your App account. Click the button below to reset your password:
                </p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="display: inline-block; background: linear-gradient(to right, #8b5cf6, #7c3aed); color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 6px; font-weight: 600; font-size: 16px;">
                        Reset Password
                    </a>
                </div>
                <p style="color: #666; font-size: 14px; margin-top: 30px; margin-bottom: 10px;">
                    Or copy and paste this link into your browser:
                </p>
                <p style="color: #8b5cf6; font-size: 12px; word-break: break-all; background-color: #f5f5f5; padding: 10px; border-radius: 4px; margin: 0;">
                    {reset_url}
                </p>
                <p style="color: #666; font-size: 14px; margin-top: 30px; margin-bottom: 10px;">
                    This link will expire in 1 hour.
                </p>
                <p style="color: #666; font-size: 14px; margin-top: 20px;">
                    If you didn't request a password reset, you can safely ignore this email. Your password will not be changed.
                </p>
            </div>
            <div style="text-align: center; margin-top: 20px; color: #999; font-size: 12px;">
                <p>© {datetime.now().year} App. All rights reserved.</p>
            </div>
        </body>
        </html>
        """

        # Plain text email body
        text_body = f"""
Reset Your App Password

Hello,

We received a request to reset your password for your App account. Click the link below to reset your password:

{reset_url}

This link will expire in 1 hour.

If you didn't request a password reset, you can safely ignore this email. Your password will not be changed.

© {datetime.now().year} App. All rights reserved.
        """

        return self.send_email(to_email, subject, html_body, text_body)


# Global email service instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get or create the global email service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
