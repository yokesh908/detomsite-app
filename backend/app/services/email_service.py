"""Email service for sending emails.

Delivery order: Resend HTTP API when ``RESEND_API_KEY`` is set (the easiest,
most reliable path — no SMTP server to maintain), then SMTP when ``SMTP_HOST``
is configured (see app.core.config). With neither, it falls back to logging the
email body so the flow still works in development. Forgot-password OTPs are
only ever delivered by email — the API never returns the code.
"""
import asyncio
import logging
import smtplib

import httpx
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(settings.SMTP_HOST)


def _send_smtp(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Deliver an email over SMTP. Returns True when accepted by the server.
    smtplib is blocking, so callers must run this off the event loop — the
    public EmailService methods wrap it in asyncio.to_thread."""
    if not _smtp_configured():
        # No mail server configured. Log clearly (warning in production) so a
        # "successful" reset email is never silently swallowed.
        if settings.DEBUG:
            logger.info(
                f"[EMAIL] To: {to_email} | Subject: {subject}\n"
                f"{text_body}"
            )
        else:
            logger.warning(
                f"[EMAIL] SMTP not configured — could NOT deliver to {to_email} | Subject: {subject}"
            )
        return True

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM
    message["To"] = to_email
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        server.ehlo()
        if settings.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], message.as_string())
        server.quit()
        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Error sending email to {to_email} ({subject}): {e}")
        return False


async def _send_resend(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Deliver over the Resend HTTP API (https://resend.com). Chosen over SMTP
    for better deliverability; no new dependency needed — httpx is already a
    backend dependency."""
    payload = {
        "from": settings.RESEND_FROM or settings.SMTP_FROM,
        "to": [to_email],
        "subject": subject,
        "text": text_body,
        "html": html_body,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
        if response.status_code < 300:
            logger.info(f"Email sent to {to_email} via Resend: {subject}")
            return True
        logger.error(
            f"Resend rejected email to {to_email} ({subject}): {response.status_code} {response.text[:300]}"
        )
        return False
    except Exception as e:
        logger.error(f"Error sending email to {to_email} via Resend ({subject}): {e}")
        return False


async def _deliver(to_email: str, subject: str, html_body: str, text_body: str) -> bool:
    """Route an email through whichever delivery path is configured:
    Resend API first, then SMTP, then the local log fallback."""
    if settings.RESEND_API_KEY:
        return await _send_resend(to_email, subject, html_body, text_body)
    return await asyncio.to_thread(_send_smtp, to_email, subject, html_body, text_body)


class EmailService:
    """Email service for sending emails"""

    @staticmethod
    async def send_verification_email(
        to_email: str,
        verification_link: str
    ) -> bool:
        """Send email verification link"""
        subject = "Verify your DETOMSITE email"
        text = f"Hi,\n\nPlease verify your email by opening this link:\n{verification_link}\n\nIf you didn't request this, you can ignore this email.\n\n— DETOMSITE"
        html = f"<p>Hi,</p><p>Please verify your email by opening this link:</p><p><a href=\"{verification_link}\">{verification_link}</a></p><p>If you didn't request this, you can ignore this email.</p><p>— DETOMSITE</p>"
        return await _deliver(to_email, subject, html, text)

    @staticmethod
    async def send_password_reset_email(
        to_email: str,
        reset_link: str
    ) -> bool:
        """Send password reset email"""
        subject = "Reset your DETOMSITE password"
        text = f"Hi,\n\nWe received a request to reset your password. Open this link to set a new one:\n{reset_link}\n\nThis link expires shortly. If you didn't request it, ignore this email.\n\n— DETOMSITE"
        html = f"<p>Hi,</p><p>We received a request to reset your password. Open this link to set a new one:</p><p><a href=\"{reset_link}\">{reset_link}</a></p><p>If you didn't request it, ignore this email.</p><p>— DETOMSITE</p>"
        return await _deliver(to_email, subject, html, text)

    @staticmethod
    async def send_otp_email(
        to_email: str,
        code: str,
        purpose: str = "verification"
    ) -> bool:
        """Send a 6-digit OTP by email (single-code forgot-password flow)."""
        subject = f"DETOMSITE {purpose.replace('_', ' ').title()} Code: {code}"
        text = (
            f"Hi,\n\nYour {purpose.replace('_', ' ')} code is:\n\n  {code}\n\n"
            f"Enter it to continue. It expires in {settings.RESET_OTP_EXPIRE_MINUTES} minutes.\n\n"
            f"If you didn't request this, you can safely ignore this email.\n\n— DETOMSITE"
        )
        html = (
            f"<p>Hi,</p><p>Your <b>{purpose.replace('_', ' ')}</b> code is:</p>"
            f"<p style=\"font-size:28px;font-weight:bold;letter-spacing:6px;color:#064E3B;\">{code}</p>"
            f"<p>Enter it to continue. It expires in {settings.RESET_OTP_EXPIRE_MINUTES} minutes.</p>"
            f"<p>If you didn't request this, you can safely ignore this email.</p><p>— DETOMSITE</p>"
        )
        return await _deliver(to_email, subject, html, text)

    @staticmethod
    async def send_username_reminder(
        to_email: str,
        username: str,
        role: str = "student",
    ) -> bool:
        """Email a forgotten username to the account's registered address."""
        subject = "Your DETOMSITE username"
        text = (
            f"Hi,\n\nYou asked us to remind you of your username.\n\n"
            f"  Username: {username}\n\n"
            f"Use it to sign in to your {role} account. If you didn't request "
            f"this, you can safely ignore this email.\n\n— DETOMSITE"
        )
        html = (
            f"<p>Hi,</p><p>You asked us to remind you of your username.</p>"
            f"<p style=\"font-size:22px;font-weight:bold;color:#064E3B;\">{username}</p>"
            f"<p>Use it to sign in to your <b>{role}</b> account. If you didn't "
            f"request this, you can safely ignore this email.</p><p>— DETOMSITE</p>"
        )
        return await _deliver(to_email, subject, html, text)

    @staticmethod
    async def send_order_notification(
        to_email: str,
        order_number: str,
        status: str
    ) -> bool:
        """Send order notification email"""
        subject = f"Order {order_number} is now {status}"
        text = f"Hi,\n\nYour order {order_number} is now: {status}.\n\n— DETOMSITE"
        html = f"<p>Hi,</p><p>Your order <b>{order_number}</b> is now: <b>{status}</b>.</p><p>— DETOMSITE</p>"
        return await _deliver(to_email, subject, html, text)

    @staticmethod
    async def send_payment_confirmation(
        to_email: str,
        order_number: str,
        amount: float
    ) -> bool:
        """Send payment confirmation email"""
        subject = f"Payment received for order {order_number}"
        text = f"Hi,\n\nWe received your payment of ₹{amount} for order {order_number}.\n\n— DETOMSITE"
        html = f"<p>Hi,</p><p>We received your payment of <b>₹{amount}</b> for order <b>{order_number}</b>.</p><p>— DETOMSITE</p>"
        return await _deliver(to_email, subject, html, text)
