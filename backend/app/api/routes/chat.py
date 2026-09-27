from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.services.pragya_service import pragya
from app.core.tenant import TenantContext, get_current_tenant

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    query: str


@router.post("/")
def chat(
    request: ChatRequest,
    tenant: TenantContext = Depends(get_current_tenant)
):
    answer = pragya.answer(request.query, tenant_id=tenant.tenant_id)

    return {
        "query": request.query,
        "answer": answer
    }