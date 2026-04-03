# =======================================
# TALLER DE MOTOS - RATE LIMITING
# =======================================
# Protección contra abuso de API y ataques DDoS
# =======================================

from rest_framework.throttling import UserRateThrottle, AnonRateThrottle, ScopedRateThrottle
import logging

logger = logging.getLogger(__name__)


# =======================================
# THROTTLE CLASSES PERSONALIZADAS
# =======================================

class CustomUserRateThrottle(UserRateThrottle):
    """
    Rate limiting para usuarios autenticados
    - Más permisivo que para usuarios anónimos
    - Logging de uso excesivo
    """
    scope = 'user'
    rate = '1000/hour'  # 1000 requests por hora para usuarios autenticados

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for user {request.user.username} "
                f"on endpoint {request.path}"
            )

        return allowed


class CustomAnonRateThrottle(AnonRateThrottle):
    """
    Rate limiting para usuarios no autenticados
    - Más restrictivo para prevenir abuso
    - Logging de intentos de ataque
    """
    scope = 'anon'
    rate = '100/hour'  # 100 requests por hora para usuarios anónimos

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"Rate limit exceeded for anonymous user "
                f"on endpoint {request.path} from IP {self.get_ident(request)}"
            )

        return allowed


class AuthThrottle(ScopedRateThrottle):
    """
    Rate limiting específico para endpoints de autenticación
    - Muy restrictivo para prevenir ataques de fuerza bruta
    """
    scope = 'auth'
    rate = '5/minute'  # Solo 5 intentos de login por minuto

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.error(
                f"Authentication rate limit exceeded "
                f"on endpoint {request.path} from IP {self.get_ident(request)}"
            )

        return allowed


class APIThrottle(ScopedRateThrottle):
    """
    Rate limiting para operaciones críticas de API
    - Balance entre funcionalidad y seguridad
    """
    scope = 'api'
    rate = '500/hour'  # 500 requests por hora para operaciones API

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"API rate limit exceeded for user {request.user.username} "
                f"on endpoint {request.path}"
            )

        return allowed


class POSThrottle(ScopedRateThrottle):
    """
    Rate limiting específico para sistema POS
    - Optimizado para operaciones de venta rápidas
    """
    scope = 'pos'
    rate = '2000/hour'  # Alto límite para operaciones POS

    def allow_request(self, request, view):
        allowed = super().allow_request(request, view)

        if not allowed:
            logger.warning(
                f"POS rate limit exceeded for user {request.user.username} "
                f"on endpoint {request.path}"
            )

        return allowed


# =======================================
# CONFIGURACIÓN DE THROTTLING
# =======================================

# Mapeo de endpoints a throttles específicos
THROTTLE_CLASSES = {
    'auth': AuthThrottle,
    'api': APIThrottle,
    'pos': POSThrottle,
    'user': CustomUserRateThrottle,
    'anon': CustomAnonRateThrottle,
}

# Configuración por defecto para vistas
DEFAULT_THROTTLE_CLASSES = [
    CustomUserRateThrottle,
    CustomAnonRateThrottle,
]

# Configuraciones específicas por endpoint
THROTTLE_RATES = {
    'auth': '5/minute',
    'api': '500/hour',
    'pos': '2000/hour',
    'user': '1000/hour',
    'anon': '100/hour',
}

# =======================================
# UTILIDADES DE MONITORING
# =======================================

def get_throttle_status(request, view):
    """
    Obtiene el estado actual de throttling para debugging
    """
    from rest_framework.throttling import UserRateThrottle, AnonRateThrottle

    status_info = {
        'user_authenticated': request.user.is_authenticated,
        'user_throttle': None,
        'anon_throttle': None,
    }

    if request.user.is_authenticated:
        throttle = CustomUserRateThrottle()
        throttle.allow_request(request, view)
        status_info['user_throttle'] = {
            'rate': throttle.rate,
            'num_requests': throttle.num_requests,
            'duration': throttle.duration,
        }

    throttle = CustomAnonRateThrottle()
    throttle.allow_request(request, view)
    status_info['anon_throttle'] = {
        'rate': throttle.rate,
        'num_requests': throttle.num_requests,
        'duration': throttle.duration,
    }

    return status_info