"""
Modelo SecurityLog — Registro de eventos de seguridad.

Guarda un log inmutable de acciones sensibles del sistema.
Útil para auditoría, debugging y detección de actividad sospechosa.

Eventos registrados:
    LOGIN_SUCCESS / LOGIN_FAILED    → intentos de autenticación
    REGISTER                        → nueva cuenta creada
    INVITE_CREATED / INVITE_USED    → invitaciones
    RESET_TOTAL                     → regeneración masiva de clases (destructivo)
    STUDENT_CREATED / DELETED       → cambios en alumnos
    TEACHER_ROLE_CHANGED            → cambios de permisos
    PASSWORD_CHANGED                → cambio de contraseña
    FULL_SYNC                       → sync completo descargado
"""

from sqlalchemy import String, Integer, Boolean, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from typing import TYPE_CHECKING

from .base import Base, TimestampMixin


class SecurityLog(Base, TimestampMixin):
    """
    Log de seguridad — inmutable por diseño.
    Nunca se actualiza ni elimina (solo INSERT).

    Atributos:
        teacher_id:   FK al teacher que ejecutó la acción (null = acción anónima, ej: login fallido)
        action:       Nombre del evento (LOGIN_SUCCESS, RESET_TOTAL, etc.)
        resource:     Tipo de recurso afectado (student, teacher, class, etc.)
        resource_id:  ID del recurso afectado (opcional)
        ip_address:   IP de quien hizo la request
        user_agent:   Cabecera User-Agent del cliente
        success:      Si la acción fue exitosa (False = intento fallido)
        detail:       Información extra en texto libre (ej: email intentado, conteo de clases)
    """
    __tablename__ = "security_logs"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True
    )

    teacher_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Teacher que ejecutó la acción (null para acciones anónimas)"
    )

    action: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        index=True,
        comment="Nombre del evento de seguridad"
    )

    resource: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
        comment="Tipo de recurso afectado (student, teacher, class, ...)"
    )

    resource_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="ID del recurso afectado"
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),   # IPv6 cabe en 45 chars
        nullable=True,
        comment="IP del cliente"
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        comment="User-Agent del cliente"
    )

    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Si la acción fue exitosa"
    )

    detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Información extra (email intentado, conteo de registros afectados, etc.)"
    )

    def __repr__(self) -> str:
        return (
            f"<SecurityLog(id={self.id}, action='{self.action}', "
            f"teacher_id={self.teacher_id}, success={self.success})>"
        )
