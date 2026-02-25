# 🔔 Sistema de Notificaciones Push - Guía Simplificada

## 📋 Configuración Básica

### 1. Firebase Setup

1. **Crear proyecto Firebase**:
   - Ve a [Firebase Console](https://console.firebase.google.com/)
   - Crea un nuevo proyecto o usa uno existente
   - Habilita Cloud Messaging

2. **Generar Service Account Key**:
   - Ve a Project Settings > Service Accounts
   - Click "Generate new private key"
   - Descarga el archivo JSON
   - Renómbralo a `firebase-service-account.json`
   - Colócalo en `backend2/taller_motos/core/api/`

3. **Configurar variables de entorno** (opcional):
   ```bash
   # En .env
   FIREBASE_CREDENTIALS_PATH=D:\ruta\completa\firebase-service-account.json
   ```

### 2. Instalar Dependencias

```bash
cd backend2/taller_motos
pip install -r requirements.txt
```

## 🚀 Ejecutar el Sistema

### 1. Servidor Django
```bash
python manage.py runserver
```

## 🧪 Probar Notificaciones

### Opción 1: Script Interactivo
```bash
python test_notifications.py
```

### Opción 2: Prueba Rápida desde Django Shell
```bash
python manage.py shell -c "from quick_test import test_notifications; test_notifications()"
```

### Opción 3: API Endpoint de Prueba
```bash
# Probar mantenimiento y cambio de aceite
POST /api/notifications/test-maintenance/
{
  "user_id": 1,
  "moto_info": "Honda CG 150 - ABC123",
  "fecha_mantenimiento": "15/01/2025",
  "kilometraje": 8500
}
```

## 📱 Uso del Sistema

### Enviar notificaciones desde el backend:

```python
from core.services.notification_service import send_maintenance_notification, send_oil_change_notification

# Notificación de mantenimiento próximo
success = send_maintenance_notification(
    user_token="token_fcm_del_usuario",
    moto_info="Honda CG 150 - ABC123",
    fecha="15/01/2025"
)

# Notificación de cambio de aceite
success = send_oil_change_notification(
    user_token="token_fcm_del_usuario",
    moto_info="Honda CG 150 - ABC123",
    kilometraje=8500
)

# Notificación básica personalizada
from core.services.notification_service import send_simple_notification
success = send_simple_notification(
    user_token="token_fcm_del_usuario",
    title="Título personalizado",
    body="Mensaje personalizado",
    data={"type": "custom", "action": "view"}
)
```

### API Endpoints:

```bash
# Notificación básica
POST /api/notifications/send/
{
  "user_id": 1,
  "title": "Mi Notificación",
  "body": "Mensaje personalizado",
  "data": {"type": "info"}
}

# Prueba específica de mantenimiento y aceite
POST /api/notifications/test-maintenance/
{
  "user_id": 1,
  "moto_info": "Honda CG 150 - ABC123",
  "fecha_mantenimiento": "15/01/2025",
  "kilometraje": 8500
}
```

## 📱 App Flutter

La app Flutter ya está configurada para:
- ✅ Recibir notificaciones push
- ✅ Mostrar notificaciones locales
- ✅ Manejar clics en notificaciones
- ✅ Actualizar tokens FCM automáticamente

## 🐛 Troubleshooting

### Error: "Firebase not initialized"
- Verifica que `firebase-service-account.json` existe en `core/api/`
- Revisa que las credenciales son válidas

### Error: "No FCM token"
- Los usuarios deben abrir la app Flutter primero
- El token se envía automáticamente al backend vía `/me/`

### Notificaciones no llegan:
- Verifica que el token FCM es válido
- Comprueba los logs del servidor Django
- Asegúrate que la app Flutter tiene permisos de notificación

## 📝 Estructura Simplificada

### Token FCM en Usuario:
```python
usuario.fcm_token = "token_del_dispositivo"
usuario.save()
```

### Payload básico de notificación:
```json
{
  "notification": {
    "title": "Mi Título",
    "body": "Mi mensaje"
  },
  "data": {
    "type": "custom",
    "action": "view"
  }
}
```

## 🎯 Funciones Disponibles

- `send_simple_notification()` - Notificación básica
- `send_maintenance_notification()` - Notificación de mantenimiento
- `send_oil_change_notification()` - Notificación de cambio de aceite

**Sistema simplificado y funcional sin complejidades innecesarias.**
