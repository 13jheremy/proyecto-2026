from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from .models import *
from datetime import timedelta
from django.utils import timezone


# Este decorador conecta la función con la señal post_save
@receiver(post_save, sender=Usuario)
def asignar_rol_superusuario(sender, instance, created, **kwargs):
    # La lógica para asignar el rol solo si el usuario es nuevo y un superusuario
    if created and instance.is_superuser:
        try:
            # Asegura que el rol "Administrador" exista antes de asignarlo
            rol_admin, _ = Rol.objects.get_or_create(nombre="Administrador")
            # Usa get_or_create para evitar errores si el usuario ya tiene el rol
            UsuarioRol.objects.get_or_create(usuario=instance, rol=rol_admin)
        except Exception:
            pass


# Este decorador conecta la función con la señal post_migrate
@receiver(post_migrate)
def crear_datos_iniciales(sender, **kwargs):
    # Importaciones de modelos dentro de la función para evitar problemas de dependencia
    # con migraciones.

    # Roles (primero)
    roles = ["Administrador", "Empleado", "Tecnico", "Cliente"]
    for nombre in roles:
        Rol.objects.get_or_create(nombre=nombre)
    # Debug prints removed

    # Categorías de servicios (segundo)
    categorias_servicio = [
        "Cambio de aceite y filtros",
        "Revisión general de la moto",
        "Arreglo del motor",
        "Reparación de sistema eléctrico (luces, batería, encendido)",
        "Frenos (cambio y ajuste de pastillas, discos o tambor)",
        "Suspensión y dirección (amortiguadores, horquillas)",
        "Cambio y reparación de llantas (neumáticos y cámaras)",
        "Instalación de accesorios (portaequipajes, luces extra, baúles)",
        "Seguridad (colocación de alarmas, mantenimiento de frenos ABS)",
        "Lavado y limpieza completa",
    ]
    for nombre in categorias_servicio:
        CategoriaServicio.objects.get_or_create(nombre=nombre)
    # Debug prints removed

    # Categorías de productos (tercero)
    categorias_producto = [
        "Motor y componentes",
        "Sistema eléctrico y encendido",
        "Transmisión y tracción",
        "Frenos",
        "Suspensión y dirección",
        "Carrocería y accesorios",
        "Neumáticos y ruedas",
        "Lubricantes y químicos",
        "Escape y admisión",
        "Seguridad y protección (cascos, guantes, chalecos, protecciones)",
    ]
    for nombre in categorias_producto:
        Categoria.objects.get_or_create(nombre=nombre)
    # Debug prints removed


# Suponiendo que RecordatorioMantenimiento ya está importado


@receiver(post_save, sender=Mantenimiento)
def crear_recordatorio_desde_mantenimiento(sender, instance, created, **kwargs):
    """
    Crea recordatorios automáticos para próximos mantenimientos o cambios de aceite
    según los servicios realizados en este mantenimiento.
    """
    if created:
        for detalle in instance.detalles.all():
            categoria = detalle.servicio.categoria_servicio

            # Definir intervalos según categoría
            if categoria.nombre.lower() == "Cambio de aceite y filtros":
                dias_para_proximo = 90  # ejemplo: cada 90 días
            else:
                dias_para_proximo = 180  # ejemplo: cada 6 meses para otros servicios

            fecha_proximo = instance.fecha_ingreso.date() + timedelta(
                days=dias_para_proximo
            )

            # Crear recordatorio
            RecordatorioMantenimiento.objects.create(
                moto=instance.moto,
                categoria_servicio=categoria,
                fecha_programada=fecha_proximo,
            )


@receiver(post_save, sender=Moto)
def crear_recordatorio_inicial_moto(sender, instance, created, **kwargs):
    """
    Opcional: al registrar una moto nueva, se pueden crear recordatorios iniciales
    para servicios periódicos predefinidos (ej: cambio de aceite).
    """
    if created:
        # Ejemplo: buscar categoría "Cambio de aceite"
        from .models import CategoriaServicio, RecordatorioMantenimiento

        try:
            categoria_aceite = CategoriaServicio.objects.get(
                nombre__iexact="Cambio de aceite y filtros"
            )
            fecha_proximo = timezone.now().date() + timedelta(days=90)
            RecordatorioMantenimiento.objects.create(
                moto=instance,
                categoria_servicio=categoria_aceite,
                fecha_programada=fecha_proximo,
            )
        except CategoriaServicio.DoesNotExist:
            pass
