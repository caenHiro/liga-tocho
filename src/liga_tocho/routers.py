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


class EstadisticasEquipoIn(BaseModel):
    touchdowns: int = 0
    puntos_extra: int = 0          # conversiones de 1 o 2 pts
    intercepciones_lanzadas: int = 0
    intercepciones_atrapadas: int = 0
    yardas_pase: int = 0
    yardas_tierra: int = 0


class ResultadoIn(BaseModel):
    goles_local: int               # puntos totales (TD×6 + extra)
    goles_visitante: int
    estado: str = "finalizado"
    stats_local: Optional[EstadisticasEquipoIn] = None
    stats_visitante: Optional[EstadisticasEquipoIn] = None


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

    # Guardar estadísticas detalladas si se proporcionaron
    for reg_id, stats in [
        (partido["registro_local_id"], body.stats_local),
        (partido["registro_visitante_id"], body.stats_visitante),
    ]:
        if stats and reg_id:
            conn.execute("""
                INSERT INTO estadisticas_partido
                    (partido_id, registro_id, touchdowns, puntos_extra,
                     intercepciones_lanzadas, intercepciones_atrapadas,
                     yardas_pase, yardas_tierra)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(partido_id, registro_id) DO UPDATE SET
                    touchdowns=excluded.touchdowns,
                    puntos_extra=excluded.puntos_extra,
                    intercepciones_lanzadas=excluded.intercepciones_lanzadas,
                    intercepciones_atrapadas=excluded.intercepciones_atrapadas,
                    yardas_pase=excluded.yardas_pase,
                    yardas_tierra=excluded.yardas_tierra
            """, (pid, reg_id, stats.touchdowns, stats.puntos_extra,
                  stats.intercepciones_lanzadas, stats.intercepciones_atrapadas,
                  stats.yardas_pase, stats.yardas_tierra))

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
# ESTADÍSTICAS AVANZADAS
# ════════════════════════════════════════════════════════════════════════════

stats_router = APIRouter(prefix="/api/estadisticas", tags=["estadisticas"])


@stats_router.get("/top/{temporada_id}")
def top_estadisticas(temporada_id: int):
    """Top stats por equipo para la temporada: touchdowns, yardas, intercepciones."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT e.nombre as equipo, r.categoria, r.division,
               COALESCE(SUM(ep.touchdowns), 0)               as touchdowns,
               COALESCE(SUM(ep.puntos_extra), 0)             as puntos_extra,
               COALESCE(SUM(ep.intercepciones_atrapadas), 0) as intercepciones,
               COALESCE(SUM(ep.yardas_pase), 0)              as yardas_pase,
               COALESCE(SUM(ep.yardas_tierra), 0)            as yardas_tierra
        FROM registros r
        JOIN equipos e ON e.id=r.equipo_id
        LEFT JOIN estadisticas_partido ep ON ep.registro_id=r.id
        WHERE r.temporada_id=? AND r.activo=1
        GROUP BY r.id
        ORDER BY touchdowns DESC, yardas_pase DESC
    """, (temporada_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@stats_router.get("/partido/{pid}")
def stats_partido(pid: int):
    """Estadísticas detalladas de un partido específico."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT ep.*, e.nombre as equipo, r.categoria, r.division
        FROM estadisticas_partido ep
        JOIN registros r ON r.id=ep.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        WHERE ep.partido_id=?
    """, (pid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


class EstadisticasJugadorIn(BaseModel):
    partido_id: int
    jugador_id: int
    registro_id: int
    touchdowns: int = 0
    puntos_extra: int = 0
    intercepciones_lanzadas: int = 0
    intercepciones_atrapadas: int = 0
    yardas_pase: int = 0
    yardas_tierra: int = 0


@stats_router.post("/jugador")
def registrar_stats_jugador(body: EstadisticasJugadorIn):
    """Registra o actualiza estadísticas individuales de un jugador en un partido."""
    conn = get_conn()
    conn.execute("""
        INSERT INTO estadisticas_jugador
            (partido_id, jugador_id, registro_id, touchdowns, puntos_extra,
             intercepciones_lanzadas, intercepciones_atrapadas, yardas_pase, yardas_tierra)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(partido_id, jugador_id) DO UPDATE SET
            touchdowns=excluded.touchdowns,
            puntos_extra=excluded.puntos_extra,
            intercepciones_lanzadas=excluded.intercepciones_lanzadas,
            intercepciones_atrapadas=excluded.intercepciones_atrapadas,
            yardas_pase=excluded.yardas_pase,
            yardas_tierra=excluded.yardas_tierra
    """, (body.partido_id, body.jugador_id, body.registro_id,
          body.touchdowns, body.puntos_extra, body.intercepciones_lanzadas,
          body.intercepciones_atrapadas, body.yardas_pase, body.yardas_tierra))
    conn.commit()
    conn.close()
    return {"ok": True}


@stats_router.get("/jugadores/{temporada_id}")
def ranking_jugadores(temporada_id: int, categoria: str | None = None):
    """Ranking individual de jugadores por temporada. Filtra por categoría opcional."""
    conn = get_conn()
    filtro = "AND r.categoria=?" if categoria else ""
    params = (temporada_id, categoria) if categoria else (temporada_id,)
    rows = conn.execute(f"""
        SELECT j.id, j.nombre, j.curp, e.nombre as equipo, r.categoria, r.division,
               COALESCE(SUM(ej.touchdowns), 0)               as touchdowns,
               COALESCE(SUM(ej.puntos_extra), 0)             as puntos_extra,
               COALESCE(SUM(ej.intercepciones_atrapadas), 0) as intercepciones,
               COALESCE(SUM(ej.yardas_pase), 0)              as yardas_pase,
               COALESCE(SUM(ej.yardas_tierra), 0)            as yardas_tierra,
               COUNT(DISTINCT ej.partido_id)                 as partidos_jugados
        FROM estadisticas_jugador ej
        JOIN jugadores j ON j.id = ej.jugador_id
        JOIN registros r ON r.id = ej.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        WHERE r.temporada_id=? {filtro}
        GROUP BY j.id, r.id
        ORDER BY touchdowns DESC, yardas_pase DESC, yardas_tierra DESC
        LIMIT 50
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@stats_router.get("/mvp/jornada/{jornada_id}")
def mvp_jornada(jornada_id: int):
    """MVP de la jornada: jugador con más TDs, desempate por yardas."""
    conn = get_conn()
    row = conn.execute("""
        SELECT j.nombre, j.curp, e.nombre as equipo,
               COALESCE(SUM(ej.touchdowns), 0)   as touchdowns,
               COALESCE(SUM(ej.yardas_pase), 0)  as yardas_pase,
               COALESCE(SUM(ej.yardas_tierra), 0) as yardas_tierra,
               COUNT(DISTINCT ej.partido_id)       as partidos
        FROM estadisticas_jugador ej
        JOIN jugadores j ON j.id = ej.jugador_id
        JOIN registros r ON r.id = ej.registro_id
        JOIN equipos e ON e.id = r.equipo_id
        JOIN partidos p ON p.id = ej.partido_id
        WHERE p.jornada_id = ?
        GROUP BY j.id
        ORDER BY touchdowns DESC, yardas_pase DESC, yardas_tierra DESC
        LIMIT 1
    """, (jornada_id,)).fetchone()
    conn.close()
    return dict(row) if row else {"mvp": None}


# ════════════════════════════════════════════════════════════════════════════
# NOTIFICACIONES OLLAMA (generación de mensajes para QBs)
# ════════════════════════════════════════════════════════════════════════════

notif_router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])

_OLLAMA_CHAT = "http://localhost:11434/api/chat"
_MODELO      = "llama3.2"


def _ollama_disponible() -> bool:
    from urllib.request import urlopen
    from urllib.error import URLError
    try:
        urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except (URLError, OSError):
        return False


@notif_router.get("/partido/{pid}")
def notificacion_partido(pid: int):
    """
    Genera mensajes de WhatsApp/Telegram para ambos equipos usando Ollama.
    Ideal para copiar y pegar al grupo del equipo.
    """
    import json
    from urllib.request import Request, urlopen
    from urllib.error import URLError

    conn = get_conn()
    p = conn.execute("""
        SELECT p.*,
               el.nombre as equipo_local, rv_eq.nombre as equipo_visitante,
               c.nombre as cancha, j.numero as jornada_num, j.fecha as fecha_jornada,
               r_local.categoria, r_local.division
        FROM partidos p
        JOIN registros r_local ON r_local.id=p.registro_local_id
        JOIN registros r_vis   ON r_vis.id=p.registro_visitante_id
        JOIN equipos el        ON el.id=r_local.equipo_id
        JOIN equipos rv_eq     ON rv_eq.id=r_vis.equipo_id
        LEFT JOIN canchas c    ON c.id=p.cancha_id
        JOIN jornadas j        ON j.id=p.jornada_id
        WHERE p.id=?
    """, (pid,)).fetchone()
    conn.close()

    if not p:
        raise HTTPException(404, "Partido no encontrado")

    if not _ollama_disponible():
        raise HTTPException(503, "Ollama no disponible — asegúrate de que está corriendo")

    franja_label = {"manana": "mañana (7am–12pm)", "mediodia": "mediodía (12pm–4pm)",
                    "tarde": "tarde (4pm–8pm)"}.get(p["franja"] or "", p["franja"] or "por definir")
    fecha = p["fecha_jornada"] or "por confirmar"
    cancha = p["cancha"] or "por asignar"

    prompt = f"""Eres el administrador de una liga de tochito bandera (flag football).
Genera DOS mensajes breves para WhatsApp, uno para cada equipo, notificándoles su próximo partido.

Información del partido:
- Jornada: {p['jornada_num']}
- Fecha: {fecha}
- Franja: {franja_label}
- Cancha: {cancha}
- Categoría: {p['categoria']} / {p['division']}
- Equipo Local: {p['equipo_local']}
- Equipo Visitante: {p['equipo_visitante']}

Formato de respuesta (exactamente así):
MENSAJE PARA {p['equipo_local'].upper()}:
[mensaje aquí — máx 3 líneas, incluye fecha, franja, rival, cancha, emoji motivacional]

MENSAJE PARA {p['equipo_visitante'].upper()}:
[mensaje aquí — máx 3 líneas, incluye fecha, franja, rival, cancha, emoji motivacional]

Escribe en español mexicano informal. Sin disclaimers."""

    payload = json.dumps({
        "model": _MODELO,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 300},
    }).encode()

    req = Request(_OLLAMA_CHAT, data=payload,
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        texto = data.get("message", {}).get("content", "").strip()
        return {
            "partido_id": pid,
            "equipo_local": p["equipo_local"],
            "equipo_visitante": p["equipo_visitante"],
            "jornada": p["jornada_num"],
            "mensajes": texto,
        }
    except (URLError, OSError) as e:
        raise HTTPException(503, f"Error al contactar Ollama: {e}")


# ════════════════════════════════════════════════════════════════════════════
# PORTAL JUGADOR — Vista pública por CURP: solicitudes + equipos
# ════════════════════════════════════════════════════════════════════════════

jugador_portal_router = APIRouter(prefix="/api/portal-jugador", tags=["portal-jugador"])


@jugador_portal_router.get("/{curp}")
def portal_jugador(curp: str):
    """Jugador entra con su CURP y ve sus solicitudes + equipos activos."""
    curp = curp.upper().strip()
    conn = get_conn()
    jug = conn.execute("SELECT * FROM jugadores WHERE curp=? AND activo=1", (curp,)).fetchone()
    if not jug:
        conn.close()
        raise HTTPException(404, "No existe ningún jugador registrado con ese CURP")
    jid = jug["id"]

    solicitudes = conn.execute("""
        SELECT sv.id, sv.estado, sv.created_at, sv.registro_id,
               e.nombre as equipo, r.categoria, r.division,
               t.nombre as temporada, t.anio
        FROM solicitudes_vinculacion sv
        JOIN registros r ON r.id=sv.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        JOIN temporadas t ON t.id=r.temporada_id
        WHERE sv.jugador_id=?
        ORDER BY sv.estado='pendiente' DESC, sv.created_at DESC
    """, (jid,)).fetchall()

    equipos = conn.execute("""
        SELECT i.id as inscripcion_id, i.registro_id, i.numero, i.posicion,
               e.nombre as equipo, r.categoria, r.division,
               t.nombre as temporada, t.anio, t.estado as temporada_estado
        FROM inscripciones i
        JOIN registros r ON r.id=i.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        JOIN temporadas t ON t.id=r.temporada_id
        WHERE i.jugador_id=? AND i.activo=1
        ORDER BY t.anio DESC
    """, (jid,)).fetchall()
    conn.close()

    return {
        "jugador": _row(jug),
        "solicitudes": [dict(r) for r in solicitudes],
        "equipos_activos": [dict(r) for r in equipos],
    }


class RespuestaSolicitudIn(BaseModel):
    accion: str  # 'aceptar' | 'rechazar'


@jugador_portal_router.patch("/solicitudes/{sid}")
def responder_solicitud(sid: int, curp: str, body: RespuestaSolicitudIn):
    """Jugador acepta o rechaza una solicitud de vinculación (autenticado por CURP)."""
    if body.accion not in ("aceptar", "rechazar"):
        raise HTTPException(422, "accion debe ser 'aceptar' o 'rechazar'")
    curp = curp.upper().strip()
    conn = get_conn()

    sol = conn.execute("""
        SELECT sv.*, j.curp as jugador_curp
        FROM solicitudes_vinculacion sv
        JOIN jugadores j ON j.id=sv.jugador_id
        WHERE sv.id=?
    """, (sid,)).fetchone()
    _or_404(sol, "Solicitud no encontrada")

    if sol["jugador_curp"] != curp:
        conn.close()
        raise HTTPException(403, "CURP no corresponde a esta solicitud")
    if sol["estado"] != "pendiente":
        conn.close()
        raise HTTPException(409, f"La solicitud ya fue {sol['estado']}")

    nuevo_estado = "aceptada" if body.accion == "aceptar" else "rechazada"
    conn.execute(
        "UPDATE solicitudes_vinculacion SET estado=?, updated_at=datetime('now') WHERE id=?",
        (nuevo_estado, sid),
    )

    if nuevo_estado == "aceptada":
        # Crear inscripción real
        try:
            conn.execute(
                "INSERT INTO inscripciones (jugador_id, registro_id) VALUES (?,?)",
                (sol["jugador_id"], sol["registro_id"]),
            )
        except Exception:
            pass  # Si ya existe (UNIQUE), ignorar

    conn.commit()
    conn.close()
    return {"id": sid, "estado": nuevo_estado}


@jugador_portal_router.delete("/desvincular/{inscripcion_id}")
def desvincular_jugador(inscripcion_id: int, curp: str):
    """Jugador se elimina de un equipo (autenticado por CURP)."""
    curp = curp.upper().strip()
    conn = get_conn()
    insc = conn.execute("""
        SELECT i.*, j.curp as jugador_curp
        FROM inscripciones i
        JOIN jugadores j ON j.id=i.jugador_id
        WHERE i.id=?
    """, (inscripcion_id,)).fetchone()
    _or_404(insc, "Inscripción no encontrada")

    if insc["jugador_curp"] != curp:
        conn.close()
        raise HTTPException(403, "CURP no corresponde a esta inscripción")

    conn.execute("UPDATE inscripciones SET activo=0 WHERE id=?", (inscripcion_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ════════════════════════════════════════════════════════════════════════════
# APP — registrar routers
# ════════════════════════════════════════════════════════════════════════════

for router in [temporadas_router, canchas_router, equipos_router,
               registros_router, jugadores_router, partidos_router,
               tabla_router, calendario_router, stats_router, notif_router,
               jugador_portal_router]:
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
