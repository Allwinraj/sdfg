from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.agents.base import AgentRegistry
from app.core.llm import LLMProvider
from app.core.storage import Storage
from app.deps import get_llm, get_registry, get_storage
from app.engine.persist import list_pipelines, load_pipeline, save_pipeline
from app.services.library import file_slots, package_session_pipeline, write_named_files
from app.services.ops import answer_run_question, library_card, missing_files, run_library_pipeline
from app.services.sessions import load_session, session_pipeline
from app.api.runs import _run_view

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class SaveBody(BaseModel):
    session_id: str
    name: str
    version: str = "v1"


class PreviewBody(BaseModel):
    session_id: str
    extra: dict = Field(default_factory=dict)


class AskBody(BaseModel):
    question: str
    run_id: str


def _session(storage: Storage, session_id: str):
    try:
        return load_session(storage, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


def _pipeline(storage: Storage, pipeline_id: str):
    try:
        return load_pipeline(storage, pipeline_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="pipeline not found") from exc


@router.get("")
def get_pipelines(storage: Storage = Depends(get_storage)) -> dict:
    items = list_pipelines(storage)
    return {"pipelines": [library_card(p) for p in items]}


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: str, storage: Storage = Depends(get_storage)) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    body = pipeline.model_dump(mode="json")
    body["file_slots"] = file_slots(pipeline)
    body["missing_files"] = missing_files(storage, pipeline)
    return body


@router.post("", status_code=status.HTTP_201_CREATED)
def save_to_library(body: SaveBody, storage: Storage = Depends(get_storage)) -> dict:
    session = _session(storage, body.session_id)
    if not session.confirmed:
        raise HTTPException(status_code=400, detail="session is not confirmed")
    draft = session_pipeline(session)
    if not draft.nodes:
        raise HTTPException(status_code=400, detail="session has no draft DAG")
    pipeline = package_session_pipeline(storage, session, body.name, body.version)
    save_pipeline(storage, pipeline)
    return pipeline.model_dump(mode="json")


@router.post("/preview")
def preview_pipeline(body: PreviewBody, storage: Storage = Depends(get_storage)) -> dict:
    session = _session(storage, body.session_id)
    pipeline = session_pipeline(session)
    return {"session_id": session.id, "confirmed": session.confirmed, "pipeline": pipeline.model_dump(mode="json")}


@router.post("/{pipeline_id}/files")
async def upload_library_files(
    pipeline_id: str,
    files: list[UploadFile] = File(),
    storage: Storage = Depends(get_storage),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    if not files:
        raise HTTPException(status_code=400, detail="files are required")
    blobs: list[tuple[str, bytes]] = []
    for item in files:
        blobs.append((item.filename or "upload.bin", await item.read()))
    try:
        written = write_named_files(storage, pipeline, blobs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "written": written,
        "file_slots": file_slots(pipeline),
        "missing_files": missing_files(storage, pipeline),
    }


@router.post("/{pipeline_id}/run")
async def run_saved_pipeline(
    pipeline_id: str,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
    registry: AgentRegistry = Depends(get_registry),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    try:
        run = await run_library_pipeline(storage, llm, registry, pipeline)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _run_view(run)


@router.post("/{pipeline_id}/ask")
async def ask_saved_pipeline(
    pipeline_id: str,
    body: AskBody,
    storage: Storage = Depends(get_storage),
    llm: LLMProvider = Depends(get_llm),
) -> dict:
    pipeline = _pipeline(storage, pipeline_id)
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="question is required")
    try:
        answer = await answer_run_question(llm, pipeline, body.run_id, storage, body.question.strip())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"answer": answer, "run_id": body.run_id}
