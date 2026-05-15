from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_teacher
from app.models.teacher import Teacher
from app.schemas.batch import BatchRequest, BatchResponse, BatchOperationResult
from app.crud.batch import BatchProcessor

router = APIRouter()

@router.post("/", response_model=BatchResponse)
async def process_batch(
    batch_request: BatchRequest,
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)
):
    """
    Procesa un lote de operaciones (CRUD) en una única transacción.
    
    Características:
    - Ejecución secuencial (respeta el orden de la lista)
    - Resolución automática de IDs temporales (negativos)
    - Atomicidad: Si una operación falla, se hace rollback de TODO.
    
    Args:
        batch_request: Lista de operaciones a ejecutar
        db: Sesión de base de datos
        current_teacher: Profesor autenticado
    
    Returns:
        Resultados de cada operación y estadísticas
    """
    processor = BatchProcessor(db, current_teacher.id)
    results = []
    
    try:
        # Iniciar transacción nested si es necesario, pero FastAPI/SQLAlchemy
        # manejan la sesión. Si falla algo, hacemos rollback manual y re-raise o return error.
        # Al usar 'await db.commit()' dentro de los CRUDs individuales, 
        # estamos commiteando paso a paso?
        # WAIT: Los CRUDs existentes (ej: student.create) hacen `await db.commit()`.
        # Esto rompe la atomicidad del batch si ya se commiteó algo.
        #
        # PROBLEMA: Los CRUDs existentes hacen commit().
        # SOLUCIÓN:
        # 1. Modificar los CRUDs para aceptar `commit=False` (invasivo).
        # 2. O confiar en que si falla uno, los anteriores ya están guardados (no es atómico total).
        # 3. O usar SAVEPOINTs (nested transactions) con AsyncSession?
        # 
        # SQLAlchemy AsyncSession con `begin_nested()` permite savepoints.
        # PERO si el CRUD hace `commit()`, commitea la transacción entera o solo el nested?
        # En SQLAlchemy, `session.commit()` commitea la transacción "top-level" siempre.
        # 
        # Si los CRUDs hacen `commit()`, NO PODEMOS garantizar atomicidad completa del batch 
        # sin modificar los CRUDs.
        #
        # Sin embargo, el prompt dice: "Si 1 falla → `rollback()` y detener".
        # Y "Si todas OK → `commit()`".
        # Esto implica que los CRUDs NO deberían estar haciendo commit, o deberíamos manejarlo.
        #
        # Dado que NO PUEDO refactorizar todo el proyecto (CRUDs existentes),
        # y debo "adherirme a convenciones", hay un conflicto.
        #
        # Opción Pragmática:
        # El usuario pidió "Batch Sync Endpoint".
        # Si los CRUDs hacen commit, los datos se persisten.
        # Si falla el 5to, los 4 primeros quedan.
        # Esto es "partial consistency".
        # Para "rollback total", necesito que los CRUDs no hagan commit.
        #
        # ¿Puedo hacer monkey-patching o mock del commit en el contexto del batch?
        # Es arriesgado.
        #
        # Revisemos `backend/app/crud/student.py`:
        # `await db.commit()` está explícito.
        #
        # Voy a asumir que el usuario es consciente de esto o que debo hacer lo mejor posible.
        # "Si 1 falla -> rollback y detener".
        # Si el CRUD ya hizo commit, no puedo hacer rollback de eso.
        #
        # SOLUCIÓN AVANZADA:
        # Usar `db.begin_nested()` y esperar que los CRUDs usen la sesión que les paso.
        # Pero si llaman a `commit()`, SQLAlchemy intentará commitear la transacción principal.
        #
        # EXCEPCIÓN:
        # Si el usuario diseñó esto, tal vez espera que yo modifique los CRUDs?
        # "Rigorously adhere to existing project conventions" vs "Si 1 falla -> rollback".
        #
        # Voy a implementar el loop. Si un CRUD hace commit, es irreversible fácilmente.
        # PERO, voy a intentar usar `db.begin()` explícito o similar si ayuda.
        # Realmente, para que funcione como pide (atomicidad), los CRUDs deberían recibir parametro commit=True/False.
        # Como no puedo cambiar todos los CRUDs ahora (sería un cambio masivo fuera del alcance "implementar endpoint"),
        # voy a implementar la lógica secuencial.
        # Y en el comentario explicare que la atomicidad depende de los CRUDs.
        #
        # OJO: Tal vez pueda envolver `db.commit` para que no haga nada durante el batch?
        #
        # ```python
        # original_commit = db.commit
        # db.commit = lambda: None  # Mock commit
        # try:
        #    ... process ...
        #    await original_commit() # Commit final
        # except:
        #    await db.rollback()
        # finally:
        #    db.commit = original_commit
        # ```
        #
        # Esto es un "hack" pero cumple con el requisito de atomicidad sin tocar otros archivos.
        # Dado que estoy en un entorno controlado, podría funcionar.
        # `db.commit` es una coroutine. `db.commit = AsyncMock()`?
        #
        # Vamos a intentar hacer el "Commit Patching" dentro del endpoint.
        # Es la única forma de cumplir "Atomicidad" sin reescribir todo el proyecto.
        
        # Patching db.commit to allow atomic batch transaction
        original_commit = db.commit
        
        async def mock_commit():
            # No-op: acumular cambios en memoria, flush/commit al final
            pass
            
        # Reemplazar commit temporalmente
        db.commit = mock_commit
        
        # Iniciar transacción si no está iniciada (FastAPI suele iniciarla)
        # Pero aseguramos con un bloque try/except general.
        
        for op in batch_request.operations:
            result = await processor.process_operation(op)
            results.append(result)
            
            if result.status == "error":
                # Si falla, restaurar commit y hacer rollback real
                db.commit = original_commit
                await db.rollback()
                return BatchResponse(
                    results=results,
                    processed_count=len(results),
                    success=False,
                    message=f"Error en operación {op.type} (Temp ID: {op.temp_id}): {result.error}"
                )
        
        # Si todo sale bien, restaurar commit y hacer el commit real final
        db.commit = original_commit
        await db.commit()
        
        return BatchResponse(
            results=results,
            processed_count=len(results),
            success=True,
            message="Lote procesado exitosamente"
        )
        
    except Exception as e:
        # Restaurar commit en caso de error inesperado y rollback
        # (Si `db.commit` sigue patcheado)
        if hasattr(db, 'commit') and db.commit == mock_commit:
            db.commit = original_commit
            
        await db.rollback()
        # Retornar error 500 o estructura de error
        # Como response_model es BatchResponse, intentamos devolver eso si es posible,
        # o raise HTTPException.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno procesando batch: {str(e)}"
        )
