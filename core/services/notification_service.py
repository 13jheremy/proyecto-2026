import json
import logging
from typing import List, Dict, Optional
from django.conf import settings
from firebase_admin import credentials, messaging, initialize_app
from firebase_admin.exceptions import FirebaseError
import firebase_admin

# Configurar logging para debug
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class FCMNotificationService:
    """Servicio para enviar notificaciones push usando Firebase Cloud Messaging"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialize_firebase()
            FCMNotificationService._initialized = True

    def _initialize_firebase(self):
        """Inicializar Firebase Admin SDK"""
        try:
            # Verificar si Firebase ya está inicializado
            if not firebase_admin._apps:
                # Usar las credenciales del archivo JSON o variables de entorno
                if hasattr(settings, "FIREBASE_CREDENTIALS_PATH"):
                    cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                    initialize_app(cred)
                    logger.info("Firebase inicializado con archivo de credenciales")
                elif hasattr(settings, "FIREBASE_CREDENTIALS_JSON"):
                    # Para usar credenciales desde variables de entorno
                    cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
                    cred = credentials.Certificate(cred_dict)
                    initialize_app(cred)
                    logger.info("Firebase inicializado con credenciales JSON")
                else:
                    logger.warning(
                        "No se encontraron credenciales de Firebase configuradas"
                    )
            else:
                logger.info("Firebase ya estaba inicializado")
        except Exception as e:
            logger.error(f"Error inicializando Firebase: {e}")

    def send_notification(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        image_url: Optional[str] = None,
        max_retries: int = 3,
    ) -> bool:
        """
        Enviar notificación push básica a un token específico con reintentos

        Args:
            token: Token FCM del dispositivo
            title: Título de la notificación
            body: Cuerpo de la notificación
            data: Datos adicionales (opcional)
            image_url: URL de imagen (opcional)
            max_retries: Número máximo de reintentos (default: 3)

        Returns:
            bool: True si se envió correctamente, False en caso contrario
        """
        logger.info(f"Enviando notificación: {title}")

        # Verificar que Firebase está inicializado
        if not firebase_admin._apps:
            logger.error("Firebase no está inicializado!")
            return False

        # Construir el mensaje básico
        message = messaging.Message(
            notification=messaging.Notification(
                title=title, body=body, image=image_url
            ),
            data=data or {},
            token=token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    icon="ic_notification",
                    color="#FF6B35",
                    sound="default",
                    click_action="FLUTTER_NOTIFICATION_CLICK",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
        )

        # Reintentar hasta max_retries veces
        for intento in range(1, max_retries + 1):
            try:
                response = messaging.send(message)
                logger.info(f"Notificación enviada exitosamente en intento {intento}")
                return True

            except FirebaseError as e:
                logger.warning(f"Error de Firebase (intento {intento}): {e}")

                # Si es un error permanente, no reintentar
                if e.code in ["NOT_FOUND", "INVALID_ARGUMENT", "UNREGISTERED"]:
                    logger.error("Error permanente, no se reintenta")
                    return False

                # Si es el último intento, retornar False
                if intento == max_retries:
                    logger.error("Todos los reintentos fallidos")
                    return False

            except Exception as e:
                logger.warning(
                    f"Error inesperado (intento {intento}): {type(e).__name__}: {e}"
                )

                # Si es el último intento, retornar False
                if intento == max_retries:
                    import traceback

                    logger.error(f"Error final: {traceback.format_exc()}")
                    return False

            # Esperar antes de reintentar (exponencial)
            import time

            tiempo_espera = 2**intento  # 2, 4, 8 segundos
            time.sleep(tiempo_espera)

        return False

    def send_multicast_notification(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict] = None,
        image_url: Optional[str] = None,
    ) -> Dict:
        """
        Enviar notificación a múltiples tokens

        Args:
            tokens: Lista de tokens FCM
            title: Título de la notificación
            body: Cuerpo de la notificación
            data: Datos adicionales (opcional)
            image_url: URL de imagen (opcional)

        Returns:
            Dict: Resultado del envío con estadísticas
        """
        try:
            if not tokens:
                return {"success_count": 0, "failure_count": 0, "responses": []}

            # Construir el mensaje multicast
            message = messaging.MulticastMessage(
                notification=messaging.Notification(
                    title=title, body=body, image=image_url
                ),
                data=data or {},
                tokens=tokens,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        icon="ic_notification",
                        color="#FF6B35",
                        sound="default",
                        click_action="FLUTTER_NOTIFICATION_CLICK",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", badge=1)
                    )
                ),
            )

            # Enviar mensaje
            response = messaging.send_multicast(message)

            logger.info(
                f"Notificación multicast enviada. Éxitos: {response.success_count}, Fallos: {response.failure_count}"
            )

            return {
                "success_count": response.success_count,
                "failure_count": response.failure_count,
                "responses": response.responses,
            }

        except FirebaseError as e:
            logger.error(f"Error de Firebase al enviar notificación multicast: {e}")
            return {"success_count": 0, "failure_count": len(tokens), "responses": []}
        except Exception as e:
            logger.error(f"Error inesperado al enviar notificación multicast: {e}")
            return {"success_count": 0, "failure_count": len(tokens), "responses": []}

    def send_topic_notification(
        self,
        topic: str,
        title: str,
        body: str,
        data: Optional[Dict] = None,
        image_url: Optional[str] = None,
    ) -> bool:
        """
        Enviar notificación a un tópico

        Args:
            topic: Nombre del tópico
            title: Título de la notificación
            body: Cuerpo de la notificación
            data: Datos adicionales (opcional)
            image_url: URL de imagen (opcional)

        Returns:
            bool: True si se envió correctamente, False en caso contrario
        """
        try:
            # Construir el mensaje
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title, body=body, image=image_url
                ),
                data=data or {},
                topic=topic,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        icon="ic_notification",
                        color="#FF6B35",
                        sound="default",
                        click_action="FLUTTER_NOTIFICATION_CLICK",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", badge=1)
                    )
                ),
            )

            # Enviar mensaje
            response = messaging.send(message)
            logger.info(f"Notificación de tópico enviada exitosamente: {response}")
            return True

        except FirebaseError as e:
            logger.error(f"Error de Firebase al enviar notificación de tópico: {e}")
            return False
        except Exception as e:
            logger.error(f"Error inesperado al enviar notificación de tópico: {e}")
            return False


# Instancia singleton del servicio
fcm_service = FCMNotificationService()


# Funciones de conveniencia para notificaciones básicas
def send_simple_notification(
    user_token: str, title: str, body: str, data: Optional[Dict] = None
) -> bool:
    """Enviar notificación push básica"""
    return fcm_service.send_notification(
        token=user_token, title=title, body=body, data=data
    )


def send_maintenance_notification(user_token: str, moto_info: str, fecha: str) -> bool:
    """Enviar notificación de mantenimiento"""
    return send_simple_notification(
        user_token=user_token,
        title="🔧 Mantenimiento",
        body=f"Tu {moto_info} tiene mantenimiento programado para el {fecha}",
        data={"type": "maintenance", "action": "view"},
    )


def send_oil_change_notification(
    user_token: str, moto_info: str, kilometraje: int
) -> bool:
    """Enviar notificación de cambio de aceite"""
    return send_simple_notification(
        user_token=user_token,
        title="🛢️ Cambio de Aceite",
        body=f"Tu {moto_info} necesita cambio de aceite. Kilometraje: {kilometraje:,} km",
        data={"type": "oil_change", "action": "view"},
    )
