# =======================================
# TALLER DE MOTOS - SECURITY MIDDLEWARE
# =======================================
# Middleware adicional para seguridad y protección
# =======================================

import re
import logging
from django.conf import settings
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Middleware para agregar headers de seguridad HTTP
    """

    def process_response(self, request, response):
        # Headers de seguridad básicos
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'

        # Content Security Policy (ajustar según necesidades)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "media-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none';"
        )
        response['Content-Security-Policy'] = csp

        # HSTS (solo en HTTPS)
        if request.is_secure():
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        return response


class SQLInjectionProtectionMiddleware(MiddlewareMixin):
    """
    Middleware básico para protección contra SQL injection
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Patrones sospechosos de SQL injection
        self.sql_patterns = [
            r';\s*(drop|delete|update|insert|alter|create|truncate)\s',
            r'union\s+select',
            r'/\*.*\*/',
            r'--',
            r'xp_',
            r'sp_',
            r'exec\s*\(',
            r'execute\s*\(',
        ]

    def process_request(self, request):
        # Revisar parámetros GET y POST
        for key, value in request.GET.items():
            if isinstance(value, str) and self._contains_suspicious_patterns(value):
                logger.warning(f"SQL injection attempt detected in GET parameter: {key}={value}")
                return HttpResponseForbidden("Request blocked: Suspicious content detected")

        for key, value in request.POST.items():
            if isinstance(value, str) and self._contains_suspicious_patterns(value):
                logger.warning(f"SQL injection attempt detected in POST parameter: {key}={value}")
                return HttpResponseForbidden("Request blocked: Suspicious content detected")

        return None

    def _contains_suspicious_patterns(self, value):
        """Verificar si el valor contiene patrones sospechosos"""
        value_lower = value.lower()
        for pattern in self.sql_patterns:
            if re.search(pattern, value_lower, re.IGNORECASE):
                return True
        return False


class RequestSizeLimitMiddleware(MiddlewareMixin):
    """
    Middleware para limitar el tamaño de las requests
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Límite de 10MB por defecto
        self.max_request_size = getattr(settings, 'MAX_REQUEST_SIZE', 10 * 1024 * 1024)

    def process_request(self, request):
        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                content_length = int(content_length)
                if content_length > self.max_request_size:
                    logger.warning(f"Request too large: {content_length} bytes from {request.META.get('REMOTE_ADDR')}")
                    return HttpResponseBadRequest("Request too large")
            except ValueError:
                pass

        return None


class IPBlocklistMiddleware(MiddlewareMixin):
    """
    Middleware para bloquear IPs específicas
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Lista de IPs bloqueadas (configurar en settings)
        self.blocked_ips = getattr(settings, 'BLOCKED_IPS', [])

    def process_request(self, request):
        client_ip = self._get_client_ip(request)

        if client_ip in self.blocked_ips:
            logger.warning(f"Blocked request from IP: {client_ip}")
            return HttpResponseForbidden("Access denied")

        return None

    def _get_client_ip(self, request):
        """Obtener IP real del cliente considerando proxies"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class UserAgentValidationMiddleware(MiddlewareMixin):
    """
    Middleware para validar User-Agent
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # User-Agents bloqueados
        self.blocked_user_agents = [
            'sqlmap',
            'nmap',
            'masscan',
            'dirbuster',
            'gobuster',
            'nikto',
            'acunetix',
            'openvas',
        ]

    def process_request(self, request):
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()

        for blocked_ua in self.blocked_user_agents:
            if blocked_ua in user_agent:
                logger.warning(f"Blocked request from suspicious User-Agent: {user_agent}")
                return HttpResponseForbidden("Access denied")

        return None


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware para logging detallado de requests
    """

    def process_request(self, request):
        # Solo loggear requests a la API
        if request.path.startswith('/api/'):
            logger.info(
                f"API Request: {request.method} {request.path} "
                f"User: {request.user.username if request.user.is_authenticated else 'Anonymous'} "
                f"IP: {request.META.get('REMOTE_ADDR')} "
                f"User-Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')[:100]}"
            )

    def process_exception(self, request, exception):
        if request.path.startswith('/api/'):
            logger.error(
                f"API Exception: {request.method} {request.path} "
                f"Exception: {str(exception)} "
                f"User: {request.user.username if request.user.is_authenticated else 'Anonymous'}"
            )


# =======================================
# CONFIGURACIÓN PARA SETTINGS.PY
# =======================================

# Agregar a MIDDLEWARE en settings.py:
MIDDLEWARE = [
    # ... otros middlewares ...
    'core.api.security_middleware.SecurityHeadersMiddleware',
    'core.api.security_middleware.SQLInjectionProtectionMiddleware',
    'core.api.security_middleware.RequestSizeLimitMiddleware',
    'core.api.security_middleware.IPBlocklistMiddleware',
    'core.api.security_middleware.UserAgentValidationMiddleware',
    'core.api.security_middleware.RequestLoggingMiddleware',
    # ... monitoring middleware si existe ...
]

# Configuraciones adicionales en settings.py:
BLOCKED_IPS = [
    # '192.168.1.100',  # Ejemplo
]

MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB