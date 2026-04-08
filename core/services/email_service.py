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


def _validate_email_config():
    """Valida que la configuración de email sea correcta."""
    required_settings = ['EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD']
    missing = []
    
    for setting in required_settings:
        value = getattr(settings, setting, '')
        if not value or value == '':
            missing.append(setting)
    
    if missing:
        logger.error(f"Email configuration incomplete. Missing: {', '.join(missing)}")
        return False
    
    return True


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
            # Validar configuración de email
            if not _validate_email_config():
                logger.error(f"Email config invalid. Cannot send email to {kwargs.get('recipient_list')}")
                return
            
            # Establecer from_email por defecto si no se proporciona
            kwargs.setdefault('from_email', settings.DEFAULT_FROM_EMAIL)
            kwargs.setdefault('fail_silently', False)
            
            send_mail(**kwargs)
            logger.info(f"✓ Email sent successfully to {kwargs.get('recipient_list')}")
            
        except Exception as e:
            logger.error(f"✗ Error sending email to {kwargs.get('recipient_list')}: {str(e)}", exc_info=True)
    
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
    
    if not user or not user.correo_electronico:
        logger.error(f"Cannot send password reset email: Invalid user or email")
        return
    
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
    
    logger.info(f"📧 Queuing password reset email for {user.correo_electronico}")
    
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
    
    if not user or not user.correo_electronico:
        logger.error(f"Cannot send welcome email: Invalid user or email")
        return
    
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
    
    logger.info(f"📧 Queuing welcome email for {user.correo_electronico}")
    
    send_email_async(
        subject="Bienvenido a JIC Taller y Repuestos de Motos",
        message=message,
        recipient_list=[user.correo_electronico],
        fail_silently=False
    )

