# 🚀 Guía de Deployment en Render - ProfesorSYS Backend

Esta guía te llevará paso a paso para desplegar tu backend FastAPI en **Render.com** con PostgreSQL.

---

## 📋 Pre-requisitos

✅ Cuenta en [Render.com](https://render.com) (gratis)
✅ Repositorio en GitHub/GitLab
✅ Backend listo con `requirements.txt` actualizado

---

## 🎯 Parte 1: Preparar el Código

### 1.1 Verificar requirements.txt

Asegúrate de que tu `requirements.txt` tenga todas las dependencias necesarias:

```txt
fastapi==0.118.0
uvicorn[standard]==0.37.0
gunicorn==24.0.0
sqlalchemy==2.0.43
psycopg2-binary==2.9.10
asyncpg==0.30.0
pydantic==2.11.10
pydantic-settings==2.11.0
bcrypt==4.1.2
python-jose[cryptography]==3.5.0
cryptography==43.0.3
python-dotenv==1.1.1
apscheduler==3.10.4
```

✅ Ya actualizado en este proyecto.

### 1.2 Verificar configuración de CORS

En `app/main.py` debe estar configurado para usar `ALLOWED_ORIGINS` desde variables de entorno:

```python
origins = settings.ALLOWED_ORIGINS.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

✅ Ya configurado en este proyecto.

### 1.3 Push a GitHub

```bash
git add .
git commit -m "Preparar backend para deployment en Render"
git push origin main
```

---

## 🗄️ Parte 2: Crear Base de Datos PostgreSQL en Render

### 2.1 Ir a Dashboard de Render

1. Inicia sesión en [dashboard.render.com](https://dashboard.render.com)
2. Click en **"New +"** → **"PostgreSQL"**

### 2.2 Configurar PostgreSQL

**Nombre:** `profesorsys-db` (o el que prefieras)
**Database:** `music_school`
**User:** (auto-generado)
**Region:** Elegir región más cercana (ej: Oregon, Ohio)
**Plan:** **Free** (para empezar)

Click en **"Create Database"**

### 2.3 Guardar Credenciales

⚠️ **IMPORTANTE:** Guarda estos datos (los necesitarás):

- **Internal Database URL**: Para conectar desde Render Web Service
- **External Database URL**: Para conectar desde tu máquina local

Ejemplo:
```
postgresql://user:password@hostname.region.render.com/database
```

---

## 🌐 Parte 3: Crear Web Service en Render

### 3.1 Crear Servicio

1. Dashboard → **"New +"** → **"Web Service"**
2. Conecta tu repositorio de GitHub
3. Selecciona el repositorio `ProfesorSYS`

### 3.2 Configuración del Servicio

**Name:** `profesorsys-backend`
**Region:** Misma región que la base de datos
**Branch:** `main`
**Root Directory:** `backend` (si tu backend está en subcarpeta)
**Runtime:** `Python 3`
**Build Command:**
```bash
pip install -r requirements.txt
```

**Start Command (OPCIÓN 1 - Recomendado con Gunicorn):**
```bash
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

**Start Command (OPCIÓN 2 - Simple con Uvicorn):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

**Instance Type:** `Free` (para empezar)

### 3.3 Configurar Variables de Entorno

En **"Environment Variables"**, agregar:

| Key | Value | Notas |
|-----|-------|-------|
| `DATABASE_URL` | *(copiar Internal Database URL de PostgreSQL)* | URL completa de la base de datos |
| `SECRET_KEY` | *(generar uno fuerte)* | Ver sección de generación abajo |
| `ENVIRONMENT` | `production` | Indica entorno de producción |
| `ALLOWED_ORIGINS` | `https://tuapp.vercel.app,https://tuapp.com` | URLs de tu frontend (separadas por coma) |
| `PYTHON_VERSION` | `3.11.0` | Opcional, para especificar versión |

#### Generar SECRET_KEY seguro:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copia el resultado y úsalo como `SECRET_KEY`.

### 3.4 Auto-Deploy

✅ Activar **"Auto-Deploy"**: Sí
(Cada push a `main` disparará un nuevo deployment automáticamente)

Click en **"Create Web Service"**

---

## 🔄 Parte 4: Primeros Pasos Post-Deployment

### 4.1 Monitorear el Deploy

Render te mostrará logs en tiempo real. Espera a ver:

```
==> Build successful
==> Deploying...
==> Starting service...
>> Iniciando ProfesorSYS API...
>> Entorno: production
[SCHEDULER] ✅ Iniciado - Job mensual configurado
>> Aplicacion lista
```

### 4.2 Verificar que Funciona

1. Copia la URL de tu servicio (ej: `https://profesorsys-backend.onrender.com`)
2. Prueba el health check:

```bash
curl https://profesorsys-backend.onrender.com/health
```

Deberías ver:
```json
{
  "status": "healthy",
  "environment": "production"
}
```

### 4.3 Acceder a Documentación API

Ve a: `https://tu-servicio.onrender.com/docs`

Deberías ver Swagger UI con todos tus endpoints.

---

## 🏗️ Parte 5: Inicializar Base de Datos

### 5.1 Opción A: Ejecutar desde Shell de Render

1. En Render Dashboard → Tu servicio → **"Shell"**
2. Ejecutar:

```bash
python -m app.core.init_db
```

### 5.2 Opción B: Conectar localmente

Usa el **External Database URL** desde tu máquina:

```bash
# En tu .env local, temporalmente usar la URL de producción
DATABASE_URL=postgresql://user:pass@host.render.com/database

# Ejecutar localmente
python -m app.core.init_db
```

⚠️ **Cuidado:** Esto ejecuta contra la BD de producción.

### 5.3 Verificar Tablas

Conectar a PostgreSQL:

```bash
psql "postgresql://user:pass@host.render.com/database"
```

```sql
\dt
-- Deberías ver: teachers, students, instruments, enrollments, schedules, classes, attendances
```

---

## ⚙️ Parte 6: Configurar Frontend

En tu app Next.js (apps/teacher), configurar la URL del backend:

### Variable de Entorno en Vercel/Render

```env
NEXT_PUBLIC_API_URL=https://profesorsys-backend.onrender.com/api/v1
```

### Verificar CORS

Asegúrate de agregar la URL de tu frontend en `ALLOWED_ORIGINS` del backend:

```
ALLOWED_ORIGINS=https://tuapp.vercel.app,https://www.tuapp.com
```

---

## 🎛️ Comandos Útiles

### Ver Logs en Tiempo Real

Render Dashboard → Tu servicio → **"Logs"**

### Ejecutar Comandos en el Servidor

Render Dashboard → Tu servicio → **"Shell"**

```bash
# Ver versión Python
python --version

# Listar dependencias instaladas
pip list

# Ejecutar migraciones (si usas Alembic)
alembic upgrade head

# Ver variables de entorno
env
```

### Reiniciar Servicio

Render Dashboard → Tu servicio → **"Manual Deploy"** → **"Deploy latest commit"**

---

## 🔧 Troubleshooting

### ❌ Error: "Application startup failed"

**Causa:** Falta alguna variable de entorno o error en el código.

**Solución:**
1. Revisa los logs en Render
2. Verifica que `DATABASE_URL` y `SECRET_KEY` estén configurados
3. Asegúrate de que `requirements.txt` tenga todas las dependencias

### ❌ Error: "Connection refused" al conectar a BD

**Causa:** Estás usando External Database URL en lugar de Internal.

**Solución:**
En Render, siempre usa el **Internal Database URL** para conectar desde el Web Service.

### ❌ Error: "CORS policy" en frontend

**Causa:** Frontend no está en `ALLOWED_ORIGINS`.

**Solución:**
Agrega la URL de tu frontend a la variable `ALLOWED_ORIGINS`:

```
ALLOWED_ORIGINS=https://tuapp.vercel.app,https://tuapp.com
```

Reinicia el servicio.

### ❌ Servicio se duerme (Free Plan)

**Comportamiento esperado:** En el plan Free, Render duerme servicios inactivos después de 15 min.

**Solución:**
- Primer request tardará ~30 segundos (cold start)
- Considera upgradar a plan pagado ($7/mes) para keep-alive
- Usa un cron job externo para ping cada 10 min

### ❌ APScheduler no ejecuta jobs

**Causa:** En Free plan, el servicio se duerme y los jobs no ejecutan.

**Solución:**
- Upgrade a plan Starter ($7/mes)
- O usa Render Cron Jobs (servicio separado)

---

## 📊 Monitoreo

### Health Check Endpoint

Render automáticamente hace ping a `/health` cada minuto.

Si tu servicio responde con 200 OK, Render lo marca como "healthy".

### Logs

Render guarda logs por 7 días en plan Free.

Para logs más largos, considera integrar:
- **Sentry** (errores)
- **LogDNA** (logs completos)
- **Datadog** (métricas)

---

## 💰 Costos

### Plan Free (0/mes):
- ✅ 750 horas/mes
- ✅ PostgreSQL con 1 GB storage
- ❌ Servicio se duerme después de 15 min inactividad
- ❌ Cold starts (~30 segundos)

### Plan Starter ($7/mes por servicio):
- ✅ Siempre activo (no cold starts)
- ✅ Background jobs funcionan 24/7
- ✅ 1 GB RAM
- ✅ Mejor performance

### PostgreSQL Starter ($7/mes):
- ✅ 1 GB de storage
- ✅ Conexiones simultáneas ilimitadas
- ✅ Backups automáticos

**Costo total recomendado para producción:** ~$14-21/mes

---

## 🎉 ¡Deployment Exitoso!

Si llegaste hasta aquí, tu backend debería estar:

✅ Corriendo en `https://tu-servicio.onrender.com`
✅ Conectado a PostgreSQL
✅ Con CORS configurado correctamente
✅ Auto-deployando en cada push a `main`
✅ Documentación en `/docs`

### Próximos Pasos:

1. Conectar tu frontend a la URL del backend
2. Probar funcionalidad end-to-end
3. Configurar dominio personalizado (opcional)
4. Agregar monitoreo (Sentry, etc.)
5. Considerar upgrade a plan Starter para producción

---

## 📚 Recursos

- [Documentación Oficial de Render](https://render.com/docs)
- [FastAPI Deployment Guide](https://fastapi.tiangolo.com/deployment/)
- [PostgreSQL en Render](https://render.com/docs/databases)
- [Troubleshooting Render](https://render.com/docs/troubleshooting)

---

**¿Problemas?** Revisa los logs en Render Dashboard y consulta la sección de Troubleshooting arriba.
