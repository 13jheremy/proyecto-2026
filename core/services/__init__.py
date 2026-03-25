"""
Servicios del núcleo de la aplicación.

Contiene la lógica de negocio aislada para mantener una arquitectura limpia.
"""

from .mantenimiento_service import MantenimientoService, RecordatorioService
from .notification_service import FCMNotificationService, fcm_service
from .notification_service import (
    send_simple_notification,
    send_maintenance_notification,
    send_oil_change_notification,
)

__all__ = [
    "MantenimientoService",
    "RecordatorioService",
    "FCMNotificationService",
    "fcm_service",
    "send_simple_notification",
    "send_maintenance_notification",
    "send_oil_change_notification",
]
