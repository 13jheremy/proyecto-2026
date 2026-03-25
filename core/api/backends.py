# =======================================
# BACKEND DE AUTENTICACIÓN POR EMAIL
# =======================================
import logging
from django.contrib.auth.backends import BaseBackend
from core.models import Usuario


class EmailBackend(BaseBackend):
    def authenticate(self, request, correo_electronico=None, password=None, **kwargs):
        logger = logging.getLogger(__name__)

        if not correo_electronico or password is None:
            logger.warning("Faltan credenciales de autenticación")
            return None

        try:
            correo_electronico = correo_electronico.lower().strip()
            user = Usuario.objects.get(correo_electronico=correo_electronico)

            # Normalizar password
            password_clean = str(password).strip()
            password_check = user.check_password(password_clean)

            if password_check and user.is_active:
                logger.info(
                    f"Autenticación exitosa para usuario: {user.correo_electronico}"
                )
                return user
            else:
                logger.warning(
                    f"Autenticación fallida para usuario: {correo_electronico}"
                )
                return None

        except Usuario.DoesNotExist:
            logger.warning(f"Usuario no encontrado: {correo_electronico}")
            return None
        except Exception as e:
            logger.error(f"Error en autenticación: {str(e)}")
            return None
