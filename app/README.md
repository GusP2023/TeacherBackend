# 🎵 ProfesorSYS - Backend API

Sistema de gestión para profesores de música - API REST con FastAPI.

---

## 📋 **Características**

- ✅ API RESTful con FastAPI
- ✅ PostgreSQL + SQLAlchemy 2.0+
- ✅ Autenticación JWT
- ✅ Validación con Pydantic
- ✅ CORS configurado
- ✅ Documentación automática (Swagger)
- ✅ Arquitectura modular

---

## 🏗️ **Arquitectura de Datos**

```
Teacher (Profesor)
  ↓
Student (Alumno - datos básicos)
  ↓
Enrollment (Inscripción a un instrumento)
  ↓
Schedule (Horario recurrente - template)
  ↓
Class (Clase específica en fecha concreta)
  ↓
Attendance (Asistencia)
```

---

## 🚀 **Instalación**

### **1. Requisitos previos**
- Python 3.11+
- PostgreSQL 14+
- pip

### **2. Clonar repositorio**
```bash
cd backend
```

### **3. Crear entorno virtual**
```bash
python -m venv venv

# Activar (Linux/Mac)
source venv/bin/activate

# Activar (Windows)
venv\Scripts\activate
```

### **4. Instalar dependencias**
```bash
pip install -r requirements.txt
```

### **5. Configurar variables de entorno**
```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar .env con tus credenciales
nano .env  # o usa tu editor favorito
```

### **6. Crear la base de datos**
```bash
# En PostgreSQL, crear la base de datos
psql -U postgres
CREATE DATABASE music_school;
\q
```

### **7. Crear las tablas**
```bash
python -m app.core.init_db
```

Deberías ver:
```
🔄 Creando tablas en la base de datos...
📍 Conectando a: localhost:5432/music_school
✅ ¡Tablas creadas exitosamente!

📋 Tablas creadas:
   - teachers
   - instruments
   - students
   - enrollments
   - schedules
   - classes
   - attendances
```

---

## 🎮 **Uso**

### **Iniciar el servidor**
```bash
# Modo desarrollo (auto-reload)
uvicorn app.main:app --reload

# Producción
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

El servidor estará disponible en: **http://localhost:8000**

### **Documentación**
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### **Health Check**
```bash
curl http://localhost:8000/health
```

---

## 🛠️ **Comandos útiles**

### **Gestión de base de datos**
```bash
# Crear tablas
python -m app.core.init_db

# Eliminar todas las tablas (⚠️ CUIDADO)
python -m app.core.init_db drop

# Reiniciar BD (eliminar + crear)
python -m app.core.init_db reset
```

### **Testing**
```bash
# TODO: Implementar tests
pytest
```

---

## 📁 **Estructura del Proyecto**

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # Aplicación FastAPI principal
│   ├── core/                    # Configuración y utilidades
│   │   ├── __init__.py
│   │   ├── config.py           # Configuración (settings)
│   │   ├── database.py         # Conexión a BD
│   │   └── init_db.py          # Script crear tablas
│   ├── models/                  # Modelos SQLAlchemy
│   │   ├── __init__.py
│   │   ├── base.py             # Base y mixins
│   │   ├── teacher.py          # Modelo Teacher
│   │   ├── student.py          # Modelo Student
│   │   ├── instrument.py       # Modelo Instrument
│   │   ├── enrollment.py       # Modelo Enrollment
│   │   ├── schedule.py         # Modelo Schedule
│   │   ├── class_model.py      # Modelo Class
│   │   └── attendance.py       # Modelo Attendance
│   ├── schemas/                 # Schemas Pydantic (TODO)
│   └── api/                     # Endpoints (TODO)
│       └── v1/
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🔑 **Modelos Principales**

### **Teacher** (Profesor)
- Email, password, nombre
- Tarifas: individual y grupal
- Gestiona alumnos e inscripciones

### **Student** (Alumno)
- Datos básicos: nombre, contacto, cumpleaños
- Notas del profesor
- Puede tener múltiples inscripciones

### **Instrument** (Instrumento)
- Catálogo: Piano, Guitarra, Canto, etc.
- Soft-delete (no se eliminan físicamente)

### **Enrollment** (Inscripción)
- Alumno + Instrumento
- Estado: active, suspended, withdrawn
- Nivel: Elemental, Nivel1-8
- Créditos de recuperación

### **Schedule** (Horario recurrente)
- Template: "Martes 16:00"
- Genera clases automáticamente
- Vigencia: desde/hasta

### **Class** (Clase concreta)
- Fecha específica: "21-enero-2025 16:00"
- Estado: scheduled, completed, cancelled
- Tipo: regular, recovery
- Formato: individual, group

### **Attendance** (Asistencia)
- Estado: present, absent, license
- Relación 1:1 con Class
- Afecta créditos y cobros

---

## 💰 **Lógica de Negocio**

### **Sistema de Créditos**
- `license` → +1 crédito
- Usar recuperación → -1 crédito
- Constraint: créditos ≥ 0

### **Cálculo de Ingresos**
Se cobran clases con:
- ✅ `attendance.status = present`
- ✅ `attendance.status = absent`

NO se cobran:
- ❌ `attendance.status = license`
- ❌ `class.status = cancelled`
- ❌ Sin attendance marcado

### **Tarifas**
- **Individual**: `tariff_individual`
- **Grupal**: `tariff_group × cantidad_alumnos`

---

## 🔧 **Próximos Pasos**

- [ ] Crear schemas Pydantic
- [ ] Implementar endpoints CRUD
- [ ] Agregar autenticación JWT
- [ ] Crear job para generar clases mes a mes
- [ ] Implementar lógica de suspensión/cancelación
- [ ] Tests unitarios e integración
- [ ] Dockerizar aplicación

---

## 📝 **Variables de Entorno**

Ver `.env.example` para la lista completa de variables configurables.

Variables principales:
- `DATABASE_URL`: Conexión a PostgreSQL
- `SECRET_KEY`: Clave para JWT (cambiar en producción)
- `ENVIRONMENT`: development, staging, production
- `BACKEND_CORS_ORIGINS`: URLs permitidas para CORS

---

## 🐛 **Troubleshooting**

### **Error: "Could not connect to database"**
```bash
# Verificar que PostgreSQL esté corriendo
sudo systemctl status postgresql

# Verificar credenciales en .env
psql -U postgres -d music_school
```

### **Error: "Table already exists"**
```bash
# Reiniciar BD
python -m app.core.init_db reset
```

### **Error: "Import error"**
```bash
# Asegúrate de estar en el entorno virtual
source venv/bin/activate

# Reinstalar dependencias
pip install -r requirements.txt
```

---

## 📄 **Licencia**

Proyecto privado - Todos los derechos reservados.

---

## 👨‍💻 **Autor**

ProfesorSYS - Sistema de gestión para profesores de música