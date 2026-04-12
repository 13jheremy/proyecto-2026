from rest_framework import viewsets, status, permissions, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.http import Http404
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.views import APIView
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.auth import authenticate
from django.db import models, transaction
from django.db.models import (
    Count,
    Sum,
    Q,
    F,
    Value,
    Case,
    When,
    ExpressionWrapper,
    fields,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from ..models import *
from .serializers import *
from .pagination import UsuarioPagination, StandardResultsSetPagination
from .pos_views import *
from .permissions import (
    IsAdministrador,
    IsEmpleado,
    IsTecnico,
    IsCliente,
    IsOwner,
    CustomPermission,
)
from .throttling import (
    CustomUserRateThrottle,
    CustomAnonRateThrottle,
    AuthThrottle,
    APIThrottle,
    POSThrottle,
)
from ..services import fcm_service

logger = logging.getLogger(__name__)


# =======================================
# CUSTOM EXCEPTIONS
# =======================================
class APIException(Exception):
    """Base exception for API errors"""

    def __init__(self, message, status_code=status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


# =======================================
# BASE VIEWSET
# =======================================
class BaseViewSet(viewsets.ModelViewSet):
    """
    ViewSet base optimizado con funcionalidades comunes:
    - Soft delete automático
    - Restauración de registros eliminados
    - Filtros estándar por activo/eliminado
    - Búsqueda avanzada
    - Acciones comunes (activar, desactivar, etc.)
    - Logging de operaciones
    - Manejo de errores estandarizado
    - Rate limiting integrado
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [CustomUserRateThrottle, CustomAnonRateThrottle]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = []
    search_fields = []
    ordering = ["-fecha_registro"]

    def get_queryset(self):
        """Retorna el queryset base optimizado"""
        model = self.serializer_class.Meta.model
        # Usar objects_all para poder ver registros eliminados cuando sea necesario
        qs = getattr(model, "objects_all", model.objects).all()

        # Aplicar filtros de eliminado si el modelo lo soporta
        eliminado = self.request.query_params.get("eliminado")
        if hasattr(model, "eliminado") and eliminado is not None:
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
            # Valor por defecto: mostrar solo no eliminados
            qs = qs.filter(eliminado=False)

        # Aplicar filtros de activo si el modelo lo soporta
        activo = self.request.query_params.get("activo")
        if hasattr(model, "activo") and activo is not None:
            if activo.lower() == "true":
                qs = qs.filter(activo=True)
            elif activo.lower() == "false":
                qs = qs.filter(activo=False)

        return qs

    def perform_create(self, serializer):
        """Configurar usuario creador automáticamente y notificar"""
        model = serializer.Meta.model

        try:
            # Intentar asignar usuario según el campo disponible
            save_kwargs = {}

            if hasattr(model, "creado_por") and self.request.user.is_authenticated:
                save_kwargs["creado_por"] = self.request.user
            elif hasattr(model, "usuario") and self.request.user.is_authenticated:
                save_kwargs["usuario"] = self.request.user
            elif (
                hasattr(model, "registrado_por") and self.request.user.is_authenticated
            ):
                save_kwargs["registrado_por"] = self.request.user

            # Guardar con los parámetros apropiados
            if save_kwargs:
                serializer.save(**save_kwargs)
            else:
                serializer.save()

            logger.info(
                f"Creado {model.__name__} ID={serializer.instance.id} por usuario {self.request.user.username if self.request.user.is_authenticated else 'N/A'}"
            )

            # Enviar notificación de creación
            self._enviar_notificacion_cambio(
                accion="creado",
                modelo=model.__name__,
                instance_id=serializer.instance.id,
                instance=serializer.instance,
            )
        except Exception as e:
            logger.error(f"Error creando {model.__name__}: {str(e)}")
            raise APIException(f"Error al crear {model.__name__}: {str(e)}")

    def perform_update(self, serializer):
        """Configurar usuario que actualiza automáticamente y notificar"""
        model = serializer.Meta.model

        try:
            # Establecer el usuario que actualiza el registro
            if hasattr(model, "actualizado_por") and self.request.user.is_authenticated:
                serializer.save(actualizado_por=self.request.user)
            else:
                serializer.save()

            logger.info(
                f"Actualizado {model.__name__} ID={serializer.instance.id} por usuario {self.request.user.username if self.request.user.is_authenticated else 'N/A'}"
            )

            # Enviar notificación de actualización
            self._enviar_notificacion_cambio(
                accion="actualizado",
                modelo=model.__name__,
                instance_id=serializer.instance.id,
                instance=serializer.instance,
            )
        except Exception as e:
            logger.error(f"Error actualizando {model.__name__}: {str(e)}")
            raise APIException(f"Error al actualizar {model.__name__}: {str(e)}")

    def perform_destroy(self, instance):
        """Soft delete por defecto con auditoría y notificación"""
        try:
            if hasattr(instance, "eliminado"):
                # Configurar el usuario actual para soft delete
                from django.utils import timezone

                instance.eliminado = True
                instance.fecha_eliminacion = timezone.now()

                # Establecer el usuario que elimina si está autenticado
                if (
                    hasattr(instance, "eliminado_por")
                    and self.request.user.is_authenticated
                ):
                    instance.eliminado_por = self.request.user

                instance.save(
                    update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
                )
                logger.info(
                    f"Soft delete {instance.__class__.__name__} ID={instance.id} por usuario {self.request.user.username if self.request.user.is_authenticated else 'N/A'}"
                )

                # Enviar notificación de eliminación
                self._enviar_notificacion_cambio(
                    accion="eliminado",
                    modelo=instance.__class__.__name__,
                    instance_id=instance.id,
                    instance=instance,
                )
            else:
                # Este caso no debería alcanzarse para modelos con soft delete
                # Pero se mantiene por compatibilidad
                instance.delete()
                logger.info(
                    f"Delete (sin campo eliminado) {instance.__class__.__name__} ID={instance.id}"
                )
        except Exception as e:
            logger.error(f"Error eliminando {instance.__class__.__name__}: {str(e)}")
            raise APIException(f"Error al eliminar: {str(e)}")

    def _enviar_notificacion_cambio(self, accion, modelo, instance_id, instance=None):
        """
        Envía notificaciones push cuando se crea, actualiza o elimina un registro.
        Solo envía notificaciones para modelos específicos (Mantenimiento, Servicio, etc.)
        """
        # Modelos que queremos notificar
        modelos_a_notificar = [
            "Mantenimiento",
            "Servicio",
            "CategoriaServicio",
            "Producto",
            "Inventario",
            "Moto",
            "Cliente",
            "Usuario",
        ]

        if modelo not in modelos_a_notificar:
            return

        # Determinar título y cuerpo según la acción
        if accion == "creado":
            titulo = f"Nuevo {modelo}"
            cuerpo = f"Se ha creado un nuevo registro de {modelo} (ID: {instance_id})"
        elif accion == "actualizado":
            titulo = f"{modelo} actualizado"
            cuerpo = f"El registro de {modelo} (ID: {instance_id}) ha sido actualizado"
        elif accion == "eliminado":
            titulo = f"{modelo} eliminado"
            cuerpo = f"El registro de {modelo} (ID: {instance_id}) ha sido eliminado"
        else:
            return

        # Obtener información adicional del registro
        data = {
            "accion": accion,
            "modelo": modelo,
            "id": str(instance_id),
            "timestamp": timezone.now().isoformat(),
        }

        # Intentar agregar información relevante según el modelo
        if instance:
            if modelo == "Mantenimiento" and hasattr(instance, "moto"):
                try:
                    data["moto_placa"] = instance.moto.placa if instance.moto else None
                    data["estado"] = instance.estado
                except:
                    pass
            elif modelo == "Moto" and hasattr(instance, "placa"):
                data["placa"] = instance.placa
            elif modelo == "Servicio" and hasattr(instance, "nombre"):
                data["nombre"] = instance.nombre

        # Enviar notificación a todos los dispositivos registrados
        try:
            from ..models import Dispositivo

            dispositivos = Dispositivo.objects.filter(activo=True)

            for dispositivo in dispositivos:
                if dispositivo.fcm_token:
                    try:
                        fcm_service.send_notification(
                            token=dispositivo.fcm_token,
                            title=titulo,
                            body=cuerpo,
                            data=data,
                        )
                        logger.info(
                            f"Notificación enviada a dispositivo {dispositivo.id}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Error enviando notificación a dispositivo {dispositivo.id}: {e}"
                        )
        except Exception as e:
            logger.warning(f"Error al obtener dispositivos para notificación: {e}")

    # =======================================
    # ACCIONES COMUNES ESTANDARIZADAS
    # =======================================

    @action(detail=True, methods=["patch"])
    def toggle_activo(self, request, pk=None):
        """Alternar estado activo/inactivo"""
        instance = self.get_object()
        if not hasattr(instance, "activo"):
            return Response(
                {"error": "Este modelo no soporta activación/desactivación"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Si se proporciona activo en el request, usarlo; de lo contrario, togglear
        activo_value = request.data.get("activo")
        if activo_value is not None:
            instance.activo = bool(activo_value)
        else:
            instance.activo = not instance.activo
        instance.save(update_fields=["activo"])
        serializer = self.get_serializer(instance)
        logger.info(
            f"Toggle activo {instance.__class__.__name__} ID={instance.id} -> {instance.activo}"
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["patch"], url_path="soft_delete")
    def soft_delete(self, request, pk=None):
        """Eliminación temporal (soft delete)"""
        logger.info(f"🔍 SOFT DELETE DEBUG - Iniciando soft_delete para pk={pk}")
        logger.info(f"🔍 SOFT DELETE DEBUG - Request user: {request.user}")
        logger.info(f"🔍 SOFT DELETE DEBUG - Request method: {request.method}")
        logger.info(f"🔍 SOFT DELETE DEBUG - Request data: {request.data}")

        try:
            instance = self.get_object()
            logger.info(
                f"🔍 SOFT DELETE DEBUG - Instance obtenida: {instance.__class__.__name__} ID={instance.id}"
            )
            logger.info(
                f"🔍 SOFT DELETE DEBUG - Instance eliminado actual: {getattr(instance, 'eliminado', 'NO_FIELD')}"
            )

            if not hasattr(instance, "eliminado"):
                logger.error(
                    f"🔍 SOFT DELETE DEBUG - ERROR: Modelo {instance.__class__.__name__} no tiene campo eliminado"
                )
                return Response(
                    {"error": "Este modelo no soporta eliminación"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            from django.utils import timezone

            instance.eliminado = True
            instance.fecha_eliminacion = timezone.now()

            # Establecer el usuario que elimina si está autenticado
            if hasattr(instance, "eliminado_por") and request.user.is_authenticated:
                instance.eliminado_por = request.user

            instance.save(
                update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
            )
            logger.info(
                f"🔍 SOFT DELETE DEBUG - SUCCESS: {instance.__class__.__name__} ID={instance.id} marcado como eliminado por {request.user.username if request.user.is_authenticated else 'N/A'}"
            )

            response_data = {
                "status": f"{instance.__class__.__name__} marcado como eliminado"
            }
            logger.info(f"🔍 SOFT DELETE DEBUG - Response data: {response_data}")

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"🔍 SOFT DELETE DEBUG - EXCEPTION: {str(e)}")
            logger.error(f"🔍 SOFT DELETE DEBUG - Exception type: {type(e)}")
            import traceback

            logger.error(f"🔍 SOFT DELETE DEBUG - Traceback: {traceback.format_exc()}")
            raise

    @action(detail=True, methods=["patch"], url_path="restore")
    def restore(self, request, pk=None):
        """Restaurar registro eliminado"""
        model = self.serializer_class.Meta.model
        try:
            # Use objects_all to get deleted records
            instance = model.objects_all.get(pk=pk)
        except model.DoesNotExist:
            return Response(
                {"detail": f"{model.__name__} no encontrado"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not hasattr(instance, "eliminado"):
            return Response(
                {"error": "Este modelo no soporta restauración"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Restaurar el registro y limpiar campos de eliminación
        instance.eliminado = False

        # Limpiar campos de eliminación si existen
        update_fields = ["eliminado"]
        if hasattr(instance, "fecha_eliminacion"):
            instance.fecha_eliminacion = None
            update_fields.append("fecha_eliminacion")
        if hasattr(instance, "eliminado_por"):
            instance.eliminado_por = None
            update_fields.append("eliminado_por")

        instance.save(update_fields=update_fields)
        serializer = self.get_serializer(instance)
        logger.info(
            f"Restaurado {instance.__class__.__name__} ID={instance.id} por usuario {request.user.username if request.user.is_authenticated else 'N/A'}"
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    # =======================================
    # ACCIONES DE CONSULTA AVANZADA
    # =======================================

    @action(detail=False, methods=["get"])
    def activos(self, request):
        """Obtener solo registros activos"""
        if not hasattr(self.serializer_class.Meta.model, "activo"):
            return Response(
                {"error": "Este modelo no tiene campo activo"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = self.get_queryset().filter(activo=True)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def eliminados(self, request):
        """Obtener solo registros eliminados"""
        if not hasattr(self.serializer_class.Meta.model, "eliminado"):
            return Response(
                {"error": "Este modelo no tiene campo eliminado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        model = self.serializer_class.Meta.model
        queryset = model.objects_all.filter(eliminado=True)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


# =======================================
# AUTHENTICATION VIEWS
# =======================================
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle, CustomAnonRateThrottle]

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                logger.info(
                    f"Login exitoso para usuario: {request.data.get('correo_electronico', 'N/A')}"
                )
            return response
        except Exception as e:
            logger.error(f"Error en login: {str(e)}")

            error_msg = str(e)
            if "Usuario no existe" in error_msg:
                return Response(
                    {"detail": "Usuario no existe"}, status=status.HTTP_401_UNAUTHORIZED
                )
            elif "Credenciales erroneas" in error_msg:
                return Response(
                    {"detail": "Credenciales erroneas"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            elif "Usuario inactivo" in error_msg:
                return Response(
                    {"detail": "Usuario inactivo"}, status=status.HTTP_401_UNAUTHORIZED
                )

            return Response(
                {"detail": "Error interno del servidor"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class MobileTokenObtainPairView(TokenObtainPairView):
    """Vista de autenticación específica para móvil (solo clientes)"""

    serializer_class = MobileTokenObtainPairSerializer
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle, CustomAnonRateThrottle]

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                logger.info(
                    f"Login móvil exitoso para usuario: {request.data.get('correo_electronico', 'N/A')}"
                )
            return response
        except Exception as e:
            logger.error(f"Error en login móvil: {str(e)}")

            error_msg = str(e)
            if "Usuario no existe" in error_msg:
                return Response(
                    {"error": "Usuario no existe"}, status=status.HTTP_401_UNAUTHORIZED
                )
            elif "Credenciales erroneas" in error_msg:
                return Response(
                    {"error": "Credenciales erroneas"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            elif "Usuario inactivo" in error_msg:
                return Response(
                    {"error": "Usuario inactivo"}, status=status.HTTP_401_UNAUTHORIZED
                )
            elif "Acceso móvil restringido" in error_msg:
                return Response(
                    {"error": "Acceso móvil restringido solo para clientes"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            return Response(
                {"error": "Error interno del servidor"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UsuarioMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Log para debugging
            logger.info(
                f"Solicitando datos de usuario: {request.user.id} - {request.user.username}"
            )

            # Obtener usuario con todas las relaciones necesarias
            usuario = (
                Usuario.objects.select_related("persona_asociada")
                .prefetch_related("roles__rol")
                .get(id=request.user.id)
            )

            # Serializar datos
            serializer = UsuarioMeSerializer(usuario)
            data = serializer.data

            # Log para debugging (solo en desarrollo)
            # Solo mostrar en modo debug
            if logger.level == logging.DEBUG:
                logger.debug(f"Datos del usuario serializados: {data}")

            # Validar que los datos críticos estén presentes
            if not data.get("roles"):
                logger.warning(f"Usuario {usuario.id} no tiene roles asignados")

            return Response(data, status=status.HTTP_200_OK)

        except Usuario.DoesNotExist:
            logger.error(f"Usuario no encontrado: {request.user.id}")
            return Response(
                {"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error obteniendo datos de usuario: {str(e)}")
            return Response(
                {"error": "Error interno del servidor"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def patch(self, request):
        """Actualizar token FCM del usuario"""
        import logging

        logger = logging.getLogger(__name__)

        try:
            fcm_token = request.data.get("fcm_token")

            if fcm_token:
                # DEBUG: Mostrar información del token FCM recibido
                logger.info(f"🔑 [DEBUG] Token FCM recibido - Longitud: {len(fcm_token)}")
                logger.info(f"🔑 [DEBUG] Token FCM - Primeros 30 chars: {fcm_token[:30]}")
                logger.info(f"🔑 [DEBUG] Token FCM - Últimos 30 chars: {fcm_token[-30:]}")
                
                request.user.fcm_token = fcm_token
                request.user.save(update_fields=["fcm_token"])
                logger.info(f"Token FCM actualizado para usuario {request.user.id}")
                
                # Verificar que se guardó correctamente
                request.user.refresh_from_db()
                logger.info(f"✅ [DEBUG] Token FCM guardado en BD - Longitud: {len(request.user.fcm_token) if request.user.fcm_token else 0}")
                
                return Response({"message": "Token FCM actualizado correctamente"})
            else:
                logger.warning(
                    "[DEBUG PATCH /api/me/] No se recibió fcm_token en el request"
                )
                return Response(
                    {"error": "Token FCM requerido"}, status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            import traceback

            logger.error(
                f"[DEBUG PATCH /api/me/] Error actualizando token FCM: {str(e)}"
            )
            logger.error(f"[DEBUG PATCH /api/me/] Traceback: {traceback.format_exc()}")
            return Response(
                {"error": "Error interno del servidor"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# También actualiza tu función dashboard_stats para mejor manejo de errores
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    """Estadísticas del dashboard con mejor manejo de errores"""
    try:
        # Verificar permisos
        user_has_permission = IsEmpleado().has_permission(
            request, None
        ) or IsAdministrador().has_permission(request, None)

        if not user_has_permission:
            logger.warning(
                f"Usuario {request.user.id} intentó acceder a dashboard_stats sin permisos"
            )
            return Response(
                {"detail": "No tienes permiso para acceder a estas estadísticas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.now().date()
        last_30_days = today - timedelta(days=30)

        # Calcular estadísticas de forma segura
        try:
            total_productos = Producto.objects.filter(
                activo=True, eliminado=False
            ).count()
        except Exception as e:
            logger.error(f"Error calculando total_productos: {e}")
            total_productos = 0

        try:
            total_clientes = Persona.objects.filter(
                usuario__roles__rol__nombre__iexact="cliente",
                usuario__roles__activo=True,
            ).count()
        except Exception as e:
            logger.error(f"Error calculando total_clientes: {e}")
            total_clientes = 0

        try:
            total_motos = Moto.objects.filter(eliminado=False).count()
        except Exception as e:
            logger.error(f"Error calculando total_motos: {e}")
            total_motos = 0

        try:
            mantenimientos_pendientes = Mantenimiento.objects.filter(
                estado__iexact="pendiente", eliminado=False
            ).count()
        except Exception as e:
            logger.error(f"Error calculando mantenimientos_pendientes: {e}")
            mantenimientos_pendientes = 0

        try:
            # Obtener el primer día del mes actual
            first_day_of_month = today.replace(day=1)
            ventas_mes = Venta.objects.filter(
                fecha_venta__date__gte=first_day_of_month, eliminado=False
            ).count()
        except Exception as e:
            logger.error(f"Error calculando ventas_mes: {e}")
            ventas_mes = 0

        try:
            # Obtener el primer día del mes actual
            first_day_of_month = today.replace(day=1)

            # Ingresos por ventas
            ingresos_ventas = (
                Venta.objects.filter(
                    fecha_venta__date__gte=first_day_of_month, eliminado=False
                ).aggregate(total=Sum("total"))["total"]
                or 0
            )

            # Ingresos por mantenimientos completados (total + costo_adicional)
            try:
                # Buscar mantenimientos completados usando fecha_completado o fecha_entrega
                # ya que el frontend puede usar cualquiera de los dos campos
                mantenimientos_query = (
                    Q(estado="completado")
                    & (
                        Q(fecha_completado__date__gte=first_day_of_month)
                        | Q(fecha_entrega__date__gte=first_day_of_month)
                    )
                    & Q(eliminado=False)
                )

                # Sumar total de mantenimientos completados en el mes
                mantenimientos_result = Mantenimiento.objects.filter(
                    mantenimientos_query
                ).aggregate(
                    total_mantenimientos=Sum("total"),
                    total_adicional=Sum("costo_adicional"),
                )
                ingresos_mantenimientos = float(
                    mantenimientos_result["total_mantenimientos"] or 0
                ) + float(mantenimientos_result["total_adicional"] or 0)
                # Contar mantenimientos completados
                mantenimientos_completados_count = Mantenimiento.objects.filter(
                    mantenimientos_query
                ).count()
            except Exception as e:
                logger.error(f"Error calculando ingresos_mantenimientos: {e}")
                ingresos_mantenimientos = 0
                mantenimientos_completados_count = 0

            # Ingreso total del mes = ventas + mantenimientos
            ingresos_mes = float(ingresos_ventas) + ingresos_mantenimientos
            ingresos_netos_mes = ingresos_mes
        except Exception as e:
            logger.error(f"Error calculando ingresos_mes: {e}")
            ingresos_mes = 0
            ingresos_netos_mes = 0

        try:
            productos_stock_bajo = Producto.objects.filter(
                inventario__stock_actual__lte=F("inventario__stock_minimo"),
                activo=True,
                eliminado=False,
                inventario__isnull=False,
            ).count()
        except Exception as e:
            logger.error(f"Error calculando productos_stock_bajo: {e}")
            productos_stock_bajo = 0

        try:
            productos_destacados = Producto.objects.filter(
                destacado=True, activo=True, eliminado=False
            ).count()
        except Exception as e:
            logger.error(f"Error calculando productos_destacados: {e}")
            productos_destacados = 0

        stats = {
            "total_productos": total_productos,
            "total_clientes": total_clientes,
            "total_motos": total_motos,
            "mantenimientos_pendientes": mantenimientos_pendientes,
            "ventas_mes": ventas_mes,
            "mantenimientos_mes": mantenimientos_completados_count,
            "ingresos_mes": float(ingresos_mes),
            "ingresos_netos_mes": float(ingresos_netos_mes),
            "productos_stock_bajo": productos_stock_bajo,
            "productos_destacados": productos_destacados,
        }

        logger.info(f"Dashboard stats generadas para usuario {request.user.id}")
        return Response(stats)

    except Exception as e:
        logger.error(
            f"Error general en dashboard_stats para usuario {request.user.id}: {str(e)}"
        )
        return Response(
            {"error": "Error al obtener estadísticas"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cliente_dashboard_stats(request):
    """Estadísticas específicas del dashboard para clientes"""
    try:
        # Verificar que el usuario sea cliente
        if not IsCliente().has_permission(request, None):
            logger.warning(
                f"Usuario {request.user.id} intentó acceder a cliente_dashboard_stats sin ser cliente"
            )
            return Response(
                {"detail": "Solo los clientes pueden acceder a estas estadísticas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Obtener el usuario cliente actual y su persona asociada
        cliente_usuario = request.user
        logger.info(
            f"🔍 Calculando estadísticas para cliente: {cliente_usuario.id} - {cliente_usuario.username}"
        )

        # Verificar si el usuario tiene persona asociada
        if not cliente_usuario.tiene_persona:
            logger.warning(f"Usuario {cliente_usuario.id} no tiene persona asociada")
            return Response(
                {
                    "success": True,
                    "data": {
                        "motos_cliente": 0,
                        "mantenimientos_cliente": 0,
                        "compras_cliente": 0,
                        "total_gastado": 0.0,
                    },
                }
            )

        cliente_persona = cliente_usuario.persona
        logger.info(
            f"👤 Persona asociada encontrada: {cliente_persona.id} - {cliente_persona.nombre}"
        )

        # Calcular estadísticas específicas del cliente
        try:
            # Contar motos del cliente
            logger.info(f"🏍️ Buscando motos para propietario: {cliente_persona.id}")
            motos_cliente = Moto.objects.filter(
                propietario=cliente_persona, eliminado=False
            ).count()
            logger.info(f"🏍️ Motos encontradas: {motos_cliente}")
        except Exception as e:
            logger.error(f"Error calculando motos_cliente: {e}")
            motos_cliente = 0

        try:
            # Contar mantenimientos del cliente
            logger.info(
                f"🔧 Buscando mantenimientos para cliente: {cliente_persona.id}"
            )
            mantenimientos_cliente = Mantenimiento.objects.filter(
                moto__propietario=cliente_persona, eliminado=False
            ).count()
            logger.info(f"🔧 Mantenimientos encontrados: {mantenimientos_cliente}")
        except Exception as e:
            logger.error(f"Error calculando mantenimientos_cliente: {e}")
            mantenimientos_cliente = 0

        try:
            # Contar compras del cliente - las ventas se asocian con la persona
            logger.info(f"🛒 Buscando ventas para cliente: {cliente_persona.id}")
            compras_cliente = Venta.objects.filter(
                cliente=cliente_persona, eliminado=False
            ).count()
            logger.info(f"🛒 Compras encontradas: {compras_cliente}")
        except Exception as e:
            logger.error(f"Error calculando compras_cliente: {e}")
            compras_cliente = 0

        try:
            # Calcular total gastado por el cliente
            logger.info(
                f"💰 Calculando total gastado para cliente: {cliente_persona.id}"
            )
            total_gastado = (
                Venta.objects.filter(
                    cliente=cliente_persona, eliminado=False
                ).aggregate(total=Sum("total"))["total"]
                or 0
            )
            logger.info(f"💰 Total gastado: {total_gastado}")
        except Exception as e:
            logger.error(f"Error calculando total_gastado: {e}")
            total_gastado = 0

        stats = {
            "motos_cliente": motos_cliente,
            "mantenimientos_cliente": mantenimientos_cliente,
            "compras_cliente": compras_cliente,
            "total_gastado": float(total_gastado),
        }

        logger.info(f"Cliente dashboard stats generadas para usuario {request.user.id}")
        return Response({"success": True, "data": stats})

    except Exception as e:
        logger.error(f"Error en cliente_dashboard_stats: {e}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tecnico_dashboard_stats(request):
    """Estadísticas específicas del dashboard para técnicos"""
    try:
        # Verificar que el usuario sea técnico
        if not IsTecnico().has_permission(request, None):
            logger.warning(
                f"Usuario {request.user.id} intentó acceder a tecnico_dashboard_stats sin ser técnico"
            )
            return Response(
                {"detail": "Solo los técnicos pueden acceder a estas estadísticas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Obtener mantenimientos asignados al técnico
        mantenimientos_asignados = Mantenimiento.objects.filter(
            tecnico_asignado=request.user, eliminado=False
        )

        # Calcular estadísticas
        total_asignados = mantenimientos_asignados.count()

        pendientes = mantenimientos_asignados.filter(estado="pendiente").count()
        en_proceso = mantenimientos_asignados.filter(estado="en_proceso").count()

        # Completados hoy
        hoy = timezone.now().date()
        completados_hoy = mantenimientos_asignados.filter(
            estado="completado", fecha_entrega__date=hoy
        ).count()

        # Completados esta semana
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        completados_semana = mantenimientos_asignados.filter(
            estado="completado", fecha_entrega__date__gte=inicio_semana
        ).count()

        # Completados este mes
        completados_mes = mantenimientos_asignados.filter(
            estado="completado",
            fecha_entrega__year=hoy.year,
            fecha_entrega__month=hoy.month,
        ).count()

        # Próximos mantenimientos (pendientes ordenados por fecha)
        proximos_mantenimientos = mantenimientos_asignados.filter(
            estado="pendiente"
        ).order_by("fecha_ingreso")[:5]

        # Mantenimientos en proceso
        mantenimientos_en_proceso = mantenimientos_asignados.filter(
            estado="en_proceso"
        ).order_by("fecha_ingreso")[:5]

        stats = {
            "mantenimientos_asignados": total_asignados,
            "mantenimientos_pendientes": pendientes,
            "mantenimientos_en_proceso": en_proceso,
            "mantenimientos_completados_hoy": completados_hoy,
            "mantenimientos_completados_semana": completados_semana,
            "mantenimientos_completados_mes": completados_mes,
            "proximos_mantenimientos": [
                {
                    "id": m.id,
                    "moto_placa": m.moto.placa if m.moto else "N/A",
                    "cliente_nombre": (
                        m.moto.propietario.nombre
                        if m.moto and m.moto.propietario
                        else "N/A"
                    ),
                    "descripcion": m.descripcion,
                    "fecha_ingreso": (
                        m.fecha_ingreso.isoformat() if m.fecha_ingreso else None
                    ),
                }
                for m in proximos_mantenimientos
            ],
            "mantenimientos_activos": [
                {
                    "id": m.id,
                    "moto_placa": m.moto.placa if m.moto else "N/A",
                    "cliente_nombre": (
                        m.moto.propietario.nombre
                        if m.moto and m.moto.propietario
                        else "N/A"
                    ),
                    "descripcion": m.descripcion,
                    "fecha_ingreso": (
                        m.fecha_ingreso.isoformat() if m.fecha_ingreso else None
                    ),
                }
                for m in mantenimientos_en_proceso
            ],
        }

        logger.info(f"Técnico dashboard stats generadas para usuario {request.user.id}")
        return Response({"success": True, "data": stats})

    except Exception as e:
        logger.error(f"Error en tecnico_dashboard_stats: {e}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCliente])
def cliente_motos(request):
    """
    Endpoint específico para obtener las motos del cliente autenticado
    """
    try:
        # Debug inicial
        logger.info(
            f"🔍 Cliente motos - Usuario: {request.user.id} - {request.user.username}"
        )

        # Verificar persona_asociada
        if not hasattr(request.user, "persona_asociada"):
            logger.error(
                f"❌ Usuario {request.user.id} no tiene atributo persona_asociada"
            )
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.persona_asociada:
            logger.error(f"❌ Usuario {request.user.id} tiene persona_asociada=None")
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = request.user.persona_asociada
        logger.info(
            f"🔍 Persona asociada: {cliente.id} - {cliente.nombre} {cliente.apellido}"
        )

        # Obtener motos del cliente
        motos = (
            Moto.objects.filter(propietario=cliente, eliminado=False)
            .select_related("propietario")
            .order_by("-fecha_registro")
        )

        logger.info(f"🔍 Motos encontradas: {motos.count()}")

        # Si no hay motos, devolver lista vacía con mensaje informativo
        if motos.count() == 0:
            logger.info(f"ℹ️ Cliente {cliente.id} no tiene motos registradas")
            return Response(
                {
                    "success": True,
                    "data": [],
                    "count": 0,
                    "message": "No tienes motos registradas. Contacta con el taller para registrar tu vehículo.",
                }
            )

        # Serializar los datos
        from .serializers import MotoSerializer

        serializer = MotoSerializer(motos, many=True)

        logger.info(f"✅ Motos serializadas correctamente para cliente {cliente.id}")
        return Response(
            {"success": True, "data": serializer.data, "count": motos.count()}
        )

    except Exception as e:
        logger.error(f"❌ Error obteniendo motos del cliente: {e}")
        import traceback

        logger.error(f"❌ Traceback completo:\n{traceback.format_exc()}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# ENDPOINTS BUSINESS INTELLIGENCE
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_analytics_advanced(request):
    """
    Analytics avanzados para Business Intelligence
    """
    try:
        # Verificar permisos (solo administradores y empleados)
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {"detail": "No tienes permiso para acceder a estos analytics."},
                status=status.HTTP_403_FORBIDDEN,
            )

        time_range = request.GET.get("range", "7d")

        # Calcular fechas según el rango
        from datetime import datetime, timedelta

        today = datetime.now().date()

        if time_range == "7d":
            start_date = today - timedelta(days=7)
        elif time_range == "30d":
            start_date = today - timedelta(days=30)
        elif time_range == "90d":
            start_date = today - timedelta(days=90)
        else:
            start_date = today - timedelta(days=7)

        # Tendencia de ventas por día
        ventas_por_dia = []
        for i in range((today - start_date).days + 1):
            fecha = start_date + timedelta(days=i)
            ventas_dia = Venta.objects.filter(
                fecha_venta__date=fecha, eliminado=False
            ).aggregate(total=models.Sum("total"), count=models.Count("id"))

            ventas_por_dia.append(
                {
                    "fecha": fecha.strftime("%Y-%m-%d"),
                    "total": float(ventas_dia["total"] or 0),
                    "cantidad": ventas_dia["count"] or 0,
                }
            )

        # Productos más vendidos
        productos_vendidos = (
            DetalleVenta.objects.filter(
                venta__fecha_venta__date__gte=start_date, venta__eliminado=False
            )
            .values("producto__nombre")
            .annotate(
                cantidad_vendida=models.Sum("cantidad"),
                ingresos=models.Sum(models.F("cantidad") * models.F("precio_unitario")),
            )
            .order_by("-cantidad_vendida")[:10]
        )

        # Servicios más solicitados
        servicios_populares = (
            DetalleMantenimiento.objects.filter(
                mantenimiento__fecha_ingreso__date__gte=start_date,
                mantenimiento__eliminado=False,
            )
            .values("servicio__nombre")
            .annotate(cantidad=models.Count("id"), ingresos=models.Sum("precio"))
            .order_by("-cantidad")[:10]
        )

        analytics_data = {
            "salesTrend": {
                "labels": [item["fecha"] for item in ventas_por_dia],
                "datasets": [
                    {
                        "label": "Ventas Diarias",
                        "data": [item["total"] for item in ventas_por_dia],
                        "borderColor": "#3B82F6",
                        "backgroundColor": "#3B82F630",
                        "tension": 0.4,
                    }
                ],
            },
            "topProducts": list(productos_vendidos),
            "popularServices": list(servicios_populares),
            "summary": {
                "totalSales": sum(item["total"] for item in ventas_por_dia),
                "totalOrders": sum(item["cantidad"] for item in ventas_por_dia),
                "avgOrderValue": sum(item["total"] for item in ventas_por_dia)
                / max(sum(item["cantidad"] for item in ventas_por_dia), 1),
            },
        }

        return Response({"success": True, "data": analytics_data})

    except Exception as e:
        logger.error(f"Error en bi_analytics_advanced: {e}")
        return Response(
            {"error": "Error al obtener analytics avanzados"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_demand_forecast(request):
    """
    Pronóstico de demanda para productos
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {"detail": "No tienes permiso para acceder a pronósticos."},
                status=status.HTTP_403_FORBIDDEN,
            )

        product_id = request.GET.get("product_id")
        days = int(request.GET.get("days", 7))

        from datetime import datetime, timedelta

        today = datetime.now().date()
        start_date = today - timedelta(days=30)  # Usar últimos 30 días para predicción

        if product_id:
            # Pronóstico para producto específico
            ventas_historicas = (
                DetalleVenta.objects.filter(
                    producto_id=product_id,
                    venta__fecha_venta__date__gte=start_date,
                    venta__eliminado=False,
                )
                .values("venta__fecha_venta__date")
                .annotate(cantidad_vendida=models.Sum("cantidad"))
                .order_by("venta__fecha_venta__date")
            )
        else:
            # Pronóstico general de ventas
            ventas_historicas = (
                Venta.objects.filter(fecha_venta__date__gte=start_date, eliminado=False)
                .values("fecha_venta__date")
                .annotate(cantidad_vendida=models.Count("id"))
                .order_by("fecha_venta__date")
            )

        # Calcular promedio móvil simple como predicción
        if ventas_historicas:
            valores = [item["cantidad_vendida"] for item in ventas_historicas]
            promedio = sum(valores) / len(valores)
            tendencia = (
                (valores[-1] - valores[0]) / len(valores) if len(valores) > 1 else 0
            )

            # Generar pronóstico
            forecast = []
            for i in range(days):
                prediccion = max(0, promedio + (tendencia * i))
                forecast.append(round(prediccion, 2))
        else:
            forecast = [0] * days

        forecast_data = {
            "forecast": forecast,
            "confidence": 75,  # Confianza básica
            "historical_data": list(ventas_historicas),
            "trend": (
                "upward"
                if len(forecast) > 1 and forecast[-1] > forecast[0]
                else "stable"
            ),
        }

        return Response({"success": True, "data": forecast_data})

    except Exception as e:
        logger.error(f"Error en bi_demand_forecast: {e}")
        return Response(
            {"error": "Error al obtener pronóstico de demanda"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_profitability_analysis(request):
    """
    Análisis de rentabilidad por productos/servicios
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {
                    "detail": "No tienes permiso para acceder a análisis de rentabilidad."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        analysis_type = request.resolver_match.kwargs.get("type", "product")

        from datetime import datetime, timedelta

        today = datetime.now().date()
        start_date = today - timedelta(days=30)

        if analysis_type == "product":
            # Análisis de rentabilidad por productos
            productos_rentabilidad = (
                DetalleVenta.objects.filter(
                    venta__fecha_venta__date__gte=start_date, venta__eliminado=False
                )
                .values("producto__nombre", "producto__precio_costo")
                .annotate(
                    cantidad_vendida=models.Sum("cantidad"),
                    ingresos=models.Sum(
                        models.F("cantidad") * models.F("precio_unitario")
                    ),
                    costo_total=models.Sum(
                        models.F("cantidad") * models.F("producto__precio_costo")
                    ),
                )
                .annotate(
                    ganancia=models.F("ingresos") - models.F("costo_total"),
                    margen=models.Case(
                        models.When(
                            ingresos__gt=0,
                            then=(
                                (models.F("ingresos") - models.F("costo_total"))
                                / models.F("ingresos")
                            )
                            * 100,
                        ),
                        default=0,
                        output_field=models.FloatField(),
                    ),
                )
                .order_by("-ganancia")[:15]
            )

            profitability_data = {
                "topProducts": [
                    {
                        "name": item["producto__nombre"],
                        "revenue": float(item["ingresos"] or 0),
                        "cost": float(item["costo_total"] or 0),
                        "profit": float(item["ganancia"] or 0),
                        "margin": float(item["margen"] or 0),
                        "quantity_sold": item["cantidad_vendida"],
                    }
                    for item in productos_rentabilidad
                ],
                "chartData": {
                    "labels": [
                        item["producto__nombre"][:20]
                        for item in productos_rentabilidad[:10]
                    ],
                    "datasets": [
                        {
                            "label": "Margen (%)",
                            "data": [
                                float(item["margen"] or 0)
                                for item in productos_rentabilidad[:10]
                            ],
                            "backgroundColor": [
                                "#10B981",
                                "#3B82F6",
                                "#8B5CF6",
                                "#F59E0B",
                                "#EF4444",
                            ]
                            * 2,
                            "borderRadius": 4,
                        }
                    ],
                },
            }

        else:  # servicios
            servicios_rentabilidad = (
                DetalleMantenimiento.objects.filter(
                    mantenimiento__fecha_ingreso__date__gte=start_date,
                    mantenimiento__eliminado=False,
                )
                .values("servicio__nombre")
                .annotate(cantidad=models.Count("id"), ingresos=models.Sum("precio"))
                .order_by("-ingresos")[:15]
            )

            profitability_data = {
                "topServices": [
                    {
                        "name": item["servicio__nombre"],
                        "revenue": float(item["ingresos"] or 0),
                        "quantity": item["cantidad"],
                    }
                    for item in servicios_rentabilidad
                ],
                "chartData": {
                    "labels": [
                        item["servicio__nombre"][:20]
                        for item in servicios_rentabilidad[:10]
                    ],
                    "datasets": [
                        {
                            "label": "Ingresos ($)",
                            "data": [
                                float(item["ingresos"] or 0)
                                for item in servicios_rentabilidad[:10]
                            ],
                            "backgroundColor": [
                                "#10B981",
                                "#3B82F6",
                                "#8B5CF6",
                                "#F59E0B",
                                "#EF4444",
                            ]
                            * 2,
                            "borderRadius": 4,
                        }
                    ],
                },
            }

        return Response({"success": True, "data": profitability_data})

    except Exception as e:
        logger.error(f"Error en bi_profitability_analysis: {e}")
        return Response(
            {"error": "Error al obtener análisis de rentabilidad"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_technician_performance(request):
    """
    Análisis de performance de técnicos
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {"detail": "No tienes permiso para acceder a performance de técnicos."},
                status=status.HTTP_403_FORBIDDEN,
            )

        technician_id = request.resolver_match.kwargs.get(
            "technician_id"
        ) or request.GET.get("technician_id")

        from datetime import datetime, timedelta

        today = datetime.now().date()
        start_date = today - timedelta(days=30)

        # Obtener técnicos
        tecnicos_query = Persona.objects.filter(
            usuario__roles__nombre__iexact="tecnico", eliminado=False
        )

        if technician_id:
            tecnicos_query = tecnicos_query.filter(id=technician_id)

        performance_data = []

        for tecnico in tecnicos_query:
            # Mantenimientos asignados
            mantenimientos = Mantenimiento.objects.filter(
                tecnico_asignado=tecnico,
                fecha_ingreso__date__gte=start_date,
                eliminado=False,
            )

            total_mantenimientos = mantenimientos.count()
            completados = mantenimientos.filter(estado="completado").count()

            # Calcular tiempo promedio
            mantenimientos_con_tiempo = mantenimientos.filter(
                fecha_entrega__isnull=False
            )

            if mantenimientos_con_tiempo.exists():
                tiempos = []
                for mant in mantenimientos_con_tiempo:
                    if mant.fecha_entrega and mant.fecha_ingreso:
                        tiempo_dias = (mant.fecha_entrega - mant.fecha_ingreso).days
                        tiempos.append(tiempo_dias)

                tiempo_promedio = sum(tiempos) / len(tiempos) if tiempos else 0
            else:
                tiempo_promedio = 0

            # Calcular eficiencia
            eficiencia = (
                (completados / total_mantenimientos * 100)
                if total_mantenimientos > 0
                else 0
            )

            performance_data.append(
                {
                    "id": tecnico.id,
                    "name": f"{tecnico.nombre} {tecnico.apellido}",
                    "total_maintenance": total_mantenimientos,
                    "completed": completados,
                    "efficiency": round(eficiencia, 2),
                    "avg_completion_time": round(tiempo_promedio, 1),
                    "satisfaction": 4.5,  # Placeholder - se puede implementar con sistema de calificaciones
                }
            )

        # Datos para gráfico radar
        if performance_data:
            chart_data = {
                "labels": [
                    "Eficiencia",
                    "Velocidad",
                    "Cantidad",
                    "Calidad",
                    "Puntualidad",
                ],
                "datasets": [],
            }

            colors = ["#8B5CF6", "#EF4444", "#10B981", "#F59E0B", "#3B82F6"]

            for i, tecnico in enumerate(
                performance_data[:5]
            ):  # Máximo 5 técnicos en el gráfico
                dataset = {
                    "label": tecnico["name"],
                    "data": [
                        tecnico["efficiency"],
                        100
                        - min(
                            tecnico["avg_completion_time"] * 10, 100
                        ),  # Velocidad inversa
                        min(
                            tecnico["total_maintenance"] * 5, 100
                        ),  # Cantidad normalizada
                        tecnico["satisfaction"] * 20,  # Calidad (satisfacción * 20)
                        90,  # Puntualidad placeholder
                    ],
                    "borderColor": colors[i % len(colors)],
                    "backgroundColor": colors[i % len(colors)] + "30",
                    "pointBackgroundColor": colors[i % len(colors)],
                }
                chart_data["datasets"].append(dataset)

        result = {
            "technicians": performance_data,
            "chartData": chart_data if performance_data else None,
            "summary": {
                "total_technicians": len(performance_data),
                "avg_efficiency": (
                    sum(t["efficiency"] for t in performance_data)
                    / len(performance_data)
                    if performance_data
                    else 0
                ),
                "avg_completion_time": (
                    sum(t["avg_completion_time"] for t in performance_data)
                    / len(performance_data)
                    if performance_data
                    else 0
                ),
            },
        }

        return Response({"success": True, "data": result})

    except Exception as e:
        logger.error(f"Error en bi_technician_performance: {e}")
        return Response(
            {"error": "Error al obtener performance de técnicos"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_customer_segmentation(request):
    """
    Segmentación de clientes
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {
                    "detail": "No tienes permiso para acceder a segmentación de clientes."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        from datetime import datetime, timedelta

        today = datetime.now().date()
        start_date = today - timedelta(days=90)  # Últimos 3 meses

        # Obtener clientes con sus compras
        clientes_data = Persona.objects.filter(
            usuario__roles__nombre__iexact="cliente", eliminado=False
        ).annotate(
            total_compras=models.Count(
                "venta",
                filter=models.Q(
                    venta__fecha_venta__date__gte=start_date, venta__eliminado=False
                ),
            ),
            total_gastado=models.Sum(
                "venta__total",
                filter=models.Q(
                    venta__fecha_venta__date__gte=start_date, venta__eliminado=False
                ),
            ),
            ultima_compra=models.Max(
                "venta__fecha_venta", filter=models.Q(venta__eliminado=False)
            ),
        )

        # Segmentar clientes
        vip_clientes = []
        frecuentes = []
        ocasionales = []
        nuevos = []
        inactivos = []

        for cliente in clientes_data:
            total_compras = cliente.total_compras or 0
            total_gastado = cliente.total_gastado or 0

            # Determinar cuándo fue la última compra
            dias_desde_ultima = None
            if cliente.ultima_compra:
                dias_desde_ultima = (today - cliente.ultima_compra.date()).days

            # Lógica de segmentación
            if total_gastado > 100000 and total_compras > 10:  # VIP
                vip_clientes.append(cliente)
            elif total_compras >= 5 and (
                dias_desde_ultima is None or dias_desde_ultima <= 30
            ):  # Frecuentes
                frecuentes.append(cliente)
            elif total_compras >= 2 and (
                dias_desde_ultima is None or dias_desde_ultima <= 60
            ):  # Ocasionales
                ocasionales.append(cliente)
            elif (
                dias_desde_ultima is None or dias_desde_ultima <= 30
            ):  # Nuevos (primera compra reciente)
                nuevos.append(cliente)
            else:  # Inactivos
                inactivos.append(cliente)

        # Calcular métricas por segmento
        segmentos = [
            {
                "name": "VIP",
                "count": len(vip_clientes),
                "revenue": sum(c.total_gastado or 0 for c in vip_clientes),
                "avg_purchase": sum(c.total_gastado or 0 for c in vip_clientes)
                / max(len(vip_clientes), 1),
            },
            {
                "name": "Frecuente",
                "count": len(frecuentes),
                "revenue": sum(c.total_gastado or 0 for c in frecuentes),
                "avg_purchase": sum(c.total_gastado or 0 for c in frecuentes)
                / max(len(frecuentes), 1),
            },
            {
                "name": "Ocasional",
                "count": len(ocasionales),
                "revenue": sum(c.total_gastado or 0 for c in ocasionales),
                "avg_purchase": sum(c.total_gastado or 0 for c in ocasionales)
                / max(len(ocasionales), 1),
            },
            {
                "name": "Nuevo",
                "count": len(nuevos),
                "revenue": sum(c.total_gastado or 0 for c in nuevos),
                "avg_purchase": sum(c.total_gastado or 0 for c in nuevos)
                / max(len(nuevos), 1),
            },
        ]

        # Datos para gráfico de dona
        chart_data = {
            "labels": [s["name"] for s in segmentos],
            "datasets": [
                {
                    "data": [s["count"] for s in segmentos],
                    "backgroundColor": ["#10B981", "#3B82F6", "#F59E0B", "#8B5CF6"],
                    "borderWidth": 2,
                    "borderColor": "#fff",
                }
            ],
        }

        result = {
            "segments": segmentos,
            "chartData": chart_data,
            "summary": {
                "total_customers": sum(s["count"] for s in segmentos),
                "total_revenue": sum(s["revenue"] for s in segmentos),
                "most_valuable_segment": (
                    max(segmentos, key=lambda x: x["revenue"])["name"]
                    if segmentos
                    else None
                ),
            },
        }

        return Response({"success": True, "data": result})

    except Exception as e:
        logger.error(f"Error en bi_customer_segmentation: {e}")
        return Response(
            {"error": "Error al obtener segmentación de clientes"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_trend_analysis(request):
    """
    Análisis de tendencias para métricas específicas
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {"detail": "No tienes permiso para acceder a análisis de tendencias."},
                status=status.HTTP_403_FORBIDDEN,
            )

        metric = request.resolver_match.kwargs.get("metric", "sales")
        time_range = request.GET.get("range", "30d")

        from datetime import datetime, timedelta

        today = datetime.now().date()

        if time_range == "7d":
            start_date = today - timedelta(days=7)
        elif time_range == "30d":
            start_date = today - timedelta(days=30)
        elif time_range == "90d":
            start_date = today - timedelta(days=90)
        else:
            start_date = today - timedelta(days=30)

        trend_data = {}

        if metric == "sales":
            # Tendencia de ventas
            ventas_data = []
            for i in range((today - start_date).days + 1):
                fecha = start_date + timedelta(days=i)
                ventas_dia = Venta.objects.filter(
                    fecha_venta__date=fecha, eliminado=False
                ).aggregate(total=models.Sum("total"))

                ventas_data.append(float(ventas_dia["total"] or 0))

            # Calcular tendencia
            if len(ventas_data) > 1:
                inicio = (
                    sum(ventas_data[:3]) / 3
                    if len(ventas_data) >= 3
                    else ventas_data[0]
                )
                final = (
                    sum(ventas_data[-3:]) / 3
                    if len(ventas_data) >= 3
                    else ventas_data[-1]
                )
                percentage_change = (
                    ((final - inicio) / inicio * 100) if inicio > 0 else 0
                )
            else:
                percentage_change = 0

            trend_data = {
                "metric": "Ventas",
                "trend": (
                    "upward"
                    if percentage_change > 5
                    else "downward" if percentage_change < -5 else "stable"
                ),
                "percentage": round(percentage_change, 2),
                "data": ventas_data,
                "labels": [
                    (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(len(ventas_data))
                ],
            }

        elif metric == "maintenance":
            # Tendencia de mantenimientos
            mantenimientos_data = []
            for i in range((today - start_date).days + 1):
                fecha = start_date + timedelta(days=i)
                mant_dia = Mantenimiento.objects.filter(
                    fecha_ingreso__date=fecha, eliminado=False
                ).count()

                mantenimientos_data.append(mant_dia)

            # Calcular tendencia
            if len(mantenimientos_data) > 1:
                inicio = (
                    sum(mantenimientos_data[:3]) / 3
                    if len(mantenimientos_data) >= 3
                    else mantenimientos_data[0]
                )
                final = (
                    sum(mantenimientos_data[-3:]) / 3
                    if len(mantenimientos_data) >= 3
                    else mantenimientos_data[-1]
                )
                percentage_change = (
                    ((final - inicio) / inicio * 100) if inicio > 0 else 0
                )
            else:
                percentage_change = 0

            trend_data = {
                "metric": "Mantenimientos",
                "trend": (
                    "upward"
                    if percentage_change > 5
                    else "downward" if percentage_change < -5 else "stable"
                ),
                "percentage": round(percentage_change, 2),
                "data": mantenimientos_data,
                "labels": [
                    (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(len(mantenimientos_data))
                ],
            }

        elif metric == "customers":
            # Tendencia de nuevos clientes
            clientes_data = []
            for i in range((today - start_date).days + 1):
                fecha = start_date + timedelta(days=i)
                nuevos_clientes = Persona.objects.filter(
                    usuario__roles__nombre__iexact="cliente",
                    fecha_registro__date=fecha,
                    eliminado=False,
                ).count()

                clientes_data.append(nuevos_clientes)

            # Calcular tendencia
            if len(clientes_data) > 1:
                inicio = (
                    sum(clientes_data[:3]) / 3
                    if len(clientes_data) >= 3
                    else clientes_data[0]
                )
                final = (
                    sum(clientes_data[-3:]) / 3
                    if len(clientes_data) >= 3
                    else clientes_data[-1]
                )
                percentage_change = (
                    ((final - inicio) / inicio * 100) if inicio > 0 else 0
                )
            else:
                percentage_change = 0

            trend_data = {
                "metric": "Nuevos Clientes",
                "trend": (
                    "upward"
                    if percentage_change > 5
                    else "downward" if percentage_change < -5 else "stable"
                ),
                "percentage": round(percentage_change, 2),
                "data": clientes_data,
                "labels": [
                    (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                    for i in range(len(clientes_data))
                ],
            }

        return Response({"success": True, "data": trend_data})

    except Exception as e:
        logger.error(f"Error en bi_trend_analysis: {e}")
        return Response(
            {"error": "Error al obtener análisis de tendencias"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bi_custom_kpis(request):
    """
    KPIs personalizados para Business Intelligence
    """
    try:
        # Verificar permisos
        user_roles = [role.nombre.lower() for role in request.user.roles.all()]
        if not any(role in ["administrador", "empleado"] for role in user_roles):
            return Response(
                {"detail": "No tienes permiso para acceder a KPIs personalizados."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from datetime import datetime, timedelta

        today = datetime.now().date()
        last_month = today - timedelta(days=30)
        last_week = today - timedelta(days=7)

        # ROI - Return on Investment
        ventas_mes = (
            Venta.objects.filter(
                fecha_venta__date__gte=last_month, eliminado=False
            ).aggregate(total=models.Sum("total"))["total"]
            or 0
        )

        costos_mes = (
            DetalleVenta.objects.filter(
                venta__fecha_venta__date__gte=last_month, venta__eliminado=False
            ).aggregate(
                costo_total=models.Sum(
                    models.F("cantidad") * models.F("producto__precio_costo")
                )
            )[
                "costo_total"
            ]
            or 0
        )

        roi = ((ventas_mes - costos_mes) / costos_mes * 100) if costos_mes > 0 else 0

        # Tiempo promedio de mantenimiento
        mantenimientos_completados = Mantenimiento.objects.filter(
            estado="completado",
            fecha_entrega__isnull=False,
            fecha_ingreso__date__gte=last_month,
            eliminado=False,
        )

        if mantenimientos_completados.exists():
            tiempos = []
            for mant in mantenimientos_completados:
                tiempo_dias = (mant.fecha_entrega - mant.fecha_ingreso).days
                tiempos.append(tiempo_dias)
            tiempo_promedio = sum(tiempos) / len(tiempos)
        else:
            tiempo_promedio = 0

        # Satisfacción del cliente (placeholder - se puede implementar con sistema de calificaciones)
        satisfaccion_cliente = 4.5

        # Eficiencia operacional
        mantenimientos_totales = Mantenimiento.objects.filter(
            fecha_ingreso__date__gte=last_month, eliminado=False
        ).count()

        mantenimientos_completados_count = mantenimientos_completados.count()
        eficiencia_operacional = (
            (mantenimientos_completados_count / mantenimientos_totales * 100)
            if mantenimientos_totales > 0
            else 0
        )

        # Rotación de inventario
        productos_vendidos = (
            DetalleVenta.objects.filter(
                venta__fecha_venta__date__gte=last_month, venta__eliminado=False
            ).aggregate(total=models.Sum("cantidad"))["total"]
            or 0
        )

        inventario_promedio = (
            Inventario.objects.filter(eliminado=False).aggregate(
                total=models.Sum("stock_actual")
            )["total"]
            or 1
        )

        rotacion_inventario = (
            productos_vendidos / inventario_promedio if inventario_promedio > 0 else 0
        )

        # Valor promedio de venta
        ventas_count = Venta.objects.filter(
            fecha_venta__date__gte=last_month, eliminado=False
        ).count()

        valor_promedio_venta = ventas_mes / ventas_count if ventas_count > 0 else 0

        kpis = [
            {
                "name": "ROI",
                "value": f"{roi:.1f}%",
                "trend": "up" if roi > 20 else "down" if roi < 10 else "stable",
                "description": "Retorno sobre inversión mensual",
            },
            {
                "name": "Tiempo Promedio Mantenimiento",
                "value": f"{tiempo_promedio:.1f} días",
                "trend": (
                    "down"
                    if tiempo_promedio < 3
                    else "up" if tiempo_promedio > 5 else "stable"
                ),
                "description": "Tiempo promedio de completar mantenimientos",
            },
            {
                "name": "Satisfacción Cliente",
                "value": f"{satisfaccion_cliente}/5",
                "trend": (
                    "up"
                    if satisfaccion_cliente >= 4.5
                    else "down" if satisfaccion_cliente < 4 else "stable"
                ),
                "description": "Calificación promedio de satisfacción",
            },
            {
                "name": "Eficiencia Operacional",
                "value": f"{eficiencia_operacional:.1f}%",
                "trend": (
                    "up"
                    if eficiencia_operacional > 85
                    else "down" if eficiencia_operacional < 70 else "stable"
                ),
                "description": "Porcentaje de mantenimientos completados",
            },
            {
                "name": "Rotación Inventario",
                "value": f"{rotacion_inventario:.2f}x",
                "trend": (
                    "up"
                    if rotacion_inventario > 0.5
                    else "down" if rotacion_inventario < 0.2 else "stable"
                ),
                "description": "Velocidad de rotación del inventario",
            },
            {
                "name": "Valor Promedio Venta",
                "value": f"${valor_promedio_venta:,.0f}",
                "trend": (
                    "up"
                    if valor_promedio_venta > 50000
                    else "down" if valor_promedio_venta < 20000 else "stable"
                ),
                "description": "Valor promedio por venta",
            },
        ]

        return Response({"success": True, "data": {"kpis": kpis}})

    except Exception as e:
        logger.error(f"Error en bi_custom_kpis: {e}")
        return Response(
            {"error": "Error al obtener KPIs personalizados"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCliente])
def cliente_ventas(request):
    """
    Endpoint específico para obtener las compras del cliente autenticado
    """
    try:
        # Debug inicial
        logger.info(
            f"🔍 Cliente ventas - Usuario: {request.user.id} - {request.user.username}"
        )

        # Verificar persona_asociada
        if not hasattr(request.user, "persona_asociada"):
            logger.error(
                f"❌ Usuario {request.user.id} no tiene atributo persona_asociada"
            )
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.persona_asociada:
            logger.error(f"❌ Usuario {request.user.id} tiene persona_asociada=None")
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = request.user.persona_asociada
        logger.info(
            f"🔍 Persona asociada: {cliente.id} - {cliente.nombre} {cliente.apellido}"
        )

        # Verificar todas las ventas del cliente (sin filtro eliminado)
        todas_ventas = Venta.objects.filter(cliente=cliente)
        logger.info(
            f"🔍 Total ventas del cliente (incluye eliminadas): {todas_ventas.count()}"
        )

        # Si hay ventas, mostrar detalles de la primera
        if todas_ventas.count() > 0:
            primera_venta = todas_ventas.first()
            logger.info(
                f"🔍 Primera venta - ID: {primera_venta.id}, eliminado: {primera_venta.eliminado}, total: {primera_venta.total}"
            )

        # Obtener ventas NO eliminadas del cliente
        ventas = (
            Venta.objects.select_related("cliente")
            .prefetch_related("detalles__producto")
            .filter(cliente=cliente, eliminado=False)
            .order_by("-fecha_venta")
        )

        logger.info(f"🔍 Ventas NO eliminadas encontradas: {ventas.count()}")

        # Si no hay ventas no eliminadas, verificar si todas están eliminadas
        if ventas.count() == 0 and todas_ventas.count() > 0:
            ventas_eliminadas = todas_ventas.filter(eliminado=True).count()
            logger.warning(
                f"⚠️ El cliente tiene {ventas_eliminadas} ventas pero todas están eliminadas"
            )

        # Serializar los datos
        from .serializers import VentaSerializer

        # Serializar las ventas
        serializer = VentaSerializer(ventas, many=True, context={"request": request})

        logger.info(f"✅ Ventas serializadas correctamente para cliente {cliente.id}")
        return Response(
            {"success": True, "data": serializer.data, "count": ventas.count()}
        )

    except Exception as e:
        logger.error(f"❌ Error obteniendo compras del cliente: {e}")
        import traceback

        logger.error(f"❌ Traceback completo:\n{traceback.format_exc()}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCliente])
def cliente_mantenimientos(request):
    """
    Endpoint específico para obtener los mantenimientos del cliente autenticado
    """
    try:
        # Debug inicial
        logger.info(
            f"🔍 Cliente mantenimientos - Usuario: {request.user.id} - {request.user.username}"
        )

        # Verificar persona_asociada
        if not hasattr(request.user, "persona_asociada"):
            logger.error(
                f"❌ Usuario {request.user.id} no tiene atributo persona_asociada"
            )
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.persona_asociada:
            logger.error(f"❌ Usuario {request.user.id} tiene persona_asociada=None")
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = request.user.persona_asociada
        logger.info(
            f"🔍 Persona asociada: {cliente.id} - {cliente.nombre} {cliente.apellido}"
        )

        # Obtener mantenimientos de las motos del cliente
        mantenimientos = (
            Mantenimiento.objects.filter(moto__propietario=cliente, eliminado=False)
            .select_related("moto__propietario", "tecnico_asignado", "completado_por")
            .prefetch_related(
                "detalles", "detalles__servicio", "repuestos", "repuestos__producto"
            )
            .order_by("-fecha_ingreso")
        )

        logger.info(f"🔍 Mantenimientos encontrados: {mantenimientos.count()}")

        # Si no hay mantenimientos, devolver lista vacía con mensaje informativo
        if mantenimientos.count() == 0:
            logger.info(f"ℹ️ Cliente {cliente.id} no tiene mantenimientos registrados")
            return Response(
                {
                    "success": True,
                    "data": [],
                    "count": 0,
                    "message": "No tienes mantenimientos registrados.",
                }
            )

        # Serializar los datos
        from .serializers import MantenimientoSerializer

        serializer = MantenimientoSerializer(
            mantenimientos, many=True, context={"request": request}
        )

        logger.info(
            f"✅ Mantenimientos serializados correctamente para cliente {cliente.id}"
        )
        return Response(
            {"success": True, "data": serializer.data, "count": mantenimientos.count()}
        )

    except Exception as e:
        logger.error(f"❌ Error obteniendo mantenimientos del cliente: {e}")
        import traceback

        logger.error(f"❌ Traceback completo:\n{traceback.format_exc()}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cliente_data_completa(request):
    """
    Endpoint unificado para obtener TODOS los datos del cliente en una sola llamada
    Útil para la app Flutter que necesita cargar datos iniciales
    """
    try:
        # Verificar que sea cliente
        if not IsCliente().has_permission(request, None):
            return Response(
                {"error": "Solo para clientes"}, status=status.HTTP_403_FORBIDDEN
            )

        logger.info(
            f"🔍 Cliente data completa - Usuario: {request.user.id} - {request.user.username}"
        )

        # Verificar persona_asociada
        if (
            not hasattr(request.user, "persona_asociada")
            or not request.user.persona_asociada
        ):
            return Response(
                {
                    "success": True,
                    "data": {
                        "motos": [],
                        "mantenimientos": [],
                        "compras": [],
                        "perfil": None,
                        "message": "Usuario sin datos de persona asociados",
                    },
                }
            )

        cliente = request.user.persona_asociada
        logger.info(
            f"🔍 Persona asociada: {cliente.id} - {cliente.nombre} {cliente.apellido}"
        )

        # Obtener motos
        motos = Moto.objects.filter(
            propietario=cliente, eliminado=False
        ).select_related("propietario")
        logger.info(f"🏍️ Motos encontradas: {motos.count()}")

        # Obtener mantenimientos
        mantenimientos = (
            Mantenimiento.objects.filter(moto__propietario=cliente, eliminado=False)
            .select_related("moto__propietario")
            .order_by("-fecha_ingreso")
        )
        logger.info(f"🔧 Mantenimientos encontrados: {mantenimientos.count()}")

        # Obtener compras
        compras = (
            Venta.objects.filter(cliente=cliente, eliminado=False)
            .select_related("cliente")
            .order_by("-fecha_venta")
        )
        logger.info(f"🛒 Compras encontradas: {compras.count()}")

        # Serializar datos
        from .serializers import (
            MotoSerializer,
            MantenimientoSerializer,
            VentaSerializer,
        )

        motos_data = MotoSerializer(motos, many=True).data
        mantenimientos_data = MantenimientoSerializer(
            mantenimientos, many=True, context={"request": request}
        ).data
        compras_data = VentaSerializer(compras, many=True).data

        # Datos del perfil
        perfil_data = {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "apellido": cliente.apellido,
            "cedula": cliente.cedula,
            "telefono": cliente.telefono,
            "direccion": cliente.direccion,
            "email": request.user.correo_electronico,
        }

        response_data = {
            "success": True,
            "data": {
                "motos": motos_data,
                "mantenimientos": mantenimientos_data,
                "compras": compras_data,
                "perfil": perfil_data,
                "counts": {
                    "motos": motos.count(),
                    "mantenimientos": mantenimientos.count(),
                    "compras": compras.count(),
                },
            },
        }

        logger.info(f"✅ Datos completos obtenidos para cliente {cliente.id}")
        return Response(response_data)

    except Exception as e:
        logger.error(f"❌ Error obteniendo datos completos del cliente: {e}")
        import traceback

        logger.error(f"❌ Traceback completo:\n{traceback.format_exc()}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class CambioPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        serializer = CambioPasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.check_password(serializer.validated_data["old_password"]):
                user.set_password(serializer.validated_data["new_password"])
                user.save()
                logger.info(
                    f"Cambio de contraseña exitoso para usuario: {user.username}"
                )
                return Response({"message": "Contraseña actualizada exitosamente"})
            return Response(
                {"error": "Contraseña actual incorrecta"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """Vista de login personalizada con protección contra ataques de fuerza bruta"""
    correo = request.data.get("correo_electronico", "").lower().strip()
    password = request.data.get("password")

    # Configuración de seguridad
    MAX_ATTEMPTS = 5
    LOCKOUT_MINUTES = 30

    if not correo or not password:
        return Response(
            {"error": "Correo electrónico y contraseña son requeridos"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # First check if user exists
    try:
        user = Usuario.objects.get(correo_electronico=correo)
    except Usuario.DoesNotExist:
        return Response(
            {"error": "Usuario no existe"}, status=status.HTTP_401_UNAUTHORIZED
        )

    # Check if account is locked
    if (
        hasattr(user, "failed_login_attempts")
        and user.failed_login_attempts >= MAX_ATTEMPTS
    ):
        # Check if lockout period has expired
        if user.last_failed_login:
            from django.utils import timezone
            from datetime import timedelta

            lockout_end = user.last_failed_login + timedelta(minutes=LOCKOUT_MINUTES)
            if timezone.now() < lockout_end:
                remaining_minutes = (lockout_end - timezone.now()).seconds // 60
                return Response(
                    {
                        "error": f"Cuenta bloqueada por demasiados intentos fallidos. Intenta en {remaining_minutes} minutos.",
                        "locked": True,
                        "remaining_minutes": remaining_minutes,
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            else:
                # Lockout expired, reset attempts
                user.failed_login_attempts = 0
                user.save(update_fields=["failed_login_attempts"])

    # Then check password
    if not user.check_password(password):
        # Increment failed login attempts
        from django.utils import timezone

        user.failed_login_attempts = getattr(user, "failed_login_attempts", 0) + 1
        user.last_failed_login = timezone.now()
        user.save(update_fields=["failed_login_attempts", "last_failed_login"])

        attempts_remaining = MAX_ATTEMPTS - user.failed_login_attempts

        if user.failed_login_attempts >= MAX_ATTEMPTS:
            return Response(
                {
                    "error": f"Demasiados intentos fallidos. Tu cuenta ha sido bloqueada por {LOCKOUT_MINUTES} minutos.",
                    "locked": True,
                    "lockout_minutes": LOCKOUT_MINUTES,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        else:
            return Response(
                {
                    "error": "Credenciales erroneas",
                    "attempts_remaining": attempts_remaining,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

    if user.is_active:
        # Reset failed login attempts on successful login
        user.failed_login_attempts = 0
        user.last_failed_login = None
        user.save(update_fields=["failed_login_attempts", "last_failed_login"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": UsuarioMeSerializer(user).data,
            }
        )

    return Response({"error": "Usuario inactivo"}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """Vista de logout"""
    try:
        refresh_token = request.data.get("refresh")
        if refresh_token:
            token = RefreshToken(refresh_token)
            token.blacklist()
        logger.info(f"Logout exitoso para usuario: {request.user.username}")
        return Response({"message": "Logout exitoso"}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error en logout: {str(e)}")
        return Response(
            {"error": "Error en logout"}, status=status.HTTP_400_BAD_REQUEST
        )


# =======================================
# PERSONA Y USUARIO VIEWSETS
# =======================================
class PersonaViewSet(viewsets.ModelViewSet):
    """
    ViewSet para manejar CRUD de Personas

    - list: Listar todas las personas
    - create: Crear nueva persona (opcionalmente con usuario anidado)
    - retrieve: Obtener una persona por ID
    - update: Actualizar persona completa
    - partial_update: Actualizar persona parcialmente
    - destroy: Eliminar persona
    """

    queryset = Persona.objects.select_related("usuario").all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return PersonaCreateSerializer
        return PersonaSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtros opcionales
        cedula = self.request.query_params.get("cedula", None)
        con_usuario = self.request.query_params.get("con_usuario", None)
        sin_usuario = self.request.query_params.get("sin_usuario", None)

        if cedula:
            queryset = queryset.filter(cedula__icontains=cedula)
        if con_usuario == "true":
            queryset = queryset.filter(usuario__isnull=False)
        if sin_usuario == "true":
            queryset = queryset.filter(usuario__isnull=True)

        return queryset

    @action(detail=True, methods=["post"])
    def asociar_usuario(self, request, pk=None):
        """Asociar un usuario existente a esta persona"""
        persona = self.get_object()
        usuario_id = request.data.get("usuario_id")

        if not usuario_id:
            return Response(
                {"error": "usuario_id es requerido"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            usuario = Usuario.objects.get(id=usuario_id)
            persona.usuario = usuario  # Asignar directamente
            persona.save()  # Guardar la persona para actualizar la relación
            serializer = self.get_serializer(persona)
            return Response(serializer.data)
        except Usuario.DoesNotExist:
            return Response(
                {"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:  # Capturar cualquier otra excepción
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def desasociar_usuario(self, request, pk=None):
        """Desasociar usuario de esta persona"""
        persona = self.get_object()

        if persona.usuario:
            persona.usuario = None  # Desasociar directamente
            persona.save()  # Guardar la persona para actualizar la relación
            serializer = self.get_serializer(persona)
            return Response(serializer.data)
        else:
            return Response(
                {"message": "Esta persona no tiene usuario asociado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"])
    def sin_usuario(self, request):
        """Obtener personas que no tienen usuario asociado"""
        personas = self.get_queryset().filter(usuario__isnull=True)
        serializer = self.get_serializer(personas, many=True)
        return Response(serializer.data)


# =======================================
# USUARIO VIEWSET
# =======================================
class UsuarioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para manejar CRUD de Usuarios

    - list: Listar todos los usuarios
    - create: Crear nuevo usuario (opcionalmente con persona anidada)
    - retrieve: Obtener un usuario por ID
    - update: Actualizar usuario completo
    - partial_update: Actualizar usuario parcialmente
    - destroy: Eliminar usuario
    """

    queryset = (
        Usuario.objects.select_related(
            "persona_asociada",
            "creado_por__persona_asociada",
            "actualizado_por__persona_asociada",
            "eliminado_por__persona_asociada",
        )
        .prefetch_related("roles__rol")
        .all()
    )
    permission_classes = [CustomPermission]
    pagination_class = UsuarioPagination  # <- aquí

    def get_permissions(self):
        """
        Permisos específicos para UsuarioViewSet:
        - Usar CustomPermission para todas las acciones
        - CustomPermission ya maneja correctamente los permisos de administrador
        """
        permission_classes = [CustomPermission]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "create":
            return UsuarioCreateSerializer
        elif self.action in [
            "crear_completo",
            "update_complete",
            "retrieve_complete",
        ]:  # Añadir update_complete y retrieve_complete
            return UsuarioPersonaCompleteSerializer
        return UsuarioSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        # -------------------------
        # Filtro por rol de usuario
        # -------------------------
        is_admin = IsAdministrador().has_permission(self.request, None)
        is_employee = IsEmpleado().has_permission(self.request, None)
        is_tecnico = IsTecnico().has_permission(self.request, None)

        # Técnicos solo pueden ver clientes relacionados con sus mantenimientos
        if is_tecnico and not is_admin:
            # Obtener IDs de usuarios que son propietarios de motos con mantenimientos asignados al técnico
            usuarios_relacionados = (
                Usuario.objects.filter(
                    persona_asociada__moto__mantenimiento__tecnico_asignado=self.request.user
                )
                .distinct()
                .values_list("id", flat=True)
            )
            queryset = queryset.filter(id__in=usuarios_relacionados)
            return queryset

        if not is_admin:
            # Si es empleado, solo mostrar usuarios con rol Cliente
            if is_employee:
                # Revertir cambio - mostrar todos los usuarios como antes
                pass

        # -------------------------
        # Filtro por 'activo'
        # -------------------------
        activo_param = self.request.query_params.get("activo", None)
        if activo_param is not None:
            if activo_param.lower() == "true":
                queryset = queryset.filter(is_active=True)
            elif activo_param.lower() == "false":
                queryset = queryset.filter(is_active=False)
        else:
            queryset = queryset.filter(is_active=True)

        # -------------------------
        # Filtro por 'eliminado' - CORREGIDO
        # -------------------------
        eliminado_param = self.request.query_params.get("eliminado", None)
        if eliminado_param is not None:
            if eliminado_param.lower() == "true":
                queryset = queryset.filter(eliminado=True)
            elif eliminado_param.lower() == "false":
                queryset = queryset.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo usuarios NO eliminados
            queryset = queryset.filter(eliminado=False)

        # -------------------------
        # Filtros opcionales desde query params
        # -------------------------
        correo = self.request.query_params.get("correo", None)
        con_persona = self.request.query_params.get("con_persona", None)
        sin_persona = self.request.query_params.get("sin_persona", None)
        search = self.request.query_params.get("search", None)

        if correo:
            queryset = queryset.filter(correo_electronico__icontains=correo)
        if con_persona == "true":
            queryset = queryset.filter(persona_asociada__isnull=False)
        if sin_persona == "true":
            queryset = queryset.filter(persona_asociada__isnull=True)

        if search:
            queryset = queryset.filter(
                models.Q(username__icontains=search)
                | models.Q(correo_electronico__icontains=search)
                | models.Q(persona_asociada__nombre__icontains=search)
                | models.Q(persona_asociada__apellido__icontains=search)
            ).distinct()

        # -------------------------
        # Filtro por roles
        # -------------------------
        roles_param = self.request.query_params.get("roles", None)
        if roles_param:
            try:
                roles_ids = [int(r) for r in roles_param.split(",") if r.isdigit()]
                if roles_ids:
                    queryset = queryset.filter(roles__rol__id__in=roles_ids).distinct()
            except ValueError:
                pass  # Ignorar si algún ID no es válido

        return queryset

    def perform_create(self, serializer):
        """Establecer el usuario que crea el registro"""
        # Guardar pasando el usuario directamente (igual que base)
        serializer.save(creado_por=self.request.user)

    def perform_update(self, serializer):
        """Establecer el usuario que actualiza el registro"""
        # Guardar pasando el usuario directamente (igual que Producto)
        serializer.save(actualizado_por=self.request.user)

    def perform_destroy(self, instance):
        """Establecer el usuario que elimina el registro (soft delete)"""
        # Configurar el usuario actual para que se guarde en eliminado_por
        instance._current_user = self.request.user
        instance.delete()

    @action(detail=True, methods=["post"])
    def asociar_persona(self, request, pk=None):
        """Asociar una persona existente a este usuario"""
        usuario = self.get_object()
        persona_id = request.data.get("persona_id")

        if not persona_id:
            return Response(
                {"error": "persona_id es requerido"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            persona = Persona.objects.get(id=persona_id)
            usuario.asociar_persona(persona)
            serializer = self.get_serializer(usuario)
            return Response(serializer.data)
        except Persona.DoesNotExist:
            return Response(
                {"error": "Persona no encontrada"}, status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"])
    def desasociar_persona(self, request, pk=None):
        """Desasociar persona de este usuario"""
        usuario = self.get_object()

        if usuario.tiene_persona:
            usuario.desasociar_persona()
            serializer = self.get_serializer(usuario)
            return Response(serializer.data)
        else:
            return Response(
                {"message": "Este usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=False, methods=["get"])
    def sin_persona(self, request):
        """Obtener usuarios que no tienen persona asociada"""
        usuarios = self.get_queryset().filter(persona_asociada__isnull=True)
        serializer = self.get_serializer(usuarios, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def crear_completo(self, request):
        """Crear usuario con persona anidada completa"""

        # Debug: Log de datos recibidos
        logger.info(f"=== INICIO crear_completo ===")
        logger.info(f"Datos recibidos: {request.data}")
        logger.info(f"Content-Type: {request.content_type}")
        logger.info(f"Método HTTP: {request.method}")

        try:
            # Debug: Antes de crear el serializer
            logger.info("Creando serializer...")
            serializer = UsuarioPersonaCompleteSerializer(data=request.data)

            # Debug: Verificar validación
            logger.info("Validando serializer...")
            if serializer.is_valid():
                logger.info("✅ Serializer válido")
                logger.info(f"Datos validados: {serializer.validated_data}")

                try:
                    # Debug: Antes de guardar
                    logger.info("Guardando usuario...")
                    usuario = serializer.save()
                    logger.info(f"✅ Usuario creado exitosamente: ID={usuario.id}")

                    # Debug: Datos del usuario creado
                    response_data = UsuarioPersonaCompleteSerializer(usuario).data
                    logger.info(f"Datos de respuesta: {response_data}")

                    return Response(
                        response_data,
                        status=status.HTTP_201_CREATED,
                    )

                except Exception as save_error:
                    logger.error(f"❌ Error al guardar usuario: {str(save_error)}")
                    logger.error(f"Tipo de error: {type(save_error).__name__}")

                    # Si es error de base de datos, mostrar más detalles
                    if hasattr(save_error, "__cause__") and save_error.__cause__:
                        logger.error(f"Causa original: {save_error.__cause__}")

                    return Response(
                        {
                            "error": "Error interno al crear usuario",
                            "detail": str(save_error),
                            "debug": True,
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            else:
                # Debug: Errores de validación detallados
                logger.warning("❌ Serializer NO válido")
                logger.warning(f"Errores de validación: {serializer.errors}")

                # Debug adicional: verificar errores por campo
                for field, errors in serializer.errors.items():
                    logger.warning(f"Campo '{field}': {errors}")

                # Verificar si hay errores no relacionados con campos específicos
                if hasattr(serializer, "_errors") and serializer._errors:
                    logger.warning(
                        f"Errores internos del serializer: {serializer._errors}"
                    )

                return Response(
                    {
                        "errors": serializer.errors,
                        "received_data": request.data,  # Para debug
                        "debug": True,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as general_error:
            logger.error(f"❌ Error general en crear_completo: {str(general_error)}")
            logger.error(f"Tipo de error: {type(general_error).__name__}")

            import traceback

            logger.error(f"Traceback completo:\n{traceback.format_exc()}")

            return Response(
                {
                    "error": "Error interno del servidor",
                    "detail": str(general_error),
                    "debug": True,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        finally:
            logger.info("=== FIN crear_completo ===")

    @action(
        detail=True, methods=["get"], url_path="complete"
    )  # Cambiar url_path para evitar conflicto
    def retrieve_complete(self, request, pk=None):
        """Obtener usuario con toda la información anidada"""
        usuario = self.get_object()
        serializer = UsuarioPersonaCompleteSerializer(usuario)
        return Response(serializer.data)

    @action(detail=True, methods=["put", "patch"], url_path="update_complete")
    def update_complete(self, request, pk=None):
        """Actualizar usuario con persona anidada completa"""
        logger.info(f"=== INICIO update_complete para usuario ID: {pk} ===")

        try:
            usuario = self.get_object()
            logger.info(f"Usuario obtenido: {usuario.username} (ID: {usuario.id})")
            logger.info(f"Datos originales: {request.data}")

            # Convertir datos anidados a campos individuales
            data = request.data.copy()
            if "persona_asociada" in data and isinstance(
                data["persona_asociada"], dict
            ):
                persona_data = data.pop("persona_asociada")
                logger.info(f"Convirtiendo persona_asociada: {persona_data}")

                # Mapear campos anidados a campos individuales
                mapping = {
                    "nombre": "persona_nombre",
                    "apellido": "persona_apellido",
                    "cedula": "persona_cedula",
                    "telefono": "persona_telefono",
                    "direccion": "persona_direccion",
                }

                for old_key, new_key in mapping.items():
                    if old_key in persona_data:
                        data[new_key] = persona_data[old_key]

            logger.info(f"Datos transformados: {data}")

            serializer = UsuarioPersonaCompleteSerializer(
                usuario, data=data, partial=True
            )

            logger.info("Validando serializer...")
            logger.info(
                f"🔍 Usuario actual autenticado: ID={self.request.user.id}, username={self.request.user.username}"
            )
            if serializer.is_valid():
                logger.info("✓ Serializer válido - Procediendo a guardar")
                # Establecer actualizado_por antes de guardar
                logger.info(f"🔍 Guardando con actualizado_por={self.request.user.id}")
                usuario = serializer.save(actualizado_por=self.request.user)
                logger.info(f"✓ Usuario guardado exitosamente: {usuario.username}")
                logger.info(
                    f"🔍 Después de guardar - actualizado_por del usuario: {usuario.actualizado_por}"
                )

                resultado = UsuarioPersonaCompleteSerializer(usuario).data
                logger.info("=== FIN update_complete EXITOSO ===")
                return Response(resultado)
            else:
                logger.error("✗ Serializer NO válido")
                logger.error(f"Errores del serializer: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as general_error:
            logger.error(f"ERROR GENERAL: {str(general_error)}", exc_info=True)
            return Response(
                {"error": f"Error interno: {str(general_error)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def cambiar_password(self, request, pk=None):
        """Cambiar contraseña del usuario - VERSIÓN MEJORADA"""
        usuario = self.get_object()
        new_password = request.data.get("new_password")

        if not new_password:
            return Response(
                {"error": "new_password es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Limpiar y convertir a string
            clean_password = str(new_password).strip()

            # Cambiar la contraseña
            usuario.set_password(clean_password)
            usuario.actualizado_por = self.request.user
            usuario.save()

            # Verificar el cambio
            usuario.refresh_from_db()

            # Probar la contraseña inmediatamente
            test_check = usuario.check_password(clean_password)

            if not test_check:
                raise Exception("La contraseña no se guardó correctamente")

            return Response(
                {
                    "message": "Contraseña actualizada exitosamente",
                    "debug": {
                        "password_test": test_check,
                        "user_active": usuario.is_active,
                    },
                }
            )

        except Exception as e:
            logger.error(
                f"Error al cambiar contraseña del usuario {usuario.id}: {str(e)}"
            )
            return Response(
                {"error": f"Error al actualizar la contraseña: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["post"])
    def assign_roles(self, request, pk=None):
        """Asignar roles a un usuario. Espera una lista de IDs de roles."""
        usuario = self.get_object()
        roles_ids = request.data.get("roles", [])

        if not isinstance(roles_ids, list):
            return Response(
                {"error": "El campo 'roles' debe ser una lista de IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for rol_id in roles_ids:
            try:
                rol = Rol.objects.get(id=rol_id)
                usuario_rol, created = UsuarioRol.objects.get_or_create(
                    usuario=usuario, rol=rol
                )
                if not created:
                    usuario_rol.activo = True
                    usuario_rol.save()
            except Rol.DoesNotExist:
                return Response(
                    {"error": f"Rol con ID {rol_id} no encontrado."},
                    status=status.HTTP_404_NOT_FOUND,
                )

        serializer = self.get_serializer(usuario)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def remove_roles(self, request, pk=None):
        """Remover roles de un usuario (desactivar). Espera una lista de IDs de roles."""
        usuario = self.get_object()
        roles_ids = request.data.get("roles", [])

        if not isinstance(roles_ids, list):
            return Response(
                {"error": "El campo 'roles' debe ser una lista de IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for rol_id in roles_ids:
            try:
                usuario_rol = UsuarioRol.objects.get(usuario=usuario, rol_id=rol_id)
                usuario_rol.activo = False
                usuario_rol.save()
            except UsuarioRol.DoesNotExist:
                pass  # El rol ya no está asignado o no estaba activo

        serializer = self.get_serializer(usuario)
        return Response(serializer.data)

    # activar y desactivar usuario
    @action(detail=True, methods=["patch"], url_path="toggle_user_status")
    def toggle_user_status(self, request, pk=None):
        try:
            # Usar queryset base sin filtros
            usuario = Usuario.objects.filter(id=pk).first()
            if not usuario:
                return Response({"error": "Usuario no encontrado"}, status=404)

            logger.info(f"🔹 toggle_user_status llamado para usuario ID={pk}")
            logger.info(f"Estado actual: is_active={usuario.is_active}")

            usuario.is_active = not usuario.is_active
            usuario.actualizado_por = self.request.user
            usuario.save(update_fields=["is_active", "actualizado_por"])

            logger.info(f"Nuevo estado: is_active={usuario.is_active}")
            serializer = self.get_serializer(usuario)
            logger.info(f"Datos devueltos: {serializer.data}")

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(
                f"❌ Error en toggle_user_status para ID={pk}: {str(e)}", exc_info=True
            )
            return Response(
                {"error": f"No se pudo cambiar el estado: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["patch"])
    def soft_delete(self, request, pk=None):
        from django.utils import timezone

        usuario = self.get_object()
        usuario.eliminado = True
        usuario.eliminado_por = request.user
        usuario.fecha_eliminacion = timezone.now()
        usuario.save(update_fields=["eliminado", "eliminado_por", "fecha_eliminacion"])
        return Response({"status": "soft deleted"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["patch"])
    def restore(self, request, pk=None):
        # Usar get_object() para mantener consistencia con permisos
        # pero obtener el objeto incluyendo los eliminados
        # Primero intentamos con el objeto normal
        try:
            usuario = self.get_object()
        except Http404:
            # Si no se encuentra en el queryset normal, buscar incluyendo eliminados
            usuario = Usuario.objects.filter(pk=pk).first()
            if not usuario:
                return Response({"detail": "Usuario no encontrado"}, status=404)
            # Verificar que el usuario estaba eliminado
            if not usuario.eliminado:
                return Response({"detail": "El usuario no está eliminado"}, status=400)

        # Restaurar el usuario
        usuario.eliminado = False
        usuario.eliminado_por = None
        usuario.fecha_eliminacion = None
        usuario.actualizado_por = request.user
        usuario.save(
            update_fields=[
                "eliminado",
                "eliminado_por",
                "fecha_eliminacion",
                "actualizado_por",
            ]
        )
        return Response(self.get_serializer(usuario).data)


class RolViewSet(BaseViewSet):
    """ViewSet para manejar CRUD de Roles"""

    queryset = Rol.objects.all()
    serializer_class = RolSerializer
    search_fields = ["nombre", "descripcion"]
    ordering = ["nombre"]


class UsuarioRolViewSet(BaseViewSet):
    """ViewSet para manejar asignación de roles a usuarios"""

    queryset = UsuarioRol.objects.select_related("usuario", "rol").all()
    serializer_class = UsuarioRolSerializer
    filterset_fields = ["usuario", "rol", "activo"]
    ordering = ["-id"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [IsAdministrador]
        return [permission() for permission in permission_classes]


# =======================================
# CATEGORIA VIEWSETS
# =======================================
class CategoriaViewSet(BaseViewSet):
    """ViewSet optimizado para Categorías de Productos"""

    queryset = Categoria.objects_all.select_related(
        "creado_por", "actualizado_por", "eliminado_por"
    ).all()
    serializer_class = CategoriaSerializer
    search_fields = ["nombre", "descripcion"]
    filterset_fields = ["activo"]
    ordering = ["nombre"]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        """Sobreescribir el método list para manejar paginación correctamente"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Aplicar paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsTecnico | IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=True, methods=["patch"], url_path="soft_delete")
    def soft_delete(self, request, pk=None):
        """Soft delete con validación de productos relacionados"""
        from django.db.models import Count

        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría no encontrada"}, status=status.HTTP_404_NOT_FOUND
            )

        # Verificar si hay productos activos relacionados
        productos_count = Producto.objects.filter(
            categoria=categoria, eliminado=False
        ).count()

        if productos_count > 0:
            return Response(
                {
                    "detail": f"No se puede eliminar la categoría '{categoria.nombre}' porque tiene {productos_count} producto(s) relacionado(s). Elimine o reasigne los productos primero."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar si hay productos eliminados también (opcional)
        productos_eliminados = Producto.objects.filter(
            categoria=categoria, eliminado=True
        ).count()

        # Proceder con el soft delete
        from django.utils import timezone

        categoria.eliminado = True
        categoria.fecha_eliminacion = timezone.now()
        if hasattr(categoria, "eliminado_por") and request.user.is_authenticated:
            categoria.eliminado_por = request.user
        categoria.save(
            update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
        )

        return Response(
            {"status": "Categoría marcada como eliminada"}, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="toggle_activo")
    def toggle_activo(self, request, pk=None):
        """Toggle activo con validación de productos relacionados"""
        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría no encontrada"}, status=status.HTTP_404_NOT_FOUND
            )

        nuevo_estado = request.data.get("activo") if request.data else None

        # Si se va a desactivar, verificar productos activos
        if nuevo_estado is False or (nuevo_estado is None and categoria.activo):
            productos_activos = Producto.objects.filter(
                categoria=categoria, activo=True, eliminado=False
            ).count()

            if productos_activos > 0:
                return Response(
                    {
                        "detail": f"No se puede desactivar la categoría '{categoria.nombre}' porque tiene {productos_activos} producto(s) activo(s). Desactive los productos primero."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Proceder con el toggle
        if nuevo_estado is not None:
            categoria.activo = bool(nuevo_estado)
        else:
            categoria.activo = not categoria.activo
        categoria.save(update_fields=["activo"])

        serializer = self.get_serializer(categoria)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def verificar_relaciones(self, request, pk=None):
        """Verifica si la categoría tiene productos o servicios relacionados"""
        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría no encontrada"}, status=status.HTTP_404_NOT_FOUND
            )

        # Contar productos relacionados
        productos_count = Producto.objects.filter(
            categoria=categoria, eliminado=False
        ).count()

        productos_eliminados_count = Producto.objects.filter(
            categoria=categoria, eliminado=True
        ).count()

        return Response(
            {
                "categoria_id": categoria.id,
                "categoria_nombre": categoria.nombre,
                "productos_activos": productos_count,
                "productos_eliminados": productos_eliminados_count,
                "puede_eliminar": productos_count == 0,
                "puede_desactivar": productos_count == 0,
                "mensaje": (
                    f"La categoría tiene {productos_count} producto(s) activo(s) relacionado(s)"
                    if productos_count > 0
                    else "La categoría no tiene productos relacionados"
                ),
            }
        )

    @action(detail=True, methods=["get"])
    def productos(self, request, pk=None):
        """Listar productos de una categoría"""
        categoria = self.get_object()
        productos = Producto.objects.filter(
            categoria=categoria, activo=True, eliminado=False
        )

        page = self.paginate_queryset(productos)
        if page is not None:
            serializer = ProductoSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ProductoSerializer(productos, many=True)
        return Response(serializer.data)


class CategoriaPublicaViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet público para consultar categorías"""

    queryset = Categoria.objects.filter(activo=True, eliminado=False)
    serializer_class = CategoriaSerializer
    permission_classes = [AllowAny]
    search_fields = ["nombre"]
    ordering = ["nombre"]

    @action(detail=True, methods=["get"])
    def productos(self, request, pk=None):
        """Listar productos activos de una categoría"""
        categoria = self.get_object()
        productos = Producto.objects.filter(
            categoria=categoria, activo=True, eliminado=False
        ).select_related("proveedor")

        page = self.paginate_queryset(productos)
        if page is not None:
            serializer = ProductoPublicoSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ProductoPublicoSerializer(productos, many=True)
        return Response(serializer.data)


class CategoriaServicioViewSet(BaseViewSet):
    """ViewSet optimizado para Categorías de Servicios"""

    queryset = CategoriaServicio.objects_all.select_related(
        "creado_por", "actualizado_por", "eliminado_por"
    ).all()
    serializer_class = CategoriaServicioSerializer
    search_fields = ["nombre", "descripcion"]
    filterset_fields = ["activo"]
    ordering = ["nombre"]
    pagination_class = StandardResultsSetPagination

    def list(self, request, *args, **kwargs):
        """Sobreescribir el método list para manejar paginación correctamente"""
        queryset = self.filter_queryset(self.get_queryset())
        
        # Aplicar paginación
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=True, methods=["patch"], url_path="soft_delete")
    def soft_delete(self, request, pk=None):
        """Soft delete con validación de servicios relacionados"""
        from ..models import Servicio

        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría de servicio no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verificar si hay servicios activos relacionados
        servicios_count = Servicio.objects.filter(
            categoria_servicio=categoria, eliminado=False
        ).count()

        if servicios_count > 0:
            return Response(
                {
                    "detail": f"No se puede eliminar la categoría '{categoria.nombre}' porque tiene {servicios_count} servicio(s) relacionado(s). Elimine o reasigne los servicios primero."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Proceder con el soft delete
        from django.utils import timezone

        categoria.eliminado = True
        categoria.fecha_eliminacion = timezone.now()
        if hasattr(categoria, "eliminado_por") and request.user.is_authenticated:
            categoria.eliminado_por = request.user
        categoria.save(
            update_fields=["eliminado", "fecha_eliminacion", "eliminado_por"]
        )

        return Response(
            {"status": "Categoría de servicio marcada como eliminada"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def verificar_relaciones(self, request, pk=None):
        """Verifica si la categoría de servicio tiene servicios relacionados"""
        from ..models import Servicio

        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría de servicio no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Contar servicios relacionados
        servicios_count = Servicio.objects.filter(
            categoria_servicio=categoria, eliminado=False
        ).count()

        servicios_eliminados_count = Servicio.objects.filter(
            categoria_servicio=categoria, eliminado=True
        ).count()

        return Response(
            {
                "categoria_id": categoria.id,
                "categoria_nombre": categoria.nombre,
                "servicios_activos": servicios_count,
                "servicios_eliminados": servicios_eliminados_count,
                "puede_eliminar": servicios_count == 0,
                "puede_desactivar": servicios_count == 0,
                "mensaje": (
                    f"La categoría tiene {servicios_count} servicio(s) activo(s) relacionado(s)"
                    if servicios_count > 0
                    else "La categoría no tiene servicios relacionados"
                ),
            }
        )

    @action(detail=True, methods=["patch"], url_path="toggle_activo")
    def toggle_activo(self, request, pk=None):
        """Toggle activo con validación de servicios relacionados"""
        from ..models import Servicio

        try:
            categoria = self.get_object()
        except Http404:
            return Response(
                {"detail": "Categoría de servicio no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        nuevo_estado = request.data.get("activo")

        # Si se va a desactivar, verificar servicios activos
        if nuevo_estado is False or (nuevo_estado is None and categoria.activo):
            servicios_activos = Servicio.objects.filter(
                categoria_servicio=categoria, activo=True, eliminado=False
            ).count()

            if servicios_activos > 0:
                return Response(
                    {
                        "detail": f"No se puede desactivar la categoría '{categoria.nombre}' porque tiene {servicios_activos} servicio(s) activo(s). Desactive los servicios primero."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Proceder con el toggle
        if nuevo_estado is not None:
            categoria.activo = bool(nuevo_estado)
        else:
            categoria.activo = not categoria.activo
        categoria.save(update_fields=["activo"])

        serializer = self.get_serializer(categoria)
        return Response(serializer.data, status=status.HTTP_200_OK)


# =======================================
# PROVEEDOR VIEWSETS
# =======================================
class ProveedorViewSet(BaseViewSet):
    """ViewSet optimizado para Proveedores"""

    queryset = Proveedor.objects_all.select_related(
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
        "eliminado_por__persona_asociada",
    ).all()
    serializer_class = ProveedorSerializer
    search_fields = ["nombre", "nit", "correo", "telefono", "contacto_principal"]
    filterset_fields = ["activo"]
    ordering = ["nombre"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=False, methods=["get"])
    def con_productos(self, request):
        """Proveedores que tienen productos"""
        queryset = (
            self.get_queryset()
            .filter(producto__isnull=False)
            .distinct()
            .annotate(productos_count=Count("producto"))
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def productos(self, request, pk=None):
        """Productos de un proveedor específico"""
        proveedor = self.get_object()
        productos = Producto.objects.filter(
            proveedor=proveedor, eliminado=False
        ).select_related("categoria")

        page = self.paginate_queryset(productos)
        if page is not None:
            serializer = ProductoSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ProductoSerializer(productos, many=True)
        return Response(serializer.data)


# =======================================
# PRODUCTO VIEWSETS
# =======================================
class ProductoViewSet(BaseViewSet):
    """ViewSet optimizado para Productos"""

    queryset = Producto.objects_all.select_related(
        "categoria",
        "proveedor",
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
        "eliminado_por__persona_asociada",
    ).all()
    serializer_class = ProductoSerializer
    search_fields = ["nombre", "descripcion"]
    filterset_fields = ["categoria", "proveedor", "activo", "destacado"]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    ordering = ["-fecha_registro"]

    def get_queryset(self):
        queryset = super().get_queryset()

        # Filtro específico para técnicos - solo productos usados en sus mantenimientos
        if IsTecnico().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            queryset = queryset.filter(
                repuestos_usados__mantenimiento__tecnico_asignado=self.request.user
            ).distinct()
            return queryset

        # -------------------------
        # Filtro por 'eliminado' - Similar a UsuarioViewSet
        # -------------------------
        eliminado_param = self.request.query_params.get("eliminado", None)
        if eliminado_param is not None:
            if eliminado_param.lower() == "true":
                queryset = queryset.filter(eliminado=True)
            elif eliminado_param.lower() == "false":
                queryset = queryset.filter(eliminado=False)
            elif eliminado_param.lower() == "all":
                pass  # No aplicar filtro, mostrar todos
            else:
                # Valor por defecto: mostrar solo no eliminados
                queryset = queryset.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo productos NO eliminados
            queryset = queryset.filter(eliminado=False)

        # -------------------------
        # Filtro por 'activo' - Exactamente como UsuarioViewSet
        # -------------------------
        activo_param = self.request.query_params.get("activo", None)
        if activo_param is not None:
            if activo_param.lower() == "true":
                queryset = queryset.filter(activo=True)
            elif activo_param.lower() == "false":
                queryset = queryset.filter(activo=False)
        else:
            # VALOR POR DEFECTO: mostrar solo productos ACTIVOS (como UsuarioViewSet)
            queryset = queryset.filter(activo=True)

        # -------------------------
        # Filtros opcionales desde query params
        # -------------------------
        search = self.request.query_params.get("search", None)
        if search:
            queryset = queryset.filter(
                models.Q(nombre__icontains=search)
                | models.Q(descripcion__icontains=search)
            ).distinct()

        return queryset

    def get_permissions(self):
        # Usar CustomPermission para todas las acciones
        # CustomPermission ya maneja correctamente los permisos de administrador
        permission_classes = [CustomPermission]
        return [permission() for permission in permission_classes]

    def create(self, request, *args, **kwargs):
        """Override create to add debugging"""
        logger.info(f"Datos recibidos para crear producto: {request.data}")

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"Errores de validación: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def perform_create(self, serializer):
        # Extraer campos de stock del validated_data
        stock_inicial = serializer.validated_data.pop("stock_inicial", 0)
        stock_minimo = serializer.validated_data.pop("stock_minimo", 0)
        precio_compra = serializer.validated_data.get("precio_compra", 0)

        # Establecer el usuario que crea el registro
        usuario_actual = (
            self.request.user if self.request.user.is_authenticated else None
        )

        # Crear el producto con el usuario creador
        producto = serializer.save(creado_por=usuario_actual)

        # Crear inventario (el stock se calculará desde los lotes)
        inventario, created = Inventario.objects.get_or_create(
            producto=producto,
            defaults={
                "stock_actual": 0,
                "stock_minimo": stock_minimo,
                "creado_por": usuario_actual,
            },
        )

        # Si hay stock inicial, crear un Lote (FIFO)
        if stock_inicial > 0:
            Lote.objects.create(
                producto=producto,
                cantidad_disponible=stock_inicial,
                precio_compra=precio_compra,
                activo=True,
                creado_por=usuario_actual,
            )
            # El save del Lote actualiza el stock del inventario automáticamente

        logger.info(
            f"Producto {producto.id} creado con lote automático por usuario {usuario_actual}. Stock inicial: {stock_inicial}, Precio compra: {precio_compra}"
        )

    def perform_update(self, serializer):
        """Actualizar producto - el stock se maneja desde inventario"""
        # Establecer el usuario que actualiza el registro
        usuario_actual = (
            self.request.user if self.request.user.is_authenticated else None
        )

        # Guardar el producto actualizado
        producto = serializer.save(actualizado_por=usuario_actual)

        # Asegurar que existe inventario para el producto
        inventario, created = Inventario.objects.get_or_create(
            producto=producto,
            defaults={
                "stock_actual": 0,
                "stock_minimo": 0,
                "creado_por": usuario_actual,
            },
        )

        logger.info(f"Producto {producto.id} actualizado")

    @action(detail=False, methods=["get"])
    def stock_bajo(self, request):
        """Productos con stock bajo"""
        queryset = (
            self.get_queryset()
            .filter(
                inventario__stock_actual__lte=F("inventario__stock_minimo"),
                activo=True,
                eliminado=False,
            )
            .select_related("inventario")
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def destacados(self, request):
        """Productos destacados"""
        queryset = self.get_queryset().filter(
            destacado=True, activo=True, eliminado=False
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"])
    def restore(self, request, pk=None):
        """Restaurar producto eliminado (similar a UsuarioViewSet)"""
        # Usar objects_all para poder encontrar registros eliminados
        producto = Producto.objects_all.filter(pk=pk).first()
        if not producto:
            return Response({"detail": "Producto no encontrado"}, status=404)
        producto.eliminado = False
        producto.eliminado_por = None
        producto.fecha_eliminacion = None
        producto.save(update_fields=["eliminado", "eliminado_por", "fecha_eliminacion"])
        return Response(self.get_serializer(producto).data)

    @action(detail=True, methods=["patch"], url_path="toggle_activo")
    def toggle_activo(self, request, pk=None):
        """Alternar estado activo/inactivo del producto"""
        # Usar objects_all para poder encontrar productos activos o inactivos
        # Similar a como funciona en toggle_user_status
        producto = Producto.objects_all.filter(pk=pk).first()
        if not producto:
            return Response({"detail": "Producto no encontrado"}, status=404)

        logger.info(f"🔹 toggle_activo llamado para producto ID={pk}")
        logger.info(f"Estado actual: activo={producto.activo}")

        producto.activo = not producto.activo
        producto.save(update_fields=["activo"])

        logger.info(f"Nuevo estado: activo={producto.activo}")
        serializer = self.get_serializer(producto)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"])
    def toggle_destacado(self, request, pk=None):
        """Alternar producto destacado"""
        producto = self.get_object()
        producto.destacado = not producto.destacado
        producto.save(update_fields=["destacado"])
        serializer = self.get_serializer(producto)
        return Response(serializer.data)

    @action(detail=True, methods=["patch"])
    def actualizar_stock(self, request, pk=None):
        """Actualizar stock del producto"""
        producto = self.get_object()
        nuevo_stock = request.data.get("stock_actual")
        motivo = request.data.get("motivo", "Ajuste manual de stock")

        if nuevo_stock is None:
            return Response(
                {"error": "stock_actual es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            nuevo_stock = int(nuevo_stock)
            if nuevo_stock < 0:
                return Response(
                    {"error": "El stock no puede ser negativo"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Obtener o crear inventario
            inventario, created = Inventario.objects.get_or_create(
                producto=producto,
                defaults={
                    "stock_actual": nuevo_stock,
                    "stock_minimo": 0,
                },
            )

            if not created:
                # Calcular diferencia para el movimiento
                stock_anterior = inventario.stock_actual
                diferencia = nuevo_stock - stock_anterior

                # Actualizar stock
                inventario.stock_actual = nuevo_stock
                inventario.save(update_fields=["stock_actual"])

                # Crear movimiento de inventario si hay diferencia
                if diferencia != 0:
                    tipo_movimiento = "entrada" if diferencia > 0 else "salida"
                    cantidad_movimiento = abs(diferencia)

                    InventarioMovimiento.objects.create(
                        inventario=inventario,
                        tipo=tipo_movimiento,
                        cantidad=cantidad_movimiento,
                        motivo=motivo,
                        usuario=(
                            request.user if request.user.is_authenticated else None
                        ),
                    )

            serializer = self.get_serializer(producto)
            logger.info(f"Stock actualizado para producto {producto.id}: {nuevo_stock}")
            return Response(serializer.data)
        except ValueError:
            return Response(
                {"error": "stock_actual debe ser un número entero"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class ProductoPublicoViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet público para productos"""

    serializer_class = ProductoPublicoSerializer
    permission_classes = [AllowAny]
    search_fields = ["nombre", "descripcion"]
    filterset_fields = ["categoria", "destacado"]
    ordering = ["nombre"]

    def get_queryset(self):
        """Catálogo público de productos con filtros"""
        qs = Producto.objects.filter(activo=True, eliminado=False).select_related(
            "categoria", "proveedor"
        )

        # Filtros adicionales
        categoria_id = self.request.query_params.get("categoria_id")
        if categoria_id:
            qs = qs.filter(categoria_id=categoria_id)

        precio_min = self.request.query_params.get("precio_min")
        precio_max = self.request.query_params.get("precio_max")
        if precio_min:
            qs = qs.filter(precio_venta__gte=precio_min)
        if precio_max:
            qs = qs.filter(precio_venta__lte=precio_max)

        destacado = self.request.query_params.get("destacado")
        if destacado == "true":
            qs = qs.filter(destacado=True)

        return qs

    @action(detail=False, methods=["get"])
    def destacados(self, request):
        """Productos destacados públicos"""
        productos = self.get_queryset().filter(destacado=True)

        page = self.paginate_queryset(productos)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(productos, many=True)
        return Response(serializer.data)


# =======================================
# SERVICIO VIEWSETS
# =======================================
class ServicioViewSet(BaseViewSet):
    """ViewSet optimizado para Servicios"""

    queryset = Servicio.objects_all.select_related(
        "categoria_servicio",
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
        "eliminado_por__persona_asociada",
    ).all()
    serializer_class = ServicioSerializer
    search_fields = ["nombre", "descripcion"]
    filterset_fields = ["categoria_servicio", "activo", "eliminado"]
    ordering = ["-fecha_registro"]

    def get_queryset(self):
        qs = super().get_queryset()

        # Los técnicos pueden ver todos los servicios activos (no solo los de sus mantenimientos)
        # Esto les permite crear, editar y gestionar servicios del catálogo

        # -------------------------
        # Filtro por 'eliminado' - Similar a ProductoViewSet
        # -------------------------
        eliminado_param = self.request.query_params.get("eliminado", None)
        if eliminado_param is not None:
            if eliminado_param.lower() == "true":
                qs = qs.filter(eliminado=True)
            elif eliminado_param.lower() == "false":
                qs = qs.filter(eliminado=False)
            elif eliminado_param.lower() == "all":
                pass  # No aplicar filtro, mostrar todos
            else:
                # Valor por defecto: mostrar solo no eliminados
                qs = qs.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo servicios NO eliminados
            qs = qs.filter(eliminado=False)

        # -------------------------
        # Filtro por 'activo' - Exactamente como ProductoViewSet
        # -------------------------
        activo_param = self.request.query_params.get("activo", None)
        if activo_param is not None:
            if activo_param.lower() == "true":
                qs = qs.filter(activo=True)
            elif activo_param.lower() == "false":
                qs = qs.filter(activo=False)
        else:
            # VALOR POR DEFECTO: mostrar solo servicios ACTIVOS
            qs = qs.filter(activo=True)

        # -------------------------
        # Filtros opcionales desde query params
        # -------------------------
        search = self.request.query_params.get("search", None)
        if search:
            qs = qs.filter(
                models.Q(nombre__icontains=search)
                | models.Q(descripcion__icontains=search)
            ).distinct()

        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=True, methods=["patch"], url_path="toggle_activo")
    def toggle_activo(self, request, pk=None):
        """Alternar estado activo/inactivo del servicio"""
        # Usar objects_all para poder encontrar servicios activos o inactivos
        from ..models import Servicio

        servicio = Servicio.objects_all.filter(pk=pk).first()
        if not servicio:
            return Response({"detail": "Servicio no encontrado"}, status=404)

        logger.info(f"🔹 toggle_activo llamado para servicio ID={pk}")
        logger.info(f"Estado actual: activo={servicio.activo}")

        # Si se proporciona activo en el request, usarlo; de lo contrario, togglear
        activo_value = request.data.get("activo")
        if activo_value is not None:
            servicio.activo = bool(activo_value)
        else:
            servicio.activo = not servicio.activo

        servicio.save(update_fields=["activo"])

        logger.info(f"Nuevo estado: activo={servicio.activo}")
        serializer = self.get_serializer(servicio)
        return Response(serializer.data)


# =======================================
# VEHICULO VIEWSETS
# =======================================
class MotoViewSet(BaseViewSet):
    """ViewSet optimizado para Motos"""

    queryset = Moto.objects_all.select_related(
        "propietario",
        "registrado_por",
        "creado_por",
        "actualizado_por",
        "eliminado_por",
    ).all()
    serializer_class = MotoSerializer
    search_fields = ["placa", "marca", "modelo", "numero_chasis", "numero_motor"]
    filterset_fields = ["propietario", "marca", "activo"]
    ordering = ["-fecha_registro"]

    def create(self, request, *args, **kwargs):
        logger = logging.getLogger(__name__)

        logger.info("=== DEBUG MOTO: Creando nueva moto ===")
        logger.info(
            f"DEBUG MOTO: Usuario: {request.user.username} (ID: {request.user.id})"
        )
        logger.info(f"DEBUG MOTO: request.data = {request.data}")

        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            logger.error(f"❌ ERRORES SERIALIZER: {serializer.errors}")
            return Response(serializer.errors, status=400)

        self.perform_create(serializer)

        headers = self.get_success_headers(serializer.data)

        return Response(serializer.data, status=201, headers=headers)

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtro específico para técnicos - pueden ver todas las motorcycles
        # Removed filtro restrictivo - técnicos ahora pueden ver todas las bikes
        # para que puedan crear nuevas y trabajar con todas
        
        # Filtro específico para clientes - solo sus motos
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(propietario=self.request.user.persona_asociada)
            else:
                qs = qs.none()

        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsCliente | IsTecnico | IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsTecnico | IsEmpleado | IsAdministrador]
        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """Asignar automáticamente el propietario para clientes"""
        logger = logging.getLogger(__name__)

        is_cliente = IsCliente().has_permission(self.request, self)
        has_persona = (
            hasattr(self.request.user, "persona_asociada")
            and self.request.user.persona_asociada
        )

        # Verificar si el serializer ya tiene un propietario en validated_data
        # (enviado desde el frontend)
        tiene_propietario_en_data = (
            hasattr(serializer, "validated_data")
            and "propietario" in serializer.validated_data
        )

        logger.info(
            f"DEBUG PERFORM_CREATE: IsCliente={is_cliente}, has_persona={has_persona}, tiene_propietario_en_data={tiene_propietario_en_data}"
        )
        if tiene_propietario_en_data:
            logger.info(
                f"DEBUG PERFORM_CREATE: Propietario en validated_data: {serializer.validated_data.get('propietario')}"
            )

        # Si es cliente Y tiene persona Y NO envió propietario explícitamente
        # -> usar su propia persona como propietario
        # Si envió propietario -> usar el que envió (respetar selección del usuario)
        if is_cliente and has_persona and not tiene_propietario_en_data:
            # Para clientes sin propietario enviado, asignar automáticamente su persona_asociada
            logger.info(
                f"DEBUG PERFORM_CREATE: Asignando propietario desde persona_asociada: {self.request.user.persona_asociada.id}"
            )
            serializer.save(
                propietario=self.request.user.persona_asociada,
                registrado_por=self.request.user,
                creado_por=self.request.user,
            )
        else:
            # Para otros roles O si el usuario envió propietario explícitamente
            # Usar los datos del serializer (incluye propietario si se envió)
            logger.info(
                f"DEBUG PERFORM_CREATE: Usando validated_data del serializer (propietario enviado desde frontend)"
            )
            serializer.save(
                registrado_por=self.request.user,
                creado_por=self.request.user,
            )


# =======================================
# MANTENIMIENTO VIEWSETS
# =======================================
class MantenimientoViewSet(BaseViewSet):
    """
    ViewSet optimizado para Mantenimientos.

    Endpoints disponibles:
    - GET /: Listar mantenimientos
    - POST /: Crear mantenimiento
    - GET /{id}/: Ver detalle
    - PATCH /{id}/: Actualizar mantenimiento
    - DELETE /{id}/: Eliminar (soft delete)
    - POST /{id}/completar/: Completar mantenimiento
    - POST /{id}/agregar_servicio/: Agregar servicio
    - POST /{id}/agregar_repuesto/: Agregar repuesto
    - POST /{id}/quitar_servicio/{detalle_id}/: Quitar servicio
    - POST /{id}/quitar_repuesto/{repuesto_id}/: Quitar repuesto
    - GET /{id}/resumen/: Obtener resumen completo
    """

    queryset = (
        Mantenimiento.objects.select_related(
            "moto__propietario",
            "tecnico_asignado",
            "completado_por",
            "creado_por",
            "actualizado_por",
        )
        .prefetch_related("detalles__servicio", "repuestos__producto")
        .all()
    )
    serializer_class = MantenimientoSerializer
    search_fields = ["descripcion_problema", "diagnostico"]
    filterset_fields = ["moto", "estado", "tipo", "prioridad"]
    ordering = ["-fecha_ingreso"]

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtro específico para técnicos - solo mantenimientos asignados a ellos
        if IsTecnico().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            qs = qs.filter(tecnico_asignado=self.request.user)
            return qs

        # Filtro específico para clientes - solo sus mantenimientos
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(moto__propietario=self.request.user.persona_asociada)
            else:
                qs = qs.none()
            return qs

        # -------------------------
        # Filtro por 'eliminado' - Igual que otros ViewSets
        # -------------------------
        eliminado_param = self.request.query_params.get("eliminado", None)
        if eliminado_param is not None:
            if eliminado_param.lower() == "true":
                qs = qs.filter(eliminado=True)
            elif eliminado_param.lower() == "false":
                qs = qs.filter(eliminado=False)
            elif eliminado_param.lower() == "all":
                pass  # No aplicar filtro, mostrar todos
            else:
                # Valor por defecto: mostrar solo no eliminados
                qs = qs.filter(eliminado=False)
        else:
            # VALOR POR DEFECTO: mostrar solo mantenimientos NO eliminados
            qs = qs.filter(eliminado=False)

        # Para empleados y administradores - todos los mantenimientos
        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsTecnico | IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        elif self.action in [
            "completar",
            "agregar_servicio",
            "agregar_repuesto",
            "quitar_servicio",
            "quitar_repuesto",
            "resumen",
        ]:
            permission_classes = [IsTecnico | IsAdministrador]
        else:
            permission_classes = [IsTecnico | IsEmpleado | IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=True, methods=["post"])
    def completar(self, request, pk=None):
        """
        Completa un mantenimiento.

        Params:
        - kilometraje_salida: (opcional) Kilometraje al salir la moto
        """
        from core.services import MantenimientoService

        mantenimiento = self.get_object()
        kilometraje_salida = request.data.get("kilometraje_salida")

        resultado = MantenimientoService.completar_mantenimiento(
            mantenimiento=mantenimiento,
            usuario=request.user,
            kilometraje_salida=kilometraje_salida,
        )

        if not resultado["success"]:
            return Response(
                {"error": resultado["message"]}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(resultado["mantenimiento"])
        return Response(
            {"message": resultado["message"], "mantenimiento": serializer.data}
        )

    @action(detail=True, methods=["post"])
    def agregar_servicio(self, request, pk=None):
        """
        Agrega un servicio a un mantenimiento.

        Body:
        {
            "servicio": id,
            "precio": decimal,
            "observaciones": string,
            "tipo_aceite": string (optional),
            "km_proximo_cambio": int (optional)
        }
        """
        from core.services import MantenimientoService

        mantenimiento = self.get_object()

        # Validar que el mantenimiento no esté completado
        if mantenimiento.estado == "completado":
            return Response(
                {"error": "No se puede modificar un mantenimiento completado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            detalle = MantenimientoService.agregar_servicio(mantenimiento, request.data)
            return Response(
                {
                    "message": "Servicio agregado correctamente",
                    "detalle": DetalleMantenimientoSerializer(detalle).data,
                    "total_actualizado": float(mantenimiento.total),
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return Response(
                {
                    "error": (
                        str(e.message_dict) if hasattr(e, "message_dict") else str(e)
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def agregar_repuesto(self, request, pk=None):
        """
        Agrega un repuesto a un mantenimiento.

        Body:
        {
            "producto": id,
            "cantidad": int,
            "precio_unitario": decimal,
            "permitir_sin_stock": bool (optional)
        }
        """
        from core.services import MantenimientoService

        mantenimiento = self.get_object()

        # Validar que el mantenimiento no esté completado
        if mantenimiento.estado == "completado":
            return Response(
                {"error": "No se puede modificar un mantenimiento completado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            repuesto = MantenimientoService.agregar_repuesto(
                mantenimiento, request.data, validar_stock=True
            )
            return Response(
                {
                    "message": "Repuesto agregado correctamente",
                    "repuesto": RepuestoMantenimientoSerializer(repuesto).data,
                    "total_actualizado": float(mantenimiento.total),
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return Response(
                {
                    "error": (
                        str(e.message_dict) if hasattr(e, "message_dict") else str(e)
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quitar_servicio/(?P<detalle_id>[^/.]+)",
    )
    def quitar_servicio(self, request, pk=None, detalle_id=None):
        """Elimina un servicio del mantenimiento"""
        from core.services import MantenimientoService

        mantenimiento = self.get_object()

        # Validar que el mantenimiento no esté completado
        if mantenimiento.estado == "completado":
            return Response(
                {"error": "No se puede modificar un mantenimiento completado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resultado = MantenimientoService.eliminar_servicio(detalle_id)

        if not resultado["success"]:
            return Response(
                {"error": resultado["message"]}, status=status.HTTP_400_BAD_REQUEST
            )

        # Recargar mantenimiento para obtener el total actualizado
        mantenimiento.refresh_from_db()
        return Response(
            {
                "message": resultado["message"],
                "total_actualizado": float(mantenimiento.total),
            }
        )

    @action(
        detail=True,
        methods=["post"],
        url_path=r"quitar_repuesto/(?P<repuesto_id>[^/.]+)",
    )
    def quitar_repuesto(self, request, pk=None, repuesto_id=None):
        """Elimina un repuesto del mantenimiento y restaura el stock"""
        from core.services import MantenimientoService

        mantenimiento = self.get_object()

        # Validar que el mantenimiento no esté completado
        if mantenimiento.estado == "completado":
            return Response(
                {"error": "No se puede modificar un mantenimiento completado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resultado = MantenimientoService.eliminar_repuesto(repuesto_id)

        if not resultado["success"]:
            return Response(
                {"error": resultado["message"]}, status=status.HTTP_400_BAD_REQUEST
            )

        # Recargar mantenimiento para obtener el total actualizado
        mantenimiento.refresh_from_db()
        return Response(
            {
                "message": resultado["message"],
                "total_actualizado": float(mantenimiento.total),
            }
        )

    @action(detail=True, methods=["get"])
    def resumen(self, request, pk=None):
        """Obtiene un resumen completo del mantenimiento"""
        from core.services import MantenimientoService

        mantenimiento = self.get_object()
        resumen = MantenimientoService.obtener_resumen_mantenimiento(mantenimiento)
        return Response(resumen)

    @action(detail=True, methods=["patch"])
    def cambiar_estado(self, request, pk=None):
        """
        Endpoint específico para técnicos para cambiar estado del mantenimiento.

        Flujo obligatorio: pendiente -> en_proceso -> completado
        """
        from core.services import MantenimientoService

        mantenimiento = self.get_object()
        nuevo_estado = request.data.get("estado")

        # Validar que el estado sea válido
        estados_validos = ["pendiente", "en_proceso", "completado", "cancelado"]
        if nuevo_estado not in estados_validos:
            return Response(
                {"error": f"Estado inválido. Estados válidos: {estados_validos}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Solo técnicos pueden cambiar a sus mantenimientos asignados
        if (
            IsTecnico().has_permission(request, self)
            and mantenimiento.tecnico_asignado != request.user
        ):
            return Response(
                {
                    "error": "Solo puedes cambiar el estado de mantenimientos asignados a ti"
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Usar el servicio para cambiar estado
        resultado = MantenimientoService.cambiar_estado(
            mantenimiento, nuevo_estado, request.user
        )

        if not resultado["success"]:
            return Response(
                {"error": resultado["message"]}, status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(resultado["mantenimiento"])
        return Response(
            {"message": resultado["message"], "mantenimiento": serializer.data}
        )

    @action(detail=True, methods=["patch"])
    def agregar_observaciones(self, request, pk=None):
        """Endpoint específico para técnicos para agregar diagnóstico/observaciones"""
        mantenimiento = self.get_object()
        diagnostico = request.data.get("diagnostico")

        if not diagnostico:
            return Response(
                {"error": "El campo 'diagnostico' es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Solo técnicos pueden agregar observaciones a sus mantenimientos asignados
        if (
            IsTecnico().has_permission(request, self)
            and mantenimiento.tecnico_asignado != request.user
        ):
            return Response(
                {
                    "error": "Solo puedes agregar observaciones a mantenimientos asignados a ti"
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        mantenimiento.diagnostico = diagnostico
        mantenimiento.save(update_fields=["diagnostico"])

        serializer = self.get_serializer(mantenimiento)
        return Response(serializer.data)

    # =======================================
    # ENDPOINTS PARA SOFT DELETE AVANZADO
    # =======================================
    @action(detail=False, methods=["get"])
    def eliminados(self, request):
        """
        Lista todos los mantenimientos eliminados (soft delete).
        GET /mantenimientos/eliminados/
        """
        from django.utils import timezone

        # Usar objects_all para incluir eliminados
        queryset = (
            Mantenimiento.objects_all.select_related(
                "moto__propietario", "tecnico_asignado"
            )
            .filter(eliminado=True)
            .order_by("-fecha_eliminacion")
        )

        # Filtrar por permisos
        if IsTecnico().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            queryset = queryset.filter(tecnico_asignado=request.user)
        elif IsCliente().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            if hasattr(request.user, "persona_asociada"):
                queryset = queryset.filter(
                    moto__propietario=request.user.persona_asociada
                )
            else:
                queryset = queryset.none()

        # Paginación
        from core.api.pagination import StandardResultsSetPagination

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(queryset, request)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["delete"])
    def eliminar_permanente(self, request, pk=None):
        """
        Elimina permanentemente un mantenimiento (hard delete).
        DELETE /mantenimientos/{id}/eliminar_permanente/
        """
        try:
            mantenimiento = Mantenimiento.objects_all.get(pk=pk)
        except Mantenimiento.DoesNotExist:
            return Response(
                {"detail": "Mantenimiento no encontrado"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Verificar permisos (solo administrador)
        if not IsAdministrador().has_permission(request, self):
            return Response(
                {"error": "No tienes permiso para eliminar permanentemente"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Eliminar detalles asociados
        mantenimiento.detalles.all().delete()
        mantenimiento.repuestos.all().delete()

        # Eliminar permanentemente
        mantenimiento.delete(force_delete=True)

        return Response(
            {"message": "Mantenimiento eliminado permanentemente"},
            status=status.HTTP_204_NO_CONTENT,
        )

    @action(detail=False, methods=["get"])
    def estadisticas(self, request):
        """
        Obtiene estadísticas de mantenimientos.
        GET /mantenimientos/estadisticas/
        """
        from django.db.models import Count, Sum, Avg, Q
        from django.utils import timezone
        from datetime import timedelta

        # Solo empleados y administradores pueden ver estadísticas
        if not (
            IsEmpleado().has_permission(request, self)
            or IsAdministrador().has_permission(request, self)
        ):
            return Response(
                {"error": "No tienes permiso para ver estadísticas"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Calcular fechas
        ahora = timezone.now()
        hace_30_dias = ahora - timedelta(days=30)
        hace_7_dias = ahora - timedelta(days=7)

        # Filtrar queryset base según permisos
        queryset = Mantenimiento.objects_all.all()
        if IsTecnico().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            queryset = queryset.filter(tecnico_asignado=request.user)
        elif IsCliente().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            if hasattr(request.user, "persona_asignada"):
                queryset = queryset.filter(
                    moto__propietario=request.user.persona_asociada
                )
            else:
                queryset = queryset.none()

        # Estadísticas generales
        total = queryset.count()
        pendientes = queryset.filter(estado="pendiente").count()
        en_proceso = queryset.filter(estado="en_proceso").count()
        completados = queryset.filter(estado="completado").count()
        eliminados = queryset.filter(eliminado=True).count()

        # Últimos 30 días
        ultimos_30_dias = queryset.filter(fecha_registro__gte=hace_30_dias).count()
        completados_30_dias = queryset.filter(
            fecha_registro__gte=hace_30_dias, estado="completado"
        ).count()

        # Última semana
        ultimos_7_dias = queryset.filter(fecha_registro__gte=hace_7_dias).count()
        completados_7_dias = queryset.filter(
            fecha_registro__gte=hace_7_dias, estado="completado"
        ).count()

        # Ingresos
        try:
            ingresos_30_dias = (
                queryset.filter(
                    fecha_registro__gte=hace_30_dias, estado="completado"
                ).aggregate(total=Sum("total"))["total"]
                or 0
            )
        except:
            ingresos_30_dias = 0

        # Promedio de duración
        try:
            avg_duration = (
                queryset.filter(estado="completado", fecha_completado__isnull=False)
                .annotate(
                    duracion=models.F("fecha_completado") - models.F("fecha_ingreso")
                )
                .aggregate(avg=Avg("duracion"))["avg"]
            )
            avg_duration_days = avg_duration.days if avg_duration else 0
        except:
            avg_duration_days = 0

        # Mantenimientos por tipo
        por_tipo = list(
            queryset.values("tipo").annotate(count=Count("id")).order_by("-count")[:5]
        )

        # Mantenimientos por estado
        por_estado = list(
            queryset.values("estado").annotate(count=Count("id")).order_by("-count")
        )

        return Response(
            {
                "total": total,
                "pendientes": pendientes,
                "en_proceso": en_proceso,
                "completados": completados,
                "eliminados": eliminados,
                "ultimos_30_dias": ultimos_30_dias,
                "completados_30_dias": completados_30_dias,
                "ultimos_7_dias": ultimos_7_dias,
                "completados_7_dias": completados_7_dias,
                "ingresos_30_dias": float(ingresos_30_dias),
                "promedio_duracion_dias": avg_duration_days,
                "por_tipo": por_tipo,
                "por_estado": por_estado,
            }
        )

    @action(detail=False, methods=["delete"])
    def eliminar_multiples_temporal(self, request):
        """
        Elimina múltiples mantenimientos temporalmente (soft delete).
        DELETE /mantenimientos/eliminar_multiples_temporal/
        Body: {"ids": [1, 2, 3]}
        """
        from django.utils import timezone

        ids = request.data.get("ids", [])

        if not ids:
            return Response(
                {"error": "Se requiere una lista de IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar permisos
        if not IsAdministrador().has_permission(request, self):
            return Response(
                {"error": "No tienes permiso para eliminar mantenimientos"},
                status=status.HTTP_403_FORBIDDEN,
            )

        mantenimientos = Mantenimiento.objects_all.filter(id__in=ids)
        count = mantenimientos.count()

        ahora = timezone.now()
        mantenimientos.update(
            eliminado=True, fecha_eliminacion=ahora, eliminado_por=request.user
        )

        return Response(
            {
                "message": f"{count} mantenimientos eliminados temporalmente",
                "eliminados": count,
            }
        )

    @action(detail=False, methods=["patch"])
    def restaurar_multiples(self, request):
        """
        Restaura múltiples mantenimientos eliminados.
        PATCH /mantenimientos/restaurar_multiples/
        Body: {"ids": [1, 2, 3]}
        """
        ids = request.data.get("ids", [])

        if not ids:
            return Response(
                {"error": "Se requiere una lista de IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verificar permisos
        if not IsAdministrador().has_permission(request, self):
            return Response(
                {"error": "No tienes permiso para restaurar mantenimientos"},
                status=status.HTTP_403_FORBIDDEN,
            )

        mantenimientos = Mantenimiento.objects_all.filter(id__in=ids, eliminado=True)
        count = mantenimientos.count()

        mantenimientos.update(
            eliminado=False, fecha_eliminacion=None, eliminado_por=None
        )

        return Response(
            {"message": f"{count} mantenimientos restaurados", "restaurados": count}
        )


class DetalleMantenimientoViewSet(BaseViewSet):
    """
    ViewSet optimizado para Detalles de Mantenimiento.

    Gestiona los servicios realizados en un mantenimiento.
    """

    queryset = DetalleMantenimiento.objects.select_related(
        "mantenimiento__moto", "servicio__categoria_servicio"
    ).all()
    serializer_class = DetalleMantenimientoSerializer
    filterset_fields = ["mantenimiento", "servicio"]
    ordering = ["-id"]

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtro específico para clientes
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(
                    mantenimiento__moto__propietario=self.request.user.persona_asociada
                )
            else:
                qs = qs.none()

        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        elif self.action in ["create"]:
            return [IsTecnico() | IsEmpleado() | IsAdministrador()]
        elif self.action in ["destroy"]:
            return [IsTecnico() | IsAdministrador()]
        return [IsTecnico() | IsEmpleado() | IsAdministrador()]


class RecordatorioMantenimientoViewSet(BaseViewSet):
    """
    ViewSet optimizado para Recordatorios de Mantenimiento.

    Endpoints adicionales:
    - GET /proximos/: Ver recordatorios próximos a vencer
    - GET /por_km/: Ver recordatorios por kilometraje para una moto
    - POST /crear_manual/: Crear recordatorio manualmente
    """

    queryset = RecordatorioMantenimiento.objects.select_related(
        "moto__propietario", "categoria_servicio", "registrado_por"
    ).all()
    serializer_class = RecordatorioMantenimientoSerializer
    filterset_fields = ["moto", "categoria_servicio", "enviado", "activo", "tipo"]
    ordering = ["fecha_programada"]

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtrar recordatorios solo del usuario logueado si es cliente
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(moto__propietario=self.request.user.persona_asociada)
            else:
                qs = qs.none()

        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated()]
        elif self.action in ["create", "destroy", "proximos", "por_km"]:
            return [IsTecnico() | IsEmpleado() | IsAdministrador() | IsCliente()]
        return [IsTecnico() | IsEmpleado() | IsAdministrador()]

    @action(detail=False, methods=["get"])
    def proximos(self, request):
        """
        Recordatorios próximos a vencer.

        Query params:
        - dias: Días de anticipación (default: 7)
        - tipo: 'fecha' o 'km'
        """
        from core.services import RecordatorioService

        dias = int(request.query_params.get("dias", 7))
        limite = int(request.query_params.get("limite", 50))
        tipo = request.query_params.get("tipo")

        # Filtrar por cliente si es un cliente (no administrador)
        # Obtener los IDs de las motos del cliente
        from core.models import Moto

        queryset = self.get_queryset()

        # Si es cliente, filtrar solo sus recordatorios
        if IsCliente().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            if (
                hasattr(request.user, "persona_asociada")
                and request.user.persona_asociada
            ):
                queryset = queryset.filter(
                    moto__propietario=request.user.persona_asociada
                )
            else:
                queryset = queryset.none()

        # Filtrar por fecha y activo
        from datetime import timedelta

        fecha_limite = timezone.now().date() + timedelta(days=dias)

        # Incluir todos los recordatorios: con fecha o sin fecha (tipo km)
        from django.db.models import Q
        queryset = queryset.filter(
            Q(fecha_programada__isnull=True) | Q(fecha_programada__lte=fecha_limite)
        )

        # Si hay tipo, filtrar por tipo
        if tipo:
            queryset = queryset.filter(tipo=tipo)

        # Obtener resultados
        queryset = queryset.select_related("moto", "categoria_servicio")[:limite]

        resultados = []
        for r in queryset:
            info = r.proximo(dias)
            resultados.append(
                {
                    "id": r.id,
                    "moto": r.moto.placa,
                    "moto_id": r.moto.id,
                    "categoria": (
                        r.categoria_servicio.nombre if r.categoria_servicio else None
                    ),
                    "tipo": r.tipo,
                    "fecha_programada": r.fecha_programada,
                    "km_proximo": r.km_proximo,
                    "alerta": info["alerta"],
                    "mensaje": info["mensaje"],
                }
            )

        return Response({"count": len(resultados), "recordatorios": resultados})

    @action(detail=False, methods=["get"])
    def por_km(self, request):
        """
        Recordatorios por kilometraje para una moto específica.

        Query params:
        - moto_id: ID de la moto (requerido)
        """
        from core.services import RecordatorioService

        moto_id = request.query_params.get("moto_id")
        if not moto_id:
            return Response(
                {"error": "El parámetro moto_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            resultados = RecordatorioService.obtener_recordatorios_por_km(
                moto_id=moto_id
            )
            return Response({"count": len(resultados), "recordatorios": resultados})
        except Moto.DoesNotExist:
            return Response(
                {"error": "La moto no existe"}, status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=["post"])
    def crear_manual(self, request):
        """
        Crea un recordatorio manualmente.

        Body:
        {
            "moto": id,
            "categoria_servicio": id,
            "tipo": "fecha" | "km",
            "fecha_programada": date (si tipo=fecha),
            "km_proximo": int (si tipo=km),
            "notas": string (optional)
        }
        """
        from core.services import RecordatorioService

        try:
            recordatorio = RecordatorioService.generar_recordatorio_manual(
                data=request.data, usuario=request.user
            )
            return Response(
                {
                    "message": "Recordatorio creado correctamente",
                    "recordatorio": RecordatorioMantenimientoSerializer(
                        recordatorio
                    ).data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            return Response(
                {
                    "error": (
                        str(e.message_dict) if hasattr(e, "message_dict") else str(e)
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=["post"])
    def marcar_enviado(self, request, pk=None):
        """Marca un recordatorio como enviado"""
        recordatorio = self.get_object()
        recordatorio.marcar_enviado()
        return Response(
            {
                "message": "Recordatorio marcado como enviado",
                "recordatorio": RecordatorioMantenimientoSerializer(recordatorio).data,
            }
        )

    @action(detail=True, methods=["post"])
    def desactivar(self, request, pk=None):
        """Desactiva un recordatorio"""
        recordatorio = self.get_object()
        recordatorio.desactivar()
        return Response(
            {
                "message": "Recordatorio desactivado",
                "recordatorio": RecordatorioMantenimientoSerializer(recordatorio).data,
            }
        )


class RepuestoMantenimientoViewSet(viewsets.ModelViewSet):
    queryset = RepuestoMantenimiento.objects.select_related("mantenimiento", "producto")
    serializer_class = RepuestoMantenimientoSerializer
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["producto__nombre"]
    filterset_fields = ["mantenimiento", "producto"]

    def perform_create(self, serializer):
        """Descontar stock automáticamente al crear repuesto de mantenimiento"""
        repuesto = serializer.save()
        producto = repuesto.producto

        # Usar inventario en lugar de producto.stock_actual
        try:
            inventario = producto.inventario
            stock_disponible = inventario.stock_actual
        except Inventario.DoesNotExist:
            stock_disponible = 0

        # Verificar stock disponible
        if stock_disponible < repuesto.cantidad:
            raise serializers.ValidationError(
                f"Stock insuficiente. Disponible: {stock_disponible}, Requerido: {repuesto.cantidad}"
            )

        # Descontar stock del inventario
        inventario.stock_actual -= repuesto.cantidad
        inventario.save(update_fields=["stock_actual"])

        # Crear movimiento de inventario
        InventarioMovimiento.objects.create(
            producto=producto,
            tipo="salida",
            cantidad=repuesto.cantidad,
            motivo=f"Usado en mantenimiento #{repuesto.mantenimiento.id}",
            usuario=self.request.user if self.request.user.is_authenticated else None,
        )

    def perform_destroy(self, instance):
        """Revertir stock si se elimina el repuesto"""
        producto = instance.producto

        # Usar inventario en lugar de producto.stock_actual
        try:
            inventario = producto.inventario
            inventario.stock_actual += instance.cantidad
            inventario.save(update_fields=["stock_actual"])
        except Inventario.DoesNotExist:
            pass

        # Crear movimiento de inventario para revertir
        InventarioMovimiento.objects.create(
            producto=producto,
            tipo="entrada",
            cantidad=instance.cantidad,
            motivo=f"Revertido de mantenimiento #{instance.mantenimiento.id}",
            usuario=self.request.user if self.request.user.is_authenticated else None,
        )

        instance.delete()


# =======================================
# VENTA VIEWSETS
# =======================================
class VentaViewSet(BaseViewSet):
    """ViewSet para Ventas"""

    queryset = (
        Venta.objects.select_related("cliente")
        .prefetch_related("detalles__producto")
        .all()
    )
    serializer_class = VentaSerializer
    search_fields = ["cliente__nombre", "cliente__apellido"]
    filterset_fields = ["cliente", "estado"]
    ordering = ["-fecha_venta"]

    def get_queryset(self):
        import logging

        logger = logging.getLogger(__name__)

        qs = (
            Venta.objects.select_related("cliente")
            .prefetch_related("detalles__producto")
            .all()
        )
        logger.info("🔎 Queryset inicial ventas: %s", qs.count())

        # Filtro por eliminado
        eliminado = self.request.query_params.get("eliminado")
        if eliminado is None:
            qs = qs.filter(eliminado=False)
            logger.info("➡️ Filtro aplicado: eliminado=False (por defecto)")
        elif eliminado.lower() == "true":
            qs = qs.filter(eliminado=True)
            logger.info("➡️ Filtro aplicado: eliminado=True")
        elif eliminado.lower() == "false":
            qs = qs.filter(eliminado=False)
            logger.info("➡️ Filtro aplicado: eliminado=False")

        # 🔑 Si es cliente, mostrar solo sus ventas
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            persona = getattr(self.request.user, "persona_asociada", None)
            if persona:
                qs = qs.filter(cliente=persona)
                logger.info(
                    "👤 Usuario %s es cliente -> filtrando ventas de persona_id=%s. Ventas encontradas=%s",
                    self.request.user.id,
                    persona.id,
                    qs.count(),
                )
            else:
                qs = qs.none()
                logger.warning(
                    "⚠️ Usuario %s es cliente pero no tiene persona_asociada -> sin resultados",
                    self.request.user.id,
                )
        else:
            logger.info(
                "👤 Usuario %s NO es cliente (o es administrador) -> ventas visibles=%s",
                self.request.user.id,
                qs.count(),
            )

        logger.info("✅ Queryset final ventas: %s", qs.count())
        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy"]:
            permission_classes = [IsAdministrador]
        elif self.action in ["soft_delete", "restore"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        else:
            permission_classes = [IsEmpleado | IsAdministrador]
        return [permission() for permission in permission_classes]

    def perform_update(self, serializer):
        """Set actualizado_por al actualizar"""
        if serializer.instance and serializer.instance.actualizado_por is None:
            serializer.save(actualizado_por=self.request.user)
        else:
            serializer.save()

    def update(self, request, *args, **kwargs):
        """Validación especial para empleados"""
        instance = self.get_object()

        # Empleados no pueden modificar ventas completadas
        if IsEmpleado().has_permission(
            request, self
        ) and not IsAdministrador().has_permission(request, self):
            if instance.estado == "PAGADA":
                return Response(
                    {"detail": "No se puede modificar una venta pagada."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=["patch"], url_path="restore")
    def restore(self, request, pk=None):
        """Restaurar venta eliminada"""
        try:
            # Venta no hereda de SoftDeleteModel, usamos.objects regular
            instance = Venta.objects.get(pk=pk)
        except Venta.DoesNotExist:
            return Response(
                {"detail": "Venta no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not hasattr(instance, "eliminado"):
            return Response(
                {"error": "Esta venta no soporta restauración"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Restaurar la venta
        instance.eliminado = False

        # Limpiar campos de eliminación
        update_fields = ["eliminado"]
        if hasattr(instance, "fecha_eliminacion"):
            instance.fecha_eliminacion = None
            update_fields.append("fecha_eliminacion")
        if hasattr(instance, "eliminado_por"):
            instance.eliminado_por = None
            update_fields.append("eliminado_por")

        instance.save(update_fields=update_fields)
        serializer = self.get_serializer(instance)
        logger.info(f"✅ Venta {pk} restaurada por {request.user.username}")
        return Response(serializer.data, status=status.HTTP_200_OK)

    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def procesar_venta_pos(request):
        """
        Endpoint específico para procesar ventas desde el POS
        Maneja la creación de venta con detalles y actualización de stock automática
        - Acepta 'items' o 'productos' del frontend
        - Reduce stock automáticamente
        - Guarda trazabilidad (creado_por)
        - Soporta descuentos y notas
        """
        try:
            data = request.data

            # Aceptar ambos nombres: 'items' o 'productos'
            items = data.get("items") or data.get("productos")

            if not items or len(items) == 0:
                return Response(
                    {"error": "La venta debe tener al menos un producto"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                # Obtener usuario actual para trazabilidad
                usuario_actual = request.user

                # Preparar datos de la venta con descuento y notas
                venta_data = {
                    "cliente": data.get("cliente_id"),
                    "fecha_venta": timezone.now(),
                    "subtotal": float(data.get("subtotal", 0)),
                    "impuesto": float(data.get("impuesto", 0)),
                    "descuento": float(data.get("descuento", 0)),
                    "total": float(data.get("total", 0)),
                    "estado": "completada",
                    "notas": data.get("notas", ""),
                }

                venta_serializer = VentaSerializer(data=venta_data)
                if venta_serializer.is_valid():
                    # Guardar con el usuario actual
                    venta = venta_serializer.save(creado_por=usuario_actual)
                else:
                    return Response(
                        venta_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                # Procesar cada item de la venta
                detalles_creados = []
                for item in items:
                    try:
                        # Aceptar tanto "producto_id" como "id" del frontend
                        producto_id = item.get("producto_id") or item.get("id")
                        if not producto_id:
                            raise Exception("ID de producto no proporcionado")

                        producto = Producto.objects.get(id=producto_id)

                        # Usar el stock del inventario como fuente principal
                        try:
                            inventario = Inventario.objects.get(producto=producto)
                            stock_disponible = inventario.stock_actual
                        except Inventario.DoesNotExist:
                            stock_disponible = 0

                        # Validar stock disponible
                        if stock_disponible < item["cantidad"]:
                            raise Exception(
                                f"Stock insuficiente para {producto.nombre}. Disponible: {stock_disponible}"
                            )

                        # Crear detalle de venta
                        detalle_data = {
                            "venta": venta.id,
                            "producto": producto.id,
                            "cantidad": item["cantidad"],
                            "precio_unitario": float(item["precio_unitario"]),
                            "subtotal": float(
                                item.get(
                                    "subtotal",
                                    item["cantidad"] * float(item["precio_unitario"]),
                                )
                            ),
                        }

                        detalle_serializer = DetalleVentaSerializer(data=detalle_data)
                        if detalle_serializer.is_valid():
                            detalle = detalle_serializer.save()
                            detalles_creados.append(detalle)
                        else:
                            raise Exception(
                                f"Error en detalle de venta: {detalle_serializer.errors}"
                            )

                        # =====================
                        # REDUCIR STOCK
                        # =====================
                        cantidad_vendida = item["cantidad"]

                        # Reducir en Inventario si existe
                        if inventario:
                            inventario.stock_actual = max(
                                0, inventario.stock_actual - cantidad_vendida
                            )
                            inventario.save(update_fields=["stock_actual"])

                            # Registrar movimiento de inventario
                            from core.models import MovimientoInventario

                            MovimientoInventario.objects.create(
                                producto=producto,
                                inventario=inventario,
                                tipo="salida",
                                cantidad=cantidad_vendida,
                                motivo=f"Venta POS #{venta.id}",
                                registrado_por=usuario_actual,
                            )

                    except Producto.DoesNotExist:
                        raise Exception(f"Producto con ID {producto_id} no encontrado")
                    except Exception as e:
                        raise Exception(str(e))

                # Serializar respuesta completa
                venta_completa = Venta.objects.prefetch_related(
                    "detalles__producto"
                ).get(id=venta.id)
                response_data = {
                    "id": venta.id,
                    "numero_venta": f"Venta-{venta.id:06d}",
                    "fecha": venta.fecha_venta.isoformat(),
                    "cliente": (
                        PersonaSerializer(venta.cliente).data if venta.cliente else None
                    ),
                    "subtotal": str(venta.subtotal),
                    "descuento": str(venta.descuento),
                    "impuesto": str(venta.impuesto),
                    "total": str(venta.total),
                    "estado": venta.estado,
                    "notas": venta.notas or "",
                    "metodo_pago": data.get("metodo_pago", "efectivo"),
                    "vendido_por": usuario_actual.username,
                    "items": [
                        {
                            "id": detalle.id,
                            "producto_id": detalle.producto.id,
                            "nombre": detalle.producto.nombre,
                            "cantidad": detalle.cantidad,
                            "precio_unitario": str(detalle.precio_unitario),
                            "subtotal": str(detalle.subtotal),
                        }
                        for detalle in venta_completa.detalles.all()
                    ],
                }

                logger.info(
                    f"✅ Venta POS procesada exitosamente: #{venta.id} por usuario {usuario_actual.username} - Total: {venta.total}"
                )
                return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"❌ Error procesando venta POS: {str(e)}")
            return Response(
                {"error": f"Error al procesar venta: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def estadisticas_pos(request):
        """
        Estadísticas para el dashboard del POS
        """
        try:
            today = timezone.now().date()

            # Ventas del día
            ventas_hoy = Venta.objects.filter(fecha_venta__date=today, eliminado=False)

            # Ingresos del día
            ingresos_dia = ventas_hoy.aggregate(total=models.Sum("total"))["total"] or 0

            # Productos más vendidos (últimos 7 días)
            hace_7_dias = today - timedelta(days=7)
            productos_vendidos = (
                DetalleVenta.objects.filter(
                    venta__fecha_venta__date__gte=hace_7_dias, venta__eliminado=False
                )
                .values("producto__nombre")
                .annotate(cantidad_total=models.Sum("cantidad"))
                .order_by("-cantidad_total")[:5]
            )

            # Productos con stock bajo
            productos_stock_bajo = Producto.objects.filter(
                inventario__stock_actual__lte=models.F("inventario__stock_minimo"),
                activo=True,
                eliminado=False,
            ).count()

            estadisticas = {
                "ventasHoy": ventas_hoy.count(),
                "ingresosDia": float(ingresos_dia),
                "clientesAtendidos": ventas_hoy.filter(cliente__isnull=False).count(),
                "productosVendidos": DetalleVenta.objects.filter(
                    venta__fecha_venta__date=today, venta__eliminado=False
                ).aggregate(total=models.Sum("cantidad"))["total"]
                or 0,
                "productosStockBajo": productos_stock_bajo,
                "productosMasVendidos": list(productos_vendidos),
            }

            return Response(estadisticas)

        except Exception as e:
            logger.error(f"Error obteniendo estadísticas POS: {str(e)}")
            return Response(
                {"error": "Error al obtener estadísticas"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def buscar_productos_pos(request):
        """
        Búsqueda optimizada de productos para POS
        Incluye información de stock y disponibilidad
        """
        try:
            query = request.GET.get("q", "").strip()
            categoria_id = request.GET.get("categoria_id")

            if not query:
                return Response({"results": []})

            # Construir queryset base
            productos = Producto.objects.filter(
                activo=True, eliminado=False
            ).select_related("categoria", "proveedor")

            # Aplicar búsqueda
            productos = productos.filter(
                models.Q(nombre__icontains=query)
                | models.Q(descripcion__icontains=query)
            )

            # Filtro por categoría
            if categoria_id:
                productos = productos.filter(categoria_id=categoria_id)

            # Limitar resultados
            productos = productos.select_related("inventario")[:20]

            results = []
            for producto in productos:
                # Usar inventario en lugar de producto.stock_actual
                try:
                    inventario = producto.inventario
                    stock_actual = inventario.stock_actual
                    stock_minimo = inventario.stock_minimo
                except Inventario.DoesNotExist:
                    stock_actual = 0
                    stock_minimo = 0

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
                        "proveedor": (
                            {
                                "id": (
                                    producto.proveedor.id
                                    if producto.proveedor
                                    else None
                                ),
                                "nombre": (
                                    producto.proveedor.nombre
                                    if producto.proveedor
                                    else None
                                ),
                            }
                            if producto.proveedor
                            else None
                        ),
                        "imagen_url": producto.imagen.url if producto.imagen else None,
                        "disponible": stock_actual > 0,
                        "display_text": f"{producto.nombre} (Stock: {stock_actual})",
                    }
                )

            return Response({"results": results})

        except Exception as e:
            logger.error(f"Error en búsqueda de productos POS: {str(e)}")
            return Response(
                {"error": "Error al buscar productos"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_view(["POST"])
    @permission_classes([IsAuthenticated])
    def crear_cliente_rapido(request):
        """
        Crear cliente rápido desde POS
        """
        try:
            # Validar datos requeridos
            required_fields = ["nombre", "apellido", "cedula", "telefono"]
            for field in required_fields:
                if not request.data.get(field):
                    return Response(
                        {"error": f"El campo {field} es requerido"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Verificar que no exista cliente con la misma cédula
            if Persona.objects.filter(cedula=request.data["cedula"]).exists():
                return Response(
                    {"error": "Ya existe un cliente con esta cédula"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Crear cliente
            persona_data = {
                "nombre": request.data["nombre"].strip(),
                "apellido": request.data["apellido"].strip(),
                "cedula": request.data["cedula"].strip(),
                "telefono": request.data["telefono"].strip(),
                "direccion": request.data.get("direccion", "").strip(),
            }

            serializer = PersonaSerializer(data=persona_data)
            if serializer.is_valid():
                persona = serializer.save()

                response_data = {
                    "id": persona.id,
                    "nombre_completo": persona.nombre_completo,
                    "cedula": persona.cedula,
                    "telefono": persona.telefono,
                    "direccion": persona.direccion,
                }

                logger.info(
                    f"Cliente rápido creado: {persona.nombre_completo} por usuario {request.user.username}"
                )
                return Response(response_data, status=status.HTTP_201_CREATED)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error creando cliente rápido: {str(e)}")
            return Response(
                {"error": f"Error al crear cliente: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @api_view(["GET"])
    @permission_classes([IsAuthenticated])
    def verificar_stock_producto(request, producto_id):
        """
        Verificar stock disponible de un producto específico
        """
        try:
            producto = Producto.objects.get(
                id=producto_id, activo=True, eliminado=False
            )

            # Usar inventario en lugar de producto.stock_actual
            try:
                inventario = producto.inventario
                stock_actual = inventario.stock_actual
                stock_minimo = inventario.stock_minimo
            except Inventario.DoesNotExist:
                stock_actual = 0
                stock_minimo = 0

            stock_info = {
                "id": producto.id,
                "nombre": producto.nombre,
                "stock_actual": stock_actual,
                "stock_minimo": stock_minimo,
                "disponible": stock_actual > 0,
                "stock_bajo": stock_actual <= stock_minimo,
                "precio_venta": str(producto.precio_venta),
            }

            return Response(stock_info)

        except Producto.DoesNotExist:
            return Response(
                {"error": "Producto no encontrado"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error verificando stock: {str(e)}")
            return Response(
                {"error": "Error al verificar stock"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PagoViewSet(viewsets.ModelViewSet):
    """ViewSet para Pagos"""

    queryset = Pago.objects.select_related("venta__cliente", "registrado_por").all()
    serializer_class = PagoSerializer
    search_fields = ["venta__id", "venta__cliente__nombre", "venta__cliente__apellido"]
    filterset_fields = ["cliente", "estado", "registrado_por"]
    ordering = ["-fecha_pago"]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtro específico para clientes - solo pagos de sus ventas
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(venta__cliente=self.request.user.persona_asociada)
            else:
                qs = qs.none()

        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsEmpleado | IsAdministrador]
        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """Asignar usuario al crear pago"""
        serializer.save(registrado_por=self.request.user)

    @action(detail=False, methods=["get"])
    def por_venta(self, request):
        """Obtener pagos de una venta específica"""
        venta_id = request.query_params.get("venta_id")
        if not venta_id:
            return Response(
                {"error": "Se requiere el parámetro venta_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            venta = Venta.objects.get(id=venta_id)
            pagos = self.get_queryset().filter(venta=venta)
            serializer = self.get_serializer(pagos, many=True)

            return Response(
                {
                    "venta_id": venta.id,
                    "total_venta": venta.total,
                    "total_pagado": venta.pagado,
                    "saldo_pendiente": venta.saldo,
                    "pagos": serializer.data,
                }
            )
        except Venta.DoesNotExist:
            return Response(
                {"error": "Venta no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=False, methods=["get"])
    def estadisticas(self, request):
        """Estadísticas de pagos"""
        from django.db.models import Sum, Count
        from datetime import datetime, timedelta

        # Filtros de fecha
        fecha_inicio = request.query_params.get("fecha_inicio")
        fecha_fin = request.query_params.get("fecha_fin")

        qs = self.get_queryset()

        if fecha_inicio:
            try:
                fecha_inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
                qs = qs.filter(fecha_pago__date__gte=fecha_inicio)
            except ValueError:
                pass

        if fecha_fin:
            try:
                fecha_fin = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
                qs = qs.filter(fecha_pago__date__lte=fecha_fin)
            except ValueError:
                pass

        # Estadísticas generales
        stats = qs.aggregate(
            total_pagos=Count("id"),
            monto_total=Sum("monto") or 0,
        )

        # Pagos por método
        pagos_por_metodo = (
            qs.values("metodo")
            .annotate(cantidad=Count("id"), monto_total=Sum("monto"))
            .order_by("-monto_total")
        )

        return Response(
            {
                "estadisticas_generales": stats,
                "pagos_por_metodo": list(pagos_por_metodo),
            }
        )


class DetalleVentaViewSet(BaseViewSet):
    """ViewSet optimizado para Detalles de Venta"""

    queryset = DetalleVenta.objects.select_related("venta", "producto").all()
    serializer_class = DetalleVentaSerializer
    search_fields = ["producto__nombre", "venta__id"]
    filterset_fields = ["venta", "producto"]
    ordering = ["-id"]

    def get_queryset(self):
        qs = super().get_queryset()

        # Filtro específico para clientes
        if IsCliente().has_permission(
            self.request, self
        ) and not IsAdministrador().has_permission(self.request, self):
            if hasattr(self.request.user, "persona_asociada"):
                qs = qs.filter(venta__cliente=self.request.user.persona_asociada)
            else:
                qs = qs.none()

        return qs

    def perform_create(self, serializer):
        """Crear detalle de venta y actualizar inventario automáticamente"""
        # Guardar el detalle de venta
        detalle = serializer.save()

        # Obtener o crear inventario para el producto
        inventario, created = Inventario.objects.get_or_create(
            producto=detalle.producto,
            defaults={"stock_actual": 0, "stock_minimo": 0},
        )

        # Validar stock disponible
        if inventario.stock_actual < detalle.cantidad:
            # Eliminar el detalle creado si no hay stock
            detalle.delete()
            raise ValidationError(
                f"Stock insuficiente para {detalle.producto.nombre}. Disponible: {inventario.stock_actual}"
            )

        # Crear movimiento de inventario (salida automática)
        InventarioMovimiento.objects.create(
            inventario=inventario,
            tipo="salida",
            cantidad=detalle.cantidad,
            motivo=f"Venta #{detalle.venta.id} - {detalle.producto.nombre}",
            usuario=self.request.user if self.request.user.is_authenticated else None,
        )

        logger.info(
            f"Detalle venta creado. Producto: {detalle.producto.nombre}, Cantidad: {detalle.cantidad}"
        )

    def perform_destroy(self, instance):
        """Al eliminar detalle de venta, devolver stock al inventario"""
        # Obtener inventario del producto
        try:
            inventario = Inventario.objects.get(producto=instance.producto)

            # Crear movimiento de entrada para devolver el stock
            InventarioMovimiento.objects.create(
                inventario=inventario,
                tipo="entrada",
                cantidad=instance.cantidad,
                motivo=f"Devolución por eliminación de venta #{instance.venta.id}",
                usuario=(
                    self.request.user if self.request.user.is_authenticated else None
                ),
            )

            logger.info(
                f"Stock devuelto al inventario. Producto: {instance.producto.nombre}, Cantidad: {instance.cantidad}"
            )
        except Inventario.DoesNotExist:
            logger.warning(
                f"No se encontró inventario para producto {instance.producto.nombre}"
            )

        # Eliminar el detalle
        super().perform_destroy(instance)


# =======================================
# INVENTARIO VIEWSETS
# =======================================
class InventarioViewSet(BaseViewSet):
    """ViewSet optimizado para Inventario"""

    queryset = Inventario.objects.select_related(
        "producto",
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
        "eliminado_por__persona_asociada",
    ).all()
    serializer_class = InventarioSerializer
    search_fields = ["producto__nombre"]
    filterset_fields = ["producto", "stock_actual", "stock_minimo"]
    ordering = ["-fecha_registro"]

    def get_permissions(self):
        """
        Usar CustomPermission para todas las acciones.
        CustomPermission ya maneja las restricciones apropiadas:
        - Administradores: Acceso completo a todas las operaciones
        - Empleados: Solo métodos seguros (lectura)
        """
        return [CustomPermission()]

    def update(self, request, *args, **kwargs):
        """Actualizar un registro de inventario con logging detallado."""
        instance = self.get_object()
        logger.info(f"Iniciando actualización de inventario ID: {instance.id}")
        logger.info(f"Datos recibidos: {request.data}")

        # Validar datos de entrada
        serializer = self.get_serializer(
            instance, data=request.data, partial=kwargs.get("partial", False)
        )
        if not serializer.is_valid():
            logger.warning(
                f"Error de validación al actualizar inventario: {serializer.errors}"
            )
            return Response(
                {
                    "error": "Error de validación",
                    "details": serializer.errors,
                    "received_data": request.data,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            self.perform_update(serializer)
            logger.info(f"Inventario ID {instance.id} actualizado exitosamente")
            return Response(serializer.data)

        except Exception as e:
            logger.error(
                f"Error al actualizar inventario ID {instance.id}: {str(e)}",
                exc_info=True,
            )
            return Response(
                {"error": "Error interno del servidor al actualizar el inventario"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"])
    def estadisticas(self, request):
        """Obtener estadísticas del inventario"""
        try:
            # Estadísticas básicas del inventario
            total_productos = Inventario.objects.filter(eliminado=False).count()

            # Productos activos/inactivos - usar el campo activo del inventario si existe, sino del producto
            try:
                productos_activos = Inventario.objects.filter(
                    eliminado=False, activo=True
                ).count()
                productos_inactivos = Inventario.objects.filter(
                    eliminado=False, activo=False
                ).count()
            except:
                # Si Inventario no tiene campo activo, usar el del producto
                productos_activos = Inventario.objects.filter(
                    eliminado=False, producto__activo=True
                ).count()
                productos_inactivos = Inventario.objects.filter(
                    eliminado=False, producto__activo=False
                ).count()

            # Productos con stock bajo (stock actual <= stock mínimo)
            productos_stock_bajo = Inventario.objects.filter(
                eliminado=False, stock_actual__lte=F("stock_minimo")
            ).count()

            # Productos sin stock
            productos_sin_stock = Inventario.objects.filter(
                eliminado=False, stock_actual=0
            ).count()

            # Valor total del inventario - calcular de forma más segura
            try:
                # Intentar con la consulta optimizada
                inventarios = Inventario.objects.filter(eliminado=False).select_related(
                    "producto"
                )
                valor_total = 0
                for inv in inventarios:
                    if inv.producto and inv.producto.precio_venta:
                        valor_total += float(inv.stock_actual) * float(
                            inv.producto.precio_venta
                        )
            except Exception as e:
                logger.warning(
                    f"Error calculando valor total con método optimizado: {e}"
                )
                valor_total = 0

            # Movimientos recientes (últimos 30 días)
            fecha_limite = timezone.now() - timedelta(days=30)
            movimientos_recientes = InventarioMovimiento.objects.filter(
                fecha_registro__gte=fecha_limite, eliminado=False
            ).count()

            # Entradas y salidas del mes
            entradas_mes = (
                InventarioMovimiento.objects.filter(
                    fecha_registro__gte=fecha_limite, tipo="entrada", eliminado=False
                ).aggregate(total=Sum("cantidad"))["total"]
                or 0
            )

            salidas_mes = (
                InventarioMovimiento.objects.filter(
                    fecha_registro__gte=fecha_limite, tipo="salida", eliminado=False
                ).aggregate(total=Sum("cantidad"))["total"]
                or 0
            )

            stats = {
                "total_productos": total_productos,
                "productos_activos": productos_activos,
                "productos_inactivos": productos_inactivos,
                "productos_stock_bajo": productos_stock_bajo,
                "productos_sin_stock": productos_sin_stock,
                "valor_total_inventario": float(valor_total),
                "movimientos_recientes": movimientos_recientes,
                "entradas_mes": int(entradas_mes),
                "salidas_mes": int(salidas_mes),
            }

            logger.info(
                f"Estadísticas de inventario generadas para usuario {request.user.id}"
            )
            return Response(stats)

        except Exception as e:
            logger.error(f"Error generando estadísticas de inventario: {str(e)}")
            import traceback

            logger.error(f"Traceback completo: {traceback.format_exc()}")
            return Response(
                {"error": "Error al obtener estadísticas del inventario"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class InventarioMovimientoViewSet(BaseViewSet):
    """ViewSet optimizado para Movimientos de Inventario"""

    queryset = InventarioMovimiento.objects.select_related(
        "inventario",
        "usuario",
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
        "eliminado_por__persona_asociada",
    ).all()
    serializer_class = InventarioMovimientoSerializer
    search_fields = ["inventario__producto__nombre", "motivo"]
    filterset_fields = ["inventario", "tipo", "usuario"]
    ordering = ["-fecha_registro"]

    def get_permissions(self):
        """
        Usar CustomPermission para todas las acciones.
        CustomPermission ya maneja las restricciones apropiadas:
        - Administradores: Acceso completo a todas las operaciones
        - Empleados: Solo métodos seguros (lectura)
        """
        return [CustomPermission()]

    def perform_create(self, serializer):
        usuario_actual = (
            self.request.user if self.request.user.is_authenticated else None
        )
        serializer.save(usuario=usuario_actual, creado_por=usuario_actual)


class LoteViewSet(BaseViewSet):
    """ViewSet para gestionar Lotes de inventario (FIFO)"""

    queryset = Lote.objects.select_related(
        "producto",
        "producto__categoria",
        "creado_por__persona_asociada",
        "actualizado_por__persona_asociada",
    ).all()
    serializer_class = LoteSerializer
    search_fields = ["producto__nombre"]
    filterset_fields = ["producto", "activo"]
    ordering = ["-fecha_ingreso"]

    def get_permissions(self):
        return [CustomPermission()]

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return LoteCreateSerializer
        return LoteSerializer

    def perform_create(self, serializer):
        lote = serializer.save()
        lote.actualizar_stock_inventario()
        logger.info(f"Lote ID {lote.id} creado para producto {lote.producto.nombre}")

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.actualizar_stock_inventario()
        logger.info(f"Lote ID {instance.id} actualizado")

    @action(detail=False, methods=["get"])
    def por_producto(self, request):
        """Obtener lotes de un producto específico"""
        producto_id = request.query_params.get("producto_id")
        if not producto_id:
            return Response(
                {"error": "Se requiere producto_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lotes = self.queryset.filter(producto_id=producto_id, activo=True).order_by("fecha_ingreso")
        serializer = self.get_serializer(lotes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Estadísticas de lotes"""
        try:
            total_lotes = Lote.objects.filter(activo=True).count()
            total_stock = Lote.objects.filter(activo=True).aggregate(
                total=Sum("cantidad_disponible")
            )["total"] or 0
            
            productos_con_lotes = Lote.objects.filter(
                activo=True, cantidad_disponible__gt=0
            ).values("producto").distinct().count()

            return Response({
                "total_lotes": total_lotes,
                "total_stock": total_stock,
                "productos_con_lotes": productos_con_lotes,
            })
        except Exception as e:
            logger.error(f"Error en lotes stats: {e}")
            return Response(
                {"error": "Error al obtener estadísticas"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# =======================================
# DASHBOARD Y REPORTES
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_ventas(request):
    """Reporte de ventas por período"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de ventas."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        fecha_inicio = request.GET.get("fecha_inicio")
        fecha_fin = request.GET.get("fecha_fin")
        group_by = (request.GET.get("group_by") or "day").lower()  # 'day' | 'month'

        if not fecha_inicio or not fecha_fin:
            return Response(
                {"error": "Se requieren fecha_inicio y fecha_fin"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ventas = (
            Venta.objects.filter(
                fecha_venta__date__range=[fecha_inicio, fecha_fin], eliminado=False
            )
            .select_related("cliente")
            .prefetch_related("detalles__producto")
        )

        total_ventas = ventas.count()
        total_ingresos = ventas.aggregate(total=Sum("total"))["total"] or 0

        # Productos más vendidos
        productos_vendidos = (
            DetalleVenta.objects.filter(venta__in=ventas)
            .values("producto__nombre")
            .annotate(cantidad_total=Sum("cantidad"), ingresos_total=Sum("subtotal"))
            .order_by("-cantidad_total")[:10]
        )

        # Series por período
        from django.db.models.functions import TruncDay, TruncMonth

        if group_by == "month":
            serie = (
                ventas.annotate(periodo=TruncMonth("fecha_venta"))
                .values("periodo")
                .annotate(total=Sum("total"), cantidad=Count("id"))
                .order_by("periodo")
            )
        else:
            serie = (
                ventas.annotate(periodo=TruncDay("fecha_venta"))
                .values("periodo")
                .annotate(total=Sum("total"), cantidad=Count("id"))
                .order_by("periodo")
            )

        reporte = {
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
            "resumen": {
                "total_ventas": total_ventas,
                "total_ingresos": float(total_ingresos),
            },
            "serie": [
                {
                    "periodo": item["periodo"].strftime(
                        "%Y-%m" if group_by == "month" else "%Y-%m-%d"
                    ),
                    "cantidad": item["cantidad"],
                    "total": float(item["total"] or 0),
                }
                for item in serie
            ],
            "productos_mas_vendidos": list(productos_vendidos),
        }

        return Response(reporte)
    except Exception as e:
        logger.error(f"Error en reporte_ventas: {str(e)}")
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# REPORTES ADICIONALES
# =======================================


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_productos(request):
    """Reporte de productos por categoría y stock"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de productos."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        total_productos = Producto.objects.filter(eliminado=False).count()
        stock_total = (
            Inventario.objects.filter(
                eliminado=False, producto__eliminado=False
            ).aggregate(total=Sum("stock_actual"))["total"]
            or 0
        )
        por_categoria = (
            Producto.objects.filter(eliminado=False)
            .values("categoria__nombre")
            .annotate(total=Count("id"))
            .order_by("-total")
        )

        reporte = {
            "resumen": {
                "total_productos": total_productos,
                "stock_total": stock_total,
            },
            "por_categoria": list(por_categoria),
        }
        return Response(reporte)
    except Exception as e:
        logger.error(f"Error en reporte_productos: {str(e)}")
        return Response(
            {"error": f"Error al generar reporte de productos: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_inventario(request):
    """Reporte de inventario: stock bajo y movimientos recientes"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de inventario."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        # Get products with low stock or missing inventory
        stock_bajo = (
            Producto.objects.filter(
                eliminado=False,
            )
            .annotate(
                current_stock=Coalesce(F("inventario__stock_actual"), 0),
                min_stock=Coalesce(F("inventario__stock_minimo"), 0),
            )
            .filter(Q(current_stock__lt=F("min_stock")) | Q(inventario__isnull=True))
            .values(
                "id",
                "nombre",
                stock_actual=F("current_stock"),
                stock_minimo=F("min_stock"),
            )
            .order_by("stock_actual")[:50]
        )

        fecha_limite = timezone.now() - timedelta(days=30)
        movimientos_recientes = (
            InventarioMovimiento.objects.filter(
                eliminado=False, fecha_registro__gte=fecha_limite
            )
            .select_related("inventario__producto")
            .values(
                "id",
                "tipo",
                "cantidad",
                "motivo",
                "fecha_registro",
                producto=F("inventario__producto__nombre"),
            )
            .order_by("-fecha_registro")[:100]
        )

        # Return data in the format expected by the frontend
        reporte = {
            "stock_bajo": list(stock_bajo),
            "movimientos_recientes": [
                {
                    "id": m["id"],
                    "tipo": m["tipo"],
                    "cantidad": m["cantidad"],
                    "motivo": m["motivo"],
                    "fecha_registro": (
                        m["fecha_registro"].strftime("%Y-%m-%d %H:%M:%S")
                        if m["fecha_registro"]
                        else None
                    ),
                    "producto": m["producto"],
                }
                for m in movimientos_recientes
            ],
        }
        return Response(reporte)
    except Exception:
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_mantenimientos(request):
    """Reporte de mantenimientos por estado y servicios más usados"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de mantenimientos."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        por_estado = (
            Mantenimiento.objects.filter(eliminado=False)
            .values("estado")
            .annotate(total=Count("id"))
            .order_by("-total")
        )

        servicios_mas_usados = (
            DetalleMantenimiento.objects.filter(eliminado=False)
            .values("servicio__nombre")
            .annotate(total=Count("id"))
            .order_by("-total")[:20]
        )

        return Response(
            {
                "por_estado": list(por_estado),
                "servicios_mas_usados": list(servicios_mas_usados),
            }
        )
    except Exception:
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_motos(request):
    """Reporte de motos por marca y año"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de motos."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        por_marca = (
            Moto.objects.filter(eliminado=False)
            .values("marca")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        por_ano = (
            Moto.objects.filter(eliminado=False)
            .values("año")
            .annotate(total=Count("id"))
            .order_by("-año")
        )

        return Response({"por_marca": list(por_marca), "por_ano": list(por_ano)})
    except Exception:
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_proveedores(request):
    """Reporte de proveedores: activos y por cantidad de productos asociados"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de proveedores."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        total_activos = Proveedor.objects.filter(eliminado=False, activo=True).count()
        por_productos = (
            Proveedor.objects.filter(eliminado=False)
            .annotate(total_productos=Count("producto"))
            .values("id", "nombre", "total_productos")
            .order_by("-total_productos")[:50]
        )

        return Response(
            {"activos": total_activos, "por_productos": list(por_productos)}
        )
    except Exception:
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_usuarios(request):
    """Reporte de usuarios por rol y estado"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de usuarios."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        por_rol = (
            UsuarioRol.objects.filter(eliminado=False, activo=True)
            .values("rol__nombre")
            .annotate(total=Count("usuario_id", distinct=True))
            .order_by("-total")
        )
        activos = Usuario.objects.filter(eliminado=False, is_active=True).count()
        inactivos = Usuario.objects.filter(eliminado=False, is_active=False).count()

        return Response(
            {
                "por_rol": list(por_rol),
                "activos": activos,
                "inactivos": inactivos,
            }
        )
    except Exception:
        return Response(
            {"error": "Error al generar reporte"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_ventas_detalle(request):
    """Reporte detallado de ventas con productos por cada venta"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de ventas."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        fecha_inicio = request.GET.get("fecha_inicio")
        fecha_fin = request.GET.get("fecha_fin")
        cliente_id = request.GET.get("cliente_id")
        producto_id = request.GET.get("producto_id")

        if not fecha_inicio or not fecha_fin:
            return Response(
                {"error": "Se requieren fecha_inicio y fecha_fin"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Query base con selects optimizados
        ventas_qs = Venta.objects.filter(
            fecha_venta__date__range=[fecha_inicio, fecha_fin],
            eliminado=False
        ).select_related(
            'cliente',
            'registrado_por'
        ).prefetch_related(
            'detalles__producto',
            'detalles__producto__categoria'
        )

        # Aplicar filtros
        if cliente_id:
            ventas_qs = ventas_qs.filter(cliente_id=cliente_id)
        
        if producto_id:
            ventas_qs = ventas_qs.filter(detalles__producto_id=producto_id).distinct()

        # Calcular totales
        total_ventas = ventas_qs.count()
        total_ingresos = float(ventas_qs.aggregate(total=Sum("total"))["total"] or 0)
        total_productos_vendidos = sum(
            sum(d.cantidad for d in v.detalles.all()) 
            for v in ventas_qs
        )

        # Obtener ventas con detalles
        ventas_data = []
        for venta in ventas_qs:
            cliente = venta.cliente
            usuario = venta.registrado_por
            
            detalles_data = []
            for detalle in venta.detalles.all():
                detalles_data.append({
                    "producto_id": detalle.producto.id,
                    "producto_nombre": detalle.producto.nombre,
                    "categoria": detalle.producto.categoria.nombre if detalle.producto.categoria else None,
                    "cantidad": detalle.cantidad,
                    "precio_unitario": float(detalle.precio_unitario),
                    "subtotal": float(detalle.subtotal),
                })
            
            ventas_data.append({
                "venta_id": venta.id,
                "cliente": {
                    "id": cliente.id,
                    "nombre": f"{cliente.nombre} {cliente.apellido}",
                    "cedula": cliente.cedula,
                },
                "usuario": {
                    "id": usuario.id if usuario else None,
                    "nombre": usuario.username if usuario else None,
                } if usuario else None,
                "fecha": venta.fecha_venta.strftime("%Y-%m-%d %H:%M:%S"),
                "estado": venta.estado,
                "subtotal": float(venta.subtotal),
                "descuento": float(venta.descuento),
                "impuesto": float(venta.impuesto),
                "total": float(venta.total),
                "notas": venta.notas or "",
                "detalles": detalles_data,
            })

        reporte = {
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
            "filtros": {
                "cliente_id": cliente_id,
                "producto_id": producto_id,
            },
            "resumen": {
                "total_ventas": total_ventas,
                "total_ingresos": total_ingresos,
                "total_productos": total_productos_vendidos,
            },
            "ventas": ventas_data,
        }

        return Response(reporte)
    except Exception as e:
        logger.error(f"Error en reporte_ventas_detalle: {str(e)}")
        return Response(
            {"error": "Error al generar reporte detallado de ventas"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_inventario_detalle(request):
    """Reporte detallado de inventario con información de lotes"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de inventario."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        producto_id = request.GET.get("producto_id")
        incluir_lotes = request.GET.get("incluir_lotes", "true").lower() == "true"
        stock_bajo = request.GET.get("stock_bajo", "false").lower() == "true"

        productos_qs = Producto.objects.filter(
            eliminado=False
        ).select_related(
            'categoria',
            'proveedor'
        )

        if producto_id:
            productos_qs = productos_qs.filter(id=producto_id)
        
        if stock_bajo:
            productos_qs = productos_qs.annotate(
                current_stock=Coalesce(F("inventario__stock_actual"), 0),
                min_stock=Coalesce(F("inventario__stock_minimo"), 10),
            ).filter(current_stock__lt=F("min_stock"))

        productos_data = []
        total_stock = 0
        total_valor = 0

        for producto in productos_qs:
            try:
                inventario = producto.inventario
                stock = inventario.stock_actual or 0
                stock_minimo = inventario.stock_minimo or 0
            except Inventario.DoesNotExist:
                stock = 0
                stock_minimo = 0

            # Obtener lotes si se requiere
            lotes_data = []
            if incluir_lotes:
                lotes = producto.lotes.filter(activo=True).order_by('fecha_ingreso')
                for lote in lotes:
                    lotes_data.append({
                        "lote_id": lote.id,
                        "cantidad_disponible": lote.cantidad_disponible,
                        "precio_compra": float(lote.precio_compra),
                        "fecha_ingreso": lote.fecha_ingreso.strftime("%Y-%m-%d %H:%M:%S"),
                        "valor_total": float(lote.cantidad_disponible * lote.precio_compra),
                    })
                valor_lotes = sum(l['valor_total'] for l in lotes_data)
            else:
                valor_lotes = float(stock * producto.precio_compra)

            productos_data.append({
                "producto_id": producto.id,
                "nombre": producto.nombre,
                "categoria": producto.categoria.nombre if producto.categoria else None,
                "proveedor": producto.proveedor.nombre if producto.proveedor else None,
                "precio_compra": float(producto.precio_compra),
                "precio_venta": float(producto.precio_venta),
                "stock_actual": stock,
                "stock_minimo": stock_minimo,
                "stock_bajo": stock < stock_minimo,
                "valor_total": valor_lotes,
                "lotes": lotes_data if incluir_lotes else [],
                "activo": producto.activo,
            })

            total_stock += stock
            total_valor += valor_lotes

        reporte = {
            "resumen": {
                "total_productos": len(productos_data),
                "total_stock": total_stock,
                "valor_total_inventario": total_valor,
                "productos_stock_bajo": sum(1 for p in productos_data if p['stock_bajo']),
            },
            "productos": productos_data,
        }

        return Response(reporte)
    except Exception as e:
        logger.error(f"Error en reporte_inventario_detalle: {str(e)}")
        return Response(
            {"error": "Error al generar reporte detallado de inventario"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def reporte_ventas_por_cliente(request):
    """Reporte de ventas agrupado por cliente"""
    if not (
        IsEmpleado().has_permission(request, None)
        or IsAdministrador().has_permission(request, None)
    ):
        return Response(
            {"detail": "No tienes permiso para generar reportes de clientes."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        fecha_inicio = request.GET.get("fecha_inicio")
        fecha_fin = request.GET.get("fecha_fin")
        cliente_id = request.GET.get("cliente_id")
        ordenar_por = request.GET.get("ordenar_por", "total")  # total | ventas | nombre

        if not fecha_inicio or not fecha_fin:
            return Response(
                {"error": "Se requieren fecha_inicio y fecha_fin"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Query de ventas
        ventas_qs = Venta.objects.filter(
            fecha_venta__date__range=[fecha_inicio, fecha_fin],
            eliminado=False
        ).select_related('cliente').prefetch_related('detalles')

        if cliente_id:
            ventas_qs = ventas_qs.filter(cliente_id=cliente_id)

        # Agrupar por cliente
        from django.db.models import Avg, Max, Min
        
        clientes_data = {}
        
        for venta in ventas_qs:
            cliente = venta.cliente
            clave = cliente.id
            
            if clave not in clientes_data:
                clientes_data[clave] = {
                    "cliente_id": cliente.id,
                    "nombre": f"{cliente.nombre} {cliente.apellido}",
                    "cedula": cliente.cedula,
                    "telefono": cliente.telefono or "",
                    "direccion": cliente.direccion or "",
                    "total_compras": 0,
                    "cantidad_ventas": 0,
                    "total_productos": 0,
                    "promedio_por_venta": 0,
                    "primera_compra": None,
                    "ultima_compra": None,
                    "ventas": [],
                }
            
            clientes_data[clave]["total_compras"] += float(venta.total)
            clientes_data[clave]["cantidad_ventas"] += 1
            
            detalles = list(venta.detalles.all())
            clientes_data[clave]["total_productos"] += sum(d.cantidad for d in detalles)
            
            fecha_str = venta.fecha_venta.strftime("%Y-%m-%d %H:%M:%S")
            
            if not clientes_data[clave]["primera_compra"]:
                clientes_data[clave]["primera_compra"] = fecha_str
            else:
                if venta.fecha_venta.strftime("%Y-%m-%d") < clientes_data[clave]["primera_compra"][:10]:
                    clientes_data[clave]["primera_compra"] = fecha_str
            
            if not clientes_data[clave]["ultima_compra"]:
                clientes_data[clave]["ultima_compra"] = fecha_str
            else:
                if venta.fecha_venta.strftime("%Y-%m-%d") > clientes_data[clave]["ultima_compra"][:10]:
                    clientes_data[clave]["ultima_compra"] = fecha_str

        # Convertir a lista y calcular promedios
        clientes_list = list(clientes_data.values())
        
        for cliente in clientes_list:
            cliente["promedio_por_venta"] = round(cliente["total_compras"] / cliente["cantidad_ventas"], 2) if cliente["cantidad_ventas"] > 0 else 0

        # Ordenar
        if ordenar_por == "ventas":
            clientes_list.sort(key=lambda x: x["cantidad_ventas"], reverse=True)
        elif ordenar_por == "nombre":
            clientes_list.sort(key=lambda x: x["nombre"])
        else:
            clientes_list.sort(key=lambda x: x["total_compras"], reverse=True)

        # Calcular totales generales
        total_ventas = sum(c["cantidad_ventas"] for c in clientes_list)
        total_ingresos = sum(c["total_compras"] for c in clientes_list)
        total_productos = sum(c["total_productos"] for c in clientes_list)

        reporte = {
            "periodo": {"inicio": fecha_inicio, "fin": fecha_fin},
            "filtros": {
                "cliente_id": cliente_id,
                "ordenar_por": ordenar_por,
            },
            "resumen": {
                "total_clientes": len(clientes_list),
                "total_ventas": total_ventas,
                "total_ingresos": total_ingresos,
                "total_productos": total_productos,
                "promedio_por_cliente": round(total_ingresos / len(clientes_list), 2) if clientes_list else 0,
            },
            "clientes": clientes_list,
        }

        return Response(reporte)
    except Exception as e:
        logger.error(f"Error en reporte_ventas_por_cliente: {str(e)}")
        return Response(
            {"error": "Error al generar reporte de ventas por cliente"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """Health check endpoint"""
    return Response(
        {"status": "healthy", "timestamp": timezone.now(), "version": "1.0.0"}
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cliente_diagnostico(request):
    """
    Endpoint de diagnóstico para clientes - útil para debugging de la app Flutter
    """
    try:
        # Verificar permisos
        if not IsCliente().has_permission(request, None):
            return Response(
                {"error": "Solo para clientes"}, status=status.HTTP_403_FORBIDDEN
            )

        diagnostico = {
            "usuario": {
                "id": request.user.id,
                "username": request.user.username,
                "correo": request.user.correo_electronico,
                "is_active": request.user.is_active,
                "tiene_persona": hasattr(request.user, "persona_asociada")
                and request.user.persona_asociada is not None,
            },
            "persona": None,
            "motos": {"count": 0, "data": []},
            "mantenimientos": {"count": 0, "data": []},
            "compras": {"count": 0, "data": []},
            "timestamp": timezone.now().isoformat(),
            "endpoints_disponibles": [
                "/api/cliente/motos/",
                "/api/cliente/ventas/",
                "/api/cliente/mantenimientos/",
                "/api/cliente/data-completa/",
                "/api/me/",
            ],
        }

        # Información de persona si existe
        if hasattr(request.user, "persona_asociada") and request.user.persona_asociada:
            persona = request.user.persona_asociada
            diagnostico["persona"] = {
                "id": persona.id,
                "nombre_completo": persona.nombre_completo,
                "cedula": persona.cedula,
                "telefono": persona.telefono,
            }

            # Contar motos
            motos_count = Moto.objects.filter(
                propietario=persona, eliminado=False
            ).count()
            diagnostico["motos"]["count"] = motos_count

            # Contar mantenimientos
            mant_count = Mantenimiento.objects.filter(
                moto__propietario=persona, eliminado=False
            ).count()
            diagnostico["mantenimientos"]["count"] = mant_count

            # Contar compras
            compras_count = Venta.objects.filter(
                cliente=persona, eliminado=False
            ).count()
            diagnostico["compras"]["count"] = compras_count

        return Response({"success": True, "diagnostico": diagnostico})

    except Exception as e:
        logger.error(f"Error en diagnóstico de cliente: {e}")
        return Response(
            {"error": f"Error en diagnóstico: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# BÚSQUEDA ENDPOINTS
# =======================================
@api_view(["GET"])
@permission_classes([IsTecnico | IsEmpleado | IsAdministrador])
def buscar_motos(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return Response({"results": []})

    q_objects = (
        Q(placa__icontains=query)
        | Q(marca__icontains=query)
        | Q(modelo__icontains=query)
        | Q(propietario__nombre__icontains=query)
        | Q(propietario__apellido__icontains=query)
        | Q(propietario__cedula__icontains=query)
    )

    if query.isdigit():
        q_objects |= Q(id=int(query))

    motos = Moto.objects.select_related("propietario").filter(
        q_objects,
        eliminado=False,
        activo=True,
    )[:20]

    results = [
        {
            "id": m.id,
            "placa": m.placa,
            "marca": m.marca,
            "modelo": m.modelo,
            "año": m.año,
            "color": m.color,
            "kilometraje": m.kilometraje,
            "propietario": {
                "id": m.propietario.id,
                "nombre_completo": m.propietario.nombre_completo,
                "cedula": m.propietario.cedula,
                "telefono": m.propietario.telefono,
            },
            "display_text": f"{m.placa} - {m.marca} {m.modelo} ({m.propietario.nombre_completo})",
        }
        for m in motos
    ]

    return Response({"results": results})


@api_view(["GET"])
@permission_classes([IsTecnico | IsEmpleado | IsAdministrador])
def buscar_productos(request):
    """Buscar productos por ID, código, nombre o categoría"""
    try:
        query = request.GET.get("q", "").strip()
        if not query:
            return Response({"results": []})

        # Buscar por múltiples campos
        productos = Producto.objects.select_related(
            "categoria", "proveedor", "inventario"
        ).filter(
            Q(id__icontains=query)
            | Q(nombre__icontains=query)
            | Q(categoria__nombre__icontains=query),
            eliminado=False,
            activo=True,
        )[
            :20
        ]  # Limitar resultados

        results = []
        for producto in productos:
            # Usar inventario en lugar de producto.stock_actual
            try:
                inventario = producto.inventario
                stock_actual = inventario.stock_actual
                stock_minimo = inventario.stock_minimo
            except Inventario.DoesNotExist:
                stock_actual = 0
                stock_minimo = 0

            results.append(
                {
                    "id": producto.id,
                    "nombre": producto.nombre,
                    "descripcion": producto.descripcion,
                    "precio_venta": str(producto.precio_venta),
                    "stock_actual": stock_actual,
                    "stock_minimo": stock_minimo,
                    "categoria": {
                        "id": producto.categoria.id,
                        "nombre": producto.categoria.nombre,
                    },
                    "proveedor": (
                        {
                            "id": producto.proveedor.id if producto.proveedor else None,
                            "nombre": (
                                producto.proveedor.nombre
                                if producto.proveedor
                                else None
                            ),
                        }
                        if producto.proveedor
                        else None
                    ),
                    "stock_disponible": stock_actual > 0,
                    "stock_bajo": stock_actual <= stock_minimo,
                    "display_text": f"{producto.nombre} (Stock: {stock_actual})",
                }
            )

        return Response({"results": results})
    except Exception as e:
        logger.error(f"Error en buscar_productos: {str(e)}")
        return Response(
            {"error": "Error al buscar productos"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsTecnico | IsEmpleado | IsAdministrador])
def buscar_servicios(request):
    """Buscar servicios por nombre o categoría"""
    try:
        query = request.GET.get("q", "").strip()
        if not query:
            return Response({"results": []})

        # Buscar por múltiples campos
        servicios = Servicio.objects.select_related("categoria_servicio").filter(
            Q(nombre__icontains=query)
            | Q(descripcion__icontains=query)
            | Q(categoria_servicio__nombre__icontains=query),
            eliminado=False,
            activo=True,
        )[
            :20
        ]  # Limitar resultados

        results = []
        for servicio in servicios:
            results.append(
                {
                    "id": servicio.id,
                    "nombre": servicio.nombre,
                    "descripcion": servicio.descripcion,
                    "precio": str(servicio.precio),
                    "duracion_estimada": servicio.duracion_estimada,
                    "categoria_servicio": {
                        "id": servicio.categoria_servicio.id,
                        "nombre": servicio.categoria_servicio.nombre,
                    },
                    "display_text": f"{servicio.nombre} - ${servicio.precio} ({servicio.duracion_estimada} min)",
                }
            )

        return Response({"results": results})
    except Exception as e:
        logger.error(f"Error en buscar_servicios: {str(e)}")
        return Response(
            {"error": "Error al buscar servicios"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_notification(request):
    """
    Endpoint simple para enviar notificaciones push
    """
    try:
        from core.services.notification_service import send_simple_notification

        # Obtener parámetros
        user_id = request.data.get("user_id")
        title = request.data.get("title", "Notificación")
        body = request.data.get("body", "Mensaje de notificación")
        data = request.data.get("data", {})

        if not user_id:
            return Response(
                {"error": "Se requiere user_id"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Buscar usuario
        try:
            usuario = Usuario.objects.get(id=user_id, is_active=True)
        except Usuario.DoesNotExist:
            return Response(
                {"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND
            )

        if not usuario.fcm_token:
            return Response(
                {"error": "El usuario no tiene token FCM registrado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Enviar notificación
        success = send_simple_notification(
            user_token=usuario.fcm_token, title=title, body=body, data=data
        )

        if success:
            return Response(
                {
                    "success": True,
                    "message": "Notificación enviada exitosamente",
                    "user": usuario.correo_electronico,
                }
            )
        else:
            return Response(
                {"error": "Error al enviar la notificación"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    except Exception as e:
        logger.error(f"Error enviando notificación: {str(e)}")
        return Response(
            {"error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_maintenance_notifications(request):
    """
    Endpoint para probar notificaciones de mantenimiento y cambio de aceite
    """
    try:
        from core.services.notification_service import (
            send_maintenance_notification,
            send_oil_change_notification,
        )

        # Obtener parámetros
        user_id = request.data.get("user_id")
        moto_info = request.data.get("moto_info", "Honda CG 150 - ABC123")
        fecha_mantenimiento = request.data.get("fecha_mantenimiento", "15/01/2025")
        kilometraje = request.data.get("kilometraje", 8500)

        if not user_id:
            return Response(
                {"error": "Se requiere user_id"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Buscar usuario
        try:
            usuario = Usuario.objects.get(id=user_id, is_active=True)
        except Usuario.DoesNotExist:
            return Response(
                {"error": "Usuario no encontrado"}, status=status.HTTP_404_NOT_FOUND
            )

        if not usuario.fcm_token:
            return Response(
                {"error": "El usuario no tiene token FCM registrado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = {}

        # Enviar notificación de mantenimiento
        success_maint = send_maintenance_notification(
            user_token=usuario.fcm_token, moto_info=moto_info, fecha=fecha_mantenimiento
        )
        results["maintenance"] = {
            "success": success_maint,
            "message": (
                "Notificación de mantenimiento enviada"
                if success_maint
                else "Error en mantenimiento"
            ),
        }

        # Enviar notificación de cambio de aceite
        success_oil = send_oil_change_notification(
            user_token=usuario.fcm_token, moto_info=moto_info, kilometraje=kilometraje
        )
        results["oil_change"] = {
            "success": success_oil,
            "message": (
                "Notificación de cambio de aceite enviada"
                if success_oil
                else "Error en cambio de aceite"
            ),
        }

        return Response(
            {
                "success": success_maint or success_oil,
                "user": usuario.correo_electronico,
                "moto_info": moto_info,
                "results": results,
            }
        )

    except Exception as e:
        logger.error(f"Error en prueba de notificaciones: {str(e)}")
        return Response(
            {"error": f"Error interno del servidor: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsCliente])
def cliente_moto_detalle(request, moto_id):
    """
    Endpoint para obtener los detalles de una moto específica del cliente,
    incluyendo información de ventas asociadas.
    """
    try:
        # Verificar persona_asociada
        if (
            not hasattr(request.user, "persona_asociada")
            or not request.user.persona_asociada
        ):
            return Response(
                {"error": "Usuario no tiene persona asociada"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = request.user.persona_asociada

        # Obtener la moto del cliente
        try:
            from core.models import Moto as MotoModel

            moto = MotoModel.objects.get(
                id=moto_id, propietario=cliente, eliminado=False
            )
        except MotoModel.DoesNotExist:
            return Response(
                {"error": "Moto no encontrada"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Serializar la moto
        from .serializers import MotoSerializer

        moto_serializer = MotoSerializer(moto)
        moto_data = moto_serializer.data

        # Buscar ventas asociadas al cliente que puedan estar relacionadas con esta moto
        # (Las ventas se asocian al cliente, no directamente a la moto)
        from ..models import Venta

        ventas = (
            Venta.objects.filter(cliente=cliente, eliminado=False)
            .select_related("registrado_por", "creado_por")
            .order_by("-fecha_venta")[:5]
        )

        from .serializers import VentaSerializer

        ventas_serializer = VentaSerializer(ventas, many=True)

        return Response(
            {
                "success": True,
                "moto": moto_data,
                "ventas_recientes": ventas_serializer.data,
                "ventas_count": len(ventas_serializer.data),
            }
        )

    except Exception as e:
        logger.error(f"Error obteniendo detalle de moto: {str(e)}")
        import traceback

        logger.error(f"Traceback: {traceback.format_exc()}")
        return Response(
            {"error": f"Error interno del servidor: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# =======================================
# RECORDATORIO VIEWSETS
# =======================================
# PRECIOS ESPECIALES POR CLIENTE
# =======================================


# =======================================
class RecordatorioMantenimientoViewSet(BaseViewSet):
    """
    ViewSet para RecordatorioMantenimiento
    Hereda de BaseViewSet para:
    - Soft delete / restore
    - Filtros por activo/eliminado
    - Logging estandarizado
    """

    serializer_class = RecordatorioMantenimientoSerializer
    queryset = RecordatorioMantenimiento.objects_all.all()  # incluir eliminados

    filterset_fields = ["moto", "categoria_servicio", "activo", "enviado"]
    search_fields = ["moto__placa", "categoria_servicio__nombre"]
    ordering = ["-fecha_registro"]

    def get_queryset(self):
        model = self.serializer_class.Meta.model
        qs = model.objects_all.all()  # usar objects_all en lugar de objects

        # Filtro por eliminado
        eliminado = self.request.query_params.get("eliminado")
        if hasattr(model, "eliminado") and eliminado is not None:
            if eliminado.lower() == "true":
                qs = qs.filter(eliminado=True)
            elif eliminado.lower() == "false":
                qs = qs.filter(eliminado=False)
            elif eliminado.lower() == "all":
                pass
            else:
                qs = qs.filter(eliminado=False)
        else:
            qs = qs.filter(eliminado=False)

        # Filtro por activo
        activo = self.request.query_params.get("activo")
        if hasattr(model, "activo") and activo is not None:
            if activo.lower() == "true":
                qs = qs.filter(activo=True)
            elif activo.lower() == "false":
                qs = qs.filter(activo=False)

        return qs

    def perform_create(self, serializer):
        """Asignar automáticamente el usuario registrador"""
        if self.request.user.is_authenticated:
            # RecordatorioMantenimiento usa el campo 'registrado_por'
            serializer.save(registrado_por=self.request.user)
        else:
            serializer.save()

    def perform_update(self, serializer):
        """Override update para validar fecha_programada no pasada"""
        instance = self.get_object()
        fecha_programada = serializer.validated_data.get("fecha_programada")
        if fecha_programada and fecha_programada < timezone.now().date():
            raise serializers.ValidationError(
                {"fecha_programada": "La fecha programada no puede ser anterior a hoy"}
            )
        serializer.save()

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            permission_classes = [permissions.IsAuthenticated]
        elif self.action in ["create", "update", "partial_update"]:
            permission_classes = [IsEmpleado | IsAdministrador]
        elif self.action in ["destroy", "soft_delete", "restore"]:
            permission_classes = [IsAdministrador]
        else:
            permission_classes = [IsEmpleado | IsAdministrador]
        return [permission() for permission in permission_classes]

    @action(detail=True, methods=["patch"])
    def marcar_enviado(self, request, pk=None):
        """Marcar recordatorio de mantenimiento como enviado"""
        recordatorio = self.get_object()
        recordatorio.enviado = True
        recordatorio.save(update_fields=["enviado"])
        serializer = self.get_serializer(recordatorio)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def proximos(self, request):
        """Obtener recordatorios de mantenimiento próximos"""
        dias_adelante = int(request.query_params.get("dias", 7))
        hoy = timezone.now().date()
        fecha_limite = hoy + timedelta(days=dias_adelante)

        queryset = self.get_queryset().filter(
            fecha_programada__range=[hoy, fecha_limite], enviado=False
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def estadisticas(self, request):
        """Estadísticas de recordatorios de mantenimiento"""
        queryset = self.get_queryset()

        total = queryset.count()
        enviados = queryset.filter(enviado=True).count()
        pendientes = queryset.filter(enviado=False).count()
        proximos = queryset.filter(
            fecha_programada__gte=timezone.now().date(), enviado=False
        ).count()

        return Response(
            {
                "total": total,
                "enviados": enviados,
                "pendientes": pendientes,
                "proximos": proximos,
                "porcentaje_enviado": (enviados / total * 100) if total > 0 else 0,
            }
        )

    # ===========================
    # Restaurar registro eliminado
    # ===========================
    @action(detail=True, methods=["patch"], url_path="restore")
    def restore(self, request, pk=None):
        """
        Restaurar un registro que fue eliminado temporalmente.
        Usar objects_all para incluir eliminados.
        """
        try:
            recordatorio = RecordatorioMantenimiento.objects_all.get(pk=pk)
        except RecordatorioMantenimiento.DoesNotExist:
            return Response(
                {"detail": "Recordatorio no encontrado"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not hasattr(recordatorio, "eliminado"):
            return Response(
                {"error": "Este modelo no soporta restauración"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if recordatorio.eliminado:
            recordatorio.eliminado = False
            recordatorio.save(update_fields=["eliminado"])
            serializer = self.get_serializer(recordatorio)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(
                {"detail": "El registro no está eliminado"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # ===========================
    # Enviar notificación push
    # ===========================
    @action(detail=True, methods=["post"], url_path="enviar_notificacion")
    def enviar_notificacion(self, request, pk=None):
        """
        Enviar notificación push para un recordatorio de mantenimiento
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            from core.services.notification_service import send_maintenance_notification

            # Obtener el recordatorio con las relaciones
            try:
                recordatorio = RecordatorioMantenimiento.objects.select_related(
                    "moto", "moto__propietario"
                ).get(pk=pk)
            except RecordatorioMantenimiento.DoesNotExist:
                logger.error(f"Recordatorio no encontrado ID: {pk}")
                return Response(
                    {"detail": "Recordatorio no encontrado"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Obtener la moto y el usuario
            moto = recordatorio.moto
            if not moto:
                logger.error("El recordatorio no tiene una moto asociada")
                return Response(
                    {"error": "El recordatorio no tiene una moto asociada"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Obtener el usuario a través del propietario (Persona)
            propietario = moto.propietario
            if not propietario:
                logger.error(f"La moto (ID: {moto.id}) no tiene propietario asignado")
                return Response(
                    {"error": f"La moto (ID: {moto.id}) no tiene propietario asignado"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # La relación es: Persona -> usuario (ForeignKey a Usuario)
            usuario = propietario.usuario
            if not usuario:
                logger.error(
                    f"El propietario (ID: {propietario.id}) no tiene usuario de app asociado"
                )
                return Response(
                    {
                        "error": f"El propietario (ID: {propietario.id}) no tiene un usuario de app asociado"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not usuario.fcm_token:
                logger.error("El usuario no tiene token FCM registrado")
                logger.error(f"🔍 [DEBUG] Usuario ID: {usuario.id}, username: {usuario.username}")
            else:
                logger.info(f"🔑 [DEBUG] Token del usuario - Longitud: {len(usuario.fcm_token)}")
                logger.info(f"🔑 [DEBUG] Token - Primeros 30: {usuario.fcm_token[:30]}")
                return Response(
                    {
                        "error": "El usuario no tiene token FCM registrado. Debe iniciar sesión en la app móvil primero."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Preparar datos de la notificación
            moto_info = f"{moto.marca} {moto.modelo} - {moto.placa}"
            fecha = (
                recordatorio.fecha_programada.strftime("%d/%m/%Y")
                if recordatorio.fecha_programada
                else ""
            )

            # Enviar notificación
            success = send_maintenance_notification(
                user_token=usuario.fcm_token, moto_info=moto_info, fecha=fecha
            )

            if success:
                # Marcar como enviado
                recordatorio.enviado = True
                recordatorio.save(update_fields=["enviado"])

                return Response(
                    {
                        "success": True,
                        "message": "Notificación enviada exitosamente",
                        "usuario": usuario.correo_electronico,
                        "moto": moto_info,
                    }
                )
            else:
                logger.error(
                    "[DEBUG] Error al enviar la notificación push - El servicio devolvió False"
                )
                return Response(
                    {"error": "Error al enviar la notificación push"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        except Exception as e:
            import traceback

            logger.error(f"[DEBUG] Error enviando notificación: {str(e)}")
            logger.error(f"[DEBUG] Traceback: {traceback.format_exc()}")
            return Response(
                {"error": f"Error interno del servidor: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
