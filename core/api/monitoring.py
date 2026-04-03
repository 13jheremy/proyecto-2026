# =======================================
# TALLER DE MOTOS - MONITORING & LOGGING
# =======================================
# Sistema avanzado de monitoreo y logging para producción
# =======================================

import time
import logging
import json
from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
import psutil
import threading
from collections import defaultdict, deque
import statistics

logger = logging.getLogger(__name__)


# =======================================
# MONITORING GLOBAL
# =======================================

class APIMonitoring:
    """Sistema de monitoreo de API requests"""

    def __init__(self):
        self.requests = defaultdict(lambda: {
            'count': 0,
            'total_time': 0.0,
            'response_times': deque(maxlen=1000),  # Últimas 1000 requests
            'status_codes': defaultdict(int),
            'errors': deque(maxlen=100),  # Últimos 100 errores
        })

    def record_request(self, endpoint, method, status_code, response_time, error=None):
        """Registra una petición API"""
        key = f"{method}:{endpoint}"
        data = self.requests[key]

        data['count'] += 1
        data['total_time'] += response_time
        data['response_times'].append(response_time)
        data['status_codes'][status_code] += 1

        if error:
            data['errors'].append({
                'timestamp': time.time(),
                'error': str(error),
                'status_code': status_code
            })

    def get_stats(self, endpoint=None, method=None):
        """Obtiene estadísticas de rendimiento"""
        if endpoint and method:
            key = f"{method}:{endpoint}"
            data = self.requests.get(key, {})
            if not data:
                return None

            response_times = list(data['response_times'])
            return {
                'endpoint': endpoint,
                'method': method,
                'total_requests': data['count'],
                'avg_response_time': statistics.mean(response_times) if response_times else 0,
                'min_response_time': min(response_times) if response_times else 0,
                'max_response_time': max(response_times) if response_times else 0,
                'p95_response_time': statistics.quantiles(response_times, n=20)[18] if len(response_times) >= 20 else 0,
                'status_codes': dict(data['status_codes']),
                'error_count': len(data['errors']),
                'recent_errors': list(data['errors'])[-5:]  # Últimos 5 errores
            }
        else:
            # Estadísticas generales
            all_stats = []
            for key, data in self.requests.items():
                method, endpoint = key.split(':', 1)
                response_times = list(data['response_times'])
                if response_times:
                    all_stats.append({
                        'endpoint': endpoint,
                        'method': method,
                        'total_requests': data['count'],
                        'avg_response_time': statistics.mean(response_times),
                        'error_count': len(data['errors'])
                    })

            return {
                'total_endpoints': len(all_stats),
                'endpoints': sorted(all_stats, key=lambda x: x['total_requests'], reverse=True)[:20]  # Top 20
            }


# Instancia global del monitor
api_monitor = APIMonitoring()


# =======================================
# DECORADORES DE MONITORING
# =======================================

def monitor_api_request(view_func):
    """Decorador para monitorear requests de API"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        start_time = time.time()

        try:
            response = view_func(request, *args, **kwargs)
            response_time = time.time() - start_time

            # Registrar la petición exitosa
            api_monitor.record_request(
                endpoint=request.path,
                method=request.method,
                status_code=response.status_code if hasattr(response, 'status_code') else 200,
                response_time=response_time
            )

            return response

        except Exception as e:
            response_time = time.time() - start_time

            # Registrar el error
            api_monitor.record_request(
                endpoint=request.path,
                method=request.method,
                status_code=500,
                response_time=response_time,
                error=e
            )

            # Re-lanzar la excepción
            raise

    return wrapper


def log_api_request(view_func):
    """Decorador para logging detallado de requests"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        start_time = time.time()

        # Log de entrada
        logger.info(
            f"API Request: {request.method} {request.path} "
            f"User: {request.user.username if request.user.is_authenticated else 'Anonymous'} "
            f"IP: {request.META.get('REMOTE_ADDR', 'Unknown')}"
        )

        try:
            response = view_func(request, *args, **kwargs)
            response_time = time.time() - start_time

            # Log de salida exitosa
            logger.info(
                f"API Response: {request.method} {request.path} "
                f"Status: {response.status_code if hasattr(response, 'status_code') else 200} "
                f"Time: {response_time:.3f}s"
            )

            return response

        except Exception as e:
            response_time = time.time() - start_time

            # Log de error
            logger.error(
                f"API Error: {request.method} {request.path} "
                f"Error: {str(e)} "
                f"Time: {response_time:.3f}s"
            )

            raise

    return wrapper


