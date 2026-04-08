#!/usr/bin/env python
"""
Script para probar la configuración de email en Django.
Uso: python manage.py shell < test_email_config.py
"""

from django.conf import settings
from django.core.mail import send_mail

print("\n" + "="*60)
print("EMAIL CONFIGURATION TEST")
print("="*60)

# Verificar configuración
config = {
    'EMAIL_BACKEND': getattr(settings, 'EMAIL_BACKEND', 'No configurado'),
    'EMAIL_HOST': getattr(settings, 'EMAIL_HOST', 'No configurado'),
    'EMAIL_PORT': getattr(settings, 'EMAIL_PORT', 'No configurado'),
    'EMAIL_USE_TLS': getattr(settings, 'EMAIL_USE_TLS', 'No configurado'),
    'EMAIL_HOST_USER': getattr(settings, 'EMAIL_HOST_USER', 'No configurado'),
    'EMAIL_HOST_PASSWORD': '***OCULTO***' if getattr(settings, 'EMAIL_HOST_PASSWORD', '') else 'No configurado',
    'DEFAULT_FROM_EMAIL': getattr(settings, 'DEFAULT_FROM_EMAIL', 'No configurado'),
}

for key, value in config.items():
    status = "✓" if value != 'No configurado' and value else "✗"
    print(f"{status} {key}: {value}")

print("\n" + "-"*60)
print("VALIDACIÓN DE CONFIGURACIÓN")
print("-"*60)

required = ['EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'EMAIL_PORT']
missing = []

for setting in required:
    value = getattr(settings, setting, '')
    if not value:
        missing.append(setting)

if missing:
    print(f"\n✗ ERROR: Faltan variables de entorno:")
    for var in missing:
        print(f"  - {var}")
    print("\n⚠️  SOLUCIÓN: Configura estas variables en Render:")
    print("  1. Ve a tu servicio en Render")
    print("  2. Environment → Add Environment Variable")
    print("  3. Agrega:")
    print("     EMAIL_HOST=smtp.gmail.com")
    print("     EMAIL_PORT=587")
    print("     EMAIL_USE_TLS=True")
    print("     EMAIL_HOST_USER=tu@gmail.com")
    print("     EMAIL_HOST_PASSWORD=tu_contraseña_app")
    print("     DEFAULT_FROM_EMAIL=tu@gmail.com")
else:
    print("\n✓ Todas las configuraciones están presentes")
    print("\nIntentando enviar email de prueba...")
    
    try:
        result = send_mail(
            subject='Test Email',
            message='Este es un email de prueba',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=['test@example.com'],
            fail_silently=False,
        )
        print(f"✓ Email enviado exitosamente (resultado: {result})")
    except Exception as e:
        print(f"✗ Error al enviar email: {str(e)}")

print("\n" + "="*60)
