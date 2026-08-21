from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.routes import router
from core.config import get_settings
from core.logging import get_logger
from core.ollama_client import health_check as ollama_health
from rag.chroma_client import health_check as chroma_health

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    if settings.llm_mode == "api":
        if settings.llm_api_key:
            logger.info({
                "event": "startup_ok",
                "llm_provider": "api",
                "base_url": settings.llm_api_base_url,
                "model": settings.llm_api_chat_model,
            })
        else:
            logger.warning({
                "event": "startup_warning",
                "llm_provider": "api",
                "message": "API mode configured without an API key",
            })
    else:
        ollama_ok = await ollama_health()
        if not ollama_ok:
            logger.warning({"event": "startup_warning", "message": f"Ollama not reachable at {settings.ollama_base_url}"})
        else:
            logger.info({"event": "startup_ok", "ollama": settings.ollama_base_url, "model": settings.ollama_chat_model})

    chroma_ok = chroma_health()
    if not chroma_ok:
        logger.warning({"event": "startup_warning", "message": "ChromaDB initialization failed"})
    else:
        logger.info({"event": "startup_ok", "chromadb": settings.chroma_persist_dir})

    logger.info({"event": "forgeai_started", "port": settings.port})
    yield
    logger.info({"event": "forgeai_shutdown"})


app = FastAPI(
    title="ForgeAI",
    description="Manufacturing equipment log multi-agent RAG system",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
