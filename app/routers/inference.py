import json
import logging
import traceback
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.crud.patient import get_patient
from app.crud.feedback import get_patient_feedbacks
from app.crud.prescription import get_logs_by_patient
from app.schemas.inference import InferenceRequest, InferenceResponse
from app.services.inference import InferenceEngine
from app.services.llm.claude import ClaudeProvider
from app.services.fast_track import quick_safety_set

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


@router.post("/analyze", response_model=InferenceResponse)
async def analyze(
    request: InferenceRequest,
    db: AsyncSession = Depends(get_db),
) -> InferenceResponse:
    patient = await get_patient(db, request.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    try:
        engine = InferenceEngine(llm=ClaudeProvider())
        return await engine.analyze(db, request)
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("inference/analyze 오류:\n%s", tb)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/analyze/stream")
async def analyze_stream(
    request: InferenceRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    patient = await get_patient(db, request.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # 히스토리 re-ranking에 필요한 데이터 선행 조회
    feedbacks = await get_patient_feedbacks(db, request.patient_id)
    recent_logs = (await get_logs_by_patient(db, request.patient_id))[:3]

    # 1단계 (Track A): 즉시 계산 — LLM 호출 없음
    meds = patient.current_medications or {}
    fast = quick_safety_set(
        physician_note=request.physician_note,
        diseases=patient.diseases,
        lab_values=patient.lab_values,
        patient_age=patient.age,
        prescription_history=meds.get("history", "").strip() if isinstance(meds, dict) else None,
        current_medications=meds.get("prescription", "").strip() if isinstance(meds, dict) else None,
        allergies=patient.allergies or [],
    )

    engine = InferenceEngine(llm=ClaudeProvider())

    async def event_generator():
        # 1단계 즉시 송출 (event: fast)
        yield f"event: fast\ndata: {json.dumps(fast, ensure_ascii=False, default=str)}\n\n"

        # 2단계 (Track B): LLM 스트리밍
        full_text = ""
        try:
            async for chunk in engine.stream_analyze(db, request):
                if chunk == "__DONE__":
                    try:
                        result = engine._parse_response(full_text)
                        # 히스토리 기반 결정론적 re-ranking 적용
                        result = engine.apply_history_priority(
                            result, patient, feedbacks, recent_logs,
                            request.disease_updates,
                        )
                        result_json = result.model_dump_json()
                        logger.info(
                            "_parse_response OK: prescription_set=%d, result_json_len=%d",
                            len(result.prescription_set), len(result_json),
                        )
                        yield f"event: result\ndata: {result_json}\n\n"
                    except Exception as parse_exc:
                        logger.error(
                            "_parse_response 오류: %s\nraw(%d chars): %s",
                            parse_exc, len(full_text), full_text[:600],
                        )
                        yield f"event: error\ndata: {json.dumps(str(parse_exc))}\n\n"
                    yield "event: done\ndata: {}\n\n"
                else:
                    full_text += chunk
                    yield f"event: chunk\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error("stream_analyze 오류: %s", exc)
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
