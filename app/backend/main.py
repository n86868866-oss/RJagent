from fastapi import FastAPI


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