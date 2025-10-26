# Deployment y Configuración del Job Automático de Clases

Este documento describe cómo configurar, probar y hacer deployment del sistema de generación automática de clases.

## 📋 Índice

1. [Arquitectura del Sistema](#arquitectura-del-sistema)
2. [Configuración Local](#configuración-local)
3. [Testing del Job](#testing-del-job)
4. [Deployment en Producción](#deployment-en-producción)
5. [Monitoreo y Troubleshooting](#monitoreo-y-troubleshooting)

---

## 🏗️ Arquitectura del Sistema

### Componentes Principales

1. **APScheduler** - Scheduler de trabajos cron
2. **class_generator.py** - Lógica de generación de clases
3. **scheduler.py** - Configuración del scheduler
4. **main.py** - Integración con FastAPI
5. **jobs.py** - Endpoints HTTP para ejecución manual

### Flujo de Generación

```
┌─────────────────────┐
│   Job Mensual       │
│   (Día 10 - 2 AM)   │
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│ Obtener enrollments │
│ con status='active' │
└──────────┬──────────┘
           │
           v
┌─────────────────────┐
│  Por cada Schedule  │
│     activo          │
└──────────┬──────────┘
           │
           v
┌─────────────────────────────┐
│  Generar clases:            │
│  - Mes actual (resto)       │
│  - Mes siguiente (completo) │
└──────────┬──────────────────┘
           │
           v
┌─────────────────────────────┐
│  Validaciones:              │
│  - Saltar duplicados        │
│  - Saltar feriados          │
│  - Respetar valid_from/until│
└─────────────────────────────┘
```

---

## 🔧 Configuración Local

### 1. Instalación de Dependencias

```bash
cd backend
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install apscheduler
```

### 2. Verificar Importaciones

```bash
python -c "from apscheduler.schedulers.asyncio import AsyncIOScheduler; print('✅ APScheduler instalado')"
```

### 3. Aplicar Migraciones

Si aún no has aplicado la migración para agregar `format` a enrollments:

```sql
-- backend/migrations/001_add_format_to_enrollments.sql
ALTER TABLE enrollments
ADD COLUMN format VARCHAR(20) NOT NULL DEFAULT 'individual';

ALTER TABLE enrollments
ADD CONSTRAINT check_enrollment_format
CHECK (format IN ('individual', 'group'));
```

Aplicar:
```bash
psql -U postgres -d profesorsys -f migrations/001_add_format_to_enrollments.sql
```

### 4. Configuración de Holidays

El sistema ya tiene configurados los feriados de Bolivia para 2025-2026 en:
- `app/core/holidays.py`

Para agregar más años:
```python
HOLIDAYS_2027 = [
    date(2027, 1, 1),   # Año Nuevo
    # ... agregar más feriados
]

ALL_HOLIDAYS = HOLIDAYS_2025 + HOLIDAYS_2026 + HOLIDAYS_2027
```

---

## 🧪 Testing del Job

### Opción 1: Ejecutar Manualmente vía API

```bash
# Generar clases para TODOS los enrollments activos (simula job mensual)
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes \
  -H "Authorization: Bearer YOUR_TOKEN"

# Generar clases para un enrollment específico (onboarding)
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes/1 \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Opción 2: Ejecutar desde Python

```python
import asyncio
from app.core.database import async_session_maker
from app.jobs.class_generator import generate_monthly_classes

async def test_job():
    async with async_session_maker() as db:
        result = await generate_monthly_classes(db)
        print(f"✅ Clases generadas: {result['created']}")
        print(f"⏭️ Clases saltadas: {result['skipped']}")
        print(f"❌ Errores: {result['errors']}")

asyncio.run(test_job())
```

### Opción 3: Forzar Ejecución Inmediata del Scheduler

Modificar temporalmente `app/core/scheduler.py`:

```python
# Cambiar de:
trigger=CronTrigger(day=10, hour=2, minute=0)

# A (ejecutar cada minuto para testing):
trigger=CronTrigger(minute='*')
```

⚠️ **IMPORTANTE**: Revertir este cambio antes de deployment en producción.

### Verificar Resultados

```sql
-- Ver clases generadas
SELECT
    c.id,
    c.date,
    c.time,
    c.type,
    c.format,
    s.name as student_name,
    i.name as instrument_name
FROM classes c
JOIN enrollments e ON c.enrollment_id = e.id
JOIN students s ON e.student_id = s.id
JOIN instruments i ON e.instrument_id = i.id
WHERE c.type = 'regular'
ORDER BY c.date, c.time;

-- Contar clases generadas por fecha
SELECT
    date,
    COUNT(*) as total_classes
FROM classes
WHERE type = 'regular'
GROUP BY date
ORDER BY date;
```

---

## 🚀 Deployment en Producción

### 1. Configuración del Servidor

#### Variables de Entorno

```bash
# .env
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
SECRET_KEY=your-secret-key-here
ENVIRONMENT=production
```

#### Timezone del Servidor

El job corre a las 2:00 AM hora del servidor. Asegurarse de que el timezone sea correcto:

```bash
# Ver timezone actual
timedatectl

# Cambiar a Bolivia (si es necesario)
sudo timedatectl set-timezone America/La_Paz
```

### 2. Proceso de Deployment

#### Opción A: Servidor con Systemd (Recomendado)

Crear servicio systemd en `/etc/systemd/system/profesorsys.service`:

```ini
[Unit]
Description=ProfesorSYS API
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/profesorsys/backend
Environment="PATH=/var/www/profesorsys/backend/venv/bin"
ExecStart=/var/www/profesorsys/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Activar:
```bash
sudo systemctl daemon-reload
sudo systemctl enable profesorsys
sudo systemctl start profesorsys
sudo systemctl status profesorsys
```

#### Opción B: Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:password@db:5432/profesorsys
    depends_on:
      - db
    restart: always

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: profesorsys
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Desplegar:
```bash
docker-compose up -d
docker-compose logs -f api
```

### 3. Verificar que el Scheduler Está Corriendo

```bash
# Ver logs del servidor
sudo journalctl -u profesorsys -f

# Deberías ver al inicio:
# INFO: APScheduler started
# INFO: Added job 'generate_monthly_classes' (trigger: cron[day='10', hour='2', minute='0'])
```

---

## 📊 Monitoreo y Troubleshooting

### Logs del Job

El job automático genera logs en la consola. Para monitorearlos:

```bash
# Systemd
sudo journalctl -u profesorsys -f | grep "generate_monthly_classes"

# Docker
docker-compose logs -f api | grep "generate_monthly_classes"
```

### Verificar Próxima Ejecución

Agregar endpoint de diagnóstico (opcional):

```python
# app/api/v1/jobs.py
@router.get("/scheduler/status")
async def get_scheduler_status():
    """Ver estado del scheduler y próxima ejecución"""
    from app.core.scheduler import scheduler

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None
        })

    return {
        "running": scheduler.running,
        "jobs": jobs
    }
```

Consultar:
```bash
curl http://localhost:8000/api/v1/jobs/scheduler/status
```

### Problemas Comunes

#### 1. El job no se ejecuta

**Síntomas**: No se generan clases automáticamente.

**Soluciones**:
```bash
# 1. Verificar que APScheduler está corriendo
curl http://localhost:8000/api/v1/jobs/scheduler/status

# 2. Verificar logs
sudo journalctl -u profesorsys -f

# 3. Reiniciar el servicio
sudo systemctl restart profesorsys
```

#### 2. Timezone incorrecto

**Síntomas**: Job se ejecuta en hora incorrecta.

**Solución**:
```python
# app/core/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone

# Especificar timezone explícitamente
bolivia_tz = timezone('America/La_Paz')

scheduler.add_job(
    monthly_class_generation_job,
    trigger=CronTrigger(day=10, hour=2, minute=0, timezone=bolivia_tz),
    id='generate_monthly_classes'
)
```

#### 3. Clases duplicadas

**Síntomas**: Se crean múltiples clases para la misma fecha/hora.

**Causa**: Job ejecutado múltiples veces manualmente.

**Solución**: El sistema ya tiene protección contra duplicados. Verificar con:
```sql
-- Ver clases duplicadas
SELECT date, time, enrollment_id, COUNT(*)
FROM classes
WHERE type = 'regular'
GROUP BY date, time, enrollment_id
HAVING COUNT(*) > 1;
```

#### 4. No se saltean feriados

**Síntomas**: Se generan clases en días feriados.

**Solución**: Agregar feriados faltantes en `app/core/holidays.py`.

### Alertas y Notificaciones (Opcional)

Agregar notificación por email cuando el job falla:

```python
# app/core/scheduler.py
async def monthly_class_generation_job():
    try:
        async for db in get_db():
            result = await generate_monthly_classes(db)

            # Enviar notificación de éxito
            print(f"✅ Job completado: {result['created']} clases generadas")

            break
    except Exception as e:
        # Enviar email de alerta
        print(f"❌ Job falló: {str(e)}")
        # TODO: Integrar con servicio de email
        raise
```

---

## 📅 Calendario de Mantenimiento

### Mensual

- **Día 10**: Verificar que el job se ejecutó correctamente
- Revisar logs por errores
- Verificar cantidad de clases generadas vs esperado

### Trimestral

- Actualizar lista de feriados para próximos meses
- Revisar y limpiar clases canceladas antiguas

### Anual

- Agregar feriados del año siguiente en `holidays.py`
- Revisar performance del job con DB creciente

---

## 🔐 Seguridad

### Endpoints Protegidos

Todos los endpoints de jobs requieren autenticación:

```python
@router.post("/generate-classes")
async def generate_all_classes(
    db: AsyncSession = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher)  # ✅ Requiere auth
):
    # ...
```

### Prevención de Ejecuciones Accidentales

El job automático NO se puede desactivar vía API por seguridad. Para desactivarlo temporalmente:

```python
# app/main.py
@app.on_event("startup")
async def startup_event():
    # Comentar esta línea para desactivar scheduler
    # start_scheduler()
    pass
```

---

## 📝 Checklist de Deployment

- [ ] Dependencias instaladas (`pip install apscheduler`)
- [ ] Migraciones aplicadas (campo `format` en enrollments)
- [ ] Feriados actualizados para el año en curso
- [ ] Timezone del servidor configurado correctamente
- [ ] Servicio systemd/Docker configurado
- [ ] Logs monitoreables
- [ ] Job ejecutado manualmente y verificado
- [ ] Scheduler corriendo y próxima ejecución confirmada
- [ ] Documentación compartida con equipo de ops

---

## 🆘 Soporte

Si encuentras problemas no cubiertos en esta guía:

1. Revisar logs del servidor
2. Ejecutar job manualmente vía API para debugging
3. Verificar que todos los enrollments tengan schedules activos
4. Consultar la tabla `classes` para verificar datos generados

**Contacto**: [Tu email o sistema de tickets]
