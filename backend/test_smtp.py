import os
from dotenv import load_dotenv
load_dotenv(override=True)

from app.core.email import send_email
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("Testing SMTP delivery...")
    success = send_email(
        to_email="test@example.com",
        subject="BRAHMA COS SMTP Test",
        body="This is a test email to verify SMTP functionality in BRAHMA COS."
    )
    if success:
        print("RESULT: SUCCESS")
    else:
        print("RESULT: FAILED")
