"""CRUD /api/liga-tocho — gestion de liga de tochito (super_admin)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from portal.api.bd import get_conn
from portal.api.seguridad.auth import require_role

router = APIRouter(prefix="/api/liga-tocho", tags=["liga-tocho"])

ROLES = ["super_admin"]


def _next_id(conn, tabla: str, prefijo: str) -> str:
    row = conn.execute(f"SELECT COUNT(*) as n FROM {tabla}").fetchone()
    return f"{prefijo}-{row['n'] + 1:03d}"


# ── Equipos ───────────────────────────────────────────────────────────────────

class EquipoIn(BaseModel):
    nombre: str
    categoria: str = "mixto"
    color: str = ""
    capitan: str = ""
    notas: str = ""


@router.get("/equipos")
def listar_equipos(_=Depends(require_role(ROLES))):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM liga_equipos WHERE activo=1 ORDER BY nombre").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/equipos", status_code=201)
def crear_equipo(body: EquipoIn, _=Depends(require_role(ROLES))):
    conn = get_conn()
    id_ = _next_id(conn, "liga_equipos", "EQ")
    conn.execute(
        "INSERT INTO liga_equipos (id, nombre, categoria, color, capitan, notas) VALUES (?,?,?,?,?,?)",
        (id_, body.nombre, body.categoria, body.color, body.capitan, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump()}


@router.delete("/equipos/{id_}", status_code=204)
def eliminar_equipo(id_: str, _=Depends(require_role(ROLES))):
    conn = get_conn()
    cur = conn.execute("UPDATE liga_equipos SET activo=0 WHERE id=?", (id_,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Equipo no encontrado")


# ── Jugadores ─────────────────────────────────────────────────────────────────

class JugadorIn(BaseModel):
    nombre: str
    equipo_id: Optional[str] = None
    posicion: str = ""
    numero: Optional[int] = None
    notas: str = ""


@router.get("/jugadores")
def listar_jugadores(
    equipo_id: Optional[str] = None,
    _=Depends(require_role(ROLES)),
):
    conn = get_conn()
    if equipo_id:
        rows = conn.execute(
            "SELECT * FROM liga_jugadores WHERE equipo_id=? AND activo=1 ORDER BY nombre",
            (equipo_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM liga_jugadores WHERE activo=1 ORDER BY nombre"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/jugadores", status_code=201)
def crear_jugador(body: JugadorIn, _=Depends(require_role(ROLES))):
    conn = get_conn()
    id_ = _next_id(conn, "liga_jugadores", "JUG")
    conn.execute(
        "INSERT INTO liga_jugadores (id, nombre, equipo_id, posicion, numero, notas) VALUES (?,?,?,?,?,?)",
        (id_, body.nombre, body.equipo_id, body.posicion, body.numero, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump()}


# ── Partidos ──────────────────────────────────────────────────────────────────

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


@router.get("/partidos")
def listar_partidos(
    estado: Optional[str] = None,
    jornada: Optional[int] = None,
    _=Depends(require_role(ROLES)),
):
    query = "SELECT p.*, el.nombre as local_nombre, ev.nombre as visitante_nombre FROM liga_partidos p LEFT JOIN liga_equipos el ON p.equipo_local_id=el.id LEFT JOIN liga_equipos ev ON p.equipo_visitante_id=ev.id WHERE 1=1"
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


@router.post("/partidos", status_code=201)
def crear_partido(body: PartidoIn, _=Depends(require_role(ROLES))):
    conn = get_conn()
    id_ = _next_id(conn, "liga_partidos", "PAR")
    conn.execute(
        "INSERT INTO liga_partidos (id, fecha, equipo_local_id, equipo_visitante_id, cancha, jornada, notas) VALUES (?,?,?,?,?,?,?)",
        (id_, body.fecha, body.equipo_local_id, body.equipo_visitante_id, body.cancha, body.jornada, body.notas),
    )
    conn.commit()
    conn.close()
    return {"id": id_, **body.model_dump(), "estado": "programado"}


@router.patch("/partidos/{id_}/resultado")
def registrar_resultado(id_: str, body: ResultadoIn, _=Depends(require_role(ROLES))):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM liga_partidos WHERE id=?", (id_,)).fetchone():
        conn.close()
        raise HTTPException(404, "Partido no encontrado")
    conn.execute(
        "UPDATE liga_partidos SET goles_local=?, goles_visitante=?, estado=? WHERE id=?",
        (body.goles_local, body.goles_visitante, body.estado, id_),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM liga_partidos WHERE id=?", (id_,)).fetchone()
    conn.close()
    return dict(row)


@router.get("/tabla")
def tabla_posiciones(_=Depends(require_role(ROLES))):
    """Calcula tabla de posiciones a partir de partidos finalizados."""
    conn = get_conn()
    equipos = conn.execute("SELECT * FROM liga_equipos WHERE activo=1").fetchall()
    partidos = conn.execute(
        "SELECT * FROM liga_partidos WHERE estado='finalizado'"
    ).fetchall()
    conn.close()

    tabla: dict[str, dict] = {}
    for e in equipos:
        tabla[e["id"]] = {
            "id": e["id"], "nombre": e["nombre"], "categoria": e["categoria"],
            "pj": 0, "pg": 0, "pe": 0, "pp": 0, "gf": 0, "gc": 0, "pts": 0,
        }

    for p in partidos:
        lid, vid = p["equipo_local_id"], p["equipo_visitante_id"]
        gl, gv = p["goles_local"], p["goles_visitante"]
        if lid not in tabla or vid not in tabla:
            continue
        for eid, gf, gc in [(lid, gl, gv), (vid, gv, gl)]:
            t = tabla[eid]
            t["pj"] += 1
            t["gf"] += gf
            t["gc"] += gc
        if gl > gv:
            tabla[lid]["pg"] += 1; tabla[lid]["pts"] += 3
            tabla[vid]["pp"] += 1
        elif gl < gv:
            tabla[vid]["pg"] += 1; tabla[vid]["pts"] += 3
            tabla[lid]["pp"] += 1
        else:
            tabla[lid]["pe"] += 1; tabla[lid]["pts"] += 1
            tabla[vid]["pe"] += 1; tabla[vid]["pts"] += 1

    return sorted(tabla.values(), key=lambda x: (-x["pts"], -(x["gf"] - x["gc"])))
