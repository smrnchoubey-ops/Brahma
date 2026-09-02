import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL is not configured in the environment.")
    sys.exit(1)

conn = psycopg2.connect(DB_URL)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
print(cur.fetchall())
