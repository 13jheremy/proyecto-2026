#!/usr/bin/env python
"""
Script de prueba para enviar notificaciones de mantenimiento y cambio de aceite
usando Firebase Cloud Messaging
"""
import os
import sys
import django

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taller_motos.settings')
django.setup()

from core.models import Usuario
from core.services.notification_service import send_maintenance_notification, send_oil_change_notification


def test_notifications():
    """Función para probar el envío de notificaciones"""

    print("🔔 PRUEBA DE NOTIFICACIONES PUSH CON FIREBASE")
    print("=" * 50)

    # Buscar usuarios con tokens FCM
    usuarios_con_token = Usuario.objects.filter(
        fcm_token__isnull=False,
        is_active=True
    ).exclude(fcm_token='')

    if not usuarios_con_token.exists():
        print("❌ No se encontraron usuarios con tokens FCM registrados")
        print("💡 Los usuarios deben abrir la app Flutter al menos una vez para registrar su token")
        return

    print(f"✅ Encontrados {usuarios_con_token.count()} usuarios con tokens FCM")

    # Mostrar usuarios disponibles
    print("\n👥 Usuarios disponibles:")
    for i, usuario in enumerate(usuarios_con_token, 1):
        print(f"{i}. {usuario.correo_electronico} (ID: {usuario.id})")

    # Seleccionar usuario para pruebas
    if len(usuarios_con_token) == 1:
        usuario_seleccionado = usuarios_con_token.first()
        print(f"\n🎯 Usando usuario: {usuario_seleccionado.correo_electronico}")
    else:
        try:
            seleccion = input(f"\nSelecciona un usuario (1-{len(usuarios_con_token)}) o presiona Enter para usar el primero: ").strip()
            if seleccion and seleccion.isdigit():
                idx = int(seleccion) - 1
                if 0 <= idx < len(usuarios_con_token):
                    usuario_seleccionado = usuarios_con_token[idx]
                else:
                    usuario_seleccionado = usuarios_con_token.first()
            else:
                usuario_seleccionado = usuarios_con_token.first()
        except:
            usuario_seleccionado = usuarios_con_token.first()

        print(f"🎯 Usando usuario: {usuario_seleccionado.correo_electronico}")

    # Probar notificación de mantenimiento
    print("\n🔧 Probando notificación de mantenimiento...")
    success1 = send_maintenance_notification(
        user_token=usuario_seleccionado.fcm_token,
        moto_info="Honda CG 150 - ABC123",
        fecha="15/01/2025"
    )

    if success1:
        print("✅ Notificación de mantenimiento enviada exitosamente")
    else:
        print("❌ Error al enviar notificación de mantenimiento")

    # Probar notificación de cambio de aceite
    print("\n🛢️ Probando notificación de cambio de aceite...")
    success2 = send_oil_change_notification(
        user_token=usuario_seleccionado.fcm_token,
        moto_info="Honda CG 150 - ABC123",
        kilometraje=8500
    )

    if success2:
        print("✅ Notificación de cambio de aceite enviada exitosamente")
    else:
        print("❌ Error al enviar notificación de cambio de aceite")

    # Resumen
    print("\n" + "=" * 50)
    print("📊 RESUMEN DE PRUEBA:")
    print(f"Usuario: {usuario_seleccionado.correo_electronico}")
    print(f"Mantenimiento: {'✅ Éxito' if success1 else '❌ Fallo'}")
    print(f"Cambio de aceite: {'✅ Éxito' if success2 else '❌ Fallo'}")

    if success1 and success2:
        print("\n🎉 ¡Todas las notificaciones se enviaron correctamente!")
        print("📱 Revisa tu dispositivo móvil para ver las notificaciones")
    else:
        print("\n⚠️ Algunas notificaciones fallaron. Revisa los logs para más detalles.")


def test_with_custom_data():
    """Función para probar con datos personalizados"""

    print("\n🔧 PRUEBA CON DATOS PERSONALIZADOS")
    print("=" * 50)

    usuarios_con_token = Usuario.objects.filter(
        fcm_token__isnull=False,
        is_active=True
    ).exclude(fcm_token='')

    if not usuarios_con_token.exists():
        print("❌ No hay usuarios con tokens FCM")
        return

    usuario = usuarios_con_token.first()

    # Datos de ejemplo
    motos_ejemplo = [
        {"marca": "Honda", "modelo": "CG 150", "placa": "ABC123", "fecha": "15/01/2025"},
        {"marca": "Yamaha", "modelo": "FZ 25", "placa": "XYZ789", "fecha": "20/01/2025"},
        {"marca": "Suzuki", "modelo": "GN 125", "placa": "DEF456", "fecha": "25/01/2025"},
    ]

    print(f"Enviando notificaciones de prueba a: {usuario.correo_electronico}")

    for moto in motos_ejemplo:
        moto_info = f"{moto['marca']} {moto['modelo']} - {moto['placa']}"

        # Notificación de mantenimiento
        success = send_maintenance_notification(
            user_token=usuario.fcm_token,
            moto_info=moto_info,
            fecha=moto['fecha']
        )

        if success:
            print(f"✅ Mantenimiento enviado: {moto_info}")
        else:
            print(f"❌ Error en mantenimiento: {moto_info}")

        # Notificación de cambio de aceite (kilometraje aleatorio)
        import random
        kilometraje = random.randint(3000, 10000)

        success = send_oil_change_notification(
            user_token=usuario.fcm_token,
            moto_info=moto_info,
            kilometraje=kilometraje
        )

        if success:
            print(f"✅ Cambio de aceite enviado: {moto_info} ({kilometraje} km)")
        else:
            print(f"❌ Error en cambio de aceite: {moto_info}")


if __name__ == "__main__":
    print("🚀 Iniciando pruebas de notificaciones...")

    # Ejecutar prueba básica
    test_notifications()

    # Preguntar si quiere prueba con datos personalizados
    try:
        respuesta = input("\n¿Quieres probar con datos personalizados? (s/n): ").strip().lower()
        if respuesta in ['s', 'si', 'yes', 'y']:
            test_with_custom_data()
    except:
        pass

    print("\n🏁 Pruebas completadas!")
    print("💡 Recuerda que las notificaciones solo llegan si la app Flutter está cerrada o en segundo plano")