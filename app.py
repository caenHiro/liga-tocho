"""Sistema de gestion de Liga de Tochito — app standalone.

Levanta FastAPI + frontend HTML. Sin dependencias de portal personal.

Uso:
    cd workspaces/liga-tocho
    python3 -m venv .venv && .venv/bin/pip install -e . -q
    .venv/bin/uvicorn app:app --reload --port 7001
    # Abrir: http://localhost:7001

Credenciales iniciales: admin / admin123  (cambiar después)
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from src.liga_tocho.bd import init_db
from src.liga_tocho import routers
from src.liga_tocho.routers_auth import (
    auth_router, qb_router, ensure_admin_default,
)

_FRONTEND = Path(__file__).parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_admin_default()
    yield


app = FastAPI(title="Liga de Tochito", version="3.0.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return (_FRONTEND / "index.html").read_text(encoding="utf-8")


# Routers públicos
app.include_router(routers.temporadas_router)
app.include_router(routers.canchas_router)
app.include_router(routers.equipos_router)
app.include_router(routers.registros_router)
app.include_router(routers.jugadores_router)
app.include_router(routers.partidos_router)
app.include_router(routers.tabla_router)
app.include_router(routers.calendario_router)

# Auth + QB
app.include_router(auth_router)
app.include_router(qb_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}
