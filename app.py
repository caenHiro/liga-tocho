"""Sistema de gestion de Liga de Tochito — app standalone.

Levanta FastAPI + frontend HTML. Sin dependencias de portal personal.

Uso:
    cd workspaces/liga-tocho
    python3 -m venv .venv && .venv/bin/pip install -e . -q
    .venv/bin/uvicorn app:app --reload --port 7001
    # Abrir: http://localhost:7001
"""
from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.liga_tocho.bd import init_db
from src.liga_tocho import routers

_FRONTEND = Path(__file__).parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Liga de Tochito", version="1.0.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (_FRONTEND / "index.html").read_text(encoding="utf-8")


app.include_router(routers.equipos_router)
app.include_router(routers.jugadores_router)
app.include_router(routers.partidos_router)
app.include_router(routers.tabla_router)


@app.get("/health")
def health():
    return {"status": "ok"}
