from pathlib import Path

from app.db.database import SessionLocal
from app.models.knowledge import Knowledge
from app.services.embedding_service import generate_embedding


def ingest():

    db = SessionLocal()

    try:

        file_path = Path("data/knowledge.txt")

        if not file_path.exists():
            print("knowledge.txt not found")
            return

        text = file_path.read_text(encoding="utf-8")

        embedding = generate_embedding(text)

        knowledge = Knowledge(
            title="BRAHMA Knowledge",
            content=text,
            embedding=embedding
        )

        db.add(knowledge)
        db.commit()

        print("Knowledge inserted successfully!")

    finally:
        db.close()


if __name__ == "__main__":
    ingest()