# 🚀 Generar Clases para tus 4 Alumnos

Ya que acabas de inscribir 4 alumnos, necesitas generar las clases manualmente.

## Opción 1: Desde Swagger UI (MÁS FÁCIL)

1. **Ir a Swagger**: http://localhost:8000/docs

2. **Hacer login** (para obtener el token):
   - Expandir `POST /api/v1/auth/login`
   - Click en "Try it out"
   - Ingresar tu email y password
   - Click "Execute"
   - **Copiar el `access_token`** de la respuesta

3. **Autorizar**:
   - Click en el botón "Authorize" (🔓 arriba a la derecha)
   - Pegar: `Bearer TU_TOKEN_AQUI`
   - Click "Authorize"

4. **Generar clases para TODOS los enrollments**:
   - Ir a la sección **Jobs**
   - Expandir `POST /api/v1/jobs/generate-classes`
   - Click "Try it out"
   - Click "Execute"
   - Deberías ver algo como:
     ```json
     {
       "message": "Generación mensual completada",
       "stats": {
         "created": 64,
         "skipped": 0,
         "enrollments_processed": 4
       }
     }
     ```

5. **Refrescar el calendario** en el frontend
   - Las clases deberían aparecer ahora

---

## Opción 2: Desde cURL (Terminal)

```bash
# 1. Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"tu@email.com","password":"tu_password"}'

# Copiar el access_token de la respuesta

# 2. Generar clases
curl -X POST http://localhost:8000/api/v1/jobs/generate-classes \
  -H "Authorization: Bearer TU_TOKEN_AQUI"
```

---

## Opción 3: Desde el Frontend (Recomendado para producción)

Puedes crear un botón temporal en el frontend:

```typescript
// En algún componente de admin
const handleGenerateClasses = async () => {
  try {
    const response = await fetch('http://localhost:8000/api/v1/jobs/generate-classes', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });

    const result = await response.json();
    console.log('Clases generadas:', result);
    alert(`✅ ${result.stats.created} clases generadas`);
  } catch (error) {
    console.error('Error:', error);
  }
};
```

---

## ¿Qué hace este endpoint?

1. Busca TODOS los enrollments con `status='active'`
2. Para cada enrollment:
   - Busca sus Schedules activos
   - Genera clases para los próximos 2 meses
   - Salta clases duplicadas
   - Salta feriados
3. Retorna estadísticas

---

## Después de generar:

✅ Refrescar el calendario en el frontend
✅ Deberías ver las clases de los 4 alumnos
✅ Las clases aparecen con colores según su tipo/formato

Si algo no funciona, revisa los logs del backend.
