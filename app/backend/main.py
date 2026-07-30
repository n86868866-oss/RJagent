from fastapi import FastAPI
from app.backend.config import get_settings


settings = get_settings()
print(settings.app_name); print(settings.text_embedding_provider); print(settings.text_embedding_model); print(settings.project_path(settings.sqlite_path))

app = FastAPI(
    title="Research Journey Agent",
    version="0.1.0",
)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Research Journey Agent",
        "status": "running",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}