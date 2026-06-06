"""Base de datos SQLite — Liga de Tochito / Flag Football.

Modelo:
  Temporada (4/año, 11 jornadas c/u)
  └── Registros (equipo inscrito en categoría+división de esa temporada)
       ├── Inscripciones (jugadores, máx 20, con validaciones multifranquicia)
       ├── Restricciones de horario (mañana/mediodía/tarde)
       └── Partidos (asignados a jornada+cancha+franja horaria)
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parents[2] / "liga.db"

DDL = """
-- ── Temporadas ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS temporadas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre       TEXT NOT NULL,
    anio         INTEGER NOT NULL,
    numero       INTEGER NOT NULL CHECK(numero BETWEEN 1 AND 4),
    fecha_inicio TEXT,
    fecha_fin    TEXT,
    estado       TEXT NOT NULL DEFAULT 'activa'
                 CHECK(estado IN ('activa','finalizada','cancelada')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(anio, numero)
);

-- ── Jornadas (11 por temporada) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jornadas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    temporada_id INTEGER NOT NULL REFERENCES temporadas(id) ON DELETE CASCADE,
    numero       INTEGER NOT NULL CHECK(numero BETWEEN 1 AND 11),
    fecha        TEXT,
    UNIQUE(temporada_id, numero)
);

-- ── Canchas ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS canchas (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    activa INTEGER NOT NULL DEFAULT 1
);

-- ── Equipos (entidad base, sin categoría — la categoría va en el registro) ────
CREATE TABLE IF NOT EXISTS equipos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL UNIQUE,
    color      TEXT DEFAULT '',
    activo     INTEGER NOT NULL DEFAULT 1,
    notas      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Registros: un equipo inscrito en categoría/división/temporada ─────────────
-- Un equipo puede tener múltiples registros (ej: equipo X en mixto-A y varonil-B)
CREATE TABLE IF NOT EXISTS registros (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    temporada_id INTEGER NOT NULL REFERENCES temporadas(id) ON DELETE CASCADE,
    equipo_id    INTEGER NOT NULL REFERENCES equipos(id),
    categoria    TEXT NOT NULL CHECK(categoria IN ('A','B','C','D','E','F')),
    division     TEXT NOT NULL CHECK(division IN ('varonil','mixto','femenino')),
    capitan      TEXT DEFAULT '',
    activo       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(temporada_id, equipo_id, categoria, division)
);

CREATE INDEX IF NOT EXISTS idx_registros_temp   ON registros(temporada_id);
CREATE INDEX IF NOT EXISTS idx_registros_equipo ON registros(equipo_id);

-- ── Restricciones de horario por registro ────────────────────────────────────
CREATE TABLE IF NOT EXISTS restricciones_horario (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id  INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    preferencia  TEXT NOT NULL
                 CHECK(preferencia IN ('manana','mediodia','tarde','sin_restriccion')),
    UNIQUE(registro_id)
);

-- ── Jugadores (sin equipo fijo — multifranquicia) ────────────────────────────
CREATE TABLE IF NOT EXISTS jugadores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    activo     INTEGER NOT NULL DEFAULT 1,
    notas      TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Inscripciones: jugador en un registro específico ─────────────────────────
-- Reglas (ver validaciones.py):
--   1. Máx 20 jugadores por registro
--   2. Jugador en máx 3 equipos DISTINTOS por temporada
--      (mismo equipo en varonil+mixto NO cuenta como 2 equipos)
--   3. Si juega en categoría X, solo puede jugar en X, X+1, X+2, X+3 (hasta 3 abajo)
CREATE TABLE IF NOT EXISTS inscripciones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    jugador_id  INTEGER NOT NULL REFERENCES jugadores(id),
    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    numero      INTEGER,
    posicion    TEXT DEFAULT '',
    activo      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(jugador_id, registro_id)
);

CREATE INDEX IF NOT EXISTS idx_inscripciones_jugador  ON inscripciones(jugador_id);
CREATE INDEX IF NOT EXISTS idx_inscripciones_registro ON inscripciones(registro_id);

-- ── Restricciones de horario POR JORNADA (QB solicita franja para esa jornada) ─
-- Tiene prioridad sobre restricciones_horario (permanente)
CREATE TABLE IF NOT EXISTS restricciones_jornada (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    registro_id  INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
    jornada_id   INTEGER NOT NULL REFERENCES jornadas(id) ON DELETE CASCADE,
    preferencia  TEXT NOT NULL
                 CHECK(preferencia IN ('manana','mediodia','tarde','sin_restriccion')),
    UNIQUE(registro_id, jornada_id)
);

