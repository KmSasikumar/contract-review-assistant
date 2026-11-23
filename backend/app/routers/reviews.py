"""Review endpoints: read the checklist verdicts, re-run a failed review."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import isolation
from ..auth import CurrentUser, get_current_user
from ..checklist import BY_KEY, risk_flags
from ..db import get_db
from ..review import get_review
from ..schemas import ReviewItemOut, ReviewOut
from . import pipeline

router = APIRouter(prefix="/api/contracts", tags=["reviews"])


@router.get("/{contract_id}/review", response_model=ReviewOut)
def read_review(
    contract_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    items = get_review(db, user.id, contract.id)
    out = [
        ReviewItemOut(
            key=it.key,
            label=BY_KEY[it.key].label,
            status=it.status,
            summary=it.summary,
            quote=it.quote,
            quote_verified=it.quote_verified,
            chunk_id=it.chunk_id,
            page=it.page,
            section=it.section,
        )
        for it in items
    ]
    flags = risk_flags({it.key: it.status for it in items})
    return ReviewOut(contract_id=contract.id, items=out, risk_flags=flags)


@router.post("/{contract_id}/review/retry", response_model=dict)
def retry_review_endpoint(
    contract_id: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Re-run the review (e.g. after a rate limit or after adding a key)."""
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    background.add_task(pipeline.retry_review, contract.id)
    return {"status": "processing"}
