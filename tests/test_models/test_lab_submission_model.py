import pytest
from sqlalchemy import select
from app.models.lab_submission import LabSubmission


@pytest.mark.asyncio
async def test_create_lab_submission(db_session):
    sub = LabSubmission(
        photo_path="uploads/lab_photos/test.jpg",
        parsed_values={"items": [{"name": "혈당", "value": 105.0, "unit": "mg/dL", "ref_range": "70-100"}]},
        raw_text='{"items": [...]}',
        is_parsed=True,
        source="photo",
        status="pending",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    result = await db_session.execute(
        select(LabSubmission).where(LabSubmission.status == "pending")
    )
    saved = result.scalar_one()
    assert saved.patient_id is None
    assert saved.is_parsed is True
    assert saved.parsed_values["items"][0]["name"] == "혈당"
