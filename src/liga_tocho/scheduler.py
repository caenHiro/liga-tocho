"""Generador de calendario (fixture) para la liga.

Algoritmo:
  1. Obtiene todos los registros activos de la temporada.
  2. Para cada categoría+división genera un round-robin.
  3. Distribuye los partidos en jornadas (11) respetando:
     a. Restricciones de franja horaria por registro (mañana/mediodía/tarde).
     b. Disponibilidad de canchas.
     c. Sin solapamiento de franja para jugadores multifranquicia (best-effort).
  4. Genera las jornadas en BD y asigna los partidos.

Uso:
    from scheduler import generar_calendario
    partidos, errores = generar_calendario(conn, temporada_id, canchas_disponibles)
"""
import itertools
import random
from collections import defaultdict
from sqlite3 import Connection
from typing import Optional


FRANJAS_ORDEN = ["manana", "mediodia", "tarde"]
MAX_JORNADAS  = 11


def _round_robin(equipos: list) -> list[list[tuple]]:
    """Genera jornadas de round-robin. Si hay número impar, agrega 'bye'."""
    if len(equipos) % 2 != 0:
        equipos = equipos + [None]  # None = descansa
    n = len(equipos)
    jornadas = []
    fijo = equipos[0]
    resto = equipos[1:]
    for _ in range(n - 1):
        jornada = [(fijo, resto[0])]
        for i in range(1, n // 2):
            jornada.append((resto[i], resto[n - 1 - i]))
        jornadas.append([(a, b) for a, b in jornada if a is not None and b is not None])
        resto = [resto[-1]] + resto[:-1]  # rotar
    return jornadas


def _franja_compatible(preferencia: str, franja: str) -> bool:
    if preferencia == "sin_restriccion":
        return True
    return preferencia == franja


def generar_calendario(
    conn: Connection,
    temporada_id: int,
    n_canchas_manana: int = 1,
    n_canchas_mediodia: int = 1,
    n_canchas_tarde: int = 1,
) -> dict:
    """
    Genera el fixture para toda una temporada.

    Retorna:
        {"partidos_generados": int, "advertencias": list[str], "por_categoria": dict}
    """
    advertencias = []
    partidos_generados = 0

    # Obtener jornadas ya creadas (o crearlas si no existen)
    jornadas_rows = conn.execute(
        "SELECT * FROM jornadas WHERE temporada_id=? ORDER BY numero",
        (temporada_id,),
    ).fetchall()

    jornada_ids = [r["id"] for r in jornadas_rows]
    if not jornada_ids:
        advertencias.append("No hay jornadas creadas. Crea las 11 jornadas primero desde el panel de temporadas.")
        return {"partidos_generados": 0, "advertencias": advertencias, "por_categoria": {}}

    # Obtener canchas activas
    canchas = conn.execute("SELECT id FROM canchas WHERE activa=1").fetchall()
    if not canchas:
        advertencias.append("No hay canchas activas. Agrega canchas primero.")
        return {"partidos_generados": 0, "advertencias": advertencias, "por_categoria": {}}

    cancha_ids = [r["id"] for r in canchas]

    # Capacidad por franja por jornada
    capacidad_franja = {
        "manana":   min(n_canchas_manana, len(cancha_ids)),
        "mediodia": min(n_canchas_mediodia, len(cancha_ids)),
        "tarde":    min(n_canchas_tarde, len(cancha_ids)),
    }

    # Restricciones por jornada (QB solicita franja para jornada específica)
    # Estructura: {registro_id: {jornada_id: preferencia}}
    rj_rows = conn.execute(
        """SELECT rj.registro_id, rj.jornada_id, rj.preferencia
           FROM restricciones_jornada rj
           JOIN registros r ON r.id=rj.registro_id
           WHERE r.temporada_id=?""",
        (temporada_id,),
    ).fetchall()
    restr_jornada: dict[int, dict[int, str]] = defaultdict(dict)
    for rj in rj_rows:
        restr_jornada[rj["registro_id"]][rj["jornada_id"]] = rj["preferencia"]

    # Agrupar registros por categoría+división
    grupos = conn.execute(
        """SELECT r.id, r.equipo_id, r.categoria, r.division,
                  rh.preferencia
           FROM registros r
           LEFT JOIN restricciones_horario rh ON rh.registro_id = r.id
           WHERE r.temporada_id=? AND r.activo=1
           ORDER BY r.categoria, r.division""",
        (temporada_id,),
    ).fetchall()

    por_cat_div: dict[tuple, list] = defaultdict(list)
    for g in grupos:
        por_cat_div[(g["categoria"], g["division"])].append(dict(g))

    resultado_categorias = {}
    # Partidos pendientes de asignar: lista de (reg_local_id, reg_vis_id, categoria, division, pref_local, pref_vis)
    partidos_pendientes = []

    for (cat, div), regs in por_cat_div.items():
        if len(regs) < 2:
            advertencias.append(f"Categoría {cat}/{div}: solo {len(regs)} equipo — se necesitan al menos 2 para generar partidos.")
            continue

        reg_ids = [r["id"] for r in regs]
        prefs = {r["id"]: r.get("preferencia") or "sin_restriccion" for r in regs}

        jornadas_rr = _round_robin(reg_ids)
        total_partidos = sum(len(j) for j in jornadas_rr)
        resultado_categorias[f"{cat}/{div}"] = {"registros": len(regs), "partidos": total_partidos}

        for jornada_idx, enfrentamientos in enumerate(jornadas_rr):
            if jornada_idx >= len(jornada_ids):
                advertencias.append(f"Cat {cat}/{div}: hay más rondas ({len(jornadas_rr)}) que jornadas ({len(jornada_ids)}). Partidos extra no asignados.")
                break
            jid = jornada_ids[jornada_idx]
            for (local_id, vis_id) in enfrentamientos:
                # Preferencia por jornada tiene prioridad sobre permanente
                pref_l = restr_jornada[local_id].get(jid) or prefs[local_id]
                pref_v = restr_jornada[vis_id].get(jid) or prefs[vis_id]
                partidos_pendientes.append({
                    "jornada_id": jid,
                    "local": local_id,
                    "vis": vis_id,
                    "pref_local": pref_l,
                    "pref_vis": pref_v,
                    "cat": cat, "div": div,
                })

    # Asignar franja y cancha a cada partido
    # Contador de slots usados: {(jornada_id, franja): partidos_asignados}
    slots_usados: dict[tuple, int] = defaultdict(int)

    for p in partidos_pendientes:
        jornada_id = p["jornada_id"]
        pref_l = p["pref_local"]
        pref_v = p["pref_vis"]

        # Elegir franja: primero intentar compatibilidad de ambas preferencias
        franja_asignada = None
        candidatas = []
        for franja in FRANJAS_ORDEN:
            compat_l = _franja_compatible(pref_l, franja)
            compat_v = _franja_compatible(pref_v, franja)
            hay_slot = slots_usados[(jornada_id, franja)] < capacidad_franja[franja]
            if compat_l and compat_v and hay_slot:
                franja_asignada = franja
                break
            elif hay_slot:
                candidatas.append((franja, compat_l + compat_v))  # puntuación compatibilidad

        if not franja_asignada and candidatas:
            # Elegir la franja con más compatibilidad que tenga slot
            candidatas.sort(key=lambda x: -x[1])
            franja_asignada = candidatas[0][0]
            advertencias.append(
                f"Jornada {jornada_id} Cat {p['cat']}/{p['div']}: "
                f"no se pudo respetar la franja preferida de algún equipo."
            )

        if not franja_asignada:
            advertencias.append(
                f"Jornada {jornada_id} Cat {p['cat']}/{p['div']}: "
                f"sin slots disponibles — partido no asignado."
            )
            continue

        # Asignar cancha (rotación simple)
        slot_idx = slots_usados[(jornada_id, franja_asignada)]
        cancha_id = cancha_ids[slot_idx % len(cancha_ids)]
        slots_usados[(jornada_id, franja_asignada)] += 1

        # Insertar partido
        conn.execute(
            """INSERT INTO partidos
               (jornada_id, cancha_id, franja, registro_local_id, registro_visitante_id)
               VALUES (?,?,?,?,?)""",
            (jornada_id, cancha_id, franja_asignada, p["local"], p["vis"]),
        )
        partidos_generados += 1

    conn.commit()

    return {
        "partidos_generados": partidos_generados,
        "advertencias": advertencias,
        "por_categoria": resultado_categorias,
    }
