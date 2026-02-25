# tasks.py
from django.utils import timezone
from datetime import timedelta
from models import RecordatorioMantenimiento
from models import Dispositivo
from .utils import enviar_notificacion


def notificar_recordatorios(dias_antes=7):
    """
    Envía notificaciones push de recordatorios de mantenimiento próximos.
    - dias_antes: cuántos días antes de la fecha_programada se envía la notificación.
    """
    hoy = timezone.now().date()
    limite = hoy + timedelta(days=dias_antes)

    # Traer solo recordatorios próximos y que no hayan sido enviados
    recordatorios = RecordatorioMantenimiento.objects.filter(
        fecha_programada__range=(hoy, limite), enviado=False
    ).select_related("moto", "categoria_servicio", "moto__propietario")

    for r in recordatorios:
        # Verificar que la moto tenga propietario asignado
        if not hasattr(r.moto, "propietario") or r.moto.propietario is None:
            continue  # saltar si no hay propietario

        usuario = r.moto.propietario
        tokens = Dispositivo.objects.filter(usuario=usuario).values_list(
            "token", flat=True
        )

        if not tokens:
            continue  # saltar si el usuario no tiene dispositivos registrados

        for token in tokens:
            try:
                enviar_notificacion(
                    token=token,
                    titulo="Recordatorio de Mantenimiento",
                    mensaje=f"Tu moto {r.moto} necesita {r.categoria_servicio.nombre} el {r.fecha_programada.strftime('%d/%m/%Y')}",
                    data={
                        "moto_id": str(r.moto.id),
                        "categoria_servicio": r.categoria_servicio.nombre,
                    },
                )
            except Exception as e:
                # Aquí puedes registrar el error en logs sin detener la tarea
                print(f"Error enviando notificación a token {token}: {e}")

        # Marcar como enviado solo si al menos un token fue procesado
        r.enviado = True
        r.save()
