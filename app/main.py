from fastapi import FastAPI
from app.routers import patients, drugs, prescriptions, inference

app = FastAPI(
    title="처방 가이드 시스템",
    description="성분명(Generic) 기반 범용 처방 레퍼런스 API — 실제 처방은 의사가 EMR에 직접 입력",
    version="0.2.0",
)

app.include_router(patients.router)
app.include_router(drugs.router)
app.include_router(prescriptions.router)
app.include_router(inference.router)

@app.get("/")
async def health_check():
    return {"status": "ok", "service": "prescription-guide", "version": "0.2.0"}
