from app.db.database import SessionLocal, Base, engine
from app.models.user import User
from app.core.security import get_password_hash

# Ensure tables are created
Base.metadata.create_all(bind=engine)

def create_initial_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "admin").first()
        if not user:
            print("Creating admin user...")
            hashed_password = get_password_hash("adminpassword")
            new_user = User(username="admin", hashed_password=hashed_password)
            db.add(new_user)
            db.commit()
            print("Admin user created successfully.")
        else:
            print("Admin user already exists.")
    finally:
        db.close()

if __name__ == "__main__":
    create_initial_user()
