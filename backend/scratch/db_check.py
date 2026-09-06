import sys
sys.path.insert(0, ".")
from app.db.database import engine
from sqlalchemy import text

def check_db():
    print("DATABASE_URL:", engine.url)
    print("DB Dialect:", engine.dialect.name)
    
    with engine.connect() as conn:
        print("\n--- MEMORY TABLE SCHEMA ---")
        res = conn.execute(text("SELECT column_name, data_type, column_default, is_nullable FROM information_schema.columns WHERE table_name = 'memory' ORDER BY ordinal_position;"))
        for row in res:
            print(dict(row._mapping))
            
        print("\n--- KNOWLEDGE TABLE SCHEMA ---")
        res = conn.execute(text("SELECT column_name, data_type, column_default, is_nullable FROM information_schema.columns WHERE table_name = 'knowledge' ORDER BY ordinal_position;"))
        for row in res:
            print(dict(row._mapping))

if __name__ == "__main__":
    check_db()
