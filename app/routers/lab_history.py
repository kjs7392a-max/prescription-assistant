import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.lab_history import LabHistoryCreate, LabHistoryResponse
from app.crud import lab_history as lab_history_crud

router = APIRouter(prefix="/lab-history", tags=["lab-history"])


@router.post("/", response_model=LabHistoryResponse, status_code=201)
async def create_lab_snapshot(data: LabHistoryCreate, db: AsyncSession = Depends(get_db)):
    return await lab_history_crud.record_lab_snapshot(db, data)


@router.get("/{patient_id}", response_model=list[LabHistoryResponse])
async def get_lab_history(
    patient_id: uuid.UUID,
    limit: int = 3,
    db: AsyncSession = Depends(get_db),
):
    return await lab_history_crud.get_recent_lab_history(db, patient_id, limit)
