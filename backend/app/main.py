from fastapi import FastAPI

from app.api.routes.tasks import router as task_router
from app.db.database import engine
from app.models.task import Base
from app.models.knowledge import Knowledge
from app.api.routes.chat import router as chat_router
from app.api.routes.upload import router as upload_router
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes.memory import router as memory_router
from app.api.routes.audit import router as audit_router


# Create all database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="BRAHMA COS Backend API",
    description="Backend APIs for BRAHMA Cognitive Operating System",
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(task_router)
app.include_router(chat_router)
app.include_router(upload_router)
app.include_router(memory_router) 
app.include_router(audit_router)


@app.get("/")
async def root():
    return {
        "message": "BRAHMA COS Backend is Running 🚀"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }