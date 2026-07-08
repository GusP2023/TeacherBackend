"""
WebSocket endpoint para sincronización en tiempo real

Permite notificar a los clientes conectados cuando hay cambios en los datos.
Cada profesor tiene su propia "sala" para recibir solo sus actualizaciones.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status
from typing import Dict, Set
import json
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("uvicorn.error")

from app.core.security import get_current_teacher_ws, decode_token
from app.core.database import async_session_maker
from app.crud import teacher as teacher_crud
from app.models.teacher import Teacher

router = APIRouter()

# Gestión de conexiones WebSocket
# Estructura: {teacher_id: Set[WebSocket]}
active_connections: Dict[int, Set[WebSocket]] = {}


class ConnectionManager:
    """
    Gestor de conexiones WebSocket por profesor

    Permite:
    - Conectar/desconectar clientes
    - Enviar mensajes a un profesor específico
    - Broadcast a todos los clientes de un profesor
    """

    async def connect(self, websocket: WebSocket, teacher_id: int, teacher_email: str = "", teacher_name: str = ""):
        await websocket.accept()

        # Cerrar conexiones anteriores del mismo profesor (reconexión)
        # IMPORTANTE: resetear el set ANTES de los awaits para evitar KeyError
        # por race condition entre conexiones simultáneas del mismo profesor
        old_connections = list(active_connections.get(teacher_id, set()))
        active_connections[teacher_id] = set()  # reset atómico antes de cualquier await
        for old_ws in old_connections:
            try:
                await old_ws.close(code=1000)
            except Exception:
                pass

        active_connections.setdefault(teacher_id, set()).add(websocket)
        logger.info(f"[WebSocket] CONECTADO — Profesor: {teacher_name} ({teacher_email}) | ID: {teacher_id}")

    def disconnect(self, websocket: WebSocket, teacher_id: int):
        """Desconectar un cliente WebSocket"""
        if teacher_id in active_connections:
            active_connections[teacher_id].discard(websocket)
            # NO eliminar la key aunque el set quede vacío
            # Evita race condition donde connect() resetea el set,
            # disconnect() lo borra, y connect() falla al hacer .add()

        logger.info(f"[WebSocket] DESCONECTADO — Profesor ID: {teacher_id}")

    async def send_to_teacher_local(self, teacher_id: int, message: dict):
        """
        Enviar mensaje a todas las conexiones locales de este worker para un profesor
        """
        if teacher_id not in active_connections:
            return

        # Convertir a JSON
        message_json = json.dumps(message)

        # Enviar a todas las conexiones activas
        disconnected = []
        for connection in active_connections[teacher_id]:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"[WebSocket] Error enviando a profesor {teacher_id}: {e}")
                disconnected.append(connection)

        # Limpiar conexiones muertas
        for conn in disconnected:
            self.disconnect(conn, teacher_id)


manager = ConnectionManager()


# ==============================================================================
# MULTI-WORKER SYNC CON POSTGRESQL LISTEN/NOTIFY
# ==============================================================================
from app.core.database import engine

async def pg_notify_listener():
    """
    Escucha notificaciones de PostgreSQL en segundo plano y las reenvía a
    las conexiones locales de este worker.
    
    NOTA CRÍTICA: Como el backend usa el pooler de Neon (PgBouncer en modo transacción),
    LISTEN no funciona a través del pooler. Para solucionarlo, creamos una conexión
    directa a la base de datos (removiendo '-pooler' de la URL) solo para el listener.
    """
    logger.info("[WebSocket] PG Listener: Iniciando tarea de sincronización multi-worker...")
    await asyncio.sleep(5)  # Esperar a que la app inicie
    
    from app.core.config import settings
    from sqlalchemy.ext.asyncio import create_async_engine
    
    # Construir URL de conexión directa sin pooler
    direct_url = settings.DATABASE_URL
    if "-pooler" in direct_url:
        direct_url = direct_url.replace("-pooler", "", 1)
        logger.info("[WebSocket] PG Listener: Usando conexión directa bypass-pooler para LISTEN...")
    
    # Crear engine dedicado de solo 1 conexión persistente para el listener
    listener_engine = create_async_engine(
        direct_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0
    )
    
    while True:
        try:
            async with listener_engine.connect() as conn:
                raw_conn = await conn.get_raw_connection()
                # El objeto de conexión real de asyncpg
                pg_conn = getattr(raw_conn, "driver_connection", None)
                if not pg_conn:
                    raise RuntimeError("No se pudo obtener la conexión de asyncpg")
                
                def notification_callback(connection, pid, channel, payload):
                    try:
                        data = json.loads(payload)
                        teacher_id = data.get("teacher_id")
                        msg = data.get("message")
                        if teacher_id and msg:
                            # Ejecutar envío asíncronamente
                            asyncio.create_task(manager.send_to_teacher_local(teacher_id, msg))
                    except Exception as ex:
                        logger.error(f"[WebSocket] PG Listener: Error decodificando payload: {ex}")
                
                # Para evitar el error de pyright, ignoramos el tipo dinámico de add_listener
                await pg_conn.add_listener("ws_notifications", notification_callback) # type: ignore
                logger.info("[WebSocket] PG Listener: Escuchando canal 'ws_notifications' de PostgreSQL (Conexión Directa)...")
                
                # Mantener la conexión abierta
                while True:
                    await asyncio.sleep(3600)
                    
        except Exception as e:
            logger.error(f"[WebSocket] PG Listener: Error de conexión (reintentando en 5s): {e}")
            await asyncio.sleep(5)

def start_websocket_listener():
    """
    Arranca el listener en segundo plano cuando el event loop ya está activo.
    """
    asyncio.create_task(pg_notify_listener())

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str,
):
    """
    Endpoint WebSocket para sincronización en tiempo real

    El cliente debe enviar el JWT token como query parameter:
    ws://localhost:8000/api/v1/ws?token=<jwt_token>

    Mensajes que envía el servidor:
    - {"type": "connected", "teacher_id": 1}
    - {"type": "data_changed", "entity": "student", "operation": "create", "id": 123}
    - {"type": "ping"}

    Mensajes que recibe del cliente:
    - {"type": "pong"}
    """
    # Autenticar usando el token
    try:
        # Decodificar token
        payload = decode_token(token)
        email: str | None = payload.get("sub")
        
        if not email:
            raise Exception("Token inválido - sin email")
        
        # Buscar teacher en BD
        async with async_session_maker() as session:
            teacher = await teacher_crud.get_by_email(session, email)
        
        if not teacher:
            raise Exception("Teacher no encontrado")
            
    except Exception as e:
        logger.warning(f"[WebSocket] Error de autenticación: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Conectar
    await manager.connect(websocket, teacher.id, teacher_email=teacher.email, teacher_name=teacher.name)

    # Enviar confirmación de conexión
    await websocket.send_text(json.dumps({
        "type": "connected",
        "teacher_id": teacher.id,
        "timestamp": datetime.utcnow().isoformat()
    }))

    try:
        # Mantener conexión activa con ping/pong
        while True:
            # Esperar mensajes del cliente
            data = await websocket.receive_text()
            message = json.loads(data)

            # Responder a pings
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            # Por ahora, solo escuchamos pings
            # En el futuro podríamos recibir otros mensajes

    except WebSocketDisconnect:
        manager.disconnect(websocket, teacher.id)
    except Exception as e:
        logger.error(f"[WebSocket] Error en conexión — Profesor ID {teacher.id}: {e}")
        manager.disconnect(websocket, teacher.id)


async def notify_data_change(
    teacher_id: int,
    entity: str,
    operation: str,
    entity_id: int | None = None,
):
    """
    Notificar a un profesor que sus datos cambiaron (vía PostgreSQL LISTEN/NOTIFY para multi-worker)
    """
    message = {
        "type": "data_changed",
        "entity": entity,
        "operation": operation,
        "entity_id": entity_id,
        "timestamp": datetime.utcnow().isoformat()
    }

    payload = json.dumps({
        "teacher_id": teacher_id,
        "message": message
    })

    try:
        from sqlalchemy import text
        async with async_session_maker() as session:
            # pg_notify es asíncrono y ultra liviano
            await session.execute(
                text("SELECT pg_notify('ws_notifications', :payload)"),
                {"payload": payload}
            )
            await session.commit()
        logger.info(f"[WebSocket] Notificación publicada en PG (Profesor {teacher_id}): {entity} {operation} id={entity_id}")
    except Exception as e:
        logger.error(f"[WebSocket] Error publicando notificación en PG (fallando a local): {e}")
        # Fallback local
        await manager.send_to_teacher_local(teacher_id, message)
