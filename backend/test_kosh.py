import psycopg2
from app.services.embedding_service import generate_embedding
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL is not configured in the environment.")
    sys.exit(1)

def insert_knowledge(title, content):
    embedding = generate_embedding(content)
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO knowledge (title, content, embedding) VALUES (%s, %s, %s)",
        (title, content, embedding_str)
    )
    conn.commit()
    conn.close()
    print(f"Inserted knowledge: {title}")

def search_knowledge(query):
    from app.services.kosh_service import kosh
    results = kosh.retrieve(query)
    print(f"Results for '{query}':")
    for r in results:
        print(f" - {r['title']}: {r['content']}")

if __name__ == "__main__":
    insert_knowledge("Project Phoenix Guidelines", "All databases related to Project Phoenix must be backed up daily to the cold storage server.")
    insert_knowledge("Employee Policy", "Employees must submit their timesheets by Friday 5PM.")
    
    search_knowledge("What is the backup policy for Project Phoenix?")
