# =======================================
# TALLER DE MOTOS - API URLS (OPTIMIZED)
# =======================================

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from . import pos_views
from .password_reset_views import PasswordResetRequestView, PasswordResetConfirmView
from .health_checks import (
    health_check,
    database_health,
    cache_health,
    services_health,
    system_metrics,
)
from .monitoring import (
    api_stats,
    system_performance,
    error_logs,
    system_alerts,
)

# =======================================
# ROUTER PRINCIPAL
# =======================================
router = DefaultRouter()

# =======================================
# GESTIÓN DE USUARIOS Y AUTENTICACIÓN
# =======================================
router.register(r"usuarios", UsuarioViewSet, basename="usuarios")
router.register(r"personas", PersonaViewSet, basename="persona")
router.register(r"roles", RolViewSet, basename="rol")
router.register(r"usuarios-roles", UsuarioRolViewSet, basename="usuario-rol")

# =======================================
# CATÁLOGOS Y CONFIGURACIÓN
# =======================================
router.register(r"categorias", CategoriaViewSet, basename="categoria")
router.register(
    r"categorias-servicio", CategoriaServicioViewSet, basename="categoria-servicio"
)
router.register(r"proveedores", ProveedorViewSet, basename="proveedor")

# =======================================
# PRODUCTOS Y SERVICIOS
# =======================================
router.register(r"productos", ProductoViewSet, basename="productos")
router.register(r"servicios", ServicioViewSet, basename="servicio")

# =======================================
# VEHÍCULOS Y MANTENIMIENTO
# =======================================
router.register(r"motos", MotoViewSet, basename="moto")
router.register(r"mantenimientos", MantenimientoViewSet, basename="mantenimiento")
router.register(
    r"detalles-mantenimiento",
    DetalleMantenimientoViewSet,
    basename="detalle-mantenimiento",
)
router.register(
    r"recordatorios-mantenimiento",
    RecordatorioMantenimientoViewSet,
    basename="recordatorio_mantenimiento",
)

# =======================================
# VENTAS E INVENTARIO
# =======================================
router.register(r"ventas", VentaViewSet, basename="venta")
router.register(r"detalles-venta", DetalleVentaViewSet, basename="detalle-venta")
router.register(r"pagos", PagoViewSet, basename="pago")
router.register(r"inventario", InventarioViewSet, basename="inventario")
router.register(
    r"inventario-movimientos",
    InventarioMovimientoViewSet,
    basename="inventario-movimiento",
)
router.register(
    r"repuestos-mantenimiento",
    RepuestoMantenimientoViewSet,
    basename="repuesto-mantenimiento",
)
router.register(r"lotes", LoteViewSet, basename="lote")

# =======================================
# PRECIOS ESPECIALES POR CLIENTE
# =======================================

# =======================================
# ENDPOINTS PÚBLICOS (SIN AUTENTICACIÓN)
# =======================================
router.register(
    r"publico/productos", ProductoPublicoViewSet, basename="producto-publico"
)
router.register(
    r"publico/destacados", ProductoPublicoViewSet, basename="destacado-publico"
)
router.register(
    r"publico/categorias", CategoriaPublicaViewSet, basename="categoria-publica"
)


