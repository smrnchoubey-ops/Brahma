from sqlalchemy import text
from app.db.database import engine

try:
    with engine.connect() as connection:
        result = connection.execute(text("SELECT version();"))

        print("\n✅ Database Connected Successfully!\n")
        print(result.fetchone()[0])

except Exception as e:
    print("\n❌ Database Connection Failed\n")
    print(e)