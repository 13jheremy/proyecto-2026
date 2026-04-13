from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from ..models import *
from datetime import timedelta
from django.utils import timezone


# ===== 1) Asignar rol a superusuario =====
@receiver(post_save, sender=Usuario)
def asignar_rol_superusuario(sender, instance, created, **kwargs):
    if created and instance.is_superuser:
        try:
            rol_admin, _ = Rol.objects.get_or_create(nombre="Administrador")
            UsuarioRol.objects.get_or_create(usuario=instance, rol=rol_admin)
        except Exception as e:
            import logging

            logging.getLogger(__name__).error(
                f"Error al asignar rol de administrador: {e}"
            )


# ===== 2) Crear inventario y movimiento al crear producto =====
@receiver(post_save, sender=Producto)
def crear_inventario_y_movimiento_producto(sender, instance, created, **kwargs):
    """
    Crea automáticamente un inventario y un movimiento de entrada 
    cuando se crea un nuevo producto.
    """
    if created:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Crear inventario con stock 0
            inventario = Inventario.objects.create(
                producto=instance,
                stock_actual=0,
                stock_minimo=0,
                activo=True
            )
            
            # Crear movimiento de entrada (stock inicial 0 = sin movimiento de entrada)
            # El movimiento se creará cuando se agregue stock via lote o inventario
            logger.info(f"Inventario creado para producto {instance.nombre}")
        except Exception as e:
            logger.error(f"Error al crear inventario para producto {instance.id}: {e}")


# ===== 2) Crear movimiento de inventario al crear inventario =====
@receiver(post_save, sender=Inventario)
def crear_movimiento_entrada_inventario(sender, instance, created, **kwargs):
    """
    Crea un movimiento de entrada cuando se crea un nuevo inventario
    con stock inicial mayor a 0.
    """
    if created and instance.stock_actual > 0:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            InventarioMovimiento.objects.create(
                inventario=instance,
                tipo="entrada",
                cantidad=instance.stock_actual,
                motivo=f"Inicialización de inventario para {instance.producto.nombre}",
                usuario=instance.creado_por if hasattr(instance, 'creado_por') else None,
            )
            logger.info(f"Movimiento de entrada creado para inventario ID {instance.id} - Producto: {instance.producto.nombre}")
        except Exception as e:
            logger.error(f"Error al crear movimiento de entrada para inventario {instance.id}: {e}")


# ===== 3) Crear movimiento de entrada al crear lote =====
@receiver(post_save, sender=Lote)
def crear_movimiento_entrada_lote(sender, instance, created, **kwargs):
    """
    Crea un movimiento de entrada cuando se crea un nuevo lote,
    representando una compra/ingreso de inventario.
    """
    if created and instance.cantidad_disponible > 0:
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            inventario = instance.producto.inventario
            InventarioMovimiento.objects.create(
                inventario=inventario,
                tipo="entrada",
                cantidad=instance.cantidad_disponible,
                motivo=f"Ingreso de lote #{instance.id} - {instance.producto.nombre}",
                usuario=instance.creado_por if hasattr(instance, 'creado_por') else None,
            )
            logger.info(f"Movimiento de entrada creado para lote ID {instance.id} - Producto: {instance.producto.nombre}")
        except Inventario.DoesNotExist:
            logger.warning(f"No existe inventario para producto {instance.producto.nombre}, no se crea movimiento")
        except Exception as e:
            logger.error(f"Error al crear movimiento de entrada para lote {instance.id}: {e}")


# ===== 2) Crear datos iniciales =====
@receiver(post_migrate)
def crear_datos_iniciales(sender, **kwargs):
    # Crear roles solo en app 'usuarios'
    if sender.name == "usuarios":
        roles = ["Administrador", "Empleado", "Tecnico", "Cliente"]
        for nombre in roles:
            Rol.objects.get_or_create(nombre=nombre)

    # Crear categorías de servicios solo en app 'servicios'
    if sender.name == "servicios":
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

    # Crear categorías de productos solo en app 'productos'
    if sender.name == "productos":
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


# Suponiendo que RecordatorioMantenimiento ya está importado


@receiver(post_save, sender=Mantenimiento)
def crear_recordatorio_desde_mantenimiento(sender, instance, created, **kwargs):
    """
    Delegate la creación de recordatorios al método generar_recordatorios()
    de DetalleMantenimiento, que ahora maneja toda la lógica correctamente:
    - Cambio de aceite y filtros: crea recordatorios por KM (usando km_proximo_cambio del usuario)
      y por fecha desde fecha_entrega
    - Mantenimiento general: crea recordatorio por fecha (60 días / 2 meses desde fecha_entrega)

    Solo se ejecutan cuando el mantenimiento está completado.
    """
    # Solo crear recordatorios cuando el mantenimiento está completado
    if not created or instance.estado != "completado":
        return

    import logging

    logger = logging.getLogger(__name__)

    # Delegar a cada detalle que llame a su propio método generar_recordatorios()
    for detalle in instance.detalles.all():
        try:
            detalle.generar_recordatorios()
            logger.info(f"Recordatorios generados para detalle {detalle.id}")
        except Exception as e:
            logger.error(
                f"Error al generar recordatorios para detalle {detalle.id}: {str(e)}"
            )
            continue  # Continuar con otros detalles si uno falla


@receiver(post_save, sender=Moto)
def crear_recordatorio_inicial_moto(sender, instance, created, **kwargs):
    """
    Al registrar una moto nueva, crea recordatorios iniciales para servicios
    periódicos predefinidos: cambio de aceite y filtros y mantenimiento general.
    """
    if created:
        from ..models import CategoriaServicio, RecordatorioMantenimiento
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
