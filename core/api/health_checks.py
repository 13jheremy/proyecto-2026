# =======================================
# TALLER DE MOTOS - HEALTH CHECKS
# =======================================
# Monitoreo de salud del sistema para producción
# =======================================

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.db import connection
from django.core.cache import cache
from django.conf import settings
import psycopg2
import redis
import time
import logging

logger = logging.getLogger(__name__)


# =======================================
# HEALTH CHECK PRINCIPAL
# =======================================

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check completo del sistema
    Verifica base de datos, cache, servicios externos
    """
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'checks': {}
    }

    # Verificar base de datos
    db_status = check_database()
    health_status['checks']['database'] = db_status

    # Verificar cache (Redis)
    cache_status = check_cache()
    health_status['checks']['cache'] = cache_status

    # Verificar servicios externos
    external_status = check_external_services()
    health_status['checks']['external_services'] = external_status

    # Verificar aplicación Django
    app_status = check_application()
    health_status['checks']['application'] = app_status

    # Determinar estado general
    all_healthy = all(
        check.get('status') == 'healthy'
        for check in health_status['checks'].values()
    )

    if not all_healthy:
        health_status['status'] = 'unhealthy'
        return Response(health_status, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(health_status, status=status.HTTP_200_OK)


# =======================================
# HEALTH CHECKS INDIVIDUALES
# =======================================

def check_database():
    """Verificar conexión a PostgreSQL"""
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()

        return {
            'status': 'healthy',
            'message': 'Database connection successful',
            'response_time': 'OK'
        }
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        return {
            'status': 'unhealthy',
            'message': f'Database connection failed: {str(e)}',
            'response_time': 'N/A'
        }


def check_cache():
    """Verificar conexión a Redis"""
    try:
        # Intentar set y get en Redis
        test_key = 'health_check_test'
        test_value = 'ok'

        cache.set(test_key, test_value, timeout=10)
        retrieved_value = cache.get(test_key)

        if retrieved_value == test_value:
            cache.delete(test_key)
            return {
                'status': 'healthy',
                'message': 'Cache connection successful',
                'response_time': 'OK'
            }
        else:
            return {
                'status': 'unhealthy',
                'message': 'Cache set/get test failed',
                'response_time': 'N/A'
            }
    except Exception as e:
        logger.error(f"Cache health check failed: {str(e)}")
        return {
            'status': 'unhealthy',
            'message': f'Cache connection failed: {str(e)}',
            'response_time': 'N/A'
        }


def check_external_services():
    """Verificar servicios externos críticos"""
    services_status = {}

    # Verificar Cloudinary (si está configurado)
    cloudinary_status = check_cloudinary()
    services_status['cloudinary'] = cloudinary_status

    # Verificar FCM (si está configurado)
    fcm_status = check_fcm()
    services_status['fcm'] = fcm_status

    # Determinar estado general de servicios externos
    all_services_healthy = all(
        service.get('status') == 'healthy'
        for service in services_status.values()
    )

    return {
        'status': 'healthy' if all_services_healthy else 'degraded',
        'message': 'External services check completed',
        'services': services_status
    }


def check_application():
    """Verificar estado de la aplicación Django"""
    try:
        from django.apps import apps
        from ..models import Usuario

        # Verificar que los modelos están registrados
        user_model = apps.get_model('core', 'Usuario')
        if user_model:
            # Intentar una query simple
            count = user_model.objects.count()
            return {
                'status': 'healthy',
                'message': f'Application models loaded successfully. User count: {count}',
                'response_time': 'OK'
            }
        else:
            return {
                'status': 'unhealthy',
                'message': 'User model not found',
                'response_time': 'N/A'
            }
    except Exception as e:
        logger.error(f"Application health check failed: {str(e)}")
        return {
            'status': 'unhealthy',
            'message': f'Application check failed: {str(e)}',
            'response_time': 'N/A'
        }


def check_cloudinary():
    """Verificar configuración de Cloudinary"""
    try:
        import cloudinary
        from cloudinary import api

        # Verificar configuración
        if hasattr(settings, 'CLOUDINARY_STORAGE') and settings.CLOUDINARY_STORAGE:
            # Intentar ping a Cloudinary
            ping_result = api.ping()
            if ping_result.get('status') == 'ok':
                return {
                    'status': 'healthy',
                    'message': 'Cloudinary connection successful'
                }
            else:
                return {
                    'status': 'unhealthy',
                    'message': 'Cloudinary ping failed'
                }
        else:
            return {
                'status': 'not_configured',
                'message': 'Cloudinary not configured'
            }
    except Exception as e:
        logger.error(f"Cloudinary health check failed: {str(e)}")
        return {
            'status': 'unhealthy',
            'message': f'Cloudinary check failed: {str(e)}'
        }


def check_fcm():
    """Verificar configuración de FCM"""
    try:
        # Verificar que las credenciales están configuradas
        if hasattr(settings, 'FCM_SERVER_KEY') and settings.FCM_SERVER_KEY:
            return {
                'status': 'configured',
                'message': 'FCM credentials configured'
            }
        else:
            return {
                'status': 'not_configured',
                'message': 'FCM credentials not configured'
            }
    except Exception as e:
        logger.error(f"FCM health check failed: {str(e)}")
        return {
            'status': 'unhealthy',
            'message': f'FCM check failed: {str(e)}'
        }


# =======================================
# HEALTH CHECKS ESPECÍFICOS
# =======================================

@api_view(['GET'])
@permission_classes([AllowAny])
def database_health(request):
    """Health check específico de base de datos"""
    status_data = check_database()
    if status_data['status'] == 'healthy':
        return Response(status_data, status=status.HTTP_200_OK)
    else:
        return Response(status_data, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['GET'])
@permission_classes([AllowAny])
def cache_health(request):
    """Health check específico de cache"""
    status_data = check_cache()
    if status_data['status'] == 'healthy':
        return Response(status_data, status=status.HTTP_200_OK)
    else:
        return Response(status_data, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(['GET'])
@permission_classes([AllowAny])
def services_health(request):
    """Health check específico de servicios externos"""
    status_data = check_external_services()
    if status_data['status'] == 'healthy':
        return Response(status_data, status=status.HTTP_200_OK)
    else:
        return Response(status_data, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# =======================================
# MÉTRICAS DE PERFORMANCE
# =======================================

@api_view(['GET'])
@permission_classes([AllowAny])
def system_metrics(request):
    """
    Métricas básicas del sistema para monitoreo
    """
    try:
        from ..models import Usuario, Producto, Venta, Mantenimiento
        import psutil
        import os

        metrics = {
            'timestamp': time.time(),
            'database': {
                'usuarios_count': Usuario.objects.count(),
                'productos_count': Producto.objects.count(),
                'ventas_count': Venta.objects.filter(eliminado=False).count(),
                'mantenimientos_count': Mantenimiento.objects.filter(eliminado=False).count(),
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=1),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent,
            }
        }

        return Response(metrics, status=status.HTTP_200_OK)

    except ImportError:
        # Si no hay psutil, devolver métricas básicas
        from ..models import Usuario, Producto, Venta, Mantenimiento

        metrics = {
            'timestamp': time.time(),
            'database': {
                'usuarios_count': Usuario.objects.count(),
                'productos_count': Producto.objects.count(),
                'ventas_count': Venta.objects.filter(eliminado=False).count(),
                'mantenimientos_count': Mantenimiento.objects.filter(eliminado=False).count(),
            },
            'note': 'psutil not available for system metrics'
        }

        return Response(metrics, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting system metrics: {str(e)}")
        return Response(
            {'error': 'Failed to get metrics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )