"""Validaciones de reglas de negocio de la liga.

Reglas de jugadores multifranquicia:
  1. Máx 20 jugadores activos por registro (equipo en categoría/división/temporada).
  2. Un jugador puede estar en máx 3 equipos DISTINTOS por temporada.
     - El mismo equipo en varonil + mixto/femenino cuenta como 1 equipo (no 2).
  3. Categoría: el jugador solo puede jugar en la misma categoría o hasta 3 por debajo
     de la más alta en que esté inscrito en esa temporada.
     - Ejemplo: si juega en A, puede jugar en A, B, C, D. No en E ni F.
  4. En partidos: un jugador no puede aparecer en dos partidos de la misma franja
     en la misma jornada (solapamiento).
"""
from sqlite3 import Connection
from typing import Optional


def _cat_idx(cat: str) -> int:
    return ["A", "B", "C", "D", "E", "F"].index(cat)


def validar_max_jugadores(conn: Connection, registro_id: int) -> Optional[str]:
    """Regla 1 — máx 20 jugadores activos por registro."""
    row = conn.execute(
        "SELECT COUNT(*) as n FROM inscripciones WHERE registro_id=? AND activo=1",
        (registro_id,),
    ).fetchone()
    if row["n"] >= 20:
        return "El registro ya tiene 20 jugadores (máximo permitido)"
    return None


def validar_max_equipos_temporada(conn: Connection, jugador_id: int, registro_id: int) -> Optional[str]:
    """Regla 2 — máx 3 equipos distintos por temporada (mismo equipo ≠ 2 equipos)."""
    # Obtener temporada del registro a inscribir
    reg = conn.execute(
        "SELECT r.temporada_id, r.equipo_id FROM registros r WHERE r.id=?",
        (registro_id,),
    ).fetchone()
    if not reg:
        return "Registro no encontrado"

    temporada_id = reg["temporada_id"]
    equipo_id_nuevo = reg["equipo_id"]

    # Equipos distintos en los que ya está inscrito en esta temporada
    equipos_actuales = conn.execute(
        """SELECT DISTINCT r.equipo_id
           FROM inscripciones i
           JOIN registros r ON r.id = i.registro_id
           WHERE i.jugador_id=? AND r.temporada_id=? AND i.activo=1
             AND r.id != ?""",
        (jugador_id, temporada_id, registro_id),
    ).fetchall()

    equipos_ids = {row["equipo_id"] for row in equipos_actuales}
    if equipo_id_nuevo in equipos_ids:
        return None  # Ya está en ese equipo — mismo equipo, diferente división, OK

    if len(equipos_ids) >= 3:
        return (
            f"El jugador ya está en 3 equipos distintos esta temporada "
            f"(máximo permitido). Solo puede cambiar si es el mismo equipo en otra división."
        )
    return None


def validar_categoria_jugador(conn: Connection, jugador_id: int, registro_id: int) -> Optional[str]:
    """Regla 3 — el jugador solo puede estar hasta 3 categorías por debajo de su máxima."""
    reg = conn.execute(
        "SELECT r.temporada_id, r.categoria FROM registros r WHERE r.id=?",
        (registro_id,),
    ).fetchone()
    if not reg:
        return "Registro no encontrado"

    temporada_id = reg["temporada_id"]
    categoria_nueva = reg["categoria"]

    # Categoría más alta (menor índice) en la que juega en esta temporada
    cats = conn.execute(
        """SELECT r.categoria
           FROM inscripciones i
           JOIN registros r ON r.id = i.registro_id
           WHERE i.jugador_id=? AND r.temporada_id=? AND i.activo=1
             AND r.id != ?""",
        (jugador_id, temporada_id, registro_id),
    ).fetchall()

    if not cats:
        return None  # Primera inscripción en la temporada, sin restricción

    idx_max_actual = min(_cat_idx(r["categoria"]) for r in cats)  # menor = más alta
    idx_nueva = _cat_idx(categoria_nueva)

    if idx_nueva < idx_max_actual:
        cats_actuales = [r["categoria"] for r in cats]
        nueva_max = categoria_nueva
        # Recalcular si la nueva categoría sube el nivel máximo
        idx_max_actual = idx_nueva  # Ahora la nueva es la más alta
        # Verificar que las categorías existentes no estén más de 3 abajo de la nueva
        for c in cats_actuales:
            if _cat_idx(c) - idx_nueva > 3:
                cat_maxima = ["A", "B", "C", "D", "E", "F"][idx_nueva]
                return (
                    f"Si el jugador sube a categoría {categoria_nueva}, "
                    f"la categoría {c} quedaría más de 3 niveles abajo. "
                    f"Jugando en {categoria_nueva}, solo puede estar hasta categoría "
                    f"{['A','B','C','D','E','F'][min(idx_nueva + 3, 5)]}."
                )
        return None

    # La categoría nueva es igual o menor (más baja) que la actual máxima
    if idx_nueva - idx_max_actual > 3:
        cat_maxima = ["A", "B", "C", "D", "E", "F"][idx_max_actual]
        cat_min_permitida = ["A", "B", "C", "D", "E", "F"][min(idx_max_actual + 3, 5)]
        return (
            f"El jugador juega en categoría {cat_maxima} (su máxima actual). "
            f"Solo puede jugar hasta categoría {cat_min_permitida}. "
            f"La categoría {categoria_nueva} está más de 3 niveles abajo."
        )
    return None


def validar_solapamiento_jornada(conn: Connection, jugador_id: int,
                                  jornada_id: int, franja: str,
                                  partido_id: Optional[int] = None) -> Optional[str]:
    """Regla 4 — jugador no puede tener dos partidos en la misma jornada+franja."""
    excluir = f"AND p.id != {partido_id}" if partido_id else ""

    conflictos = conn.execute(
        f"""SELECT p.id, e.nombre as equipo
            FROM partidos p
            JOIN registros rl ON rl.id = p.registro_local_id
            JOIN registros rv ON rv.id = p.registro_visitante_id
            JOIN equipos e ON e.id IN (rl.equipo_id, rv.equipo_id)
            JOIN inscripciones i ON i.registro_id IN (p.registro_local_id, p.registro_visitante_id)
            WHERE i.jugador_id=? AND p.jornada_id=? AND p.franja=?
              AND p.estado NOT IN ('suspendido') {excluir}""",
        (jugador_id, jornada_id, franja),
    ).fetchall()

    if conflictos:
        equipos = list({r["equipo"] for r in conflictos})
        return (
            f"El jugador ya tiene partido en la franja '{franja}' de esta jornada "
            f"(equipo: {', '.join(equipos)}). No se pueden asignar dos partidos simultáneos."
        )
    return None


def validar_inscripcion(conn: Connection, jugador_id: int, registro_id: int) -> list[str]:
    """Ejecuta todas las validaciones de inscripción. Retorna lista de errores."""
    errores = []
    for fn in [validar_max_jugadores, validar_max_equipos_temporada, validar_categoria_jugador]:
        err = fn(conn, jugador_id, registro_id)
        if err:
            errores.append(err)
    return errores
