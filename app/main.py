import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.dm.kimi import KimiDM
from app.dm.scripted import ScriptedDM
from app.models import build_character
from app.orchestrator import Orchestrator
from app.repo import Repo

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="D&D AI DM")

repo = Repo(os.getenv("DND_DB_PATH", str(BASE_DIR / "data" / "dnd.db")))
dm = KimiDM() if os.getenv("MOONSHOT_API_KEY") else ScriptedDM()
orchestrator = Orchestrator(dm=dm, repo=repo, scenarios_dir=BASE_DIR / "scenarios")


class CreateSessionRequest(BaseModel):
    scenario_id: str
    character_name: str
    character_class: str


class ActionRequest(BaseModel):
    text: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/scenarios")
def list_scenarios() -> list[dict[str, str]]:
    return orchestrator.list_scenarios()


@app.post("/sessions", status_code=201)
def create_session(request: CreateSessionRequest):
    try:
        character = build_character(request.character_name, request.character_class)
        return orchestrator.start_session(request.scenario_id, character)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/actions")
def submit_action(session_id: str, request: ActionRequest):
    try:
        return orchestrator.submit_action(session_id, request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.post("/sessions/{session_id}/questions")
def ask_question(session_id: str, request: ActionRequest):
    try:
        return {"answer": orchestrator.ask_dm(session_id, request.text)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return orchestrator.get_state(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