# =======================================
# URL PATTERNS
# =======================================
urlpatterns = [
    # =======================================
    # AUTENTICACIÓN JWT
    # =======================================
    path("auth/login/", CustomTokenObtainPairView.as_view(), name="auth_login"),
    path(
        "auth/mobile-login/",
        MobileTokenObtainPairView.as_view(),
        name="mobile_auth_login",
    ),
    path("auth/refresh/", CustomTokenRefreshView.as_view(), name="auth_refresh"),
    path("auth/logout/", logout_view, name="auth_logout"),
    # Login alternativo (compatibilidad)
    path("login/", login_view, name="login"),
    # =======================================
    # RECUPERACIÓN DE CONTRASEÑA (SOLO CLIENTES)
    # =======================================
    path(
        "password-reset/",
        PasswordResetRequestView.as_view(),
        name="password_reset_request",
    ),
    path(
        "password-reset-confirm/",
        PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    # =======================================
    # PERFIL DE USUARIO
    # =======================================
    path("me/", UsuarioMeView.as_view(), name="usuario_me"),
    path("me/cambiar-password/", CambioPasswordView.as_view(), name="cambiar_password"),
    # =======================================
    # DASHBOARD Y REPORTES
    # =======================================
    path("dashboard/stats/", dashboard_stats, name="dashboard_stats"),
    path(
        "cliente/dashboard/stats/",
        cliente_dashboard_stats,
        name="cliente_dashboard_stats",
    ),
    path(
        "tecnico/dashboard/stats/",
        tecnico_dashboard_stats,
        name="tecnico_dashboard_stats",
    ),
    # =======================================
    # BUSINESS INTELLIGENCE ENDPOINTS
    # =======================================
    path("bi/analytics/advanced/", bi_analytics_advanced, name="bi_analytics_advanced"),
    path("bi/forecasting/demand/", bi_demand_forecast, name="bi_demand_forecast"),
    path(
        "bi/profitability/<str:type>/",
        bi_profitability_analysis,
        name="bi_profitability_analysis",
    ),
    path(
        "bi/performance/technicians/",
        bi_technician_performance,
        name="bi_technician_performance",
    ),
    path(
        "bi/performance/technicians/<int:technician_id>/",
        bi_technician_performance,
        name="bi_technician_performance_specific",
    ),
    path(
        "bi/customers/segmentation/",
        bi_customer_segmentation,
        name="bi_customer_segmentation",
    ),
    path("bi/trends/<str:metric>/", bi_trend_analysis, name="bi_trend_analysis"),
    path("bi/kpis/custom/", bi_custom_kpis, name="bi_custom_kpis"),
    # =======================================
    # ENDPOINTS ESPECÍFICOS PARA CLIENTES
    # =======================================
    path("cliente/motos/", cliente_motos, name="cliente_motos"),
    path(
        "cliente/motos/<int:moto_id>/",
        cliente_moto_detalle,
        name="cliente_moto_detalle",
    ),
    path("cliente/ventas/", cliente_ventas, name="cliente_ventas"),
    path(
        "cliente/mantenimientos/", cliente_mantenimientos, name="cliente_mantenimientos"
    ),
    path("cliente/data-completa/", cliente_data_completa, name="cliente_data_completa"),
    path("cliente/diagnostico/", cliente_diagnostico, name="cliente_diagnostico"),
    path("reportes/ventas/", reporte_ventas, name="reporte_ventas"),
    path("reportes/productos/", reporte_productos, name="reporte_productos"),
    path("reportes/inventario/", reporte_inventario, name="reporte_inventario"),
    path(
        "reportes/mantenimientos/",
        reporte_mantenimientos,
        name="reporte_mantenimientos",
    ),
    path("reportes/motos/", reporte_motos, name="reporte_motos"),
    path("reportes/proveedores/", reporte_proveedores, name="reporte_proveedores"),
    path("reportes/usuarios/", reporte_usuarios, name="reporte_usuarios"),
    # =======================================
    # BÚSQUEDA
    # =======================================
    path("buscar/motos/", buscar_motos, name="buscar_motos"),
    path("buscar/productos/", buscar_productos, name="buscar_productos"),
    path("buscar/servicios/", buscar_servicios, name="buscar_servicios"),
    # =======================================
    # POS SYSTEM ENDPOINTS
    # =======================================    # POS endpoints
    path("pos/ventas/crear/", pos_views.crear_venta_pos, name="crear_venta_pos"),
    path(
        "pos/pagos/registrar/",
        pos_views.registrar_pago_venta,
        name="registrar_pago_venta",
    ),
    path(
        "pos/productos/buscar/",
        pos_views.buscar_productos_pos,
        name="buscar_productos_pos",
    ),
    path(
        "pos/clientes/buscar/",
        pos_views.buscar_clientes_pos,
        name="pos_buscar_clientes",
    ),
    path(
        "pos/tecnicos/buscar/",
        pos_views.buscar_tecnicos_pos,
        name="pos_buscar_tecnicos",
    ),
    path(
        "pos/mantenimientos/crear/",
        crear_mantenimiento_pos,
        name="pos_crear_mantenimiento",
    ),
    path("pos/motos/buscar/", pos_views.buscar_motos_pos, name="pos_buscar_motos"),
    path(
        "pos/servicios/buscar/",
        pos_views.buscar_servicios_pos,
        name="pos_buscar_servicios",
    ),
    path("pos/inventario/alertas/", alertas_inventario, name="pos_alertas_inventario"),
    path("pos/inventario/ajustar/", ajustar_inventario, name="pos_ajustar_inventario"),
    path("pos/dashboard/stats/", dashboard_pos_stats, name="pos_dashboard_stats"),
    # =======================================
    # NOTIFICACIONES PUSH
    # =======================================
    path("notifications/send/", send_notification, name="send_notification"),
    path(
        "notifications/test-maintenance/",
        test_maintenance_notifications,
        name="test_maintenance_notifications",
    ),
    # =======================================
    # SALUD DEL SISTEMA
    # =======================================
    path("health/", health_check, name="health_check"),
    path("health/database/", database_health, name="database_health"),
    path("health/cache/", cache_health, name="cache_health"),
    path("health/services/", services_health, name="services_health"),
    path("health/metrics/", system_metrics, name="system_metrics"),
    # =======================================
    # MONITORING Y LOGGING
    # =======================================
    path("monitoring/api-stats/", api_stats, name="api_stats"),
    path("monitoring/performance/", system_performance, name="system_performance"),
    path("monitoring/errors/", error_logs, name="error_logs"),
    path("monitoring/alerts/", system_alerts, name="system_alerts"),
    # =======================================
    # RUTAS DEL ROUTER
    # =======================================
    path("", include(router.urls)),
]
