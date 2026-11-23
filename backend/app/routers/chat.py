"""Chat endpoints: history + streaming follow-up questions.

POST /api/contracts/{id}/chat streams server-sent events:
  {"type": "token", "text": "..."}  — answer tokens as generated
  {"type": "done", "sources": [...]} — verified quotes used in the answer
  {"type": "error", "text": "..."}  — e.g. rate limit, shown plainly
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import isolation
from ..auth import CurrentUser, get_current_user
from ..chat import answer_stream, get_history
from ..db import get_db
from ..schemas import ChatAsk, ChatMessageOut

router = APIRouter(prefix="/api/contracts", tags=["chat"])


@router.get("/{contract_id}/chat", response_model=list[ChatMessageOut])
def read_history(
    contract_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    out = []
    for msg in get_history(db, user.id, contract.id):
        sources = json.loads(msg.sources) if msg.sources else []
        out.append(
            ChatMessageOut(
                id=msg.id, role=msg.role, content=msg.content, sources=sources,
                created_at=msg.created_at,
            )
        )
    return out


@router.post("/{contract_id}/chat")
def ask_question(
    contract_id: str,
    body: ChatAsk,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty.")
    if len(question) > 2000:
        raise HTTPException(status_code=400, detail="Question is too long.")

    def event_stream():
        try:
            for event in answer_stream(db, contract, question):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # e.g. no API key, rate limit
            yield f"data: {json.dumps({'type': 'error', 'text': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
