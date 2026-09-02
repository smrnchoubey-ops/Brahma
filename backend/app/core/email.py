import os
import smtplib
from email.message import EmailMessage
import logging

logger = logging.getLogger(__name__)

def send_email(to_email: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = os.getenv("SMTP_PORT", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.error("SMTP configuration is incomplete in environment variables.")
        return False

    msg = EmailMessage()
    msg.set_content(body)
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email

    try:
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        print(f"DEBUG IN EMAIL.PY - User: '{smtp_user}' | Pass Length: {len(smtp_pass)}")
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False
