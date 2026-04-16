import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text

from app.crud import student, enrollment, schedule, class_crud, attendance
from app.models.enrollment import Enrollment
from app.models.class_model import ClassType
from app.schemas.batch import BatchOperation, BatchOperationResult, ClassRecoveryCreate
from app.schemas.student import StudentCreate, StudentUpdate
from app.schemas.enrollment import EnrollmentCreate, EnrollmentUpdate
from app.schemas.schedule import ScheduleCreate, ScheduleUpdate
from app.schemas.class_schema import ClassCreate, ClassUpdate
from app.schemas.attendance import AttendanceCreate, AttendanceUpdate

logger = logging.getLogger(__name__)

class BatchProcessor:
    def __init__(self, db: AsyncSession, teacher_id: int):
        self.db = db
        self.teacher_id = teacher_id
        self.id_mapping: Dict[int, int] = {}  # Map temp_id (negative) -> real_id (positive)

    def resolve_id(self, id_value: int | None) -> int | None:
        """
        Resuelve un ID.
        Si es negativo (temp_id), busca su ID real en el mapping.
        Si es positivo, lo devuelve tal cual.
        """
        if id_value is None:
            return None
        
        if id_value < 0:
            if id_value in self.id_mapping:
                return self.id_mapping[id_value]
            else:
                raise ValueError(f"ID temporal {id_value} no encontrado en mapping de referencias previas")
        
        return id_value

    def resolve_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Busca campos que son IDs (terminan en _id) y los resuelve si son temporales.
        También inyecta teacher_id si es necesario.
        """
        resolved = payload.copy()
        
        # Campos conocidos que son IDs
        id_fields = ['student_id', 'enrollment_id', 'schedule_id', 'class_id']
        
        for field in id_fields:
            if field in resolved:
                resolved[field] = self.resolve_id(resolved[field])

        # Inyectar teacher_id para operaciones de creación
        # (Student, Enrollment, Schedule, Class, pero NO Attendance)
        # Verificamos si el payload "parece" requerir teacher_id (o si el schema lo tiene)
        # Por simplicidad, lo inyectamos siempre, los schemas que no lo usen lo ignorarán 
        # (si strict=False o extra='ignore', pero Pydantic por defecto puede quejarse)
        # Mejor inyectarlo solo si no está o es None, y dejar que el schema decida.
        # Pero los schemas Create lo tienen.
        resolved['teacher_id'] = self.teacher_id
        
        return resolved

    async def process_operation(self, op: BatchOperation) -> BatchOperationResult:
        try:
            # Resolver ID del objeto a manipular (para update/delete)
            target_id = self.resolve_id(op.id)
            
            # Resolver referencias dentro del payload
            payload_data = self.resolve_payload(op.payload)
            
            result_id = None
            
            # ==========================================
            # STUDENT
            # ==========================================
            if op.type == "CREATE_STUDENT":
                schema = StudentCreate(**payload_data)
                obj = await student.create(self.db, schema)
                result_id = obj.id
            
            elif op.type == "UPDATE_STUDENT":
                if not target_id: raise ValueError("ID requerido para UPDATE")
                schema = StudentUpdate(**payload_data)
                await student.update(self.db, target_id, schema)
                result_id = target_id

            elif op.type == "DELETE_STUDENT":
                if not target_id: raise ValueError("ID requerido para DELETE")
                # Hard-delete: eliminar completamente del sistema (no solo suspender)
                await student.remove(self.db, target_id)
                result_id = target_id

            # ==========================================
            # ENROLLMENT
            # ==========================================
            elif op.type == "CREATE_ENROLLMENT":
                schema = EnrollmentCreate(**payload_data)
                obj = await enrollment.create(self.db, schema)
                result_id = obj.id

            elif op.type == "UPDATE_ENROLLMENT":
                if not target_id: raise ValueError("ID requerido para UPDATE")
                schema = EnrollmentUpdate(**payload_data)
                await enrollment.update(self.db, target_id, schema)
                result_id = target_id
            
            elif op.type == "DELETE_ENROLLMENT":
                if not target_id: raise ValueError("ID requerido para DELETE")
                await enrollment.remove(self.db, target_id)
                result_id = target_id

            # ==========================================
            # SCHEDULE
            # ==========================================
            elif op.type == "CREATE_SCHEDULE":
                schema = ScheduleCreate(**payload_data)
                obj = await schedule.create(self.db, schema)
                result_id = obj.id

            elif op.type == "UPDATE_SCHEDULE":
                if not target_id: raise ValueError("ID requerido para UPDATE")
                schema = ScheduleUpdate(**payload_data)
                await schedule.update(self.db, target_id, schema)
                result_id = target_id
            
            elif op.type == "DELETE_SCHEDULE":
                if not target_id: raise ValueError("ID requerido para DELETE")
                await schedule.remove(self.db, target_id)
                result_id = target_id

            # ==========================================
            # CLASS
            # ==========================================
            elif op.type == "CREATE_CLASS":
                schema = ClassCreate(**payload_data)
                obj = await class_crud.create(self.db, schema)
                result_id = obj.id
            
            elif op.type == "CREATE_RECOVERY_CLASS":
                # Usar schema específico o ClassCreate forzando type
                schema = ClassRecoveryCreate(**payload_data)
                # create_recovery valida créditos y descuenta
                obj = await class_crud.create_recovery(self.db, schema)
                if not obj:
                    raise ValueError("No se pudo crear clase de recuperación (posible falta de créditos)")
                result_id = obj.id

            elif op.type == "UPDATE_CLASS":
                if not target_id: raise ValueError("ID requerido para UPDATE")
                schema = ClassUpdate(**payload_data)
                await class_crud.update(self.db, target_id, schema)
                result_id = target_id
            
            elif op.type == "DELETE_CLASS":
                # Eliminación física de clase regular (solo si no es recovery, esa tiene su propia lógica?)
                if not target_id: raise ValueError("ID requerido para DELETE")
                obj = await class_crud.get(self.db, target_id)
                if obj:
                    # Si es recuperación, usar lógica específica que devuelve crédito
                    if obj.type == ClassType.RECOVERY:
                        await class_crud.delete_recovery(self.db, target_id)
                    else:
                        await self.db.delete(obj)
                        await self.db.commit()
                result_id = target_id

            elif op.type == "DELETE_RECOVERY_CLASS":
                if not target_id: raise ValueError("ID requerido para DELETE RECOVERY")
                await class_crud.delete_recovery(self.db, target_id)
                result_id = target_id

            elif op.type == "CANCEL_CLASS":
                if not target_id: raise ValueError("ID requerido para CANCEL")
                await class_crud.cancel(self.db, target_id)
                result_id = target_id

            # ==========================================
            # ATTENDANCE
            # ==========================================
            elif op.type == "CREATE_ATTENDANCE":
                # Attendance no lleva teacher_id en schema create
                # payload_data tiene teacher_id inyectado, Pydantic lo ignorará si extra='ignore'
                # o debemos quitarlo. AttendanceCreate hereda de AttendanceBase, no tiene teacher_id.
                # Pydantic BaseConfig default es ignore extra fields? 
                # StudentBase no tiene config extra. BaseModel default es 'ignore'.
                # Vamos a limpiar teacher_id por seguridad para Attendance
                clean_payload = {k: v for k, v in payload_data.items() if k != 'teacher_id'}
                schema = AttendanceCreate(**clean_payload)
                obj = await attendance.create(self.db, schema)
                result_id = obj.id

            elif op.type == "UPDATE_ATTENDANCE":
                if not target_id: raise ValueError("ID requerido para UPDATE")
                clean_payload = {k: v for k, v in payload_data.items() if k != 'teacher_id'}
                schema = AttendanceUpdate(**clean_payload)
                await attendance.update(self.db, target_id, schema)
                result_id = target_id

            elif op.type == "DELETE_ATTENDANCE":
                if not target_id: raise ValueError("ID requerido para DELETE")
                await attendance.delete(self.db, target_id)
                result_id = target_id

            # ==========================================
            # PARTIAL RECOVERIES
            # ==========================================
            elif op.type == "ADD_PARTIAL_RECOVERY":
                enrollment_id = payload_data.get('enrollment_id')
                if not enrollment_id: raise ValueError("enrollment_id requerido para ADD_PARTIAL_RECOVERY")
                date_str = payload_data.get('date')
                time_str = payload_data.get('time')
                minutes = payload_data.get('minutes')
                if not all([date_str, time_str, minutes]): raise ValueError("date, time, minutes requeridos")
                
                # Validar que el enrollment existe
                result = await self.db.execute(
                    select(Enrollment).where(Enrollment.id == enrollment_id)
                )
                enr = result.scalar_one_or_none()
                if not enr: raise ValueError(f"Enrollment {enrollment_id} no encontrado")
                
                # Agregar sesión parcial de forma segura
                new_session = {"date": date_str, "time": time_str, "minutes": minutes}
                current_sessions = enr.partial_sessions or []
                updated_sessions = current_sessions + [new_session]
                
                # Update usando SQLAlchemy (seguro contra SQL injection)
                await self.db.execute(
                    update(Enrollment)
                    .where(Enrollment.id == enrollment_id)
                    .values(partial_sessions=updated_sessions)
                )
                await self.db.commit()
                result_id = enrollment_id

            elif op.type == "REMOVE_PARTIAL_RECOVERY":
                enrollment_id = payload_data.get('enrollment_id')
                session_index = payload_data.get('session_index')
                if enrollment_id is None or session_index is None: raise ValueError("enrollment_id y session_index requeridos")
                
                # Verificar que el índice sea válido
                result = await self.db.execute(
                    select(Enrollment).where(Enrollment.id == enrollment_id)
                )
                enr = result.scalar_one_or_none()
                if not enr: raise ValueError(f"Enrollment {enrollment_id} no encontrado")
                
                current_sessions = enr.partial_sessions or []
                if session_index < 0 or session_index >= len(current_sessions):
                    raise ValueError(f"session_index {session_index} inválido (rango: 0-{len(current_sessions)-1})")
                
                # Construir nuevo array sin el elemento en session_index
                updated_sessions = current_sessions[:session_index] + current_sessions[session_index + 1:]
                
                # Update atómico
                await self.db.execute(
                    update(Enrollment)
                    .where(Enrollment.id == enrollment_id)
                    .values(partial_sessions=updated_sessions)
                )
                await self.db.commit()
                result_id = enrollment_id

            elif op.type == "CLEAR_PARTIAL_RECOVERIES":
                enrollment_id = payload_data.get('enrollment_id')
                if not enrollment_id: raise ValueError("enrollment_id requerido para CLEAR_PARTIAL_RECOVERIES")
                
                # Verificar que el enrollment exista
                result = await self.db.execute(
                    select(Enrollment).where(Enrollment.id == enrollment_id)
                )
                enr = result.scalar_one_or_none()
                if not enr: raise ValueError(f"Enrollment {enrollment_id} no encontrado")
                
                await self.db.execute(
                    update(Enrollment)
                    .where(Enrollment.id == enrollment_id)
                    .values(partial_sessions=[])
                )
                await self.db.commit()
                result_id = enrollment_id
            
            else:
                raise ValueError(f"Tipo de operación no soportado: {op.type}")

            # Registrar mapping si es una creación con ID temporal
            if op.temp_id and op.temp_id < 0 and result_id:
                self.id_mapping[op.temp_id] = result_id
                logger.debug(f"Mapped temp_id {op.temp_id} -> real_id {result_id}")

            return BatchOperationResult(
                temp_id=op.temp_id,
                real_id=result_id,
                type=op.type,
                status="success"
            )

        except Exception as e:
            logger.error(f"Error procesando batch op {op.type}: {str(e)}")
            return BatchOperationResult(
                temp_id=op.temp_id,
                type=op.type,
                status="error",
                error=str(e)
            )
