#!/usr/bin/env python
"""
Prueba rápida de notificaciones desde Django shell
Ejecutar con: python manage.py shell -c "from quick_test import test_notifications; test_notifications()"
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taller_motos.settings')
django.setup()

from core.models import Usuario
from core.services.notification_service import send_maintenance_notification, send_oil_change_notification


def test_notifications():
    """Función de prueba rápida para notificaciones"""

    print("🔔 PRUEBA RÁPIDA DE NOTIFICACIONES")
    print("=" * 40)

    # Buscar primer usuario con token FCM
    usuario = Usuario.objects.filter(
        fcm_token__isnull=False,
        is_active=True
    ).exclude(fcm_token='').first()

    if not usuario:
        print("❌ No hay usuarios con tokens FCM registrados")
        print("💡 Los usuarios deben abrir la app Flutter primero")
        return

    print(f"✅ Usuario encontrado: {usuario.correo_electronico}")
    print(f"📱 Token FCM: {usuario.fcm_token[:20]}...")

    # Probar mantenimiento
    print("\n🔧 Enviando notificación de mantenimiento...")
    success1 = send_maintenance_notification(
        user_token=usuario.fcm_token,
        moto_info="Honda CG 150 - ABC123",
        fecha="15/01/2025"
    )

    print(f"Resultado mantenimiento: {'✅ Éxito' if success1 else '❌ Fallo'}")

    # Probar cambio de aceite
    print("\n🛢️ Enviando notificación de cambio de aceite...")
    success2 = send_oil_change_notification(
        user_token=usuario.fcm_token,
        moto_info="Honda CG 150 - ABC123",
        kilometraje=8500
    )

    print(f"Resultado cambio de aceite: {'✅ Éxito' if success2 else '❌ Fallo'}")

    print("\n" + "=" * 40)
    if success1 and success2:
        print("🎉 ¡Todas las notificaciones enviadas correctamente!")
        print("📱 Revisa tu dispositivo móvil")
    else:
        print("⚠️ Algunas notificaciones fallaron")


def test_multiple_users():
    """Probar con múltiples usuarios"""

    print("👥 PRUEBA CON MÚLTIPLES USUARIOS")
    print("=" * 40)

    usuarios = Usuario.objects.filter(
        fcm_token__isnull=False,
        is_active=True
    ).exclude(fcm_token='')[:3]  # Máximo 3 usuarios

    if not usuarios:
        print("❌ No hay usuarios con tokens FCM")
        return

    for usuario in usuarios:
        print(f"\n📤 Enviando a: {usuario.correo_electronico}")

        # Mantenimiento
        success = send_maintenance_notification(
            user_token=usuario.fcm_token,
            moto_info="Test Moto - TEST123",
            fecha="20/01/2025"
        )
        print(f"  🔧 Mantenimiento: {'✅' if success else '❌'}")

        # Cambio de aceite
        success = send_oil_change_notification(
            user_token=usuario.fcm_token,
            moto_info="Test Moto - TEST123",
            kilometraje=5000
        )
        print(f"  🛢️ Cambio aceite: {'✅' if success else '❌'}")


if __name__ == "__main__":
    test_notifications()