"""Routers FastAPI para la liga de tochito."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .bd import get_conn


def _next_id(conn, tabla: str, prefijo: str) -> str:
    row = conn.execute(f"SELECT COUNT(*) as n FROM {tabla}").fetchone()
    return f"{prefijo}-{row['n'] + 1:03d}"


# ── Equipos ───────────────────────────────────────────────────────────────────

equipos_router = APIRouter(prefix="/api/equipos", tags=["equipos"])


class EquipoIn(BaseModel):
    nombre: str
    categoria: str = "mixto"
    color: str = ""
    capitan: str = ""
    notas: str = ""


@equipos_router.get("/")
def listar_equipos():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM equipos WHERE activo=1 ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@equipos_router.post("/", status_code=201)
def crear_equipo(body: EquipoIn):
    conn = get_conn()
    id_ = _next_id(conn, "equipos", "EQ")
    conn.execute(
        "INSERT INTO equipos (id, nombre, categoria, color, capitan, notas) VALUES (?,?,?,?,?,?)",
        (id_, body.nombre, body.categoria, body.color, body.capitan, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump(), "activo": 1}


@equipos_router.delete("/{id_}", status_code=204)
def eliminar_equipo(id_: str):
    conn = get_conn()
    cur = conn.execute("UPDATE equipos SET activo=0 WHERE id=?", (id_,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Equipo no encontrado")


# ── Jugadores ─────────────────────────────────────────────────────────────────

jugadores_router = APIRouter(prefix="/api/jugadores", tags=["jugadores"])


class JugadorIn(BaseModel):
    nombre: str
    equipo_id: Optional[str] = None
    posicion: str = ""
    numero: Optional[int] = None
    notas: str = ""


@jugadores_router.get("/")
def listar_jugadores(equipo_id: Optional[str] = None):
    conn = get_conn()
    if equipo_id:
        rows = conn.execute(
            "SELECT j.*, e.nombre as equipo_nombre FROM jugadores j LEFT JOIN equipos e ON j.equipo_id=e.id WHERE j.equipo_id=? AND j.activo=1 ORDER BY j.nombre",
            (equipo_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT j.*, e.nombre as equipo_nombre FROM jugadores j LEFT JOIN equipos e ON j.equipo_id=e.id WHERE j.activo=1 ORDER BY j.nombre"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@jugadores_router.post("/", status_code=201)
def crear_jugador(body: JugadorIn):
    conn = get_conn()
    id_ = _next_id(conn, "jugadores", "JUG")
    conn.execute(
        "INSERT INTO jugadores (id, nombre, equipo_id, posicion, numero, notas) VALUES (?,?,?,?,?,?)",
        (id_, body.nombre, body.equipo_id, body.posicion, body.numero, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump(), "activo": 1}


@jugadores_router.patch("/{id_}/equipo")
def cambiar_equipo(id_: str, equipo_id: Optional[str] = None):
    conn = get_conn()
    conn.execute("UPDATE jugadores SET equipo_id=? WHERE id=?", (equipo_id, id_))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Partidos ──────────────────────────────────────────────────────────────────

partidos_router = APIRouter(prefix="/api/partidos", tags=["partidos"])


class PartidoIn(BaseModel):
    fecha: str
    equipo_local_id: str
    equipo_visitante_id: str
    cancha: str = ""
    jornada: int = 1
    notas: str = ""


class ResultadoIn(BaseModel):
    goles_local: int
    goles_visitante: int
    estado: str = "finalizado"


@partidos_router.get("/")
def listar_partidos(estado: Optional[str] = None, jornada: Optional[int] = None):
    query = """
        SELECT p.*, el.nombre as local_nombre, el.color as local_color,
               ev.nombre as visitante_nombre, ev.color as visitante_color
        FROM partidos p
        LEFT JOIN equipos el ON p.equipo_local_id=el.id
        LEFT JOIN equipos ev ON p.equipo_visitante_id=ev.id
        WHERE 1=1
    """
    params: list = []
    if estado:
        query += " AND p.estado=?"
        params.append(estado)
    if jornada:
        query += " AND p.jornada=?"
        params.append(jornada)
    query += " ORDER BY p.fecha DESC"
    conn = get_conn()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@partidos_router.post("/", status_code=201)
def crear_partido(body: PartidoIn):
    conn = get_conn()
    id_ = _next_id(conn, "partidos", "PAR")
    conn.execute(
        "INSERT INTO partidos (id, fecha, equipo_local_id, equipo_visitante_id, cancha, jornada, notas) VALUES (?,?,?,?,?,?,?)",
        (id_, body.fecha, body.equipo_local_id, body.equipo_visitante_id, body.cancha, body.jornada, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump(), "estado": "programado", "goles_local": 0, "goles_visitante": 0}


@partidos_router.patch("/{id_}/resultado")
def registrar_resultado(id_: str, body: ResultadoIn):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM partidos WHERE id=?", (id_,)).fetchone():
        conn.close()
        raise HTTPException(404, "Partido no encontrado")
    conn.execute(
        "UPDATE partidos SET goles_local=?, goles_visitante=?, estado=? WHERE id=?",
        (body.goles_local, body.goles_visitante, body.estado, id_),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM partidos WHERE id=?", (id_,)).fetchone()
    conn.close()
    return dict(row)


# ── Tabla posiciones ──────────────────────────────────────────────────────────

tabla_router = APIRouter(prefix="/api/tabla", tags=["tabla"])


@tabla_router.get("/")
def tabla_posiciones():
    conn = get_conn()
    equipos = conn.execute("SELECT * FROM equipos WHERE activo=1").fetchall()
    partidos = conn.execute("SELECT * FROM partidos WHERE estado='finalizado'").fetchall()
    conn.close()

    tabla: dict[str, dict] = {}
    for e in equipos:
        tabla[e["id"]] = {
            "id": e["id"], "nombre": e["nombre"], "color": e["color"] or "",
            "categoria": e["categoria"], "capitan": e["capitan"] or "",
            "pj": 0, "pg": 0, "pe": 0, "pp": 0,
            "gf": 0, "gc": 0, "dif": 0, "pts": 0,
        }

    for p in partidos:
        lid, vid = p["equipo_local_id"], p["equipo_visitante_id"]
        gl, gv = p["goles_local"] or 0, p["goles_visitante"] or 0
        if lid not in tabla or vid not in tabla:
            continue
        for eid, gf, gc in [(lid, gl, gv), (vid, gv, gl)]:
            t = tabla[eid]
            t["pj"] += 1; t["gf"] += gf; t["gc"] += gc; t["dif"] = t["gf"] - t["gc"]
        if gl > gv:
            tabla[lid]["pg"] += 1; tabla[lid]["pts"] += 3; tabla[vid]["pp"] += 1
        elif gl < gv:
            tabla[vid]["pg"] += 1; tabla[vid]["pts"] += 3; tabla[lid]["pp"] += 1
        else:
            tabla[lid]["pe"] += 1; tabla[lid]["pts"] += 1
            tabla[vid]["pe"] += 1; tabla[vid]["pts"] += 1

    return sorted(tabla.values(), key=lambda x: (-x["pts"], -x["dif"], -x["gf"]))
