"""Contract endpoints: upload, list, get (with chunks), delete.

Upload is non-blocking: the file is stored, the contract is created with
status ``processing``, and extraction/chunking/embedding/review run in a
background task. The frontend polls the contract until it is ``reviewed``
or ``failed``.
"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import isolation
from ..auth import CurrentUser, get_current_user
from ..checklist import BY_KEY
from ..config import settings
from ..db import get_db
from ..models import Chunk
from ..parsing import ParseError, parse_file
from ..schemas import ChunkOut, ContractOut
from . import pipeline

router = APIRouter(prefix="/api/contracts", tags=["contracts"])

ALLOWED_EXTS = (".pdf", ".docx", ".txt")
MAX_BYTES = settings.max_upload_mb * 1024 * 1024


@router.get("", response_model=list[ContractOut])
def list_contracts(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return isolation.list_contracts_for_user(db, user.id)


@router.post("", response_model=ContractOut, status_code=201)
async def upload_contract(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    name = file.filename or "contract"
    if not name.lower().endswith(ALLOWED_EXTS):
        raise HTTPException(status_code=400, detail="Upload a PDF, DOCX or TXT file.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File is over the {settings.max_upload_mb} MB limit."
        )
    contract = pipeline.create_contract(db, user.id, name, len(data), file.content_type or "")
    # Hand the raw bytes to the background task (small enough: <= 20 MB).
    background.add_task(pipeline.process_contract, contract.id, data, name)
    return contract


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(
    contract_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    return contract


@router.get("/{contract_id}/text", response_model=list[ChunkOut])
def get_contract_text(
    contract_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Full contract text as chunks (for the jump-to-clause viewer)."""
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    chunks = (
        db.query(Chunk)
        .filter(Chunk.user_id == user.id, Chunk.contract_id == contract.id)
        .order_by(Chunk.chunk_index)
        .all()
    )
    return chunks


@router.delete("/{contract_id}", status_code=204)
def delete_contract(
    contract_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    contract = isolation.get_contract_for_user(db, user.id, contract_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    db.delete(contract)
    db.commit()
    return None
