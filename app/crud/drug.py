import uuid
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.drug import DrugKnowledgeBase
from app.schemas.drug import DrugKnowledgeBaseCreate, DrugKnowledgeBaseUpdate


async def create_drug(db: AsyncSession, data: DrugKnowledgeBaseCreate) -> DrugKnowledgeBase:
    drug = DrugKnowledgeBase(**data.model_dump())
    db.add(drug)
    await db.commit()
    await db.refresh(drug)
    return drug


async def get_drug(db: AsyncSession, drug_id: uuid.UUID) -> DrugKnowledgeBase | None:
    result = await db.execute(select(DrugKnowledgeBase).where(DrugKnowledgeBase.id == drug_id))
    return result.scalar_one_or_none()


async def search_drugs(db: AsyncSession, query: str) -> list[DrugKnowledgeBase]:
    """성분명(한글/영문) 또는 약물 분류로 검색"""
    result = await db.execute(
        select(DrugKnowledgeBase).where(
            or_(
                DrugKnowledgeBase.generic_name_ko.ilike(f"%{query}%"),
                DrugKnowledgeBase.generic_name_en.ilike(f"%{query}%"),
                DrugKnowledgeBase.drug_class.ilike(f"%{query}%"),
            )
        )
    )
    return list(result.scalars().all())


async def list_drugs(db: AsyncSession, skip: int = 0, limit: int = 100) -> list[DrugKnowledgeBase]:
    result = await db.execute(select(DrugKnowledgeBase).offset(skip).limit(limit))
    return list(result.scalars().all())


async def update_drug(
    db: AsyncSession, drug: DrugKnowledgeBase, data: DrugKnowledgeBaseUpdate
) -> DrugKnowledgeBase:
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(drug, field, value)
    await db.commit()
    await db.refresh(drug)
    return drug