-- ── Usuarios (admin + QB por equipo) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS usuarios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    rol          TEXT NOT NULL DEFAULT 'publico'
                 CHECK(rol IN ('admin','qb','publico')),
    registro_id  INTEGER REFERENCES registros(id) ON DELETE SET NULL,
    activo       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Partidos ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS partidos (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    jornada_id            INTEGER NOT NULL REFERENCES jornadas(id) ON DELETE CASCADE,
    cancha_id             INTEGER REFERENCES canchas(id),
    hora_inicio           TEXT,   -- HH:MM
    franja                TEXT    CHECK(franja IN ('manana','mediodia','tarde')),
    registro_local_id     INTEGER REFERENCES registros(id),
    registro_visitante_id INTEGER REFERENCES registros(id),
    goles_local           INTEGER DEFAULT 0,
    goles_visitante       INTEGER DEFAULT 0,
    estado                TEXT NOT NULL DEFAULT 'programado'
                          CHECK(estado IN ('programado','en_juego','finalizado','suspendido')),
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_partidos_jornada    ON partidos(jornada_id);
CREATE INDEX IF NOT EXISTS idx_partidos_registro_l ON partidos(registro_local_id);
CREATE INDEX IF NOT EXISTS idx_partidos_registro_v ON partidos(registro_visitante_id);

-- ── Estadísticas por partido (touchdowns, yardas, intercepciones) ─────────────
CREATE TABLE IF NOT EXISTS estadisticas_partido (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    partido_id               INTEGER NOT NULL REFERENCES partidos(id) ON DELETE CASCADE,
    registro_id              INTEGER NOT NULL REFERENCES registros(id),
    touchdowns               INTEGER NOT NULL DEFAULT 0,
    yardas_pase              INTEGER NOT NULL DEFAULT 0,
    yardas_tierra            INTEGER NOT NULL DEFAULT 0,
    intercepciones_lanzadas  INTEGER NOT NULL DEFAULT 0,
    intercepciones_atrapadas INTEGER NOT NULL DEFAULT 0,
    puntos_extra             INTEGER NOT NULL DEFAULT 0,
    UNIQUE(partido_id, registro_id)
);

CREATE INDEX IF NOT EXISTS idx_stats_partido  ON estadisticas_partido(partido_id);
CREATE INDEX IF NOT EXISTS idx_stats_registro ON estadisticas_partido(registro_id);
"""

FRANJAS = {
    "manana":   ("07:00", "12:00"),
    "mediodia": ("12:00", "16:00"),
    "tarde":    ("16:00", "20:00"),
}

CATEGORIAS = ["A", "B", "C", "D", "E", "F"]
DIVISIONES  = ["varonil", "mixto", "femenino"]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


MIGRACIONES = [
    "ALTER TABLE jugadores ADD COLUMN posicion_principal TEXT DEFAULT ''",
    "ALTER TABLE jugadores ADD COLUMN numero_camiseta INTEGER",
    "ALTER TABLE jugadores ADD COLUMN telefono TEXT DEFAULT ''",
    """CREATE TABLE IF NOT EXISTS estadisticas_jugador (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        partido_id               INTEGER NOT NULL REFERENCES partidos(id) ON DELETE CASCADE,
        jugador_id               INTEGER NOT NULL REFERENCES jugadores(id),
        registro_id              INTEGER NOT NULL REFERENCES registros(id),
        touchdowns               INTEGER NOT NULL DEFAULT 0,
        yardas_pase              INTEGER NOT NULL DEFAULT 0,
        yardas_tierra            INTEGER NOT NULL DEFAULT 0,
        intercepciones_lanzadas  INTEGER NOT NULL DEFAULT 0,
        intercepciones_atrapadas INTEGER NOT NULL DEFAULT 0,
        puntos_extra             INTEGER NOT NULL DEFAULT 0,
        UNIQUE(partido_id, jugador_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_stats_jug_jugador ON estadisticas_jugador(jugador_id)",
    "CREATE INDEX IF NOT EXISTS idx_stats_jug_partido ON estadisticas_jugador(partido_id)",
]


def init_db() -> None:
    conn = get_conn()
    conn.executescript(DDL)
    # Migraciones idempotentes (ignora "duplicate column" silenciosamente)
    for sql in MIGRACIONES:
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()
