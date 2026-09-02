from fastapi import APIRouter
from pydantic import BaseModel

from app.services.pragya_service import pragya

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    query: str


@router.post("/")
def chat(request: ChatRequest):

    answer = pragya.answer(request.query)

    return {
        "query": request.query,
        "answer": answer
    }