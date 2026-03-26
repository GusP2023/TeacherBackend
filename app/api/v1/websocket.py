"""
WebSocket endpoint para sincronización en tiempo real

Permite notificar a los clientes conectados cuando hay cambios en los datos.
Cada profesor tiene su propia "sala" para recibir solo sus actualizaciones.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status
from typing import Dict, Set
import json
import asyncio
from datetime import datetime

from app.core.security import get_current_teacher_ws
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

    async def connect(self, websocket: WebSocket, teacher_id: int):
        """Conectar un cliente WebSocket"""
        await websocket.accept()

        if teacher_id not in active_connections:
            active_connections[teacher_id] = set()

        active_connections[teacher_id].add(websocket)
        print(f"[WebSocket] Profesor {teacher_id} conectado. Total: {len(active_connections[teacher_id])}")

    def disconnect(self, websocket: WebSocket, teacher_id: int):
        """Desconectar un cliente WebSocket"""
        if teacher_id in active_connections:
            active_connections[teacher_id].discard(websocket)

            # Limpiar si no hay más conexiones
            if len(active_connections[teacher_id]) == 0:
                del active_connections[teacher_id]

            print(f"[WebSocket] Profesor {teacher_id} desconectado")

    async def send_to_teacher(self, teacher_id: int, message: dict):
        """
        Enviar mensaje a todas las conexiones de un profesor

        Args:
            teacher_id: ID del profesor
            message: Diccionario con el mensaje a enviar
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
                print(f"[WebSocket] Error enviando a profesor {teacher_id}: {e}")
                disconnected.append(connection)

        # Limpiar conexiones muertas
        for conn in disconnected:
            self.disconnect(conn, teacher_id)


manager = ConnectionManager()


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
        teacher = await get_current_teacher_ws(token)
    except Exception as e:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Conectar
    await manager.connect(websocket, teacher.id)

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
        print(f"[WebSocket] Error en conexión: {e}")
        manager.disconnect(websocket, teacher.id)


async def notify_data_change(
    teacher_id: int,
    entity: str,
    operation: str,
    entity_id: int | None = None,
):
    """
    Notificar a un profesor que sus datos cambiaron

    Args:
        teacher_id: ID del profesor a notificar
        entity: Tipo de entidad (student, enrollment, schedule, etc)
        operation: Operación realizada (create, update, delete)
        entity_id: ID de la entidad afectada (opcional)

    Ejemplo:
        await notify_data_change(1, "student", "create", 123)
    """
    message = {
        "type": "data_changed",
        "entity": entity,
        "operation": operation,
        "entity_id": entity_id,
        "timestamp": datetime.utcnow().isoformat()
    }

    await manager.send_to_teacher(teacher_id, message)
    print(f"[WebSocket] Notificado profesor {teacher_id}: {entity} {operation} {entity_id}")
