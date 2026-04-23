import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.drug import DrugKnowledgeBaseCreate, DrugKnowledgeBaseUpdate, DrugKnowledgeBaseResponse
from app.crud import drug as drug_crud

router = APIRouter(prefix="/drugs", tags=["drugs"])


@router.post("/", response_model=DrugKnowledgeBaseResponse, status_code=status.HTTP_201_CREATED)
async def create_drug(data: DrugKnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    return await drug_crud.create_drug(db, data)


@router.get("/search", response_model=list[DrugKnowledgeBaseResponse])
async def search_drugs(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    return await drug_crud.search_drugs(db, q)


@router.get("/{drug_id}", response_model=DrugKnowledgeBaseResponse)
async def get_drug(drug_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    drug = await drug_crud.get_drug(db, drug_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    return drug


@router.get("/", response_model=list[DrugKnowledgeBaseResponse])
async def list_drugs(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    return await drug_crud.list_drugs(db, skip, limit)


@router.patch("/{drug_id}", response_model=DrugKnowledgeBaseResponse)
async def update_drug(
    drug_id: uuid.UUID, data: DrugKnowledgeBaseUpdate, db: AsyncSession = Depends(get_db)
):
    drug = await drug_crud.get_drug(db, drug_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    return await drug_crud.update_drug(db, drug, data)
