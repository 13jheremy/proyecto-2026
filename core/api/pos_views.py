# =======================================
# POS SYSTEM - ENHANCED VIEWS
# =======================================
# Comprehensive POS system for motorcycle workshop
# - Sales with automatic inventory management
# - Service/maintenance with parts tracking
# - Real-time inventory updates
# - PDF receipt generation
# =======================================

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, F, Sum
from decimal import Decimal
import logging
from datetime import datetime, timedelta

from ..models import *
from .serializers import *

logger = logging.getLogger(__name__)


# =======================================
# POS SALES ENDPOINTS
# =======================================


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crear_venta_pos(request):
    """
    Crear venta completa desde POS con actualización automática de inventario
    """
    try:
        with transaction.atomic():
            # Validar datos de entrada
            cliente_id = request.data.get("cliente_id")
            productos = request.data.get("productos", [])
            impuesto_porcentaje = Decimal(
                str(request.data.get("impuesto_porcentaje", 0))
            )
            metodo_pago = request.data.get("metodo_pago", "EFECTIVO")

            if not cliente_id:
                return Response(
                    {"error": "Cliente es requerido"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not productos:
                return Response(
                    {"error": "Debe agregar al menos un producto"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verificar cliente existe
            try:
                cliente = Persona.objects.get(id=cliente_id, eliminado=False)
            except Persona.DoesNotExist:
                return Response(
                    {"error": "Cliente no encontrado"}, status=status.HTTP_404_NOT_FOUND
                )

            # Validar disponibilidad de productos y calcular totales
            subtotal = Decimal("0.00")
            productos_validados = []

            for item in productos:
                producto_id = item.get("producto_id")
                cantidad = int(item.get("cantidad", 0))
                precio_unitario = Decimal(str(item.get("precio_unitario", 0)))

                if cantidad <= 0:
                    return Response(
                        {"error": f"Cantidad debe ser mayor a 0"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    producto = Producto.objects.get(
                        id=producto_id, eliminado=False, activo=True
                    )
                except Producto.DoesNotExist:
                    return Response(
                        {"error": f"Producto no encontrado o inactivo"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Verificar inventario disponible
                try:
                    inventario = Inventario.objects.get(producto=producto)
                    if inventario.stock_actual < cantidad:
                        return Response(
                            {
                                "error": f"Stock insuficiente para {producto.nombre}. Disponible: {inventario.stock_actual}"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                except Inventario.DoesNotExist:
                    return Response(
                        {
                            "error": f"No hay inventario configurado para {producto.nombre}"
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                item_subtotal = cantidad * precio_unitario
                subtotal += item_subtotal

                productos_validados.append(
                    {
                        "producto": producto,
                        "inventario": inventario,
                        "cantidad": cantidad,
                        "precio_unitario": precio_unitario,
                        "subtotal": item_subtotal,
                    }
                )

            # Calcular impuesto y total
            impuesto = subtotal * (impuesto_porcentaje / Decimal("100"))
            total = subtotal + impuesto

            # Crear venta en estado PENDIENTE inicialmente
            venta = Venta.objects.create(
                cliente=cliente,
                fecha_venta=timezone.now(),
                subtotal=subtotal,
                impuesto=impuesto,
                total=total,
                estado="PENDIENTE",
                registrado_por=request.user,
            )

            # Crear detalles de venta (sin descontar stock aún)
            for item in productos_validados:
                DetalleVenta.objects.create(
                    venta=venta,
                    producto=item["producto"],
                    cantidad=item["cantidad"],
                    precio_unitario=item["precio_unitario"],
                    subtotal=item["subtotal"],
                )

            # Si se proporciona método de pago, crear el pago
            # (esto automáticamente cambiará el estado a PAGADA y descontará stock)
            if metodo_pago:
                Pago.objects.create(
                    venta=venta,
                    monto=total,
                    metodo=metodo_pago,
                    registrado_por=request.user,
                )
                # Recargar la venta para obtener el estado actualizado
                venta.refresh_from_db()

            # Preparar respuesta
            response_data = {
                "success": True,
                "venta_id": venta.id,
                "numero_venta": venta.id,
                "message": "Venta procesada exitosamente",
                "cliente": {
                    "id": cliente.id,
                    "nombre_completo": cliente.nombre_completo,
                    "cedula": cliente.cedula,
                    "telefono": cliente.telefono,
                },
                "fecha_venta": venta.fecha_venta.isoformat(),
                "subtotal": str(venta.subtotal),
                "impuesto": str(venta.impuesto),
                "total": str(venta.total),
                "estado": venta.estado,
                "metodo_pago": metodo_pago if metodo_pago else None,
                "productos": [
                    {
                        "producto_id": item["producto"].id,
                        "nombre": item["producto"].nombre,
                        "cantidad": item["cantidad"],
                        "precio_unitario": str(item["precio_unitario"]),
                        "subtotal": str(item["subtotal"]),
                    }
                    for item in productos_validados
                ],
            }

            logger.info(
                f"Venta POS creada #{venta.id} por usuario {request.user.username}"
            )
            return Response(response_data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error procesando venta POS: {str(e)}")
        return Response(
            {"error": f"Error interno del servidor: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def registrar_pago_venta(request):
    """
    Registra un pago para una venta existente.
    Casos de uso:
    - Pagos posteriores para ventas a crédito
    - Pagos parciales
    - Completar el pago de una venta pendiente
    """
    try:
        data = request.data
        logger.info(f"Registrando pago: {data}")

        # Validar datos requeridos
        venta_id = data.get("venta")
        metodo = data.get("metodo", "EFECTIVO")
        monto = data.get("monto")

        if not venta_id:
            return Response(
                {"error": "El ID de la venta es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not monto:
            return Response(
                {"error": "El monto del pago es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            monto = Decimal(str(monto))
            if monto <= 0:
                return Response(
                    {"error": "El monto debe ser mayor a 0"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except (ValueError, TypeError):
            return Response(
                {"error": "El monto debe ser un número válido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Buscar la venta
        try:
            venta = Venta.objects.get(id=venta_id, eliminado=False)
        except Venta.DoesNotExist:
            return Response(
                {"error": "Venta no encontrada"}, status=status.HTTP_404_NOT_FOUND
            )

        # Verificar que la venta no esté anulada
        if venta.estado == "ANULADA":
            return Response(
                {"error": "No se puede registrar pago en una venta anulada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar que no se exceda el monto total
        total_pagado_actual = sum(p.monto for p in venta.pagos.all())
        if total_pagado_actual + monto > venta.total:
            return Response(
                {
                    "error": f"El pago excede el monto pendiente. Saldo pendiente: {venta.total - total_pagado_actual}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Crear el pago (esto automáticamente actualizará el estado y stock si es necesario)
        pago = Pago.objects.create(
            venta=venta, monto=monto, metodo=metodo, registrado_por=request.user
        )

        # Recargar la venta para obtener el estado actualizado
        venta.refresh_from_db()

        # Preparar respuesta
        response_data = {
            "success": True,
            "pago_id": pago.id,
            "venta_id": venta.id,
            "message": "Pago registrado exitosamente",
            "pago": {
                "id": pago.id,
                "monto": str(pago.monto),
                "metodo": pago.metodo,
                "fecha_pago": pago.fecha_pago.isoformat(),
            },
            "venta": {
                "id": venta.id,
                "estado": venta.estado,
                "total": str(venta.total),
                "pagado": str(venta.pagado),
                "saldo": str(venta.saldo),
            },
        }

        logger.info(
            f"Pago registrado #{pago.id} para venta #{venta.id} por usuario {request.user.username}"
        )
        return Response(response_data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error registrando pago: {str(e)}")
        return Response(
            {"error": f"Error interno del servidor: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buscar_productos_pos(request):
    """
    Búsqueda avanzada de productos para POS con información de stock
    """
    try:
        query = request.GET.get("q", "").strip()
        categoria_id = request.GET.get("categoria_id")
        solo_con_stock = request.GET.get("solo_con_stock", "true").lower() == "true"

        if not query and not categoria_id:
            return Response({"results": []})

        # Construir filtros
        filters = Q(eliminado=False, activo=True)

        if query:
            # Determinar si es una búsqueda por ID (número) o texto
            if query.isdigit():
                # Búsqueda por ID exacto
                filters &= Q(id=int(query))
            else:
                # Búsqueda por texto (nombre o descripción)
                filters &= (
                    Q(nombre__icontains=query)
                    | Q(descripcion__icontains=query)
                )

        if categoria_id:
            filters &= Q(categoria_id=categoria_id)

        # Obtener productos con inventario
        productos = Producto.objects.filter(filters).select_related(
            "categoria", "proveedor", "inventario"
        )[:20]

        results = []
        for producto in productos:
            try:
                inventario = producto.inventario
                stock_actual = inventario.stock_actual
                stock_minimo = inventario.stock_minimo
            except Inventario.DoesNotExist:
                stock_actual = 0
                stock_minimo = 0

            # Filtrar por stock si es necesario
            if solo_con_stock and stock_actual <= 0:
                continue

            # Determinar estado del stock
            if stock_actual <= 0:
                stock_status = "sin_stock"
                stock_color = "red"
            elif stock_actual <= stock_minimo:
                stock_status = "stock_bajo"
                stock_color = "yellow"
            else:
                stock_status = "stock_normal"
                stock_color = "green"

            results.append(
                {
                    "id": producto.id,
                    "nombre": producto.nombre,
                    "descripcion": producto.descripcion,
                    "precio_venta": str(producto.precio_venta),
                    "stock_actual": stock_actual,
                    "stock_minimo": stock_minimo,
                    "stock_status": stock_status,
                    "stock_color": stock_color,
                    "categoria": {
                        "id": producto.categoria.id,
                        "nombre": producto.categoria.nombre,
                    },
                    "imagen_url": producto.imagen.url if producto.imagen else None,
                    "disponible": stock_actual > 0,
                }
            )

        return Response({"success": True, "data": results, "status": 200})

    except Exception as e:
        logger.error(f"Error en búsqueda de productos POS: {str(e)}")
        return Response(
            {"error": "Error al buscar productos"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buscar_clientes_pos(request):
    """
    Búsqueda de clientes para POS
    Solo retorna personas que tienen el rol de 'cliente'
    """
    try:
        query = request.GET.get("q", "").strip()

        if not query:
            return Response({"results": []})

        # Buscar personas (clientes) que tienen el rol de 'cliente'
        personas = Persona.objects.filter(
            Q(nombre__icontains=query)
            | Q(apellido__icontains=query)
            | Q(cedula__icontains=query)
            | Q(telefono__icontains=query),
            eliminado=False,
            usuario__roles__rol__nombre__iexact="cliente",
            usuario__roles__activo=True,
        ).distinct()[:10]

        results = []
        for persona in personas:
            results.append(
                {
                    "id": persona.id,
                    "nombre_completo": persona.nombre_completo,
                    "cedula": persona.cedula,
                    "telefono": persona.telefono,
                    "direccion": persona.direccion,
                    "display_text": f"{persona.nombre_completo} (CI: {persona.cedula})",
                }
            )

        return Response({"success": True, "data": results, "status": 200})

    except Exception as e:
        logger.error(f"Error en búsqueda de clientes POS: {str(e)}")
        return Response(
            {"error": "Error al buscar clientes"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# POS MAINTENANCE/SERVICE ENDPOINTS
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buscar_tecnicos_pos(request):
    """
    Búsqueda de técnicos para POS
    """
    try:
        # Buscar usuarios con rol técnico activos
        tecnicos = (
            Usuario.objects.select_related("persona_asociada")
            .prefetch_related("roles__rol")
            .filter(
                roles__rol__nombre__iexact="tecnico",
                roles__activo=True,
                is_active=True,
                eliminado=False,
            )
            .distinct()
        )

        results = []
        for tecnico in tecnicos:
            results.append(
                {
                    "id": tecnico.id,
                    "correo_electronico": tecnico.correo_electronico,
                    "nombre_completo": (
                        tecnico.persona_asociada.nombre_completo
                        if tecnico.persona_asociada
                        else tecnico.correo_electronico
                    ),
                    "persona_asociada": (
                        {
                            "nombre_completo": tecnico.persona_asociada.nombre_completo,
                            "telefono": tecnico.persona_asociada.telefono,
                            "cedula": tecnico.persona_asociada.cedula,
                        }
                        if tecnico.persona_asociada
                        else None
                    ),
                    "display_text": f"{tecnico.persona_asociada.nombre_completo if tecnico.persona_asociada else tecnico.correo_electronico} (Técnico)",
                }
            )

        return Response({"success": True, "data": results, "status": 200})

    except Exception as e:
        logger.error(f"Error en búsqueda de técnicos POS: {str(e)}")
        return Response(
            {"error": "Error al buscar técnicos"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crear_mantenimiento_pos(request):
    """
    Crear mantenimiento completo desde POS con servicios y repuestos
    Solo empleados y administradores pueden crear mantenimientos
    """
    try:
        # Verificar permisos: solo empleados y administradores
        user_roles = request.user.roles.filter(activo=True).values_list(
            "rol__nombre", flat=True
        )
        allowed_roles = ["Empleado", "Administrador"]

        if not any(role in allowed_roles for role in user_roles):
            return Response(
                {"error": "No tienes permisos para crear mantenimientos"},
                status=status.HTTP_403_FORBIDDEN,
            )
        with transaction.atomic():
            # Validar datos de entrada
            moto_id = request.data.get("moto_id")
            descripcion_problema = request.data.get("descripcion_problema", "")
            diagnostico = request.data.get("diagnostico", "")
            kilometraje_ingreso = request.data.get("kilometraje_ingreso", 0)
            total_manual = request.data.get("total", 0)
            servicios = request.data.get("servicios", [])
            repuestos = request.data.get("repuestos", [])

            if not moto_id:
                return Response(
                    {"error": "Moto es requerida"}, status=status.HTTP_400_BAD_REQUEST
                )

            if not descripcion_problema:
                return Response(
                    {"error": "Descripción del problema es requerida"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verificar moto existe
            try:
                moto = Moto.objects.get(id=moto_id, eliminado=False, activo=True)
            except Moto.DoesNotExist:
                return Response(
                    {"error": "Moto no encontrada"}, status=status.HTTP_404_NOT_FOUND
                )

            # Obtener campos adicionales del frontend
            fecha_ingreso = request.data.get("fecha_ingreso")
            fecha_entrega = request.data.get("fecha_entrega")
            estado = request.data.get("estado", "pendiente")

            # Parsear fecha_ingreso si viene del frontend, sino usar fecha actual
            if fecha_ingreso:
                try:
                    from datetime import datetime

                    fecha_ingreso_parsed = datetime.fromisoformat(
                        fecha_ingreso.replace("Z", "+00:00")
                    )
                except:
                    fecha_ingreso_parsed = timezone.now()
            else:
                fecha_ingreso_parsed = timezone.now()

            # Parsear fecha_entrega si existe
            fecha_entrega_parsed = None
            if fecha_entrega:
                try:
                    fecha_entrega_parsed = datetime.fromisoformat(
                        fecha_entrega.replace("Z", "+00:00")
                    )
                except:
                    fecha_entrega_parsed = None

            # Crear mantenimiento con total manual
            mantenimiento = Mantenimiento.objects.create(
                moto=moto,
                fecha_ingreso=fecha_ingreso_parsed,
                fecha_entrega=fecha_entrega_parsed,
                descripcion_problema=descripcion_problema,
                diagnostico=diagnostico,
                kilometraje_ingreso=kilometraje_ingreso,
                estado=estado,
                total=Decimal(str(total_manual)) if total_manual else Decimal("0.00"),
            )

            total_mantenimiento = Decimal("0.00")

            # Procesar servicios
            servicios_creados = []
            for servicio_data in servicios:
                servicio_id = servicio_data.get("servicio_id")
                precio = Decimal(str(servicio_data.get("precio", 0)))
                observaciones = servicio_data.get("observaciones", "")

                try:
                    servicio = Servicio.objects.get(
                        id=servicio_id, eliminado=False, activo=True
                    )
                except Servicio.DoesNotExist:
                    return Response(
                        {"error": f"Servicio no encontrado"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                detalle = DetalleMantenimiento.objects.create(
                    mantenimiento=mantenimiento,
                    servicio=servicio,
                    precio=precio,
                    observaciones=observaciones,
                )

                total_mantenimiento += precio
                servicios_creados.append(detalle)

            # Procesar repuestos
            repuestos_creados = []
            for repuesto_data in repuestos:
                producto_id = repuesto_data.get("producto_id")
                cantidad = int(repuesto_data.get("cantidad", 0))
                precio_unitario = Decimal(str(repuesto_data.get("precio_unitario", 0)))

                if cantidad <= 0:
                    return Response(
                        {"error": "Cantidad de repuesto debe ser mayor a 0"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    producto = Producto.objects.get(
                        id=producto_id, eliminado=False, activo=True
                    )
                except Producto.DoesNotExist:
                    return Response(
                        {"error": "Repuesto no encontrado"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                # Verificar inventario disponible
                try:
                    inventario = Inventario.objects.get(producto=producto)
                    if inventario.stock_actual < cantidad:
                        return Response(
                            {
                                "error": f"Stock insuficiente para {producto.nombre}. Disponible: {inventario.stock_actual}"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                except Inventario.DoesNotExist:
                    return Response(
                        {"error": f"No hay inventario para {producto.nombre}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                subtotal = cantidad * precio_unitario

                repuesto = RepuestoMantenimiento.objects.create(
                    mantenimiento=mantenimiento,
                    producto=producto,
                    cantidad=cantidad,
                    precio_unitario=precio_unitario,
                    subtotal=subtotal,
                )

                # Actualizar inventario (reducir stock)
                inventario.stock_actual -= cantidad
                inventario.save(update_fields=["stock_actual"])

                # Registrar movimiento de inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="salida",
                    cantidad=cantidad,
                    motivo=f"Mantenimiento #{mantenimiento.id}",
                    usuario=request.user,
                )

                total_mantenimiento += subtotal
                repuestos_creados.append(repuesto)

            # Procesar recordatorios si existen
            recordatorios_data = request.data.get("recordatorios", [])
            recordatorios_creados = []

            for recordatorio_data in recordatorios_data:
                categoria_servicio_id = recordatorio_data.get("categoria_servicio_id")
                fecha_programada = recordatorio_data.get("fecha_programada")

                if categoria_servicio_id and fecha_programada:
                    try:
                        categoria_servicio = CategoriaServicio.objects.get(
                            id=categoria_servicio_id, eliminado=False, activo=True
                        )

                        # Parsear fecha programada
                        from datetime import datetime

                        fecha_programada_parsed = datetime.fromisoformat(
                            fecha_programada
                        ).date()

                        # ✅ VERIFICAR SI YA EXISTE recordatorio activo para evitar duplicados
                        existente = RecordatorioMantenimiento.objects.filter(
                            moto=moto,
                            categoria_servicio=categoria_servicio,
                            tipo="fecha",
                            activo=True,
                        ).first()

                        if existente:
                            # Actualizar fecha existente
                            existente.fecha_programada = fecha_programada_parsed
                            existente.enviado = False
                            existente.save()
                            recordatorios_creados.append(existente)
                            logger.info(
                                f"Recordatorio actualizado para moto {moto.placa} - {categoria_servicio.nombre}"
                            )
                        else:
                            # Crear nuevo recordatorio
                            recordatorio = RecordatorioMantenimiento.objects.create(
                                moto=moto,
                                categoria_servicio=categoria_servicio,
                                fecha_programada=fecha_programada_parsed,
                                enviado=False,
                                tipo="fecha",
                            )
                            recordatorios_creados.append(recordatorio)
                            logger.info(
                                f"Recordatorio creado para moto {moto.placa} - {categoria_servicio.nombre}"
                            )

                    except (CategoriaServicio.DoesNotExist, ValueError) as e:
                        logger.warning(f"Error procesando recordatorio: {str(e)}")
                        continue

            # Si no se especificó total manual, usar el calculado automáticamente
            if not total_manual:
                mantenimiento.total = total_mantenimiento
                mantenimiento.save(update_fields=["total"])

            # Preparar respuesta
            response_data = {
                "mantenimiento_id": mantenimiento.id,
                "moto": {
                    "id": moto.id,
                    "placa": moto.placa,
                    "marca": moto.marca,
                    "modelo": moto.modelo,
                    "propietario": moto.propietario.nombre_completo,
                },
                "fecha_ingreso": mantenimiento.fecha_ingreso.isoformat(),
                "descripcion_problema": mantenimiento.descripcion_problema,
                "diagnostico": mantenimiento.diagnostico,
                "estado": mantenimiento.estado,
                "total": str(mantenimiento.total),
                "servicios": [
                    {
                        "servicio_id": detalle.servicio.id,
                        "nombre": detalle.servicio.nombre,
                        "precio": str(detalle.precio),
                        "observaciones": detalle.observaciones,
                    }
                    for detalle in servicios_creados
                ],
                "repuestos": [
                    {
                        "producto_id": repuesto.producto.id,
                        "nombre": repuesto.producto.nombre,
                        "cantidad": repuesto.cantidad,
                        "precio_unitario": str(repuesto.precio_unitario),
                        "subtotal": str(repuesto.subtotal),
                    }
                    for repuesto in repuestos_creados
                ],
                "recordatorios": [
                    {
                        "id": recordatorio.id,
                        "categoria_servicio": recordatorio.categoria_servicio.nombre,
                        "fecha_programada": recordatorio.fecha_programada.isoformat(),
                        "enviado": recordatorio.enviado,
                    }
                    for recordatorio in recordatorios_creados
                ],
            }

            logger.info(
                f"Mantenimiento POS creado #{mantenimiento.id} por usuario {request.user.username}"
            )
            return Response(response_data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creando mantenimiento POS: {str(e)}")
        return Response(
            {"error": f"Error interno: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buscar_motos_pos(request):
    """
    Búsqueda de motos para POS
    """
    try:
        query = request.GET.get("q", "").strip()

        # Debug logging
        logger.info(f"🔍 MOTO SEARCH DEBUG - Query recibida: '{query}'")
        logger.info(f"🔍 MOTO SEARCH DEBUG - Usuario: {request.user}")

        # Contar total de motos en la base de datos
        total_motos = Moto.objects.count()
        motos_activas = Moto.objects.filter(eliminado=False, activo=True).count()
        logger.info(f"🔍 MOTO SEARCH DEBUG - Total motos en DB: {total_motos}")
        logger.info(f"🔍 MOTO SEARCH DEBUG - Motos activas: {motos_activas}")

        if not query:
            logger.info("🔍 MOTO SEARCH DEBUG - Query vacía, retornando lista vacía")
            return Response({"results": []})

        # Buscar motos sin filtros primero para debug
        all_motos = Moto.objects.all()[:5]
        logger.info(f"🔍 MOTO SEARCH DEBUG - Primeras 5 motos:")
        for m in all_motos:
            logger.info(
                f"  - ID: {m.id}, Placa: {m.placa}, Marca: {m.marca}, Activo: {m.activo}, Eliminado: {m.eliminado}"
            )

        # Buscar motos con filtros
        motos = Moto.objects.filter(
            Q(placa__icontains=query)
            | Q(marca__icontains=query)
            | Q(modelo__icontains=query)
            | Q(propietario__nombre__icontains=query)
            | Q(propietario__apellido__icontains=query)
            | Q(propietario__cedula__icontains=query),
            eliminado=False,
            activo=True,
        ).select_related("propietario")[:10]

        logger.info(
            f"🔍 MOTO SEARCH DEBUG - Motos encontradas con filtros: {motos.count()}"
        )

        results = []
        for moto in motos:
            logger.info(
                f"🔍 MOTO SEARCH DEBUG - Procesando moto: {moto.placa} - {moto.marca}"
            )
            logger.info(f"🔍 MOTO SEARCH DEBUG - Propietario: {moto.propietario}")
            logger.info(
                f"🔍 MOTO SEARCH DEBUG - Propietario nombre: {getattr(moto.propietario, 'nombre_completo', 'NO_NOMBRE')}"
            )

            propietario_data = None
            if moto.propietario:
                propietario_data = {
                    "id": moto.propietario.id,
                    "nombre_completo": getattr(moto.propietario, "nombre_completo", ""),
                    "nombre": getattr(moto.propietario, "nombre", ""),
                    "apellido": getattr(moto.propietario, "apellido", ""),
                    "cedula": getattr(moto.propietario, "cedula", ""),
                    "telefono": getattr(moto.propietario, "telefono", ""),
                }
                logger.info(
                    f"🔍 MOTO SEARCH DEBUG - Propietario data: {propietario_data}"
                )

            display_text = f"{moto.placa} - {moto.marca} {moto.modelo}"
            if propietario_data and propietario_data.get("nombre_completo"):
                display_text += f" ({propietario_data['nombre_completo']})"
            elif propietario_data and propietario_data.get("nombre"):
                nombre_completo = f"{propietario_data['nombre']} {propietario_data.get('apellido', '')}".strip()
                display_text += f" ({nombre_completo})"

            results.append(
                {
                    "id": moto.id,
                    "placa": moto.placa,
                    "marca": moto.marca,
                    "modelo": moto.modelo,
                    "año": moto.año,
                    "color": moto.color,
                    "kilometraje": moto.kilometraje,
                    "activo": moto.activo,
                    "propietario": propietario_data,
                    "display_text": display_text,
                }
            )

        logger.info(f"🔍 MOTO SEARCH DEBUG - Resultados finales: {len(results)} motos")
        return Response({"success": True, "data": results, "status": 200})

    except Exception as e:
        logger.error(f"❌ ERROR en búsqueda de motos POS: {str(e)}")
        import traceback

        logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
        return Response(
            {"error": "Error al buscar motos"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def buscar_servicios_pos(request):
    """
    Búsqueda de servicios para POS
    """
    try:
        query = request.GET.get("q", "").strip()
        categoria_id = request.GET.get("categoria_id")

        logger.info(f"🔍 SERVICIOS POS DEBUG - Query recibida: '{query}'")
        logger.info(f"🔍 SERVICIOS POS DEBUG - Categoria ID: '{categoria_id}'")

        # Contar servicios totales en la base de datos
        total_servicios = Servicio.objects.count()
        servicios_activos = Servicio.objects.filter(
            eliminado=False, activo=True
        ).count()
        servicios_inactivos = Servicio.objects.filter(
            eliminado=False, activo=False
        ).count()
        servicios_eliminados = Servicio.objects.filter(eliminado=True).count()

        logger.info(
            f"🔍 SERVICIOS POS DEBUG - Total servicios en DB: {total_servicios}"
        )
        logger.info(f"🔍 SERVICIOS POS DEBUG - Servicios activos: {servicios_activos}")
        logger.info(
            f"🔍 SERVICIOS POS DEBUG - Servicios inactivos: {servicios_inactivos}"
        )
        logger.info(
            f"🔍 SERVICIOS POS DEBUG - Servicios eliminados: {servicios_eliminados}"
        )

        if not query and not categoria_id:
            logger.info(
                "🔍 SERVICIOS POS DEBUG - Sin query ni categoria, retornando lista vacía"
            )
            return Response(
                {
                    "success": True,
                    "data": [],
                    "status": 200,
                    "debug_info": {
                        "total_servicios": total_servicios,
                        "servicios_activos": servicios_activos,
                    },
                }
            )

        # Construir filtros
        filters = Q(eliminado=False, activo=True)

        if query:
            filters &= Q(nombre__icontains=query) | Q(descripcion__icontains=query)

        if categoria_id:
            filters &= Q(categoria_servicio=categoria_id)

        logger.info(f"🔍 SERVICIOS POS DEBUG - Filtros aplicados: {filters}")

        servicios = Servicio.objects.filter(filters).select_related(
            "categoria_servicio"
        )[:20]

        logger.info(
            f"🔍 SERVICIOS POS DEBUG - Servicios encontrados con filtros: {servicios.count()}"
        )

        # Log de los primeros servicios encontrados
        for i, servicio in enumerate(servicios[:3]):
            logger.info(
                f"🔍 SERVICIOS POS DEBUG - Servicio {i+1}: ID={servicio.id}, Nombre='{servicio.nombre}', Activo={servicio.activo}, Eliminado={servicio.eliminado}"
            )

        results = []
        for servicio in servicios:
            results.append(
                {
                    "id": servicio.id,
                    "nombre": servicio.nombre,
                    "descripcion": servicio.descripcion,
                    "precio": str(servicio.precio),
                    "duracion_estimada": servicio.duracion_estimada,
                    "categoria": {
                        "id": (
                            servicio.categoria_servicio.id
                            if servicio.categoria_servicio
                            else None
                        ),
                        "nombre": (
                            servicio.categoria_servicio.nombre
                            if servicio.categoria_servicio
                            else "Sin categoría"
                        ),
                    },
                    "display_text": f"{servicio.nombre} - ${servicio.precio}",
                }
            )

        logger.info(
            f"🔍 SERVICIOS POS DEBUG - Resultados finales: {len(results)} servicios"
        )

        return Response(
            {
                "success": True,
                "data": results,
                "status": 200,
                "debug_info": {
                    "total_servicios": total_servicios,
                    "servicios_activos": servicios_activos,
                    "query": query,
                    "categoria_id": categoria_id,
                    "servicios_encontrados": len(results),
                },
            }
        )

    except Exception as e:
        logger.error(f"❌ ERROR en búsqueda de servicios POS: {str(e)}")
        import traceback

        logger.error(f"❌ TRACEBACK: {traceback.format_exc()}")
        return Response(
            {"error": "Error al buscar servicios"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# INVENTORY MANAGEMENT
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def alertas_inventario(request):
    """
    Obtener alertas de inventario (stock bajo, sin stock)
    """
    try:
        # Productos sin stock
        sin_stock = Inventario.objects.filter(
            stock_actual=0, producto__eliminado=False, producto__activo=True
        ).select_related("producto", "producto__categoria")

        # Productos con stock bajo
        stock_bajo = Inventario.objects.filter(
            stock_actual__gt=0,
            stock_actual__lte=F("stock_minimo"),
            producto__eliminado=False,
            producto__activo=True,
        ).select_related("producto", "producto__categoria")

        response_data = {
            "sin_stock": [
                {
                    "producto_id": inv.producto.id,
                    "nombre": inv.producto.nombre,
                    "categoria": inv.producto.categoria.nombre,
                    "stock_actual": inv.stock_actual,
                    "stock_minimo": inv.stock_minimo,
                }
                for inv in sin_stock
            ],
            "stock_bajo": [
                {
                    "producto_id": inv.producto.id,
                    "nombre": inv.producto.nombre,
                    "categoria": inv.producto.categoria.nombre,
                    "stock_actual": inv.stock_actual,
                    "stock_minimo": inv.stock_minimo,
                }
                for inv in stock_bajo
            ],
            "total_alertas": sin_stock.count() + stock_bajo.count(),
        }

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error obteniendo alertas de inventario: {str(e)}")
        return Response(
            {"error": "Error al obtener alertas"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ajustar_inventario(request):
    """
    Realizar ajuste manual de inventario
    """
    try:
        with transaction.atomic():
            producto_id = request.data.get("producto_id")
            nuevo_stock = int(request.data.get("nuevo_stock", 0))
            motivo = request.data.get("motivo", "Ajuste manual")

            if not producto_id:
                return Response(
                    {"error": "Producto es requerido"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if nuevo_stock < 0:
                return Response(
                    {"error": "El stock no puede ser negativo"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                inventario = Inventario.objects.get(producto_id=producto_id)
            except Inventario.DoesNotExist:
                return Response(
                    {"error": "Inventario no encontrado"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            stock_anterior = inventario.stock_actual
            inventario.stock_actual = nuevo_stock
            inventario.save(update_fields=["stock_actual"])

            # Registrar movimiento de ajuste
            InventarioMovimiento.objects.create(
                inventario=inventario,
                tipo="ajuste",
                cantidad=nuevo_stock,  # Para ajustes, guardamos el stock final
                motivo=motivo,
                usuario=request.user,
            )

            response_data = {
                "producto_id": inventario.producto.id,
                "nombre": inventario.producto.nombre,
                "stock_anterior": stock_anterior,
                "stock_nuevo": nuevo_stock,
                "diferencia": nuevo_stock - stock_anterior,
            }

            logger.info(
                f"Ajuste de inventario: {inventario.producto.nombre} de {stock_anterior} a {nuevo_stock}"
            )
            return Response(response_data)

    except Exception as e:
        logger.error(f"Error ajustando inventario: {str(e)}")
        return Response(
            {"error": f"Error interno: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# DASHBOARD STATS
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_pos_stats(request):
    """
    Estadísticas del dashboard POS
    """
    try:
        hoy = timezone.now().date()

        # Ventas de hoy
        ventas_hoy = Venta.objects.filter(
            fecha_venta__date=hoy, eliminado=False
        ).aggregate(total_ventas=Sum("total"), cantidad_ventas=Count("id"))

        # Los ingresos netos son iguales a las ventas totales
        # (las devoluciones se manejan por separado)
        monto_ventas = float(ventas_hoy["total_ventas"] or 0)
        ingresos_netos = monto_ventas

        # Mantenimientos activos
        mantenimientos_activos = Mantenimiento.objects.filter(
            estado__in=["pendiente", "en_proceso"], eliminado=False
        ).count()

        # Productos con stock bajo
        productos_stock_bajo = Inventario.objects.filter(
            stock_actual__lte=F("stock_minimo"),
            stock_actual__gt=0,
            producto__eliminado=False,
            producto__activo=True,
        ).count()

        # Productos sin stock
        productos_sin_stock = Inventario.objects.filter(
            stock_actual=0, producto__eliminado=False, producto__activo=True
        ).count()

        response_data = {
            "ventas_hoy": {
                "total": str(monto_ventas),
                "cantidad": ventas_hoy["cantidad_ventas"] or 0,
            },
            "devoluciones_hoy": {
                "total": str(monto_devoluciones),
            },
            "ingresos_netos_hoy": str(ingresos_netos),
            "mantenimientos_activos": mantenimientos_activos,
            "alertas_inventario": {
                "stock_bajo": productos_stock_bajo,
                "sin_stock": productos_sin_stock,
                "total": productos_stock_bajo + productos_sin_stock,
            },
        }

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error obteniendo estadísticas POS: {str(e)}")
        return Response(
            {"error": "Error al obtener estadísticas"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
