#!/usr/bin/env python
"""
TALLER DE MOTOS - VALIDACIÓN DE CONFIGURACIÓN PARA PRODUCCIÓN
===============================================================
Script para validar que todas las configuraciones críticas estén presentes
y correctamente configuradas antes del despliegue.
"""

import os
import sys
import django
from pathlib import Path

# Configurar Django
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taller_motos.settings')
django.setup()

from django.conf import settings
from django.core.management import execute_from_command_line
from django.db import connection
import logging

logger = logging.getLogger(__name__)

# Colores para output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_header(text):
    """Imprimir encabezado"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text.center(60)}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")

def print_check(name, status, message=""):
    """Imprimir resultado de verificación"""
    if status:
        print(f"{Colors.GREEN}✓{Colors.END} {name}: {message}")
    else:
        print(f"{Colors.RED}✗{Colors.END} {name}: {message}")

def check_environment_variables():
    """Verificar variables de entorno críticas"""
    print_header("VERIFICACIÓN DE VARIABLES DE ENTORNO")

    required_vars = [
        'SECRET_KEY',
        'DATABASE_URL',
        'REDIS_URL',
        'FCM_SERVER_KEY',
        'CLOUDINARY_CLOUD_NAME',
        'CLOUDINARY_API_KEY',
        'CLOUDINARY_API_SECRET',
    ]

    all_present = True

    for var in required_vars:
        value = os.environ.get(var)
        if value:
            # No mostrar valores sensibles
            display_value = "***CONFIGURADO***" if 'SECRET' in var or 'KEY' in var else value[:20] + "..."
            print_check(f"Variable {var}", True, display_value)
        else:
            print_check(f"Variable {var}", False, "NO CONFIGURADA")
            all_present = False

    return all_present

def check_database_connection():
    """Verificar conexión a base de datos"""
    print_header("VERIFICACIÓN DE CONEXIÓN A BASE DE DATOS")

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()

        # Verificar que las tablas existen
        from django.apps import apps
        tables_exist = True
        required_models = ['Usuario', 'Producto', 'Venta', 'Mantenimiento']

        for model_name in required_models:
            try:
                model = apps.get_model('core', model_name)
                # Intentar hacer una query simple
                count = model.objects.count()
                print_check(f"Tabla {model_name}", True, f"{count} registros")
            except Exception as e:
                print_check(f"Tabla {model_name}", False, str(e))
                tables_exist = False

        return True and tables_exist

    except Exception as e:
        print_check("Conexión a BD", False, str(e))
        return False

def check_cache_connection():
    """Verificar conexión a Redis"""
    print_header("VERIFICACIÓN DE CONEXIÓN A CACHE (REDIS)")

    try:
        from django.core.cache import cache
        cache.set('test_key', 'test_value', timeout=10)
        value = cache.get('test_key')

        if value == 'test_value':
            cache.delete('test_key')
            print_check("Conexión Redis", True, "OK")
            return True
        else:
            print_check("Conexión Redis", False, "Set/Get test failed")
            return False

    except Exception as e:
        print_check("Conexión Redis", False, str(e))
        return False

def check_external_services():
    """Verificar servicios externos"""
    print_header("VERIFICACIÓN DE SERVICIOS EXTERNOS")

    services_ok = True

    # Verificar Cloudinary
    try:
        import cloudinary
        from cloudinary import api

        if hasattr(settings, 'CLOUDINARY_STORAGE') and settings.CLOUDINARY_STORAGE:
            ping_result = api.ping()
            if ping_result.get('status') == 'ok':
                print_check("Cloudinary", True, "Conectado")
            else:
                print_check("Cloudinary", False, "Ping failed")
                services_ok = False
        else:
            print_check("Cloudinary", False, "No configurado")
            services_ok = False
    except Exception as e:
        print_check("Cloudinary", False, str(e))
        services_ok = False

    # Verificar FCM
    try:
        if hasattr(settings, 'FCM_SERVER_KEY') and settings.FCM_SERVER_KEY:
            print_check("FCM", True, "Configurado")
        else:
            print_check("FCM", False, "No configurado")
            services_ok = False
    except Exception as e:
        print_check("FCM", False, str(e))
        services_ok = False

    return services_ok

def check_security_settings():
    """Verificar configuraciones de seguridad"""
    print_header("VERIFICACIÓN DE CONFIGURACIONES DE SEGURIDAD")

    security_ok = True

    # Verificar DEBUG
    if settings.DEBUG:
        print_check("DEBUG mode", False, "DEBE estar False en producción")
        security_ok = False
    else:
        print_check("DEBUG mode", True, "False (correcto para prod)")

    # Verificar HTTPS settings
    if not settings.DEBUG:
        https_settings = [
            ('SECURE_SSL_REDIRECT', getattr(settings, 'SECURE_SSL_REDIRECT', False)),
            ('SESSION_COOKIE_SECURE', getattr(settings, 'SESSION_COOKIE_SECURE', False)),
            ('CSRF_COOKIE_SECURE', getattr(settings, 'CSRF_COOKIE_SECURE', False)),
        ]

        for setting_name, value in https_settings:
            if value:
                print_check(f"HTTPS {setting_name}", True, "Habilitado")
            else:
                print_check(f"HTTPS {setting_name}", False, "Deshabilitado")
                security_ok = False

    # Verificar CORS
    cors_origins = getattr(settings, 'CORS_ALLOWED_ORIGINS', [])
    if cors_origins:
        print_check("CORS origins", True, f"{len(cors_origins)} dominios configurados")
    else:
        print_check("CORS origins", False, "No configurados")
        security_ok = False

    # Verificar rate limiting
    rest_framework = getattr(settings, 'REST_FRAMEWORK', {})
    throttle_classes = rest_framework.get('DEFAULT_THROTTLE_CLASSES', [])
    if throttle_classes:
        print_check("Rate limiting", True, f"{len(throttle_classes)} clases configuradas")
    else:
        print_check("Rate limiting", False, "No configurado")
        security_ok = False

    return security_ok

def check_logging_configuration():
    """Verificar configuración de logging"""
    print_header("VERIFICACIÓN DE CONFIGURACIÓN DE LOGGING")

    logging_ok = True

    # Verificar que existe directorio de logs
    logs_dir = BASE_DIR / "logs"
    if logs_dir.exists():
        print_check("Directorio de logs", True, str(logs_dir))
    else:
        print_check("Directorio de logs", False, "No existe")
        logging_ok = False

    # Verificar configuración de loggers
    loggers_config = getattr(settings, 'LOGGING', {}).get('loggers', {})
    required_loggers = ['core', 'core.api', 'django.security']

    for logger_name in required_loggers:
        if logger_name in loggers_config:
            print_check(f"Logger {logger_name}", True, "Configurado")
        else:
            print_check(f"Logger {logger_name}", False, "No configurado")
            logging_ok = False

    return logging_ok

def run_django_checks():
    """Ejecutar verificaciones de Django"""
    print_header("VERIFICACIONES DE DJANGO")

    try:
        from django.core.management import call_command
        from io import StringIO

        # Ejecutar check --deploy
        output = StringIO()
        call_command('check', '--deploy', stdout=output)
        check_output = output.getvalue()

        if check_output.strip():
            print(f"{Colors.YELLOW}Advertencias de Django:{Colors.END}")
            print(check_output)
            return False
        else:
            print_check("Django checks", True, "Sin problemas detectados")
            return True

    except Exception as e:
        print_check("Django checks", False, str(e))
        return False

def main():
    """Función principal"""
    print(f"{Colors.BOLD}🚀 VALIDACIÓN DE CONFIGURACIÓN PARA PRODUCCIÓN{Colors.END}")
    print(f"{Colors.BOLD}Taller de Motos - Sistema de Gestión{Colors.END}")

    results = []

    # Ejecutar todas las verificaciones
    checks = [
        ("Variables de entorno", check_environment_variables),
        ("Conexión BD", check_database_connection),
        ("Conexión Cache", check_cache_connection),
        ("Servicios externos", check_external_services),
        ("Configuración seguridad", check_security_settings),
        ("Configuración logging", check_logging_configuration),
        ("Verificaciones Django", run_django_checks),
    ]

    for check_name, check_func in checks:
        try:
            result = check_func()
            results.append((check_name, result))
        except Exception as e:
            print(f"{Colors.RED}Error ejecutando {check_name}: {str(e)}{Colors.END}")
            results.append((check_name, False))

    # Resumen final
    print_header("RESUMEN FINAL")

    all_passed = True
    for check_name, result in results:
        status = "✓ PASÓ" if result else "✗ FALLÓ"
        color = Colors.GREEN if result else Colors.RED
        print(f"{color}{status}{Colors.END} - {check_name}")
        if not result:
            all_passed = False

    print_header("RESULTADO")

    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 ¡CONFIGURACIÓN LISTA PARA PRODUCCIÓN!{Colors.END}")
        print(f"{Colors.GREEN}Todas las verificaciones pasaron exitosamente.{Colors.END}")
        return 0
    else:
        print(f"{Colors.RED}{Colors.BOLD}❌ CONFIGURACIÓN INCOMPLETA{Colors.END}")
        print(f"{Colors.RED}Corrija los problemas identificados antes del despliegue.{Colors.END}")
        return 1

if __name__ == '__main__':
    sys.exit(main())