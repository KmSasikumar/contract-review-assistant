"""Data isolation helpers.

Every query that touches user data filters on ``user_id`` taken from the
verified Clerk token. The user id never comes from the request body, query
string or headers — only from the token. A lookup for another user's
contract returns None, so the API answers 404 (never 403, which would
confirm the row exists).
"""
import uuid

from sqlalchemy.orm import Session

from .models import Contract


def get_contract_for_user(db: Session, user_id: str, contract_id: str) -> Contract | None:
    try:
        cid = uuid.UUID(str(contract_id))
    except (ValueError, TypeError):
        return None
    return (
        db.query(Contract)
        .filter(Contract.id == cid, Contract.user_id == user_id)
        .first()
    )


def list_contracts_for_user(db: Session, user_id: str) -> list[Contract]:
    return (
        db.query(Contract)
        .filter(Contract.user_id == user_id)
        .order_by(Contract.created_at.desc())
        .all()
    )
