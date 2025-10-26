# 🚀 Quick Start - Generación Automática de Clases

## Uso Rápido

### Testing Local

```bash
# Ver estadísticas del sistema
python test_job.py --stats

# Generar clases para TODOS los enrollments (simula job mensual)
python test_job.py

# Generar clases para un enrollment específico
python test_job.py --enrollment 1

# Solo verificar clases generadas
python test_job.py --verify
```

### Ejecución Manual vía API

```bash
# Obtener token de autenticación primero
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"tu@email.com","password":"tupassword"}' \
  | jq -r '.access_token')

# Generar clases para todos los enrollments activos
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes \
  -H "Authorization: Bearer $TOKEN"

# Generar clases para un enrollment específico (onboarding)
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes/1 \
  -H "Authorization: Bearer $TOKEN"

# Eliminar clases futuras de un schedule (cuando cambia de horario)
curl -X DELETE http://localhost:8000/api/v1/jobs/schedules/1/future-classes \
  -H "Authorization: Bearer $TOKEN"
```

## Cómo Funciona

### Job Automático

- **Cuándo**: Día 10 de cada mes a las 2:00 AM
- **Qué hace**: Genera clases para todos los enrollments activos
- **Alcance**: Mes actual (resto) + mes siguiente completo

### Ejemplo

Si hoy es **22 de septiembre 2025**:

1. Genera clases desde **22-sep** hasta **30-sep** (resto del mes actual)
2. Genera clases de **1-oct** hasta **31-oct** (mes siguiente completo)

### Reglas de Negocio

✅ **Genera clases si**:
- Enrollment tiene `status='active'`
- Schedule tiene `active=True`
- Fecha está entre `valid_from` y `valid_until`
- No es feriado
- No existe clase duplicada (misma fecha/hora/enrollment)

❌ **NO genera clases si**:
- Enrollment está suspendido o retirado
- Schedule está inactivo
- Es día feriado
- Ya existe clase en esa fecha/hora

### Formato de Clases

El formato (`individual` o `group`) se hereda desde `Enrollment.format`:

```python
enrollment.format = 'individual'  # → classes tendrán format='individual'
enrollment.format = 'group'       # → classes tendrán format='group'
```

## Archivos Importantes

```
backend/
├── app/
│   ├── jobs/
│   │   └── class_generator.py     # 🎯 Lógica principal de generación
│   ├── core/
│   │   ├── scheduler.py           # ⏰ Configuración del job automático
│   │   └── holidays.py            # 📅 Feriados de Bolivia
│   └── api/v1/
│       └── jobs.py                # 🔌 Endpoints HTTP
├── test_job.py                    # 🧪 Script de testing
├── DEPLOYMENT_JOB.md              # 📚 Guía completa de deployment
└── README_JOBS.md                 # 📖 Esta guía rápida
```

## Troubleshooting

### ❌ "No se generaron clases"

```bash
# 1. Verificar que hay enrollments activos
python test_job.py --stats

# 2. Verificar que los schedules tienen valid_from correcto
# El valid_from debe ser <= fecha actual
```

### ❌ "Se generaron clases en feriados"

```bash
# Agregar el feriado en app/core/holidays.py
HOLIDAYS_2025 = [
    date(2025, 12, 25),  # Agregar fecha aquí
    # ...
]
```

### ❌ "Clases solo hasta el 21 de noviembre"

Esto está corregido. La nueva lógica genera:
- Resto del mes de inscripción
- Mes completo siguiente

### ❌ "Job no se ejecuta automáticamente"

```bash
# Verificar logs del servidor
sudo journalctl -u profesorsys -f | grep "APScheduler"

# Debería mostrar:
# INFO: APScheduler started
# INFO: Added job 'generate_monthly_classes'
```

## Ver Deployment Completo

Para instrucciones completas de deployment en producción, ver:
- **[DEPLOYMENT_JOB.md](./DEPLOYMENT_JOB.md)**

## Contacto

Si tienes dudas, revisa los logs y ejecuta el script de testing para diagnosticar.
