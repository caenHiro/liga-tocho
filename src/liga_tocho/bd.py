"""Base de datos SQLite para la liga de tochito."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[3] / "liga.db"

DDL = """
CREATE TABLE IF NOT EXISTS equipos (
    id        TEXT PRIMARY KEY,
    nombre    TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT 'mixto',
    color     TEXT DEFAULT '',
    capitan   TEXT DEFAULT '',
    activo    INTEGER NOT NULL DEFAULT 1,
    notas     TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jugadores (
    id        TEXT PRIMARY KEY,
    nombre    TEXT NOT NULL,
    equipo_id TEXT REFERENCES equipos(id),
    posicion  TEXT DEFAULT '',
    numero    INTEGER,
    activo    INTEGER NOT NULL DEFAULT 1,
    notas     TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS partidos (
    id                  TEXT PRIMARY KEY,
    fecha               TEXT NOT NULL,
    equipo_local_id     TEXT REFERENCES equipos(id),
    equipo_visitante_id TEXT REFERENCES equipos(id),
    goles_local         INTEGER DEFAULT 0,
    goles_visitante     INTEGER DEFAULT 0,
    estado              TEXT NOT NULL DEFAULT 'programado',
    cancha              TEXT DEFAULT '',
    jornada             INTEGER DEFAULT 1,
    notas               TEXT DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partidos_fecha  ON partidos(fecha);
CREATE INDEX IF NOT EXISTS idx_jugadores_equipo ON jugadores(equipo_id);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(DDL)
    conn.commit()
    conn.close()
