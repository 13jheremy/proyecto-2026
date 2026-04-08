# 🔧 DEBUG PASSWORD RESET - GUÍA DE SOLUCIÓN DE PROBLEMAS

## ❌ Problema: "Error al procesar la solicitud. Intenta nuevamente."

El error ocurre cuando el frontend recibe una respuesta que no tiene la estructura esperada.

---

## 🔍 PASO 1: Verificar configuración de email en Render

### En Render Dashboard:
1. Ve a tu servicio backend
2. Haz clic en **Environment**
3. Verifica que estas variables estén presentes:

```
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=tu_correo@gmail.com
EMAIL_HOST_PASSWORD=tu_contraseña_app
DEFAULT_FROM_EMAIL=tu_correo@gmail.com
FRONTEND_URL=https://frontend-proyecto-2026.vercel.app
```

Si faltan, **agregalas ahora** y espera el redeploy (~2 min).

---

## 🔍 PASO 2: Verificar usuario en BD

Ejecuta el script de debug en Render:

### Opción A: Usando Render Shell
1. En Render Dashboard → Backend Service → Shell
2. Ejecuta:
```bash
python manage.py shell < debug_password_reset.py
```

###  Opción B: En tu máquina local (si tienes acceso a BD)
```bash
cd proyecto-2026
python manage.py shell < debug_password_reset.py
```

**Qué buscar en la salida:**
- ✓ EMAIL_BACKEND debe mostrar un valor (no "Not set")
- ✓ Debe haber usuarios en la BD
- ✓ El usuario debe tener `Active: True`

---

## 📝 PASO 3: Verificar los logs en Render

### En Render Dashboard:
1. Ve a tu servicio backend
2. Haz clic en **Logs**
3. Filtra por "password" o "email"
4. Busca líneas con:
   - `✓ Password reset email queued for ...` (éxito)
   - `✗ Error...` (error específico)

**Si ves un error específico, cópialo aquí** para diagnóstico.

---

## 🧪 PASO 4: Hacer un test manual

### En tu máquina local:
```bash
cd proyecto-2026

# Crear cliente API
python manage.py shell

# Luego ejecuta esto en la consola Python:
from rest_framework.test import APIClient
from django.conf import settings

client = APIClient()

# Test del endpoint
response = client.post(
    'http://127.0.0.1:8000/api/password-reset/',
    {'email': 'usuario@ejemplo.com'},
    format='json'
)

print(f"Status: {response.status_code}")
print(f"Response: {response.data}")
```

---

## 🐛 Errores comunes y soluciones

### "Usuario no encontrado"
- ✓ Asegúrate de que el email existe exactamente como está en la BD
- ✓ El campo debe ser `correo_electronico` (no `email`)

### "Cuenta inactiva"
- ✓ El usuario debe tener `is_active=True`

### "Error de mail"
- ✓ Las credenciales de Gmail son incorrectas
- ✓ No usaste una "contraseña de app" (sólo funciona con esa)

### "Email no llega"
- ✓ Revisa spam/correo no deseado
- ✓ Verifica que el FROM_EMAIL sea el mismo que EMAIL_HOST_USER

---

## ✅ Checklist final

- [ ] Variables de entorno configuradas en Render
- [ ] Backend redeploy completado (~2 min)
- [ ] Usuario existe en BD con correo correcto
- [ ] Usuario tiene `is_active=True`
- [ ] Gmail tiene contraseña de app configurada
- [ ] FRONTEND_URL apunta a Vercel

---

## 💡 Si todo falla:

Corre estos comandos en Render Shell:

```bash
# Ver configuración
python manage.py shell < test_email_config.py

# Ver usuarios
python manage.py shell < debug_password_reset.py

# Ver logs completos
tail -f logs/api.log
```

Copia toda la salida y comparte para debugging.
