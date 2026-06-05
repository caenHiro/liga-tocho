"""API FastAPI — Liga de Tochito. Versión completa con temporadas, categorías y validaciones."""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .bd import CATEGORIAS, DIVISIONES, get_conn, init_db
from .scheduler import generar_calendario
from .validaciones import validar_inscripcion, validar_solapamiento_jornada

app = FastAPI(title="Liga Tochito", version="2.0.0")


# ── helpers ──────────────────────────────────────────────────────────────────

def _row(r) -> dict:
    return dict(r)


def _or_404(obj, msg: str = "No encontrado"):
    if obj is None:
        raise HTTPException(404, msg)
    return obj


# ════════════════════════════════════════════════════════════════════════════
# TEMPORADAS
# ════════════════════════════════════════════════════════════════════════════

temporadas_router = APIRouter(prefix="/api/temporadas", tags=["temporadas"])


class TemporadaIn(BaseModel):
    nombre: str
    anio: int
    numero: int  # 1-4
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None


@temporadas_router.get("/")
def listar_temporadas():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM temporadas ORDER BY anio DESC, numero DESC"
    ).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@temporadas_router.post("/", status_code=201)
def crear_temporada(body: TemporadaIn):
    if body.numero not in range(1, 5):
        raise HTTPException(400, "El número de temporada debe ser 1, 2, 3 o 4")
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO temporadas (nombre, anio, numero, fecha_inicio, fecha_fin) VALUES (?,?,?,?,?)",
            (body.nombre, body.anio, body.numero, body.fecha_inicio, body.fecha_fin),
        )
        tid = cur.lastrowid
        # Crear las 11 jornadas automáticamente
        for j in range(1, 12):
            conn.execute(
                "INSERT INTO jornadas (temporada_id, numero) VALUES (?,?)", (tid, j)
            )
        conn.commit()
        row = conn.execute("SELECT * FROM temporadas WHERE id=?", (tid,)).fetchone()
        conn.close()
        return _row(row)
    except Exception as e:
        conn.close()
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"Ya existe la temporada {body.numero} del año {body.anio}")
        raise HTTPException(400, str(e))


