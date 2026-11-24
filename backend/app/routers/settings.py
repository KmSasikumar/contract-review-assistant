"""Per-user AI settings: which LLM model reviews and chat use.

GET returns the user's saved choice (Gemini 2.5 Flash by default) plus
the list of models the Settings page may offer. PUT saves a choice;
only a (provider, model) pair from llm.MODEL_OPTIONS is accepted, so a
bad model name can never break reviews or chat.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import CurrentUser, get_current_user
from ..db import get_db
from ..llm import DEFAULT_MODEL, DEFAULT_PROVIDER, MODEL_OPTIONS
from ..models import UserSettings
from ..schemas import SettingsIn, SettingsOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _valid(provider: str, model: str) -> bool:
    return any(
        o["provider"] == provider and o["model"] == model for o in MODEL_OPTIONS
    )


@router.get("", response_model=SettingsOut)
def get_settings(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    row = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    return SettingsOut(
        chat_provider=row.chat_provider if row else DEFAULT_PROVIDER,
        chat_model=row.chat_model if row else DEFAULT_MODEL,
        options=MODEL_OPTIONS,
    )


@router.put("", response_model=SettingsOut)
def put_settings(
    body: SettingsIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    if not _valid(body.chat_provider, body.chat_model):
        raise HTTPException(
            status_code=400,
            detail="Unknown model. Pick one from the settings list.",
        )
    row = db.query(UserSettings).filter(UserSettings.user_id == user.id).first()
    if row is None:
        row = UserSettings(
            user_id=user.id,
            chat_provider=body.chat_provider,
            chat_model=body.chat_model,
        )
        db.add(row)
    else:
        row.chat_provider = body.chat_provider
        row.chat_model = body.chat_model
    db.commit()
    return SettingsOut(
        chat_provider=row.chat_provider,
        chat_model=row.chat_model,
        options=MODEL_OPTIONS,
    )
