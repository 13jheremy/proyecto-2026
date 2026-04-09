"""
Servicios de lógica de negocio para Mantenimientos.

Este módulo contiene toda la lógica de negocio relacionada con el sistema
de mantenimiento de motorcycles, aislada de los modelos y vistas para
mantener una arquitectura limpia y reutilizable.

Funcionalidades:
- Creación y gestión de mantenimientos
- Control de estados y transiciones
- Cálculo automático de totales
- Validaciones de negocio
- Gestión de repuestos y servicios
"""

from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from core.models import (
    Mantenimiento,
    DetalleMantenimiento,
    RepuestoMantenimiento,
    RecordatorioMantenimiento,
    Moto,
    Servicio,
    Producto,
    Inventario,
)


class MantenimientoService:
    """
    Servicio para gestionar la lógica de negocio de mantenimientos.

    Proporciona métodos para:
    - Crear mantenimientos con validaciones
    - Gestionar el flujo de estados
    - Agregar servicios y repuestos
    - Calcular totales
    - Completar mantenimientos
    """

    # Transiciones de estado válidas
    TRANSICIONES_VALIDAS = {
        "pendiente": ["en_proceso", "cancelado"],
        "en_proceso": ["completado", "cancelado"],
        "completado": [],  # No se puede cambiar desde completado
        "cancelado": [],  # No se puede cambiar desde cancelado
    }

    @classmethod
    def crear_mantenimiento(cls, data, usuario=None):
        """
        Crea un nuevo mantenimiento con validaciones.

        Args:
            data: Dictionary con los datos del mantenimiento
            usuario: Usuario que crea el mantenimiento

        Returns:
            Mantenimiento: Instancia creada

        Raises:
            ValidationError: Si los datos no son válidos
        """
        # Validar moto existe
        moto_id = data.get("moto")
        if not moto_id:
            raise ValidationError("El mantenimiento debe estar asociado a una moto")

        try:
            moto = Moto.objects.get(id=moto_id)
        except Moto.DoesNotExist:
            raise ValidationError("La moto especificada no existe")

        # Validar kilometraje
        km_ingreso = data.get("kilometraje_ingreso")
        if km_ingreso is None:
            raise ValidationError("El kilometraje de ingreso es requerido")

        km_actual = moto.kilometraje or 0
        if km_ingreso < km_actual:
            raise ValidationError(
                f"El kilometraje de ingreso ({km_ingreso}) no puede ser menor "
                f"al kilometraje actual de la moto ({km_actual})"
            )

        # Crear mantenimiento
        mantenimiento = Mantenimiento.objects.create(
            moto=moto,
            tecnico_asignado=data.get("tecnico_asignado"),
            fecha_ingreso=data.get("fecha_ingreso"),
            fecha_entrega=data.get("fecha_entrega"),
            descripcion_problema=data.get("descripcion_problema"),
            diagnostico=data.get("diagnostico", ""),
            estado=data.get("estado", "pendiente"),
            kilometraje_ingreso=km_ingreso,
            tipo=data.get("tipo", "correctivo"),
            prioridad=data.get("prioridad", "media"),
            creado_por=usuario,
            actualizado_por=usuario,
        )

        # Agregar servicios si se proporcionan
        servicios_data = data.get("servicios", [])
        for servicio_data in servicios_data:
            cls.agregar_servicio(mantenimiento, servicio_data)

        # Agregar repuestos si se proporcionan
        repuestos_data = data.get("repuestos", [])
        for repuesto_data in repuestos_data:
            cls.agregar_repuesto(mantenimiento, repuesto_data)

        # Calcular total
        mantenimiento.calcular_total()

        return mantenimiento

    @classmethod
    def agregar_servicio(cls, mantenimiento, data):
        """
        Agrega un servicio a un mantenimiento.

        Args:
            mantenimiento: Instancia de Mantenimiento
            data: Dictionary con datos del servicio

        Returns:
            DetalleMantenimiento: Instancia creada
        """
        servicio_id = data.get("servicio") or data.get("servicio_id")
        if not servicio_id:
            raise ValidationError("El servicio es requerido")

        try:
            servicio = Servicio.objects.get(id=servicio_id)
        except Servicio.DoesNotExist:
            raise ValidationError("El servicio especificado no existe")

        # Usar precio del servicio o el proporcionado
        precio = data.get("precio", servicio.precio)

        detalle = DetalleMantenimiento.objects.create(
            mantenimiento=mantenimiento,
            servicio=servicio,
            precio=precio,
            observaciones=data.get("observaciones", ""),
            tipo_aceite=data.get("tipo_aceite"),
            km_proximo_cambio=data.get("km_proximo_cambio"),
        )

        # Crear recordatorio automáticamente si el servicio es de "cambio de aceite" o "mantenimiento general"
        cls._crear_recordatorio_si_aplica(mantenimiento, servicio, data)

        # Recalcular total
        mantenimiento.calcular_total()

        return detalle

    @classmethod
    def _crear_recordatorio_si_aplica(cls, mantenimiento, servicio, data):
        """
        Crea un recordatorio automáticamente si el servicio es de cambio de aceite
        o mantenimiento general.
        """
        from core.models import CategoriaServicio
        from datetime import timedelta

        nombre_categoria = servicio.categoria_servicio.nombre.lower() if servicio.categoria_servicio else ""
        
        # Categorías que generan recordatorio automático
        categorias_con_recordatorio = ["cambio de aceite", "mantenimiento general", "aceite", "mantenimiento"]
        
        # Verificar si la categoría del servicio genera recordatorio
        debe_crear = any(cat in nombre_categoria for cat in categorias_con_recordatorio)
        
        if not debe_crear:
            return  # No crear recordatorio

        # Obtener km_proximo del data o usar valores por defecto
        km_proximo = data.get("km_proximo")
        if not km_proximo:
            moto = mantenimiento.moto
            kilometraje_actual = kilometraje_salida = data.get("km_proximo_cambio")
            if kilometraje_actual:
                # Calcular próximo cambio: 5000km para aceite, 10000km para mantenimiento general
                km_adicional = 5000 if "aceite" in nombre_categoria else 10000
                km_proximo = kilometraje_actual + km_adicional
            elif moto.kilometraje:
                km_adicional = 5000 if "aceite" in nombre_categoria else 10000
                km_proximo = moto.kilometraje + km_adicional

        # Usar el tipo de recordatorio según la categoría
        tipo_recordatorio = "km" if km_proximo else "fecha"
        
        # Calcular fecha programada: 3 meses para aceite, 6 meses para mantenimiento general
        fecha_programada = None
        if not km_proximo:
            meses = 3 if "aceite" in nombre_categoria else 6
            fecha_programada = timezone.now().date() + timedelta(days=meses * 30)

        # Crear el recordatorio
        RecordatorioMantenimiento.objects.create(
            moto=mantenimiento.moto,
            categoria_servicio=servicio.categoria_servicio,
            tipo=tipo_recordatorio,
            km_proximo=km_proximo,
            fecha_programada=fecha_programada,
            notas=f"Recordatorio automático creado al realizar {servicio.nombre}"
        )

    @classmethod
    def agregar_repuesto(cls, mantenimiento, data, validar_stock=True):
        """
        Agrega un repuesto a un mantenimiento.

        Args:
            mantenimiento: Instancia de Mantenimiento
            data: Dictionary con datos del repuesto
            validar_stock: Si True, valida que haya stock disponible

        Returns:
            RepuestoMantenimiento: Instancia creada

        Raises:
            ValidationError: Si no hay stock o el producto no existe
        """
        producto_id = data.get("producto") or data.get("producto_id")
        if not producto_id:
            raise ValidationError("El producto es requerido")

        try:
            producto = Producto.objects.get(id=producto_id)
        except Producto.DoesNotExist:
            raise ValidationError("El producto especificado no existe")

        cantidad = data.get("cantidad", 1)
        precio_unitario = data.get("precio_unitario", producto.precio_venta)
        permitir_sin_stock = data.get("permitir_sin_stock", False)

        # Validar stock si es requerido
        if validar_stock and not permitir_sin_stock:
            try:
                inventario = producto.inventario
                if inventario.stock_actual < cantidad:
                    raise ValidationError(
                        f"Stock insuficiente. Disponible: {inventario.stock_actual}, "
                        f"Solicitado: {cantidad}"
                    )
            except Inventario.DoesNotExist:
                raise ValidationError("El producto no tiene inventario configurado")

        repuesto = RepuestoMantenimiento.objects.create(
            mantenimiento=mantenimiento,
            producto=producto,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            permitir_sin_stock=permitir_sin_stock,
        )

        # NOTA: El stock se descuenta al completar el mantenimiento, no al agregar
        # Esto permite que si se cancela el mantenimiento, el stock no se vea afectado

        # Recalcular total
        mantenimiento.calcular_total()

        return repuesto

    @classmethod
    def cambiar_estado(cls, mantenimiento, nuevo_estado, usuario=None):
        """
        Cambia el estado de un mantenimiento con validaciones.

        Args:
            mantenimiento: Instancia de Mantenimiento
            nuevo_estado: Nuevo estado a aplicar
            usuario: Usuario que realiza el cambio

        Returns:
            dict: {success: bool, message: str, mantenimiento: Mantenimiento}
        """
        # Validar transición
        transiciones = cls.TRANSICIONES_VALIDAS.get(mantenimiento.estado, [])
        if nuevo_estado not in transiciones:
            return {
                "success": False,
                "message": (
                    f"No se puede cambiar de '{mantenimiento.estado}' a '{nuevo_estado}'. "
                    f"Flujo válido: pendiente → en_proceso → completado"
                ),
                "mantenimiento": mantenimiento,
            }

        # Validar que tenga servicios o repuestos al completar
        if nuevo_estado == "completado" and not mantenimiento.tiene_items():
            return {
                "success": False,
                "message": "No se puede completar un mantenimiento sin servicios ni repuestos",
                "mantenimiento": mantenimiento,
            }

        # Guardar estado anterior
        estado_anterior = mantenimiento.estado

        # Realizar el cambio
        mantenimiento.estado = nuevo_estado

        # Si se completa
        if nuevo_estado == "completado":
            mantenimiento.fecha_completado = timezone.now()
            if usuario:
                mantenimiento.completado_por = usuario

            # Actualizar kilometraje de la moto si hay salida
            if (
                hasattr(mantenimiento, "kilometraje_salida")
                and mantenimiento.kilometraje_salida
            ):
                mantenimiento.moto.kilometraje = mantenimiento.kilometraje_salida
                mantenimiento.moto.save(update_fields=["kilometraje"])

            # Descontar stock de los repuestos usados
            for repuesto in mantenimiento.repuestos.all():
                if not repuesto.permitir_sin_stock:
                    try:
                        inventario = repuesto.producto.inventario
                        inventario.stock_actual -= repuesto.cantidad
                        inventario.save(update_fields=["stock_actual"])
                    except Inventario.DoesNotExist:
                        pass

        # Si se cancela, restaurar el stock de los repuestos
        if nuevo_estado == "cancelado" and estado_anterior != "cancelado":
            for repuesto in mantenimiento.repuestos.all():
                try:
                    inventario = repuesto.producto.inventario
                    inventario.stock_actual += repuesto.cantidad
                    inventario.save(update_fields=["stock_actual"])
                except Inventario.DoesNotExist:
                    pass

        if usuario:
            mantenimiento.actualizado_por = usuario

        mantenimiento.save()

        return {
            "success": True,
            "message": f"Estado cambiado de '{estado_anterior}' a '{nuevo_estado}'",
            "mantenimiento": mantenimiento,
        }

    @classmethod
    def completar_mantenimiento(
        cls, mantenimiento, usuario=None, kilometraje_salida=None
    ):
        """
        Completa un mantenimiento con todas las validaciones necesarias.

        Args:
            mantenimiento: Instancia de Mantenimiento
            usuario: Usuario que completa el mantenimiento
            kilometraje_salida: Kilometraje al salir la moto

        Returns:
            dict: {success: bool, message: str, mantenimiento: Mantenimiento}
        """
        # Validar que no esté ya completado
        if mantenimiento.estado == "completado":
            return {
                "success": False,
                "message": "El mantenimiento ya está completado",
                "mantenimiento": mantenimiento,
            }

        # Validar que tenga items
        if not mantenimiento.tiene_items():
            return {
                "success": False,
                "message": "No se puede completar un mantenimiento sin servicios ni repuestos",
                "mantenimiento": mantenimiento,
            }

        # Actualizar kilometraje si se proporciona
        if kilometraje_salida:
            mantenimiento.kilometraje_salida = kilometraje_salida

        # Realizar el cambio de estado
        resultado = cls.cambiar_estado(mantenimiento, "completado", usuario)

        return resultado

    @classmethod
    def eliminar_servicio(cls, detalle_id):
        """
        Elimina un servicio del mantenimiento.

        Args:
            detalle_id: ID del DetalleMantenimiento a eliminar

        Returns:
            dict: {success: bool, message: str}
        """
        try:
            detalle = DetalleMantenimiento.objects.get(id=detalle_id)
        except DetalleMantenimiento.DoesNotExist:
            return {"success": False, "message": "El detalle no existe"}

        mantenimiento = detalle.mantenimiento
        detalle.delete()

        # Recalcular total
        mantenimiento.calcular_total()

        return {"success": True, "message": "Servicio eliminado correctamente"}

    @classmethod
    def eliminar_repuesto(cls, repuesto_id):
        """
        Elimina un repuesto del mantenimiento.

        Args:
            repuesto_id: ID del RepuestoMantenimiento a eliminar

        Returns:
            dict: {success: bool, message: str}
        """
        try:
            repuesto = RepuestoMantenimiento.objects.get(id=repuesto_id)
        except RepuestoMantenimiento.DoesNotExist:
            return {"success": False, "message": "El repuesto no existe"}

        mantenimiento = repuesto.mantenimiento

        # Solo restaurar stock si el mantenimiento ya estaba completado
        # (ya que el stock se descuenta al completar, no al agregar)
        if mantenimiento.estado == "completado":
            try:
                inventario = repuesto.producto.inventario
                inventario.stock_actual += repuesto.cantidad
                inventario.save(update_fields=["stock_actual"])
            except Inventario.DoesNotExist:
                pass

        repuesto.delete()

        # Recalcular total
        mantenimiento.calcular_total()

        return {"success": True, "message": "Repuesto eliminado correctamente"}

    @classmethod
    def obtener_resumen_mantenimiento(cls, mantenimiento):
        """
        Obtiene un resumen completo del mantenimiento.

        Args:
            mantenimiento: Instancia de Mantenimiento

        Returns:
            dict: Resumen con todos los datos relevantes
        """
        return {
            "id": mantenimiento.id,
            "moto": {
                "id": mantenimiento.moto.id,
                "placa": mantenimiento.moto.placa,
                "marca": mantenimiento.moto.marca,
                "modelo": mantenimiento.moto.modelo,
                "kilometraje_actual": mantenimiento.moto.kilometraje,
            },
            "estado": mantenimiento.estado,
            "tipo": mantenimiento.tipo,
            "prioridad": mantenimiento.prioridad,
            "fecha_ingreso": mantenimiento.fecha_ingreso,
            "fecha_entrega": mantenimiento.fecha_entrega,
            "kilometraje_ingreso": mantenimiento.kilometraje_ingreso,
            "total": float(mantenimiento.total),
            "servicios_count": mantenimiento.detalles.count(),
            "repuestos_count": mantenimiento.repuestos.count(),
            "servicios": [
                {
                    "id": d.id,
                    "servicio": d.servicio.nombre,
                    "precio": float(d.precio),
                    "observaciones": d.observaciones,
                }
                for d in mantenimiento.detalles.all()
            ],
            "repuestos": [
                {
                    "id": r.id,
                    "producto": r.producto.nombre,
                    "cantidad": r.cantidad,
                    "precio_unitario": float(r.precio_unitario),
                    "subtotal": float(r.subtotal),
                }
                for r in mantenimiento.repuestos.all()
            ],
        }

    @classmethod
    def listar_mantenimientos_por_estado(cls, estado, **filtros):
        """
        Lista mantenimientos por estado con filtros adicionales.

        Args:
            estado: Estado de los mantenimientos
            **filtros: Filtros adicionales (moto, tecnico, fecha_desde, fecha_hasta, eliminado)

        Returns:
            QuerySet: Mantenimientos filtrados
        """
        qs = Mantenimiento.objects.filter(estado=estado)

        if "moto" in filtros:
            qs = qs.filter(moto=filtros["moto"])

        if "tecnico" in filtros:
            qs = qs.filter(tecnico_asignado=filtros["tecnico"])

        if "fecha_desde" in filtros:
            qs = qs.filter(fecha_ingreso__gte=filtros["fecha_desde"])

        if "fecha_hasta" in filtros:
            qs = qs.filter(fecha_ingreso__lte=filtros["fecha_hasta"])

        # Filtro por eliminado
        eliminado = filtros.get("eliminado")
        if eliminado is not None:
            if eliminado.lower() == "true":
                qs = qs.filter(eliminado=True)
            elif eliminado.lower() == "false":
                qs = qs.filter(eliminado=False)
            elif eliminado.lower() == "all":
                pass  # No aplicar filtro, mostrar todos
            else:
                # Valor por defecto: mostrar solo no eliminados
                qs = qs.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo mantenimientos NO eliminados
            qs = qs.filter(eliminado=False)

        return qs.select_related("moto", "tecnico_asignado").prefetch_related(
            "detalles", "repuestos"
        )

    @classmethod
    def obtener_mantenimientos(cls, **filtros):
        """
        Lista mantenimientos con filtros avanzados.
        Método principal que soporta filtrado por eliminado.

        Args:
            **filtros: Filtros disponibles
                - estado: Estado del mantenimiento (pendiente, en_proceso, completado, cancelado)
                - moto: ID de la moto
                - tecnico: ID del técnico asignado
                - fecha_desde: Fecha de inicio de filtro
                - fecha_hasta: Fecha de fin de filtro
                - eliminado: Filtro de eliminado (true/false/all)
                - buscar: Texto para búsqueda en descripción/problema

        Returns:
            QuerySet: Mantenimientos filtrados
        """
        # Usar objects_all para poder ver registros eliminados cuando sea necesario
        qs = Mantenimiento.objects_all.select_related(
            "moto__propietario", "tecnico_asignado"
        ).prefetch_related("detalles", "repuestos")

        # Filtro por estado
        estado = filtros.get("estado")
        if estado:
            qs = qs.filter(estado=estado)

        # Filtro por moto
        moto = filtros.get("moto")
        if moto:
            qs = qs.filter(moto=moto)

        # Filtro por técnico
        tecnico = filtros.get("tecnico")
        if tecnico:
            qs = qs.filter(tecnico_asignado=tecnico)

        # Filtro por fecha desde
        fecha_desde = filtros.get("fecha_desde")
        if fecha_desde:
            qs = qs.filter(fecha_ingreso__gte=fecha_desde)

        # Filtro por fecha hasta
        fecha_hasta = filtros.get("fecha_hasta")
        if fecha_hasta:
            qs = qs.filter(fecha_ingreso__lte=fecha_hasta)

        # Filtro por eliminado - Lógica idéntica a ServicioViewSet
        eliminado = filtros.get("eliminado")
        if eliminado is not None:
            if eliminado.lower() == "true":
                qs = qs.filter(eliminado=True)
            elif eliminado.lower() == "false":
                qs = qs.filter(eliminado=False)
            elif eliminado.lower() == "all":
                pass  # No aplicar filtro, mostrar todos
            else:
                # Valor por defecto: mostrar solo no eliminados
                qs = qs.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo mantenimientos NO eliminados
            qs = qs.filter(eliminado=False)

        # Filtro por búsqueda
        buscar = filtros.get("buscar")
        if buscar:
            qs = qs.filter(
                Q(descripcion_problema__icontains=buscar)
                | Q(diagnostico__icontains=buscar)
            )

        # Ordenar por fecha de ingreso descendente
        qs = qs.order_by("-fecha_ingreso")

        return qs

    @classmethod
    def obtener_eliminados(cls, **filtros):
        """
        Lista mantenimientos eliminados (soft delete).
        Método específico para obtener solo registros eliminados.

        Args:
            **filtros: Filtros adicionales opcionales
                - moto: ID de la moto
                - tecnico: ID del técnico asignado
                - fecha_desde: Fecha de inicio de filtro
                - fecha_hasta: Fecha de fin de filtro

        Returns:
            QuerySet: Mantenimientos eliminados
        """
        # Usar objects_all para incluir eliminados
        qs = (
            Mantenimiento.objects_all.select_related(
                "moto__propietario", "tecnico_asignado", "eliminado_por"
            )
            .prefetch_related("detalles", "repuestos")
            .filter(eliminado=True)
        )

        # Filtro por moto
        moto = filtros.get("moto")
        if moto:
            qs = qs.filter(moto=moto)

        # Filtro por técnico
        tecnico = filtros.get("tecnico")
        if tecnico:
            qs = qs.filter(tecnico_asignado=tecnico)

        # Filtro por fecha desde
        fecha_desde = filtros.get("fecha_desde")
        if fecha_desde:
            qs = qs.filter(fecha_eliminacion__gte=fecha_desde)

        # Filtro por fecha hasta
        fecha_hasta = filtros.get("fecha_hasta")
        if fecha_hasta:
            qs = qs.filter(fecha_eliminacion__lte=fecha_hasta)

        # Ordenar por fecha de eliminación descendente
        qs = qs.order_by("-fecha_eliminacion")

        return qs

    @classmethod
    def restaurar_mantenimiento(cls, mantenimiento_id):
        """
        Restaura un mantenimiento eliminado (soft delete).

        Args:
            mantenimiento_id: ID del mantenimiento a restaurar

        Returns:
            dict: {success: bool, message: str, mantenimiento: Mantenimiento}
        """
        try:
            # Usar objects_all para poder encontrar registros eliminados
            mantenimiento = Mantenimiento.objects_all.get(id=mantenimiento_id)
        except Mantenimiento.DoesNotExist:
            return {
                "success": False,
                "message": "El mantenimiento no existe",
                "mantenimiento": None,
            }

        # Verificar que está eliminado
        if not mantenimiento.eliminado:
            return {
                "success": False,
                "message": "El mantenimiento no está eliminado",
                "mantenimiento": mantenimiento,
            }

        # Restaurar el registro
        mantenimiento.eliminado = False
        mantenimiento.fecha_eliminacion = None
        if hasattr(mantenimiento, "eliminado_por"):
            mantenimiento.eliminado_por = None

        mantenimiento.save(
            update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
        )

        return {
            "success": True,
            "message": "Mantenimiento restaurado correctamente",
            "mantenimiento": mantenimiento,
        }

    @classmethod
    def eliminar_mantenimiento(cls, mantenimiento_id, usuario=None):
        """
        Elimina lógicamente un mantenimiento (soft delete).

        Args:
            mantenimiento_id: ID del mantenimiento a eliminar
            usuario: Usuario que realiza la eliminación

        Returns:
            dict: {success: bool, message: str, mantenimiento: Mantenimiento}
        """
        try:
            mantenimiento = Mantenimiento.objects.get(id=mantenimiento_id)
        except Mantenimiento.DoesNotExist:
            return {
                "success": False,
                "message": "El mantenimiento no existe",
                "mantenimiento": None,
            }

        # Verificar que no esté ya eliminado
        if mantenimiento.eliminado:
            return {
                "success": False,
                "message": "El mantenimiento ya está eliminado",
                "mantenimiento": mantenimiento,
            }

        # Realizar soft delete
        mantenimiento.eliminado = True
        mantenimiento.fecha_eliminacion = timezone.now()
        if usuario and hasattr(mantenimiento, "eliminado_por"):
            mantenimiento.eliminado_por = usuario

        mantenimiento.save(
            update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
        )

        return {
            "success": True,
            "message": "Mantenimiento eliminado correctamente",
            "mantenimiento": mantenimiento,
        }


