from django.db.models.signals import post_save, post_delete, post_migrate
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
        "Mantenimiento general",
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
    Crea recordatorios automáticos SOLO para servicios específicos:
    - Cambio de aceite y filtros: cada 90 días
    - Mantenimiento general: cada 2 meses (60 días) desde la fecha de entrega

    Solo se ejecutan cuando el mantenimiento está completado.
    """
    # Solo crear recordatorios cuando el mantenimiento está completado
    if not created or instance.estado != "completado":
        return

    import logging

    logger = logging.getLogger(__name__)

    # Categorías válidas para recordatorios automáticos
    CATEGORIAS_VALIDAS = ["cambio de aceite y filtros", "mantenimiento general"]

    for detalle in instance.detalles.all():
        try:
            categoria = detalle.servicio.categoria_servicio
            nombre_categoria = categoria.nombre.lower()

            # Solo crear recordatorios para las categorías específicas
            if nombre_categoria not in CATEGORIAS_VALIDAS:
                logger.debug(
                    f"Saltando recordatorio para categoría: {categoria.nombre} "
                    f"(no es cambio de aceite y filtros ni mantenimiento general)"
                )
                continue

            # Determinar intervalo según categoría
            if nombre_categoria == "cambio de aceite y filtros":
                dias_para_proximo = 90  # 3 meses
            elif nombre_categoria == "mantenimiento general":
                dias_para_proximo = 60  # 2 meses
            else:
                dias_para_proximo = 60  # Default para servicios específicos

            # Usar fecha de entrega si existe, si no usar fecha de ingreso
            fecha_base = (
                instance.fecha_entrega.date()
                if instance.fecha_entrega
                else instance.fecha_ingreso.date()
            )
            fecha_proximo = fecha_base + timedelta(days=dias_para_proximo)

            # ✅ VERIFICAR SI YA EXISTE recordatorio activo para evitar duplicados
            existente = RecordatorioMantenimiento.objects.filter(
                moto=instance.moto,
                categoria_servicio=categoria,
                tipo="fecha",
                activo=True,
            ).first()

            if existente:
                # Actualizar fecha existente
                existente.fecha_programada = fecha_proximo
                existente.enviado = False  # Resetear para reenviar
                existente.save()
                logger.info(
                    f"Recordatorio actualizado para moto {instance.moto.placa} - {categoria.nombre}"
                )
            else:
                # Crear nuevo recordatorio
                RecordatorioMantenimiento.objects.create(
                    moto=instance.moto,
                    categoria_servicio=categoria,
                    fecha_programada=fecha_proximo,
                    tipo="fecha",
                )
                logger.info(
                    f"Recordatorio creado para moto {instance.moto.placa} - {categoria.nombre}"
                )

        except Exception as e:
            logger.error(f"Error al crear recordatorio desde mantenimiento: {str(e)}")
            continue  # Continuar con otros detalles si uno falla


@receiver(post_save, sender=Moto)
def crear_recordatorio_inicial_moto(sender, instance, created, **kwargs):
    """
    Al registrar una moto nueva, crea recordatorios iniciales para servicios
    periódicos predefinidos: cambio de aceite y filtros y mantenimiento general.
    """
    if created:
        # Ejemplo: buscar categoría "Cambio de aceite"
        from .models import CategoriaServicio, RecordatorioMantenimiento
        import logging

        logger = logging.getLogger(__name__)

        # Categorías para crear recordatorios iniciales
        categorias_iniciales = [
            ("Cambio de aceite y filtros", 90),  # 3 meses
            ("Mantenimiento general", 60),  # 2 meses
        ]

        for nombre_categoria, dias in categorias_iniciales:
            try:
                categoria = CategoriaServicio.objects.get(
                    nombre__iexact=nombre_categoria
                )
                fecha_proximo = timezone.now().date() + timedelta(days=dias)

                # ✅ VERIFICAR SI YA EXISTE recordatorio activo para evitar duplicados
                existente = RecordatorioMantenimiento.objects.filter(
                    moto=instance,
                    categoria_servicio=categoria,
                    tipo="fecha",
                    activo=True,
                ).first()

                if existente:
                    # Actualizar fecha existente
                    existente.fecha_programada = fecha_proximo
                    existente.enviado = False
                    existente.save()
                    logger.info(
                        f"Recordatorio inicial actualizado para moto {instance.placa} - {categoria.nombre}"
                    )
                else:
                    # Crear nuevo recordatorio
                    RecordatorioMantenimiento.objects.create(
                        moto=instance,
                        categoria_servicio=categoria,
                        fecha_programada=fecha_proximo,
                        tipo="fecha",
                    )
                    logger.info(
                        f"Recordatorio inicial creado para moto {instance.placa} - {categoria.nombre}"
                    )

            except CategoriaServicio.DoesNotExist:
                logger.warning(
                    f"No se encontró categoría '{nombre_categoria}' para crear recordatorio inicial de moto {instance.placa}"
                )
            except Exception as e:
                logger.error(
                    f"Error al crear recordatorio inicial para moto {instance.placa}: {str(e)}"
                )


# =======================================
# SEÑALES DE MANTENIMIENTO (AUTOMATIZACIÓN)
# =======================================


@receiver(post_save, sender=DetalleMantenimiento)
def recalcular_total_desde_detalle(sender, instance, created, **kwargs):
    """
    Recalcula el total del mantenimiento cuando se agrega/modifica un servicio.

    Se ejecuta después de guardar un DetalleMantenimiento.
    """
    try:
        mantenimiento = instance.mantenimiento
        mantenimiento.calcular_total()
    except Exception as e:
        # Loguear error pero no interrumpir
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al recalcular total desde detalle: {e}")


@receiver(post_delete, sender=DetalleMantenimiento)
def recalcular_total_al_eliminar_detalle(sender, instance, **kwargs):
    """
    Recalcula el total del mantenimiento cuando se elimina un servicio.

    Se ejecuta después de eliminar un DetalleMantenimiento.
    """
    try:
        # Usar el ID porque la instancia ya fue eliminada
        from .models import Mantenimiento

        mantenimiento = Mantenimiento.objects.get(id=instance.mantenimiento_id)
        mantenimiento.calcular_total()
    except Mantenimiento.DoesNotExist:
        pass
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al recalcular total al eliminar detalle: {e}")


@receiver(post_save, sender=RepuestoMantenimiento)
def recalcular_total_desde_repuesto(sender, instance, created, **kwargs):
    """
    Recalcula el total del mantenimiento cuando se agrega/modifica un repuesto.

    Se ejecuta después de guardar un RepuestoMantenimiento.
    """
    try:
        mantenimiento = instance.mantenimiento
        mantenimiento.calcular_total()
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al recalcular total desde repuesto: {e}")


@receiver(post_delete, sender=RepuestoMantenimiento)
def recalcular_total_al_eliminar_repuesto(sender, instance, **kwargs):
    """
    Recalcula el total del mantenimiento cuando se elimina un repuesto.

    Se ejecuta después de eliminar un RepuestoMantenimiento.
    """
    try:
        from .models import Mantenimiento

        mantenimiento = Mantenimiento.objects.get(id=instance.mantenimiento_id)
        mantenimiento.calcular_total()
    except Mantenimiento.DoesNotExist:
        pass
    except Exception as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Error al recalcular total al eliminar repuesto: {e}")


@receiver(post_save, sender=Mantenimiento)
def actualizar_estado_moto_al_completar(sender, instance, created, **kwargs):
    """
    Actualiza el kilometraje de la moto cuando se completa un mantenimiento.

    Solo se ejecuta cuando el mantenimiento cambia a estado 'completado'.
    """
    if not created and instance.estado == "completado":
        # Verificar si hay un kilometraje de salida
        if hasattr(instance, "kilometraje_salida") and instance.kilometraje_salida:
            try:
                moto = instance.moto
                moto.kilometraje = instance.kilometraje_salida
                moto.save(update_fields=["kilometraje"])
            except Exception as e:
                import logging

                logger = logging.getLogger(__name__)
                logger.error(f"Error al actualizar kilometraje de moto: {e}")
