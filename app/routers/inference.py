from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.crud.patient import get_patient
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.inference import InferenceEngine
from app.services.llm.claude import ClaudeProvider

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


@router.post("/analyze", response_model=InferenceResponse)
async def analyze(
    request: InferenceRequest,
    db: AsyncSession = Depends(get_db),
) -> InferenceResponse:
    patient = await get_patient(db, request.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    engine = InferenceEngine(llm=ClaudeProvider())
    return await engine.analyze(db, request)
