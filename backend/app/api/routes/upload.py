import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from app.services.pdf_service import extract_text
from app.services.chunk_service import split_into_chunks
from app.services.embedding_service import generate_embedding

from app.db.database import get_db
from app.api.auth import get_current_user
from app.models.knowledge import Knowledge

router = APIRouter(prefix="/upload", tags=["Upload"])

UPLOAD_DIR = "app/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/")
async def upload_pdf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    text = extract_text(file_path)
    chunks = split_into_chunks(text)

    try:
        for chunk in chunks:
            embedding = generate_embedding(chunk)

            knowledge = Knowledge(
                tenant_id=getattr(current_user, "tenant_id", "tenant_default") if current_user else "tenant_default",
                title=file.filename,
                content=chunk,
                embedding=embedding,
                user_id=getattr(current_user, "id", None) if current_user else None
            )
            db.add(knowledge)

        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Document upload failed during embedding generation: {str(e)}"
        )

    return {
        "message": "Knowledge uploaded successfully",
        "chunks": len(chunks),
        "uploaded_by": current_user.username
    }