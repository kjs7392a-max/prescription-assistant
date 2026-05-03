import os
import traceback
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.routers import patients, drugs, prescriptions, inference, lab_history, lab_upload

logger = logging.getLogger("uvicorn.error")

app = FastAPI(
    title="처방 가이드 시스템",
    description="성분명(Generic) 기반 범용 처방 레퍼런스 API — 실제 처방은 의사가 EMR에 직접 입력",
    version="0.3.0",
)

app.include_router(patients.router, prefix="/api/v1")
app.include_router(drugs.router, prefix="/api/v1")
app.include_router(prescriptions.router, prefix="/api/v1")
app.include_router(inference.router)          # already has /api/v1/inference prefix
app.include_router(lab_history.router, prefix="/api/v1")
app.include_router(lab_upload.router, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    logger.error("Unhandled exception on %s:\n%s", request.url.path, tb)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}", "traceback": tb[-800:]},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "prescription-guide", "version": "0.3.0"}


_uploads_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")

_static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
