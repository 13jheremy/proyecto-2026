# 🏍️ TALLER DE MOTOS - API DOCUMENTATION

## 📋 Índice
- [Información General](#información-general)
- [Autenticación](#autenticación)
- [Endpoints por Módulo](#endpoints-por-módulo)
- [Modelos de Datos](#modelos-de-datos)
- [Códigos de Estado](#códigos-de-estado)
- [Ejemplos de Uso](#ejemplos-de-uso)

## 🔧 Información General

### Base URL
```
http://localhost:8000/api/
```

### Formato de Respuesta
Todas las respuestas están en formato JSON y siguen la estructura estándar de Django REST Framework.

### Paginación
- **Clase**: `UsuarioPagination`
- **Tamaño por defecto**: 20 elementos por página
- **Parámetros**: `?page=1&page_size=20`

### Filtros Comunes
- `?activo=true/false` - Filtrar por estado activo
- `?eliminado=true/false` - Filtrar por estado eliminado
- `?search=texto` - Búsqueda en campos configurados
- `?ordering=campo` - Ordenar por campo

## 🔐 Autenticación

### JWT Authentication
El API utiliza JSON Web Tokens (JWT) para autenticación.

#### Obtener Token
```http
POST /api/auth/login/
Content-Type: application/json

{
    "correo_electronico": "usuario@ejemplo.com",
    "password": "contraseña"
}
```

**Respuesta:**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "user": {
        "id": 1,
        "correo_electronico": "usuario@ejemplo.com",
        "username": "usuario",
        "roles_activos": ["Administrador"]
    }
}
```

#### Renovar Token
```http
POST /api/auth/refresh/
Content-Type: application/json

{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

#### Usar Token
```http
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

## 📚 Endpoints por Módulo

### 👥 Gestión de Usuarios

#### Usuarios
- `GET /api/usuarios/` - Listar usuarios
- `POST /api/usuarios/` - Crear usuario
- `GET /api/usuarios/{id}/` - Obtener usuario específico
- `PUT /api/usuarios/{id}/` - Actualizar usuario completo
- `PATCH /api/usuarios/{id}/` - Actualizar usuario parcial
- `DELETE /api/usuarios/{id}/` - Soft delete del usuario
- `PATCH /api/usuarios/{id}/toggle_activo/` - Activar/desactivar usuario
- `PATCH /api/usuarios/{id}/soft_delete/` - Eliminación temporal
- `PATCH /api/usuarios/{id}/restore/` - Restaurar usuario eliminado
- `DELETE /api/usuarios/{id}/hard_delete/` - Eliminación permanente
- `POST /api/usuarios/{id}/cambiar_password/` - Cambiar contraseña
- `GET /api/usuarios/activos/` - Solo usuarios activos
- `GET /api/usuarios/eliminados/` - Solo usuarios eliminados

#### Personas
- `GET /api/personas/` - Listar personas
- `POST /api/personas/` - Crear persona
- `GET /api/personas/{id}/` - Obtener persona específica
- `PUT /api/personas/{id}/` - Actualizar persona
- `DELETE /api/personas/{id}/` - Eliminar persona
- `POST /api/personas/{id}/asociar_usuario/` - Asociar usuario existente
- `DELETE /api/personas/{id}/desasociar_usuario/` - Desasociar usuario
- `GET /api/personas/sin_usuario/` - Personas sin usuario asociado

#### Roles
- `GET /api/roles/` - Listar roles
- `POST /api/roles/` - Crear rol
- `GET /api/roles/{id}/` - Obtener rol específico
- `PUT /api/roles/{id}/` - Actualizar rol
- `DELETE /api/roles/{id}/` - Eliminar rol

### 🏷️ Catálogos

#### Categorías de Productos
- `GET /api/categorias/` - Listar categorías
- `POST /api/categorias/` - Crear categoría
- `GET /api/categorias/{id}/` - Obtener categoría
- `PUT /api/categorias/{id}/` - Actualizar categoría
- `DELETE /api/categorias/{id}/` - Eliminar categoría
- `GET /api/categorias/{id}/productos/` - Productos de la categoría
- `GET /api/categorias/activos/` - Solo categorías activas

#### Categorías de Servicios
- `GET /api/categorias-servicio/` - Listar categorías de servicios
- `POST /api/categorias-servicio/` - Crear categoría de servicio
- `GET /api/categorias-servicio/{id}/` - Obtener categoría de servicio
- `PUT /api/categorias-servicio/{id}/` - Actualizar categoría de servicio
- `DELETE /api/categorias-servicio/{id}/` - Eliminar categoría de servicio

#### Proveedores
- `GET /api/proveedores/` - Listar proveedores
- `POST /api/proveedores/` - Crear proveedor
- `GET /api/proveedores/{id}/` - Obtener proveedor
- `PUT /api/proveedores/{id}/` - Actualizar proveedor
- `DELETE /api/proveedores/{id}/` - Eliminar proveedor
- `GET /api/proveedores/con_productos/` - Proveedores con productos
- `GET /api/proveedores/{id}/productos/` - Productos del proveedor

### 📦 Productos y Servicios

#### Productos
- `GET /api/productos/` - Listar productos
- `POST /api/productos/` - Crear producto
- `GET /api/productos/{id}/` - Obtener producto
- `PUT /api/productos/{id}/` - Actualizar producto
- `DELETE /api/productos/{id}/` - Eliminar producto
- `PATCH /api/productos/{id}/toggle_activo/` - Activar/desactivar producto
- `GET /api/productos/stock_bajo/` - Productos con stock bajo
- `GET /api/productos/destacados/` - Productos destacados
- `PATCH /api/productos/{id}/toggle_destacado/` - Marcar/desmarcar destacado
- `PATCH /api/productos/{id}/actualizar_stock/` - Actualizar stock

#### Servicios
- `GET /api/servicios/` - Listar servicios
- `POST /api/servicios/` - Crear servicio
- `GET /api/servicios/{id}/` - Obtener servicio
- `PUT /api/servicios/{id}/` - Actualizar servicio
- `DELETE /api/servicios/{id}/` - Eliminar servicio
- `PATCH /api/servicios/{id}/toggle_activo/` - Activar/desactivar servicio

### 🏍️ Vehículos y Mantenimiento

#### Motos
- `GET /api/motos/` - Listar motos
- `POST /api/motos/` - Crear moto
- `GET /api/motos/{id}/` - Obtener moto
- `PUT /api/motos/{id}/` - Actualizar moto
- `DELETE /api/motos/{id}/` - Eliminar moto
- `GET /api/motos/{id}/mantenimientos/` - Mantenimientos de la moto
- `GET /api/motos/mis_motos/` - Motos del cliente autenticado

#### Mantenimientos
- `GET /api/mantenimientos/` - Listar mantenimientos
- `POST /api/mantenimientos/` - Crear mantenimiento
- `GET /api/mantenimientos/{id}/` - Obtener mantenimiento
- `PUT /api/mantenimientos/{id}/` - Actualizar mantenimiento
- `DELETE /api/mantenimientos/{id}/` - Eliminar mantenimiento
- `GET /api/mantenimientos/mis_mantenimientos/` - Mantenimientos del cliente
- `GET /api/mantenimientos/pendientes/` - Mantenimientos pendientes
- `GET /api/mantenimientos/en_proceso/` - Mantenimientos en proceso

#### Recordatorios
- `GET /api/recordatorios/` - Listar recordatorios
- `POST /api/recordatorios/` - Crear recordatorio
- `GET /api/recordatorios/{id}/` - Obtener recordatorio
- `PUT /api/recordatorios/{id}/` - Actualizar recordatorio
- `DELETE /api/recordatorios/{id}/` - Eliminar recordatorio
- `GET /api/recordatorios/proximos/` - Recordatorios próximos

### 💰 Ventas e Inventario

#### Ventas
- `GET /api/ventas/` - Listar ventas
- `POST /api/ventas/` - Crear venta
- `GET /api/ventas/{id}/` - Obtener venta
- `PUT /api/ventas/{id}/` - Actualizar venta
- `DELETE /api/ventas/{id}/` - Eliminar venta
- `GET /api/ventas/mis_ventas/` - Ventas del cliente

#### Movimientos de Inventario
- `GET /api/inventario-movimientos/` - Listar movimientos
- `POST /api/inventario-movimientos/` - Crear movimiento
- `GET /api/inventario-movimientos/{id}/` - Obtener movimiento
- `PUT /api/inventario-movimientos/{id}/` - Actualizar movimiento
- `DELETE /api/inventario-movimientos/{id}/` - Eliminar movimiento

### 🌐 Endpoints Públicos (Sin Autenticación)

#### Catálogo Público
- `GET /api/publico/productos/` - Catálogo público de productos
- `GET /api/publico/productos/destacados/` - Productos destacados públicos
- `GET /api/publico/categorias/` - Categorías públicas
- `GET /api/publico/categorias/{id}/productos/` - Productos de categoría pública

### 📊 Dashboard y Reportes

#### Dashboard
- `GET /api/dashboard/stats/` - Estadísticas del dashboard

#### Reportes
- `GET /api/reportes/ventas/` - Reporte de ventas por período

### 🔧 Sistema

#### Salud del Sistema
- `GET /api/health/` - Estado de salud del sistema

## 📋 Modelos de Datos

### Usuario
```json
{
    "id": 1,
    "correo_electronico": "usuario@ejemplo.com",
    "username": "usuario123",
    "first_name": "Juan",
    "last_name": "Pérez",
    "is_active": true,
    "date_joined": "2024-01-01T00:00:00Z",
    "roles": [
        {
            "id": 1,
            "rol": {
                "id": 1,
                "nombre": "Administrador"
            },
            "activo": true
        }
    ]
}
```

### Persona
```json
{
    "id": 1,
    "nombre": "Juan",
    "apellido": "Pérez",
    "cedula": "12345678",
    "telefono": "+591 70123456",
    "direccion": "Av. Ejemplo 123",
    "fecha_nacimiento": "1990-01-01",
    "usuario": 1
}
```

### Producto
```json
{
    "id": 1,
    "nombre": "Aceite Motor 20W-50",
    "codigo": "ACE001",
    "descripcion": "Aceite para motor de motocicleta",
    "categoria": {
        "id": 1,
        "nombre": "Lubricantes"
    },
    "proveedor": {
        "id": 1,
        "nombre": "Proveedor ABC"
    },
    "precio_compra": "25.00",
    "precio_venta": "35.00",
    "stock_minimo": 10,
    "stock_actual": 50,
    "activo": true,
    "destacado": false,
    "imagen": "https://res.cloudinary.com/..."
}
```

### Moto
```json
{
    "id": 1,
    "propietario": {
        "id": 1,
        "nombre_completo": "Juan Pérez"
    },
    "marca": "Honda",
    "modelo": "CB190R",
    "año": 2023,
    "placa": "ABC-123",
    "numero_chasis": "JH2MC4309LM000001",
    "numero_motor": "MC43E1000001",
    "color": "Rojo",
    "cilindrada": 184,
    "kilometraje": 5000,
    "activo": true
}
```

### Mantenimiento
```json
{
    "id": 1,
    "moto": {
        "id": 1,
        "placa": "ABC-123",
        "marca": "Honda",
        "modelo": "CB190R"
    },
    "fecha_ingreso": "2024-01-15T10:00:00Z",
    "fecha_entrega": null,
    "descripcion_problema": "Cambio de aceite y filtro",
    "diagnostico": "Mantenimiento preventivo",
    "estado": "en_proceso",
    "kilometraje_ingreso": 5000,
    "total": "150.00",
    "detalles": [
        {
            "id": 1,
            "servicio": {
                "id": 1,
                "nombre": "Cambio de aceite"
            },
            "precio": "100.00",
            "observaciones": ""
        }
    ]
}
```

## 📊 Códigos de Estado HTTP

- `200 OK` - Solicitud exitosa
- `201 Created` - Recurso creado exitosamente
- `204 No Content` - Solicitud exitosa sin contenido
- `400 Bad Request` - Datos inválidos
- `401 Unauthorized` - No autenticado
- `403 Forbidden` - Sin permisos
- `404 Not Found` - Recurso no encontrado
- `409 Conflict` - Conflicto de datos
- `500 Internal Server Error` - Error del servidor

## 💡 Ejemplos de Uso

### Crear Usuario Completo
```http
POST /api/usuarios/
Authorization: Bearer {token}
Content-Type: application/json

{
    "correo_electronico": "nuevo@ejemplo.com",
    "username": "nuevo_usuario",
    "password": "contraseña_segura",
    "first_name": "Nuevo",
    "last_name": "Usuario",
    "persona_data": {
        "nombre": "Nuevo",
        "apellido": "Usuario",
        "cedula": "87654321",
        "telefono": "+591 70987654",
        "direccion": "Calle Nueva 456",
        "fecha_nacimiento": "1985-05-15"
    },
    "roles": [1, 2]
}
```

### Crear Producto
```http
POST /api/productos/
Authorization: Bearer {token}
Content-Type: application/json

{
    "nombre": "Llanta Trasera 130/70-17",
    "codigo": "LLT001",
    "descripcion": "Llanta trasera para motocicleta deportiva",
    "categoria": 2,
    "proveedor": 1,
    "precio_compra": "180.00",
    "precio_venta": "250.00",
    "stock_minimo": 5,
    "stock_actual": 20,
    "activo": true,
    "destacado": true
}
```

### Registrar Mantenimiento
```http
POST /api/mantenimientos/
Authorization: Bearer {token}
Content-Type: application/json

{
    "moto": 1,
    "fecha_ingreso": "2024-01-20T09:00:00Z",
    "descripcion_problema": "Ruido en el motor y pérdida de potencia",
    "kilometraje_ingreso": 15000,
    "detalles": [
        {
            "servicio": 1,
            "precio": "150.00",
            "observaciones": "Cambio de aceite y filtro"
        },
        {
            "servicio": 2,
            "precio": "80.00",
            "observaciones": "Limpieza de carburador"
        }
    ]
}
```

### Filtros Avanzados
```http
GET /api/productos/?categoria=1&activo=true&search=aceite&ordering=-fecha_creacion&page=1&page_size=10
Authorization: Bearer {token}
```

### Dashboard Stats
```http
GET /api/dashboard/stats/
Authorization: Bearer {token}
```

**Respuesta:**
```json
{
    "total_usuarios": 25,
    "total_productos": 150,
    "total_motos": 80,
    "mantenimientos_pendientes": 12,
    "ventas_mes_actual": "15750.00",
    "productos_stock_bajo": 8
}
```

## 🔒 Permisos y Roles

### Roles Disponibles
- **Administrador**: Acceso completo a todos los endpoints
- **Empleado**: Acceso a gestión de productos, servicios, mantenimientos y ventas
- **Técnico**: Acceso a mantenimientos y servicios
- **Cliente**: Acceso limitado a sus propios datos (motos, mantenimientos, ventas)

### Matriz de Permisos

| Endpoint | Administrador | Empleado | Técnico | Cliente |
|----------|---------------|----------|---------|---------|
| Usuarios | ✅ CRUD | ❌ | ❌ | ❌ |
| Productos | ✅ CRUD | ✅ CRUD | 👁️ Read | 👁️ Read |
| Servicios | ✅ CRUD | ✅ CRUD | ✅ CRUD | 👁️ Read |
| Motos | ✅ CRUD | ✅ CRUD | 👁️ Read | 👁️ Propias |
| Mantenimientos | ✅ CRUD | ✅ CRUD | ✅ CRUD | 👁️ Propios |
| Ventas | ✅ CRUD | ✅ CRUD | ❌ | 👁️ Propias |

## 📝 Notas Importantes

1. **Autenticación Requerida**: Todos los endpoints requieren autenticación JWT excepto los marcados como públicos.

2. **Soft Delete**: La mayoría de modelos implementan eliminación suave (soft delete). Los registros eliminados no aparecen en listados normales pero pueden ser restaurados.

3. **Filtros por Usuario**: Los clientes solo pueden ver sus propios registros (motos, mantenimientos, ventas).

4. **Validaciones**: Todos los endpoints incluyen validaciones robustas y mensajes de error descriptivos.

5. **Logging**: Todas las operaciones importantes son registradas para auditoría.

6. **Rate Limiting**: Se aplican límites de velocidad para prevenir abuso:
   - Usuarios anónimos: 100 requests/hora
   - Usuarios autenticados: 1000 requests/hora
   - Login: 5 intentos/minuto

7. **Paginación**: Todos los listados están paginados. Use los parámetros `page` y `page_size` para navegar.

8. **Búsqueda**: Use el parámetro `search` para buscar en múltiples campos configurados por modelo.

9. **Ordenamiento**: Use el parámetro `ordering` para ordenar resultados. Prefije con `-` para orden descendente.

10. **Campos de Auditoría**: Todos los modelos incluyen `fecha_creacion` y `fecha_actualizacion` automáticas.
