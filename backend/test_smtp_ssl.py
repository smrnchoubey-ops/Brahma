import smtplib
import os
from dotenv import load_dotenv

load_dotenv(override=True)
smtp_user = os.getenv("SMTP_USER", "").strip()
smtp_pass = os.getenv("SMTP_PASS", "").strip()

print(f"Testing port 465 SSL for {smtp_user}...")
try:
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(smtp_user, smtp_pass)
    print("PORT 465 LOGIN SUCCESS!")
    server.quit()
except Exception as e:
    print(f"PORT 465 LOGIN FAILED: {e}")