class RecordatorioService:
    """
    Servicio para gestionar recordatorios de mantenimiento.
    """

    @classmethod
    def obtener_proximos_recordatorios(cls, dias_antes=7, limite=50):
        """
        Obtiene los recordatorios próximos a vencer.

        Args:
            dias_antes: Días de anticipación
            limite: Límite de resultados

        Returns:
            list: Recordatorios próximos
        """
        from datetime import timedelta

        fecha_limite = timezone.now().date() + timedelta(days=dias_antes)

        recordatorios = RecordatorioMantenimiento.objects.filter(
            activo=True,
            fecha_programada__lte=fecha_limite,
        ).select_related("moto", "categoria_servicio")[:limite]

        resultados = []
        for r in recordatorios:
            info = r.proximo(dias_antes)
            resultados.append(
                {
                    "id": r.id,
                    "moto": r.moto.placa,
                    "categoria": r.categoria_servicio.nombre,
                    "tipo": r.tipo,
                    "fecha_programada": r.fecha_programada,
                    "km_proximo": r.km_proximo,
                    "alerta": info["alerta"],
                    "mensaje": info["mensaje"],
                }
            )

        return resultados

    @classmethod
    def obtener_recordatorios_por_km(cls, moto_id, limite=10):
        """
        Obtiene los recordatorios por kilometraje para una moto.

        Args:
            moto_id: ID de la moto
            limite: Límite de resultados

        Returns:
            list: Recordatorios por km
        """
        moto = Moto.objects.get(id=moto_id)
        km_actual = moto.kilometraje or 0

        recordatorios = RecordatorioMantenimiento.objects.filter(
            moto=moto,
            tipo="km",
            activo=True,
        ).select_related("categoria_servicio")[:limite]

        resultados = []
        for r in recordatorios:
            km_faltantes = (r.km_proximo or 0) - km_actual
            resultados.append(
                {
                    "id": r.id,
                    "categoria": r.categoria_servicio.nombre,
                    "km_proximo": r.km_proximo,
                    "km_actual": km_actual,
                    "km_faltantes": km_faltantes,
                    "alerta": 0 < km_faltantes <= 500,
                }
            )

        return resultados

    @classmethod
    def generar_recordatorio_manual(cls, data, usuario=None):
        """
        Genera un recordatorio manualmente.

        Args:
            data: Datos del recordatorio
            usuario: Usuario que crea el recordatorio

        Returns:
            RecordatorioMantenimiento: Instancia creada
        """
        moto_id = data.get("moto")
        categoria_id = data.get("categoria_servicio")

        if not moto_id or not categoria_id:
            raise ValidationError("Moto y categoría son requeridos")

        return RecordatorioMantenimiento.objects.create(
            moto_id=moto_id,
            categoria_servicio_id=categoria_id,
            tipo=data.get("tipo", "fecha"),
            fecha_programada=data.get("fecha_programada"),
            km_proximo=data.get("km_proximo"),
            registrado_por=usuario,
            notas=data.get("notas", ""),
        )
