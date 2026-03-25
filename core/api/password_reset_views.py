# core/api/password_reset_views.py
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class PasswordResetRequestView(APIView):
    """
    Vista para solicitar recuperación de contraseña.
    Disponible para todos los usuarios del sistema.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response(
                {"error": "El correo electrónico es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(correo_electronico=email)

            # Verificar que el usuario esté activo
            if not user.is_active:
                return Response(
                    {"error": "Cuenta inactiva. Contacta al administrador."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        except User.DoesNotExist:
            # Por seguridad, no revelamos si el usuario existe o no
            return Response(
                {
                    "message": "Si el correo existe en nuestro sistema, recibirás un enlace de recuperación."
                },
                status=status.HTTP_200_OK,
            )

        # Generar token y uid
        token = PasswordResetTokenGenerator().make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        # Crear enlace de recuperación
        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        reset_link = f"{frontend_url}/reset-password/{uid}/{token}"

        # Enviar correo
        try:
            send_mail(
                subject="Recuperación de Contraseña - JIC Taller y Repuestos de Motos",
                message=f"""
Hola {user.username},

Has solicitado recuperar tu contraseña para el sistema de JIC Taller y Repuestos de Motos.

Usa este enlace para cambiar tu contraseña:
{reset_link}

Este enlace expirará en 24 horas por seguridad.

Si no solicitaste este cambio, puedes ignorar este correo.

Saludos,
Equipo de JIC Taller y Repuestos de Motos
                """,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.correo_electronico],
                fail_silently=False,
            )

            logger.info(f"Password reset email sent to {email}")

        except Exception as e:
            logger.error(f"Error sending password reset email to {email}: {str(e)}")
            return Response(
                {"error": "Error al enviar el correo. Intenta nuevamente más tarde."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "message": "Si el correo existe en nuestro sistema, recibirás un enlace de recuperación."
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """
    Vista para confirmar y cambiar la contraseña usando el token.
    Disponible para todos los usuarios del sistema.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        uid = request.data.get("uid")
        token = request.data.get("token")
        new_password = request.data.get("new_password")

        if not all([uid, token, new_password]):
            return Response(
                {"error": "Todos los campos son requeridos"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validar longitud de contraseña
        if len(new_password) < 8:
            return Response(
                {"error": "La contraseña debe tener al menos 8 caracteres"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Decodificar uid y obtener usuario
            uid_decoded = urlsafe_base64_decode(uid).decode()
            user = User.objects.get(pk=uid_decoded)

            # Verificar que el usuario esté activo
            if not user.is_active:
                return Response(
                    {"error": "Cuenta inactiva. Contacta al administrador."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"error": "Token inválido"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Verificar token
        if not PasswordResetTokenGenerator().check_token(user, token):
            return Response(
                {"error": "Token inválido o expirado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Cambiar contraseña
        try:
            user.set_password(new_password)
            user.save()

            logger.info(f"Password reset successful for user {user.correo_electronico}")

            return Response(
                {
                    "message": "Contraseña actualizada con éxito. Ya puedes iniciar sesión con tu nueva contraseña."
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.error(
                f"Error updating password for user {user.correo_electronico}: {str(e)}"
            )
            return Response(
                {"error": "Error al actualizar la contraseña. Intenta nuevamente."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
