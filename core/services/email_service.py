# core/services/email_service.py
"""
Servicio de envío de correos asíncrono para evitar bloqueos en Gunicorn.
Utiliza threading para enviar emails sin bloquear el worker principal.
"""

import threading
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_email_async(**kwargs):
    """
    Envía un correo de forma asíncrona usando threading.
    
    Args:
        subject: Asunto del correo
        message: Cuerpo del correo
        from_email: Email remitente (por defecto: DEFAULT_FROM_EMAIL)
        recipient_list: Lista de destinatarios
        fail_silently: Si debe fallar silenciosamente (por defecto: False)
    
    Returns:
        None (ejecuta en background)
    
    Ejemplo de uso:
        send_email_async(
            subject="Recuperación de Contraseña",
            message="Haz clic aquí: ...",
            recipient_list=["user@ejemplo.com"],
            fail_silently=False
        )
    """
    
    def _send():
        try:
            # Establecer from_email por defecto si no se proporciona
            kwargs.setdefault('from_email', settings.DEFAULT_FROM_EMAIL)
            kwargs.setdefault('fail_silently', False)
            
            send_mail(**kwargs)
            logger.info(f"Email enviado a {kwargs.get('recipient_list')}")
            
        except Exception as e:
            logger.error(f"Error enviando email a {kwargs.get('recipient_list')}: {str(e)}")
    
    # Crear y ejecutar thread en background
    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def send_password_reset_email(user, reset_link):
    """
    Envía un correo de recuperación de contraseña de forma asíncrona.
    
    Args:
        user: Objeto de usuario de Django
        reset_link: URL del enlace de recuperación
    """
    
    message = f"""
Hola {user.username},

Has solicitado recuperar tu contraseña para el sistema de JIC Taller y Repuestos de Motos.

Usa este enlace para cambiar tu contraseña:
{reset_link}

Este enlace expirará en 24 horas por seguridad.

Si no solicitaste este cambio, puedes ignorar este correo.

Saludos,
Equipo de JIC Taller y Repuestos de Motos
    """
    
    send_email_async(
        subject="Recuperación de Contraseña - JIC Taller y Repuestos de Motos",
        message=message,
        recipient_list=[user.correo_electronico],
        fail_silently=False
    )


def send_welcome_email(user, password=None):
    """
    Envía un correo de bienvenida de forma asíncrona.
    
    Args:
        user: Objeto de usuario de Django
        password: Contraseña temporal (si aplica)
    """
    
    password_info = f"\nContraseña temporal: {password}\n" if password else ""
    
    message = f"""
Hola {user.username},

¡Bienvenido a JIC Taller y Repuestos de Motos!

Tu cuenta ha sido creada exitosamente.

Datos de acceso:
Email: {user.correo_electronico}
{password_info}

Si tienes preguntas, contacta a nuestro equipo de soporte.

Saludos,
Equipo de JIC Taller y Repuestos de Motos
    """
    
    send_email_async(
        subject="Bienvenido a JIC Taller y Repuestos de Motos",
        message=message,
        recipient_list=[user.correo_electronico],
        fail_silently=False
    )
