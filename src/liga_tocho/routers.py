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


@registros_router.patch("/{rid}/horario-jornada")
def restriccion_por_jornada(rid: int, jornada_id: int, preferencia: str):
    """Admin o QB: establece restricción de horario para una jornada específica."""
    if preferencia not in ("manana", "mediodia", "tarde", "sin_restriccion"):
        raise HTTPException(400, "Preferencia inválida")
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO restricciones_jornada (registro_id, jornada_id, preferencia) VALUES (?,?,?)",
        (rid, jornada_id, preferencia),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@registros_router.get("/{rid}/horario-jornadas")
def ver_restricciones_jornada(rid: int):
    """Lista todas las restricciones por jornada de un registro."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT rj.*, j.numero as jornada_num
           FROM restricciones_jornada rj JOIN jornadas j ON j.id=rj.jornada_id
           WHERE rj.registro_id=? ORDER BY j.numero""",
        (rid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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
    posicion_principal: str = ""
    numero_camiseta: Optional[int] = None
    telefono: str = ""


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
    cur = conn.execute(
        "INSERT INTO jugadores (nombre, notas, posicion_principal, numero_camiseta, telefono) VALUES (?,?,?,?,?)",
        (body.nombre, body.notas, body.posicion_principal, body.numero_camiseta, body.telefono),
    )
    row = conn.execute("SELECT * FROM jugadores WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.commit()
    conn.close()
    return _row(row)


@jugadores_router.patch("/{jid}")
def actualizar_jugador(jid: int, body: JugadorIn):
    conn = get_conn()
    conn.execute(
        "UPDATE jugadores SET nombre=?, notas=?, posicion_principal=?, numero_camiseta=?, telefono=? WHERE id=?",
        (body.nombre, body.notas, body.posicion_principal, body.numero_camiseta, body.telefono, jid),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM jugadores WHERE id=?", (jid,)).fetchone()
    conn.close()
    return _row(_or_404(row, "Jugador no encontrado"))


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


class EstadisticasIn(BaseModel):
    touchdowns: int = 0
    yardas_pase: int = 0
    yardas_tierra: int = 0
    intercepciones_lanzadas: int = 0
    intercepciones_atrapadas: int = 0
    puntos_extra: int = 0


class ResultadoIn(BaseModel):
    goles_local: int
    goles_visitante: int
    estado: str = "finalizado"
    stats_local: Optional[EstadisticasIn] = None
    stats_visitante: Optional[EstadisticasIn] = None


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
    partido = conn.execute("SELECT * FROM partidos WHERE id=?", (pid,)).fetchone()
    if not partido:
        conn.close()
        raise HTTPException(404, "Partido no encontrado")
    conn.execute(
        "UPDATE partidos SET goles_local=?, goles_visitante=?, estado=? WHERE id=?",
        (body.goles_local, body.goles_visitante, body.estado, pid),
    )
    # Upsert estadísticas si se enviaron
    for stats, reg_id in [
        (body.stats_local, partido["registro_local_id"]),
        (body.stats_visitante, partido["registro_visitante_id"]),
    ]:
        if stats and reg_id:
            conn.execute("""
                INSERT INTO estadisticas_partido
                    (partido_id, registro_id, touchdowns, yardas_pase, yardas_tierra,
                     intercepciones_lanzadas, intercepciones_atrapadas, puntos_extra)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(partido_id, registro_id) DO UPDATE SET
                    touchdowns=excluded.touchdowns,
                    yardas_pase=excluded.yardas_pase,
                    yardas_tierra=excluded.yardas_tierra,
                    intercepciones_lanzadas=excluded.intercepciones_lanzadas,
                    intercepciones_atrapadas=excluded.intercepciones_atrapadas,
                    puntos_extra=excluded.puntos_extra
            """, (pid, reg_id, stats.touchdowns, stats.yardas_pase, stats.yardas_tierra,
                  stats.intercepciones_lanzadas, stats.intercepciones_atrapadas, stats.puntos_extra))
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
# ESTADÍSTICAS
# ════════════════════════════════════════════════════════════════════════════

estadisticas_router = APIRouter(prefix="/api/estadisticas", tags=["estadisticas"])


@estadisticas_router.get("/partido/{pid}")
def stats_partido(pid: int):
    """Estadísticas detalladas de un partido: local vs visitante."""
    conn = get_conn()
    partido = conn.execute("SELECT * FROM partidos WHERE id=?", (pid,)).fetchone()
    if not partido:
        conn.close()
        raise HTTPException(404, "Partido no encontrado")
    rows = conn.execute("""
        SELECT sp.*, e.nombre as equipo, r.categoria, r.division
        FROM estadisticas_partido sp
        JOIN registros r ON r.id = sp.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        WHERE sp.partido_id = ?
    """, (pid,)).fetchall()
    conn.close()
    return {"partido_id": pid, "estadisticas": [_row(r) for r in rows]}


class EstadisticasJugadorIn(BaseModel):
    partido_id: int
    jugador_id: int
    registro_id: int
    touchdowns: int = 0
    yardas_pase: int = 0
    yardas_tierra: int = 0
    intercepciones_lanzadas: int = 0
    intercepciones_atrapadas: int = 0
    puntos_extra: int = 0


@estadisticas_router.post("/jugador", status_code=201)
def registrar_stats_jugador(body: EstadisticasJugadorIn):
    """Registra o actualiza estadísticas individuales de un jugador en un partido."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO estadisticas_jugador
            (partido_id, jugador_id, registro_id, touchdowns, yardas_pase, yardas_tierra,
             intercepciones_lanzadas, intercepciones_atrapadas, puntos_extra)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(partido_id, jugador_id) DO UPDATE SET
            touchdowns=excluded.touchdowns, yardas_pase=excluded.yardas_pase,
            yardas_tierra=excluded.yardas_tierra,
            intercepciones_lanzadas=excluded.intercepciones_lanzadas,
            intercepciones_atrapadas=excluded.intercepciones_atrapadas,
            puntos_extra=excluded.puntos_extra
    """, (body.partido_id, body.jugador_id, body.registro_id,
          body.touchdowns, body.yardas_pase, body.yardas_tierra,
          body.intercepciones_lanzadas, body.intercepciones_atrapadas, body.puntos_extra))
    conn.commit()
    conn.close()
    return {"ok": True}


@estadisticas_router.get("/jugadores/{temporada_id}")
def ranking_jugadores(
    temporada_id: int,
    categoria: Optional[str] = None,
    division: Optional[str] = None,
    limit: int = 10,
):
    """Ranking individual de jugadores por TDs y yardas en la temporada."""
    conn = get_conn()
    filtros = ""
    params: list = [temporada_id]
    if categoria:
        filtros += " AND r.categoria=?"
        params.append(categoria)
    if division:
        filtros += " AND r.division=?"
        params.append(division)
    params.append(limit)
    rows = conn.execute(f"""
        SELECT j.id as jugador_id, j.nombre as jugador,
               j.posicion_principal as posicion, j.numero_camiseta as numero,
               e.nombre as equipo, r.categoria, r.division,
               SUM(sj.touchdowns) as total_tds,
               SUM(sj.yardas_pase + sj.yardas_tierra) as total_yardas,
               SUM(sj.intercepciones_atrapadas) as total_int,
               COUNT(DISTINCT sj.partido_id) as partidos_jugados
        FROM estadisticas_jugador sj
        JOIN jugadores j ON j.id = sj.jugador_id
        JOIN registros r ON r.id = sj.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        WHERE r.temporada_id = ? {filtros}
        GROUP BY j.id, r.id
        ORDER BY total_tds DESC, total_yardas DESC
        LIMIT ?
    """, params).fetchall()
    conn.close()
    return {"temporada_id": temporada_id, "jugadores": [_row(r) for r in rows]}


@estadisticas_router.get("/mvp/jornada/{jornada_id}")
def mvp_jornada(jornada_id: int):
    """MVP de la jornada: jugador con más TDs + desempate por yardas."""
    conn = get_conn()
    row = conn.execute("""
        SELECT j.id as jugador_id, j.nombre as jugador,
               j.posicion_principal as posicion,
               e.nombre as equipo, r.categoria, r.division,
               SUM(sj.touchdowns) as total_tds,
               SUM(sj.yardas_pase + sj.yardas_tierra) as total_yardas,
               SUM(sj.intercepciones_atrapadas) as total_int
        FROM estadisticas_jugador sj
        JOIN partidos p ON p.id = sj.partido_id
        JOIN jugadores j ON j.id = sj.jugador_id
        JOIN registros r ON r.id = sj.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        WHERE p.jornada_id = ?
        GROUP BY j.id, r.id
        ORDER BY total_tds DESC, total_yardas DESC
        LIMIT 1
    """, (jornada_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Sin estadísticas de jugadores para esta jornada")
    return {"jornada_id": jornada_id, "mvp": _row(row)}


@estadisticas_router.get("/top/{temporada_id}")
def stats_top(temporada_id: int, categoria: Optional[str] = None, division: Optional[str] = None):
    """Ranking de equipos por temporada: touchdowns, yardas totales."""
    conn = get_conn()
    filtro = "AND r.categoria=?" if categoria else ""
    filtro2 = "AND r.division=?" if division else ""
    params: list = [temporada_id]
    if categoria:
        params.append(categoria)
    if division:
        params.append(division)
    rows = conn.execute(f"""
        SELECT e.nombre as equipo, e.color, r.categoria, r.division,
               SUM(sp.touchdowns) as total_tds,
               SUM(sp.yardas_pase + sp.yardas_tierra) as total_yardas,
               SUM(sp.intercepciones_atrapadas) as total_int_atrapadas,
               COUNT(DISTINCT sp.partido_id) as partidos_con_stats
        FROM estadisticas_partido sp
        JOIN registros r ON r.id = sp.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        JOIN jornadas j ON j.temporada_id = ?
        WHERE r.temporada_id = ? {filtro} {filtro2}
        GROUP BY r.id
        ORDER BY total_tds DESC, total_yardas DESC
    """, [temporada_id] + params).fetchall()
    conn.close()
    return {"temporada_id": temporada_id, "ranking": [_row(r) for r in rows]}


# ════════════════════════════════════════════════════════════════════════════
# NOTIFICACIONES (mensajes WhatsApp via Ollama)
# ════════════════════════════════════════════════════════════════════════════

notificaciones_router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])


def _ollama_chat(prompt: str, modelo: str = "llama3.2") -> str:
    """Llama a Ollama local. Retorna '' si no está disponible."""
    import json as _json
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    payload = _json.dumps({
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 300},
    }).encode()
    try:
        req = Request("http://localhost:11434/api/chat", data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=45) as resp:
            data = _json.loads(resp.read())
        return data.get("message", {}).get("content", "").strip()
    except (URLError, OSError):
        return ""


@notificaciones_router.get("/partido/{pid}")
def notificacion_partido(pid: int, modelo: str = "llama3.2"):
    """Genera mensajes WhatsApp para ambos equipos con resultado y stats."""
    conn = get_conn()
    partido = conn.execute("""
        SELECT p.*,
               el.nombre as equipo_local, ev.nombre as equipo_visitante,
               c.nombre as cancha,
               j.numero as jornada_num
        FROM partidos p
        JOIN registros rl ON rl.id=p.registro_local_id
        JOIN registros rv ON rv.id=p.registro_visitante_id
        JOIN equipos el ON el.id=rl.equipo_id
        JOIN equipos ev ON ev.id=rv.equipo_id
        LEFT JOIN canchas c ON c.id=p.cancha_id
        LEFT JOIN jornadas j ON j.id=p.jornada_id
        WHERE p.id=?
    """, (pid,)).fetchone()
    if not partido:
        conn.close()
        raise HTTPException(404, "Partido no encontrado")

    stats_rows = conn.execute("""
        SELECT sp.*, e.nombre as equipo
        FROM estadisticas_partido sp
        JOIN registros r ON r.id=sp.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        WHERE sp.partido_id=?
    """, (pid,)).fetchall()
    conn.close()

    p = dict(partido)
    stats_txt = ""
    for s in stats_rows:
        sd = dict(s)
        stats_txt += (
            f"\n  {sd['equipo']}: {sd['touchdowns']} TDs, "
            f"{sd['yardas_pase']+sd['yardas_tierra']} yds, "
            f"{sd['intercepciones_atrapadas']} INT atrapadas"
        )

    prompt = f"""Eres el community manager de una liga de tochito bandera.
Redacta un mensaje corto y emocionante para WhatsApp (máx 5 líneas) anunciando este resultado:

Jornada {p.get('jornada_num','?')} — Cancha: {p.get('cancha','?')}
{p['equipo_local']} {p['goles_local']} — {p['goles_visitante']} {p['equipo_visitante']}
Estado: {p['estado']}
Estadísticas:{stats_txt if stats_txt else ' no disponibles'}

El mensaje debe:
- Mencionar al ganador (o empate)
- Incluir un dato de estadística si está disponible
- Usar 1-2 emojis deportivos
- Terminar con hashtag de la liga
Responde solo el mensaje, sin explicaciones."""

    msg = _ollama_chat(prompt, modelo)
    if not msg:
        # Fallback sin Ollama
        ganador = p['equipo_local'] if p['goles_local'] > p['goles_visitante'] else (
            p['equipo_visitante'] if p['goles_visitante'] > p['goles_local'] else "Empate"
        )
        msg = (
            f"Resultado J{p.get('jornada_num','?')}: "
            f"{p['equipo_local']} {p['goles_local']}-{p['goles_visitante']} {p['equipo_visitante']}. "
            f"{'Gana ' + ganador if ganador != 'Empate' else 'Empate'} #LigaTochito"
        )

    return {
        "partido_id": pid,
        "equipo_local": p["equipo_local"],
        "equipo_visitante": p["equipo_visitante"],
        "resultado": f"{p['goles_local']}-{p['goles_visitante']}",
        "mensaje_whatsapp": msg,
        "modelo_usado": modelo if _ollama_chat else "fallback",
    }


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
