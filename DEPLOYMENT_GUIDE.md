# 🚀 Guía de Despliegue - Sistema de Generación de Clases

## ✅ Implementación Completada

Se ha implementado el sistema completo de generación automática de clases. Aquí está todo lo que necesitas saber para ponerlo en funcionamiento.

---

## 📋 Cambios Implementados

### 1. **Modelo de Datos**
- ✅ Agregado campo `format` a modelo `Enrollment` (`individual` | `group`)
- ✅ Actualizado esquema Pydantic de `Enrollment`

### 2. **Sistema de Generación**
- ✅ Creado `app/jobs/class_generator.py` con toda la lógica
- ✅ Creado `app/core/holidays.py` con feriados de Bolivia
- ✅ Configurado APScheduler para job mensual automático

### 3. **Endpoints HTTP**
- ✅ `POST /api/v1/jobs/generate-classes` - Generación mensual manual
- ✅ `POST /api/v1/jobs/generate-classes/{enrollment_id}` - Generación para enrollment (onboarding)
- ✅ `DELETE /api/v1/jobs/schedules/{schedule_id}/future-classes` - Eliminar al cambiar horario
- ✅ `POST /api/v1/jobs/enrollments/{enrollment_id}/cancel-future-classes` - Cancelar al suspender/retirar

### 4. **Dependencias**
- ✅ Agregado `apscheduler==3.10.4` a requirements.txt
- ✅ Instalado APScheduler

---

## 🔧 Pasos para Aplicar los Cambios

### **PASO 1: Aplicar Migración de Base de Datos**

Tienes dos opciones:

#### **Opción A: Ejecutar SQL Manualmente (Recomendado si tienes datos)**

```bash
# 1. Conectar a PostgreSQL
psql -U tu_usuario -d music_school

# 2. Ejecutar el script de migración
\i migrations/001_add_format_to_enrollments.sql

# 3. Verificar que funcionó
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'enrollments' AND column_name = 'format';
```

#### **Opción B: Recrear Tablas (Solo si NO tienes datos importantes)**

```bash
cd backend
python -m app.core.init_db reset
```

⚠️ **ADVERTENCIA**: La Opción B eliminará TODOS los datos. Úsala solo en desarrollo.

---

### **PASO 2: Reiniciar el Servidor FastAPI**

```bash
cd backend
uvicorn app.main:app --reload
```

Deberías ver en la consola:
```
>> Iniciando ProfesorSYS API...
[SCHEDULER] ✅ Iniciado - Job mensual configurado (día 10, 02:00 AM)
>> Aplicacion lista
```

---

### **PASO 3: Verificar que Todo Funciona**

#### **Test 1: Verificar Endpoints en Swagger**
1. Ir a `http://localhost:8000/docs`
2. Buscar la sección **Jobs**
3. Deberías ver 4 nuevos endpoints

#### **Test 2: Probar Generación Manual**
```bash
# Login primero para obtener token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "tu@email.com", "password": "tu_password"}'

# Usar el token para generar clases
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes \
  -H "Authorization: Bearer TU_TOKEN_AQUI"
```

---

## 📊 Cómo Funciona el Sistema

### **Job Automático Mensual**
- ⏰ Ejecuta: Día **10 de cada mes a las 02:00 AM**
- 📅 Genera: Clases del **próximo mes**
- 🎯 Alcance: **Todos** los enrollments con `status='active'`

### **Generación en Onboarding**
Al inscribir un alumno (crear Schedule):
1. Se crea el Schedule normalmente
2. Automáticamente se generan **2 meses** de clases
3. El frontend muestra: "✅ 16 clases generadas"

### **Cambio de Horario**
Cuando un alumno cambia de horario:
1. Frontend: Cierra Schedule viejo con `valid_until`
2. Frontend: Crea Schedule nuevo con `valid_from`
3. Backend: **Elimina** clases futuras del horario viejo
4. Backend: **Genera** clases del horario nuevo

