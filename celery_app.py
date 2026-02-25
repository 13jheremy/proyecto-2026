import os
from celery import Celery
from django.conf import settings

# Configurar Django settings module para Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'taller_motos.settings')

app = Celery('taller_motos')

# Usar Django settings para configurar Celery
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodescubrir tareas en todas las apps instaladas
app.autodiscover_tasks()

# Configuración de tareas programadas
app.conf.beat_schedule = {
    # Recordatorios de mantenimiento - diariamente a las 9:00 AM
    'send-maintenance-reminders': {
        'task': 'core.tasks.send_maintenance_reminders',
        'schedule': 60.0 * 60.0 * 24.0,  # 24 horas
        'options': {'expires': 60.0 * 60.0 * 2.0}  # Expira en 2 horas
    },
    
    # Recordatorios de cambio de aceite - semanalmente los lunes a las 10:00 AM
    'send-oil-change-reminders': {
        'task': 'core.tasks.send_oil_change_reminders',
        'schedule': 60.0 * 60.0 * 24.0 * 7.0,  # 7 días
        'options': {'expires': 60.0 * 60.0 * 4.0}  # Expira en 4 horas
    },
    
    # Limpieza de tokens FCM inválidos - semanalmente los domingos a las 2:00 AM
    'cleanup-invalid-fcm-tokens': {
        'task': 'core.tasks.cleanup_invalid_fcm_tokens',
        'schedule': 60.0 * 60.0 * 24.0 * 7.0,  # 7 días
        'options': {'expires': 60.0 * 60.0 * 1.0}  # Expira en 1 hora
    },
    
    # Resumen semanal para administradores - viernes a las 5:00 PM
    'send-weekly-summary': {
        'task': 'core.tasks.send_weekly_maintenance_summary',
        'schedule': 60.0 * 60.0 * 24.0 * 7.0,  # 7 días
        'options': {'expires': 60.0 * 60.0 * 2.0}  # Expira en 2 horas
    },
}

app.conf.timezone = 'America/Bogota'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
