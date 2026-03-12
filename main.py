"""
Workflow Decision Platform — Main Entry Point
=============================================
Start with:  uvicorn main:app --reload
API docs at: http://localhost:8000/docs
"""
from fastapi import FastAPI
from src.models.database import Base, engine
from src.api.routes import router

# Create all database tables on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Workflow Decision Platform",
    description=(
        "A configurable, rule-driven workflow engine. "
        "Supports multiple business workflows via YAML configuration. "
        "Features: idempotency, full audit trail, retry logic, explainable decisions."
    ),
    version="1.0.0",
)

app.include_router(router, prefix="/api/v1")


@app.get("/")
def root():
    return {
        "service":  "Workflow Decision Platform",
        "version":  "1.0.0",
        "docs":     "/docs",
        "health":   "/api/v1/health",
        "workflows": "/api/v1/workflows",
    }