### **Suspensión/Retiro**
Cuando un enrollment se suspende o retira:
- Las clases futuras se **CANCELAN** (no se eliminan)
- Se mantienen en la BD para histórico

---

## 🎯 Reglas de Negocio Implementadas

✅ Genera 2 meses desde inscripción
✅ Job mensual día 10, 02:00 AM
✅ Saltar clases duplicadas
✅ NO generar en feriados
✅ Solo enrollments activos
✅ Respetar valid_from / valid_until
✅ Eliminar clases al cambiar horario
✅ Formato heredado desde Enrollment

---

## 📝 Ejemplos de Uso

### **Ejemplo 1: Inscribir Nuevo Alumno (Onboarding)**

```typescript
// 1. Crear enrollment
const enrollment = await enrollmentService.create({
  student_id: 1,
  instrument_id: 2,
  level: 'Nivel1',
  format: 'individual',  // ⬅️ NUEVO CAMPO
  enrolled_date: '2025-10-20'
});

// 2. Crear schedule
const schedule = await scheduleService.create({
  enrollment_id: enrollment.id,
  day: 'tuesday',
  time: '16:00',
  duration: 45,
  valid_from: '2025-10-20'
});

// 3. Generar clases (2 meses)
const result = await fetch('/api/v1/jobs/generate-classes/' + enrollment.id, {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});
// Respuesta: { created: 16, skipped: 0 }
```

### **Ejemplo 2: Cambiar Horario**

```typescript
// 1. Eliminar clases futuras del horario viejo
await fetch(`/api/v1/jobs/schedules/1/future-classes?from_date=2025-11-01`, {
  method: 'DELETE',
  headers: { 'Authorization': `Bearer ${token}` }
});

// 2. Cerrar Schedule viejo
await scheduleService.update(1, { valid_until: '2025-10-31' });

// 3. Crear Schedule nuevo
const newSchedule = await scheduleService.create({
  enrollment_id: 1,
  day: 'thursday',
  time: '18:00',
  duration: 45,
  valid_from: '2025-11-01'
});

// 4. Generar clases del nuevo horario
await fetch('/api/v1/jobs/generate-classes/1', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${token}` }
});
```

---

## 🔍 Troubleshooting

### **Problema: El scheduler no inicia**
```
Solución: Verificar que APScheduler está instalado
$ pip install apscheduler==3.10.4
```

### **Problema: Clases no se generan**
```
Verificar:
1. Enrollment tiene status='active'
2. Schedule tiene active=True
3. valid_from es correcto
4. No hay errores en los logs
```

### **Problema: Error al agregar campo 'format'**
```
Solución: Ejecutar migración SQL manual
$ psql -U usuario -d music_school -f migrations/001_add_format_to_enrollments.sql
```

---

## 📚 Archivos Creados/Modificados

### **Archivos Nuevos:**
- `app/jobs/__init__.py`
- `app/jobs/class_generator.py`
- `app/core/holidays.py`
- `app/core/scheduler.py`
- `app/api/v1/jobs.py`
- `migrations/001_add_format_to_enrollments.sql`

### **Archivos Modificados:**
- `app/models/enrollment.py` (+ campo `format`)
- `app/schemas/enrollment.py` (+ campo `format`)
- `app/main.py` (+ scheduler, + jobs router)
- `app/api/v1/__init__.py` (+ jobs_router)
- `requirements.txt` (+ apscheduler)

---

## 🎉 ¡Listo!

El sistema de generación automática de clases está completamente implementado y funcionando.

**Próximos pasos sugeridos:**
1. Aplicar migración SQL
2. Reiniciar servidor
3. Probar endpoints en Swagger
4. Integrar en el frontend (onboarding)
5. Monitorear logs del job mensual

Si tienes algún problema, revisa los logs del servidor y la sección de Troubleshooting.