# =======================================
# VISTAS DE MONITORING
# =======================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_stats(request):
    """Estadísticas de API para monitoreo"""
    try:
        endpoint = request.query_params.get('endpoint')
        method = request.query_params.get('method')

        stats = api_monitor.get_stats(endpoint=endpoint, method=method)

        if stats is None and (endpoint or method):
            return Response(
                {'error': 'Endpoint not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(stats, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting API stats: {str(e)}")
        return Response(
            {'error': 'Failed to get stats'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_performance(request):
    """Métricas de performance del sistema"""
    try:
        import os

        # CPU y memoria
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        # Procesos Python/Django
        python_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                if 'python' in proc.info['name'].lower():
                    python_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cpu_percent': proc.info['cpu_percent'],
                        'memory_percent': proc.info['memory_percent']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        performance_data = {
            'timestamp': time.time(),
            'system': {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_gb': memory.used / (1024**3),
                'memory_total_gb': memory.total / (1024**3),
                'disk_percent': disk.percent,
                'disk_used_gb': disk.used / (1024**3),
                'disk_total_gb': disk.total / (1024**3),
            },
            'processes': {
                'python_process_count': len(python_processes),
                'top_python_processes': sorted(
                    python_processes,
                    key=lambda x: x['cpu_percent'],
                    reverse=True
                )[:5]  # Top 5 procesos Python
            }
        }

        return Response(performance_data, status=status.HTTP_200_OK)

    except ImportError:
        return Response(
            {'error': 'psutil not available'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )
    except Exception as e:
        logger.error(f"Error getting system performance: {str(e)}")
        return Response(
            {'error': 'Failed to get performance data'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def error_logs(request):
    """Logs de errores recientes"""
    try:
        # Obtener errores de todos los endpoints
        all_errors = []
        for key, data in api_monitor.requests.items():
            method, endpoint = key.split(':', 1)
            for error in data['errors']:
                all_errors.append({
                    'endpoint': endpoint,
                    'method': method,
                    'timestamp': error['timestamp'],
                    'error': error['error'],
                    'status_code': error['status_code']
                })

        # Ordenar por timestamp descendente y tomar los más recientes
        recent_errors = sorted(all_errors, key=lambda x: x['timestamp'], reverse=True)[:50]

        return Response({
            'total_errors': len(all_errors),
            'recent_errors': recent_errors
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting error logs: {str(e)}")
        return Response(
            {'error': 'Failed to get error logs'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =======================================
# ALERTAS AUTOMÁTICAS
# =======================================

class AlertSystem:
    """Sistema de alertas automáticas"""

    def __init__(self):
        self.alerts = []
        self.thresholds = {
            'response_time': 5.0,  # 5 segundos
            'error_rate': 0.05,    # 5% de errores
            'cpu_percent': 90.0,   # 90% CPU
            'memory_percent': 90.0 # 90% memoria
        }

    def check_alerts(self):
        """Verificar condiciones de alerta"""
        alerts = []

        # Verificar response times altos
        for key, data in api_monitor.requests.items():
            if data['count'] > 10:  # Solo endpoints con suficiente tráfico
                response_times = list(data['response_times'])
                if response_times:
                    avg_time = statistics.mean(response_times)
                    if avg_time > self.thresholds['response_time']:
                        alerts.append({
                            'type': 'high_response_time',
                            'endpoint': key,
                            'value': avg_time,
                            'threshold': self.thresholds['response_time'],
                            'severity': 'warning'
                        })

        # Verificar tasa de errores alta
        for key, data in api_monitor.requests.items():
            if data['count'] > 10:
                error_rate = len(data['errors']) / data['count']
                if error_rate > self.thresholds['error_rate']:
                    alerts.append({
                        'type': 'high_error_rate',
                        'endpoint': key,
                        'value': error_rate,
                        'threshold': self.thresholds['error_rate'],
                        'severity': 'error'
                    })

        # Verificar recursos del sistema
        try:
            cpu_percent = psutil.cpu_percent()
            memory_percent = psutil.virtual_memory().percent

            if cpu_percent > self.thresholds['cpu_percent']:
                alerts.append({
                    'type': 'high_cpu_usage',
                    'value': cpu_percent,
                    'threshold': self.thresholds['cpu_percent'],
                    'severity': 'critical'
                })

            if memory_percent > self.thresholds['memory_percent']:
                alerts.append({
                    'type': 'high_memory_usage',
                    'value': memory_percent,
                    'threshold': self.thresholds['memory_percent'],
                    'severity': 'critical'
                })
        except ImportError:
            pass  # psutil no disponible

        self.alerts = alerts
        return alerts


# Instancia global del sistema de alertas
alert_system = AlertSystem()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def system_alerts(request):
    """Obtener alertas del sistema"""
    try:
        alerts = alert_system.check_alerts()

        return Response({
            'alert_count': len(alerts),
            'alerts': alerts
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error getting system alerts: {str(e)}")
        return Response(
            {'error': 'Failed to get alerts'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# =======================================
# MIDDLEWARE DE MONITORING
# =======================================

class MonitoringMiddleware:
    """Middleware para monitoreo automático de requests"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()

        # Procesar la request
        response = self.get_response(request)
        response_time = time.time() - start_time

        # Registrar en el monitor (solo para API)
        if request.path.startswith('/api/'):
            api_monitor.record_request(
                endpoint=request.path,
                method=request.method,
                status_code=response.status_code,
                response_time=response_time
            )

        return response