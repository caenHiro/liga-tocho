"""Auth simple + endpoints QB (quarterback) + endpoints Admin para Liga Tochito.

Auth: token simple en memoria (sin JWT — app local de liga, no necesita más).
Roles:
  admin   — ve todo, registra equipos, gestiona temporadas
  qb      — ve su equipo, solicita preferencia de horario por jornada
  publico — solo lectura (tabla posiciones, partidos)
"""
import hashlib
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from .bd import get_conn

# ── Token store en memoria (dura mientras el proceso vive) ───────────────────
_tokens: dict[str, dict] = {}  # token → {user_id, username, rol, registro_id}


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _require_auth(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token requerido")
    token = authorization.split(" ", 1)[1]
    user = _tokens.get(token)
    if not user:
        raise HTTPException(401, "Token inválido o expirado")
    return user


def _require_admin(user: dict = Depends(_require_auth)) -> dict:
    if user["rol"] != "admin":
        raise HTTPException(403, "Solo administradores")
    return user


def _require_qb(user: dict = Depends(_require_auth)) -> dict:
    if user["rol"] not in ("admin", "qb"):
        raise HTTPException(403, "Solo QB o admin")
    return user


# ════════════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════════════

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class RegistroUsuarioIn(BaseModel):
    username: str
    password: str
    rol: str = "qb"
    registro_id: Optional[int] = None


@auth_router.post("/login")
def login(body: LoginIn):
    conn = get_conn()
    user = conn.execute(
        "SELECT * FROM usuarios WHERE username=? AND activo=1",
        (body.username,),
    ).fetchone()
    conn.close()
    if not user or user["password_hash"] != _hash_pw(body.password):
        raise HTTPException(401, "Credenciales incorrectas")
    token = secrets.token_hex(24)
    _tokens[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "rol": user["rol"],
        "registro_id": user["registro_id"],
    }
    return {
        "token": token,
        "username": user["username"],
        "rol": user["rol"],
        "registro_id": user["registro_id"],
    }


@auth_router.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        _tokens.pop(token, None)
    return {"ok": True}


@auth_router.get("/me")
def me(user: dict = Depends(_require_auth)):
    return user


@auth_router.post("/usuarios", status_code=201)
def crear_usuario(body: RegistroUsuarioIn, _admin: dict = Depends(_require_admin)):
    if body.rol not in ("admin", "qb", "publico"):
        raise HTTPException(400, "Rol inválido")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO usuarios (username, password_hash, rol, registro_id) VALUES (?,?,?,?)",
            (body.username, _hash_pw(body.password), body.rol, body.registro_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "username": body.username, "rol": body.rol}
    except Exception as e:
        conn.close()
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"El usuario '{body.username}' ya existe")
        raise HTTPException(400, str(e))


@auth_router.get("/usuarios")
def listar_usuarios(_admin: dict = Depends(_require_admin)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, rol, registro_id, activo, created_at FROM usuarios ORDER BY rol, username"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@auth_router.patch("/usuarios/{uid}/password")
def cambiar_password(uid: int, body: LoginIn, _admin: dict = Depends(_require_admin)):
    conn = get_conn()
    conn.execute(
        "UPDATE usuarios SET password_hash=? WHERE id=?",
        (_hash_pw(body.password), uid),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Setup inicial: crear admin por defecto si no existe ──────────────────────

def ensure_admin_default():
    """Crea usuario admin/admin123 si no hay ningún admin. Solo para primera vez."""
    conn = get_conn()
    existe = conn.execute("SELECT 1 FROM usuarios WHERE rol='admin'").fetchone()
    if not existe:
        conn.execute(
            "INSERT OR IGNORE INTO usuarios (username, password_hash, rol) VALUES (?,?,?)",
            ("admin", _hash_pw("admin123"), "admin"),
        )
        conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# QB — endpoints del quarterback (capitán de equipo)
# ════════════════════════════════════════════════════════════════════════════

qb_router = APIRouter(prefix="/api/qb", tags=["qb"])


class RestriccionJornadaIn(BaseModel):
    preferencia: str  # manana | mediodia | tarde | sin_restriccion


@qb_router.get("/mi-equipo")
def mi_equipo(user: dict = Depends(_require_qb)):
    registro_id = user.get("registro_id")
    if not registro_id and user["rol"] != "admin":
        raise HTTPException(400, "QB no tiene registro asignado")
    conn = get_conn()

    if user["rol"] == "admin":
        # Admin puede ver cualquier equipo con ?registro_id=X
        raise HTTPException(400, "Admin: usa /api/registros/{id} directamente")

    reg = conn.execute("""
        SELECT r.*, e.nombre as equipo_nombre, e.color,
               rh.preferencia as preferencia_permanente
        FROM registros r
        JOIN equipos e ON e.id=r.equipo_id
        LEFT JOIN restricciones_horario rh ON rh.registro_id=r.id
        WHERE r.id=?
    """, (registro_id,)).fetchone()
    if not reg:
        conn.close()
        raise HTTPException(404, "Registro no encontrado")

    jugadores = conn.execute("""
        SELECT i.id, i.numero, i.posicion, i.activo,
               j.id as jugador_id, j.nombre, j.posicion_principal, j.numero_camiseta, j.telefono
        FROM inscripciones i
        JOIN jugadores j ON j.id=i.jugador_id
        WHERE i.registro_id=? AND i.activo=1
        ORDER BY j.nombre
    """, (registro_id,)).fetchall()

    conn.close()
    return {
        "registro": dict(reg),
        "jugadores": [dict(j) for j in jugadores],
    }


@qb_router.get("/jornadas/{temporada_id}")
def mis_jornadas(temporada_id: int, user: dict = Depends(_require_qb)):
    registro_id = user.get("registro_id")
    conn = get_conn()
    jornadas = conn.execute(
        "SELECT * FROM jornadas WHERE temporada_id=? ORDER BY numero",
        (temporada_id,),
    ).fetchall()
    # Adjuntar restricciones propias si QB
    restricciones: dict[int, str] = {}
    if registro_id:
        rows = conn.execute(
            "SELECT jornada_id, preferencia FROM restricciones_jornada WHERE registro_id=?",
            (registro_id,),
        ).fetchall()
        restricciones = {r["jornada_id"]: r["preferencia"] for r in rows}
    conn.close()
    return [
        {**dict(j), "mi_restriccion": restricciones.get(j["id"], "sin_restriccion")}
        for j in jornadas
    ]


@qb_router.post("/jornadas/{jornada_id}/restriccion")
def solicitar_restriccion(jornada_id: int, body: RestriccionJornadaIn,
                          user: dict = Depends(_require_qb)):
    if body.preferencia not in ("manana", "mediodia", "tarde", "sin_restriccion"):
        raise HTTPException(400, "Preferencia inválida")
    registro_id = user.get("registro_id")
    if not registro_id and user["rol"] != "admin":
        raise HTTPException(400, "QB no tiene registro asignado")
    if not registro_id:
        raise HTTPException(400, "Especifica registro_id en el header o usa /api/registros/{rid}/horario-jornada")

    conn = get_conn()
    jornada = conn.execute("SELECT id FROM jornadas WHERE id=?", (jornada_id,)).fetchone()
    if not jornada:
        conn.close()
        raise HTTPException(404, "Jornada no encontrada")

    conn.execute(
        "INSERT OR REPLACE INTO restricciones_jornada (registro_id, jornada_id, preferencia) VALUES (?,?,?)",
        (registro_id, jornada_id, body.preferencia),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "jornada_id": jornada_id, "preferencia": body.preferencia}


# ── Endpoint público: restricciones de una jornada (para el scheduler) ───────

@qb_router.get("/jornadas/{jornada_id}/todas-restricciones")
def restricciones_jornada(jornada_id: int, _admin: dict = Depends(_require_admin)):
    conn = get_conn()
    rows = conn.execute("""
        SELECT rj.registro_id, rj.preferencia,
               e.nombre as equipo, r.categoria, r.division
        FROM restricciones_jornada rj
        JOIN registros r ON r.id=rj.registro_id
        JOIN equipos e ON e.id=r.equipo_id
        WHERE rj.jornada_id=?
    """, (jornada_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Admin: crear QB para un registro ─────────────────────────────────────────

@qb_router.post("/asignar/{registro_id}")
def asignar_qb(registro_id: int, body: RegistroUsuarioIn, _admin: dict = Depends(_require_admin)):
    """Crea usuario QB asociado a un registro (equipo en categoría/división/temporada)."""
    conn = get_conn()
    reg = conn.execute("SELECT id FROM registros WHERE id=?", (registro_id,)).fetchone()
    if not reg:
        conn.close()
        raise HTTPException(404, "Registro no encontrado")
    try:
        conn.execute(
            "INSERT INTO usuarios (username, password_hash, rol, registro_id) VALUES (?,?,?,?)",
            (body.username, _hash_pw(body.password), "qb", registro_id),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "username": body.username, "registro_id": registro_id}
    except Exception as e:
        conn.close()
        if "UNIQUE" in str(e):
            raise HTTPException(409, f"El usuario '{body.username}' ya existe")
        raise HTTPException(400, str(e))