@temporadas_router.patch("/{tid}")
def actualizar_temporada(tid: int, body: TemporadaIn):
    conn = get_conn()
    conn.execute(
        "UPDATE temporadas SET nombre=?, fecha_inicio=?, fecha_fin=? WHERE id=?",
        (body.nombre, body.fecha_inicio, body.fecha_fin, tid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM temporadas WHERE id=?", (tid,)).fetchone()
    conn.close()
    return _row(_or_404(row, "Temporada no encontrada"))


@temporadas_router.patch("/{tid}/estado")
def cambiar_estado(tid: int, estado: str):
    if estado not in ("activa", "finalizada", "cancelada"):
        raise HTTPException(400, "Estado inválido")
    conn = get_conn()
    conn.execute("UPDATE temporadas SET estado=? WHERE id=?", (estado, tid))
    conn.commit()
    conn.close()
    return {"ok": True}


@temporadas_router.get("/{tid}/jornadas")
def listar_jornadas(tid: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jornadas WHERE temporada_id=? ORDER BY numero", (tid,)
    ).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@temporadas_router.patch("/jornadas/{jid}/fecha")
def actualizar_fecha_jornada(jid: int, fecha: Optional[str] = None):
    conn = get_conn()
    conn.execute("UPDATE jornadas SET fecha=? WHERE id=?", (fecha, jid))
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# CANCHAS
# ════════════════════════════════════════════════════════════════════════════

canchas_router = APIRouter(prefix="/api/canchas", tags=["canchas"])


class CancharIn(BaseModel):
    nombre: str
    activa: int = 1


@canchas_router.get("/")
def listar_canchas():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM canchas ORDER BY nombre").fetchall()
    conn.close()
    return [_row(r) for r in rows]


@canchas_router.post("/", status_code=201)
def crear_cancha(body: CancharIn):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO canchas (nombre, activa) VALUES (?,?)", (body.nombre, body.activa))
        row = conn.execute("SELECT * FROM canchas WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.commit()
        conn.close()
        return _row(row)
    except Exception:
        conn.close()
        raise HTTPException(409, f"Ya existe una cancha con el nombre '{body.nombre}'")


@canchas_router.delete("/{cid}", status_code=204)
def eliminar_cancha(cid: int):
    conn = get_conn()
    conn.execute("DELETE FROM canchas WHERE id=?", (cid,))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# EQUIPOS
# ════════════════════════════════════════════════════════════════════════════

equipos_router = APIRouter(prefix="/api/equipos", tags=["equipos"])


class EquipoIn(BaseModel):
    nombre: str
    color: str = ""
    notas: str = ""


@equipos_router.get("/")
def listar_equipos():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM equipos WHERE activo=1 ORDER BY nombre").fetchall()
    conn.close()
    return [_row(r) for r in rows]


@equipos_router.post("/", status_code=201)
def crear_equipo(body: EquipoIn):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO equipos (nombre, color, notas) VALUES (?,?,?)",
            (body.nombre, body.color, body.notas),
        )
        row = conn.execute("SELECT * FROM equipos WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.commit()
        conn.close()
        return _row(row)
    except Exception:
        conn.close()
        raise HTTPException(409, f"Ya existe un equipo con el nombre '{body.nombre}'")


@equipos_router.patch("/{eid}")
def actualizar_equipo(eid: int, body: EquipoIn):
    conn = get_conn()
    conn.execute("UPDATE equipos SET nombre=?, color=?, notas=? WHERE id=?",
                 (body.nombre, body.color, body.notas, eid))
    conn.commit()
    row = conn.execute("SELECT * FROM equipos WHERE id=?", (eid,)).fetchone()
    conn.close()
    return _row(_or_404(row))


@equipos_router.delete("/{eid}", status_code=204)
def eliminar_equipo(eid: int):
    conn = get_conn()
    conn.execute("UPDATE equipos SET activo=0 WHERE id=?", (eid,))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# REGISTROS (equipo en categoría/división/temporada)
# ════════════════════════════════════════════════════════════════════════════

registros_router = APIRouter(prefix="/api/registros", tags=["registros"])


class RegistroIn(BaseModel):
    temporada_id: int
    equipo_id: int
    categoria: str  # A-F
    division: str   # varonil | mixto | femenino
    capitan: str = ""
    preferencia_horario: str = "sin_restriccion"


def _row_registro(r) -> dict:
    d = dict(r)
    return d


@registros_router.get("/")
def listar_registros(temporada_id: Optional[int] = None):
    conn = get_conn()
    q = """
        SELECT r.*, e.nombre as equipo_nombre, e.color,
               rh.preferencia as preferencia_horario,
               COUNT(i.id) as n_jugadores
        FROM registros r
        JOIN equipos e ON e.id = r.equipo_id
        LEFT JOIN restricciones_horario rh ON rh.registro_id = r.id
        LEFT JOIN inscripciones i ON i.registro_id = r.id AND i.activo=1
        WHERE r.activo=1
    """
    params = []
    if temporada_id:
        q += " AND r.temporada_id=?"
        params.append(temporada_id)
    q += " GROUP BY r.id ORDER BY r.categoria, r.division, e.nombre"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@registros_router.post("/", status_code=201)
def crear_registro(body: RegistroIn):
    if body.categoria not in CATEGORIAS:
        raise HTTPException(400, f"Categoría inválida. Usar: {CATEGORIAS}")
    if body.division not in DIVISIONES:
        raise HTTPException(400, f"División inválida. Usar: {DIVISIONES}")
    if body.preferencia_horario not in ("manana", "mediodia", "tarde", "sin_restriccion"):
        raise HTTPException(400, "Preferencia horario inválida")
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO registros (temporada_id, equipo_id, categoria, division, capitan) VALUES (?,?,?,?,?)",
            (body.temporada_id, body.equipo_id, body.categoria, body.division, body.capitan),
        )
        rid = cur.lastrowid
        conn.execute(
            "INSERT INTO restricciones_horario (registro_id, preferencia) VALUES (?,?)",
            (rid, body.preferencia_horario),
        )
        conn.commit()
        row = conn.execute("""
            SELECT r.*, e.nombre as equipo_nombre, rh.preferencia as preferencia_horario
            FROM registros r JOIN equipos e ON e.id=r.equipo_id
            LEFT JOIN restricciones_horario rh ON rh.registro_id=r.id
            WHERE r.id=?""", (rid,)).fetchone()
        conn.close()
        return _row(row)
    except Exception as e:
        conn.close()
        if "UNIQUE" in str(e):
            raise HTTPException(409, "El equipo ya está inscrito en esa categoría/división/temporada")
        raise HTTPException(400, str(e))


@registros_router.patch("/{rid}/horario")
def actualizar_horario(rid: int, preferencia: str):
    if preferencia not in ("manana", "mediodia", "tarde", "sin_restriccion"):
        raise HTTPException(400, "Preferencia inválida")
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO restricciones_horario (registro_id, preferencia) VALUES (?,?)",
        (rid, preferencia),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@registros_router.delete("/{rid}", status_code=204)
def eliminar_registro(rid: int):
    conn = get_conn()
    conn.execute("UPDATE registros SET activo=0 WHERE id=?", (rid,))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# JUGADORES
# ════════════════════════════════════════════════════════════════════════════

jugadores_router = APIRouter(prefix="/api/jugadores", tags=["jugadores"])


class JugadorIn(BaseModel):
    nombre: str
    notas: str = ""


class InscripcionIn(BaseModel):
    registro_id: int
    numero: Optional[int] = None
    posicion: str = ""


@jugadores_router.get("/")
def listar_jugadores():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM jugadores WHERE activo=1 ORDER BY nombre").fetchall()
    conn.close()
    return [_row(r) for r in rows]


@jugadores_router.post("/", status_code=201)
def crear_jugador(body: JugadorIn):
    conn = get_conn()
    cur = conn.execute("INSERT INTO jugadores (nombre, notas) VALUES (?,?)", (body.nombre, body.notas))
    row = conn.execute("SELECT * FROM jugadores WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.commit()
    conn.close()
    return _row(row)


@jugadores_router.get("/{jid}/inscripciones")
def inscripciones_jugador(jid: int):
    conn = get_conn()
    rows = conn.execute("""
        SELECT i.*, r.categoria, r.division, e.nombre as equipo, t.nombre as temporada
        FROM inscripciones i
        JOIN registros r ON r.id=i.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        JOIN temporadas t ON t.id=r.temporada_id
        WHERE i.jugador_id=? AND i.activo=1
        ORDER BY t.anio DESC, t.numero DESC
    """, (jid,)).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@jugadores_router.post("/{jid}/inscribir", status_code=201)
def inscribir_jugador(jid: int, body: InscripcionIn):
    conn = get_conn()
    jug = conn.execute("SELECT * FROM jugadores WHERE id=?", (jid,)).fetchone()
    _or_404(jug, "Jugador no encontrado")
    reg = conn.execute("SELECT * FROM registros WHERE id=? AND activo=1", (body.registro_id,)).fetchone()
    _or_404(reg, "Registro no encontrado")

    errores = validar_inscripcion(conn, jid, body.registro_id)
    if errores:
        conn.close()
        raise HTTPException(422, {"errores": errores})

    try:
        cur = conn.execute(
            "INSERT INTO inscripciones (jugador_id, registro_id, numero, posicion) VALUES (?,?,?,?)",
            (jid, body.registro_id, body.numero, body.posicion),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM inscripciones WHERE id=?", (cur.lastrowid,)).fetchone()
        conn.close()
        return _row(row)
    except Exception as e:
        conn.close()
        if "UNIQUE" in str(e):
            raise HTTPException(409, "El jugador ya está inscrito en ese registro")
        raise HTTPException(400, str(e))


@jugadores_router.delete("/{jid}/desinscribir/{rid}", status_code=204)
def desinscribir_jugador(jid: int, rid: int):
    conn = get_conn()
    conn.execute(
        "UPDATE inscripciones SET activo=0 WHERE jugador_id=? AND registro_id=?",
        (jid, rid),
    )
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# PARTIDOS
# ════════════════════════════════════════════════════════════════════════════

partidos_router = APIRouter(prefix="/api/partidos", tags=["partidos"])


class ResultadoIn(BaseModel):
    goles_local: int
    goles_visitante: int
    estado: str = "finalizado"


@partidos_router.get("/")
def listar_partidos(jornada_id: Optional[int] = None, temporada_id: Optional[int] = None):
    conn = get_conn()
    q = """
        SELECT p.*,
               el.nombre as equipo_local, rl.categoria, rl.division,
               ev.nombre as equipo_visitante,
               c.nombre as cancha_nombre,
               j.numero as jornada_num, j.fecha as jornada_fecha
        FROM partidos p
        JOIN jornadas j ON j.id=p.jornada_id
        JOIN registros rl ON rl.id=p.registro_local_id
        JOIN registros rv ON rv.id=p.registro_visitante_id
        JOIN equipos el ON el.id=rl.equipo_id
        JOIN equipos ev ON ev.id=rv.equipo_id
        LEFT JOIN canchas c ON c.id=p.cancha_id
        WHERE 1=1
    """
    params = []
    if jornada_id:
        q += " AND p.jornada_id=?"
        params.append(jornada_id)
    if temporada_id:
        q += " AND j.temporada_id=?"
        params.append(temporada_id)
    q += " ORDER BY j.numero, p.franja, p.hora_inicio"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [_row(r) for r in rows]


@partidos_router.patch("/{pid}/resultado")
def registrar_resultado(pid: int, body: ResultadoIn):
    if body.estado not in ("finalizado", "suspendido", "en_juego"):
        raise HTTPException(400, "Estado inválido")
    conn = get_conn()
    conn.execute(
        "UPDATE partidos SET goles_local=?, goles_visitante=?, estado=? WHERE id=?",
        (body.goles_local, body.goles_visitante, body.estado, pid),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# TABLA DE POSICIONES
# ════════════════════════════════════════════════════════════════════════════

tabla_router = APIRouter(prefix="/api/tabla", tags=["tabla"])


@tabla_router.get("/")
def tabla_posiciones(temporada_id: int, categoria: Optional[str] = None, division: Optional[str] = None):
    conn = get_conn()
    q = """
        SELECT r.id, r.categoria, r.division, e.nombre as equipo, e.color,
               COUNT(CASE WHEN (p.registro_local_id=r.id AND p.goles_local > p.goles_visitante)
                            OR (p.registro_visitante_id=r.id AND p.goles_visitante > p.goles_local)
                         THEN 1 END) as ganados,
               COUNT(CASE WHEN p.goles_local = p.goles_visitante
                           AND (p.registro_local_id=r.id OR p.registro_visitante_id=r.id)
                         THEN 1 END) as empatados,
               COUNT(CASE WHEN (p.registro_local_id=r.id AND p.goles_local < p.goles_visitante)
                            OR (p.registro_visitante_id=r.id AND p.goles_visitante < p.goles_local)
                         THEN 1 END) as perdidos,
               COALESCE(SUM(CASE WHEN p.registro_local_id=r.id THEN p.goles_local
                                 WHEN p.registro_visitante_id=r.id THEN p.goles_visitante END), 0) as gf,
               COALESCE(SUM(CASE WHEN p.registro_local_id=r.id THEN p.goles_visitante
                                 WHEN p.registro_visitante_id=r.id THEN p.goles_local END), 0) as gc
        FROM registros r
        JOIN equipos e ON e.id=r.equipo_id
        LEFT JOIN partidos p ON (p.registro_local_id=r.id OR p.registro_visitante_id=r.id)
                              AND p.estado='finalizado'
        WHERE r.temporada_id=? AND r.activo=1
    """
    params: list = [temporada_id]
    if categoria:
        q += " AND r.categoria=?"
        params.append(categoria)
    if division:
        q += " AND r.division=?"
        params.append(division)
    q += " GROUP BY r.id ORDER BY r.categoria, r.division, ganados DESC, (gf-gc) DESC, gf DESC"

    rows = conn.execute(q, params).fetchall()
    conn.close()

    tabla = []
    for r in rows:
        d = dict(r)
        d["jugados"] = d["ganados"] + d["empatados"] + d["perdidos"]
        d["puntos"] = d["ganados"] * 3 + d["empatados"]
        d["diferencia"] = d["gf"] - d["gc"]
        tabla.append(d)
    return tabla


# ════════════════════════════════════════════════════════════════════════════
# CALENDARIO (generador de fixture)
# ════════════════════════════════════════════════════════════════════════════

calendario_router = APIRouter(prefix="/api/calendario", tags=["calendario"])


class CalendarioIn(BaseModel):
    temporada_id: int
    canchas_manana: int = 1
    canchas_mediodia: int = 1
    canchas_tarde: int = 1


@calendario_router.post("/generar")
def generar(body: CalendarioIn):
    conn = get_conn()
    resultado = generar_calendario(
        conn,
        body.temporada_id,
        body.canchas_manana,
        body.canchas_mediodia,
        body.canchas_tarde,
    )
    conn.close()
    return resultado


@calendario_router.delete("/temporada/{tid}", status_code=204)
def limpiar_calendario(tid: int):
    """Elimina todos los partidos de la temporada para regenerar."""
    conn = get_conn()
    conn.execute(
        "DELETE FROM partidos WHERE jornada_id IN (SELECT id FROM jornadas WHERE temporada_id=?)",
        (tid,),
    )
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# APP — registrar routers
# ════════════════════════════════════════════════════════════════════════════

for router in [temporadas_router, canchas_router, equipos_router,
               registros_router, jugadores_router, partidos_router,
               tabla_router, calendario_router]:
    app.include_router(router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/config")
def config():
    return {"categorias": CATEGORIAS, "divisiones": DIVISIONES,
            "franjas": ["manana", "mediodia", "tarde"],
            "max_jugadores_registro": 20, "max_equipos_por_jugador": 3,
            "jornadas_por_temporada": 11, "temporadas_por_anio": 4}
