from rest_framework import permissions
from django.db.models import Q
from ..models import *


class IsAdministrador(permissions.BasePermission):
    message = "Debes ser un Administrador para realizar esta acción."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Usar normalización a minúsculas para comparación consistente
        roles = request.user.roles.filter(activo=True).values_list(
            "rol__nombre", flat=True
        )
        roles_normalized = [role.lower() for role in roles]
        return "administrador" in roles_normalized


class IsEmpleado(permissions.BasePermission):
    message = "Debes ser un Empleado o Administrador para realizar esta acción."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        roles = request.user.roles.filter(activo=True).values_list(
            "rol__nombre", flat=True
        )
        # Normalizar roles a minúsculas para comparación consistente
        roles_normalized = [role.lower() for role in roles]
        return "empleado" in roles_normalized or "administrador" in roles_normalized


class IsTecnico(permissions.BasePermission):
    message = "Debes ser un Técnico o Administrador para realizar esta acción."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        roles = request.user.roles.filter(activo=True).values_list(
            "rol__nombre", flat=True
        )
        # Normalizar roles a minúsculas para comparación consistente
        roles_normalized = [role.lower() for role in roles]
        return "tecnico" in roles_normalized or "administrador" in roles_normalized


class IsCliente(permissions.BasePermission):
    message = "Debes ser un Cliente o Administrador para realizar esta acción."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        roles = request.user.roles.filter(activo=True).values_list(
            "rol__nombre", flat=True
        )
        # Normalizar roles a minúsculas para comparación consistente
        roles_normalized = [role.lower() for role in roles]
        return "cliente" in roles_normalized or "administrador" in roles_normalized


class IsOwner(permissions.BasePermission):
    message = "No tienes permiso para acceder a este objeto."

    def has_object_permission(self, request, view, obj):
        if not hasattr(request.user, "persona") or not request.user.persona:
            return False

        if isinstance(obj, Persona):
            return obj == request.user.persona
        if isinstance(obj, Moto):
            return obj.propietario == request.user.persona
        if isinstance(obj, Mantenimiento):
            return obj.moto.propietario == request.user.persona
        if isinstance(obj, Venta):
            return obj.cliente == request.user.persona
        if isinstance(obj, DetalleMantenimiento):
            return obj.mantenimiento.moto.propietario == request.user.persona
        if isinstance(obj, DetalleVenta):
            return obj.venta.cliente == request.user.persona

        return False


class CustomPermission(permissions.BasePermission):

    def has_permission(self, request, view):
        # Debug logs removed

        # Administradores tienen acceso completo
        is_admin = IsAdministrador().has_permission(request, view)
        if is_admin:
            return True

        # Restricciones específicas para empleados en ciertos módulos
        if view.basename in ["roles", "usuarios-roles"]:
            return IsAdministrador().has_permission(request, view)

        # Empleados pueden acceder a usuarios con restricciones adicionales
        if view.basename == "usuarios":
            is_employee = IsEmpleado().has_permission(request, view)
            # Bloquear acciones específicas para empleados
            if is_employee and view.action in [
                "reset_password",
                "cambiar_password",
                "activate",
                "deactivate",
            ]:
                return False
            # Bloquear métodos PATCH/PUT que podrían cambiar estado activo
            if is_employee and request.method in ["PATCH", "PUT"]:
                # Verificar si se está intentando cambiar el campo 'is_active'
                if hasattr(request, "data") and "is_active" in request.data:
                    return False
            result = is_employee or IsAdministrador().has_permission(request, view)
            return result

        # Productos: empleados solo pueden VER (no crear/editar/eliminar)
        if view.basename == "productos":
            is_employee = IsEmpleado().has_permission(request, view)
            if is_employee and request.method not in permissions.SAFE_METHODS:
                return False
            result = is_employee or IsAdministrador().has_permission(request, view)
            return result

        if IsEmpleado().has_permission(request, view):
            if view.basename in [
                "personas",
                "categorias",
                "categorias-servicio",
            ]:
                return True
            # Empleados tienen acceso completo a inventario y movimientos
            if view.basename in ["inventario", "inventario-movimiento"]:
                return True
            # Empleados solo pueden VER (no crear/editar/eliminar) estos módulos
            if view.basename in [
                "proveedores",
                "servicios",
                "ventas",
                "detalles-venta",
            ]:
                is_safe_method = request.method in permissions.SAFE_METHODS
                return is_safe_method
            if view.basename in [
                "motos",
                "mantenimientos",
                "detalles-mantenimiento",
            ]:
                return request.method in permissions.SAFE_METHODS

        if IsTecnico().has_permission(request, view):
            # Técnicos pueden ver mantenimientos asignados y cambiar su estado/observaciones
            if view.basename == "mantenimientos":
                # Solo pueden ver sus mantenimientos asignados y actualizar estado/observaciones
                if request.method in permissions.SAFE_METHODS:
                    return True
                # Solo pueden hacer PUT/PATCH para cambiar estado o agregar observaciones
                if request.method in ["PUT", "PATCH"]:
                    return True
                # NO pueden crear ni eliminar mantenimientos
                return False

            # Técnicos pueden ver detalles de mantenimiento (solo lectura)
            if view.basename == "detalles-mantenimiento":
                return request.method in permissions.SAFE_METHODS

            # Técnicos pueden ver motos relacionadas con sus mantenimientos (solo lectura)
            if view.basename == "motos":
                return request.method in permissions.SAFE_METHODS

            # Técnicos pueden ver usuarios/clientes relacionados con sus mantenimientos (solo lectura)
            if view.basename == "usuarios":
                return request.method in permissions.SAFE_METHODS

            # Técnicos pueden ver productos/repuestos asignados a sus mantenimientos (solo lectura)
            if view.basename in ["productos", "inventario"]:
                return request.method in permissions.SAFE_METHODS

            # Técnicos pueden ver servicios que deben realizar (solo lectura)
            if view.basename == "servicios":
                return request.method in permissions.SAFE_METHODS

            # NO pueden acceder a ventas
            if view.basename in ["ventas", "detalles-venta", "pagos"]:
                return False

        if IsCliente().has_permission(request, view):
            if view.basename in [
                "personas",
                "motos",
                "mantenimientos",
                "ventas",
                "detalles-mantenimiento",
                "detalles-venta",
                "productos",
                "servicios",
            ]:
                return request.method in permissions.SAFE_METHODS

        return False

    def has_object_permission(self, request, view, obj):
        if IsAdministrador().has_permission(request, view):
            return True

        if view.basename in ["roles", "usuarios-roles"]:
            return IsAdministrador().has_permission(request, view)

        # Empleados pueden acceder a usuarios con restricciones
        if view.basename == "usuarios":
            return IsEmpleado().has_permission(
                request, view
            ) or IsAdministrador().has_permission(request, view)

        # Productos: empleados solo pueden VER objetos específicos
        if view.basename == "productos":
            is_employee = IsEmpleado().has_permission(request, view)
            if is_employee and request.method not in permissions.SAFE_METHODS:
                return False
            return is_employee or IsAdministrador().has_permission(request, view)

        # Técnicos solo pueden ver/editar objetos relacionados con sus mantenimientos asignados
        if IsTecnico().has_permission(request, view):
            if view.basename == "mantenimientos":
                # Solo pueden ver/editar mantenimientos asignados a ellos
                if hasattr(obj, "tecnico_asignado"):
                    return obj.tecnico_asignado == request.user
                return False

            if view.basename == "motos":
                # Solo pueden ver motos que tienen mantenimientos asignados a ellos
                return obj.mantenimiento_set.filter(
                    tecnico_asignado=request.user
                ).exists()

            if view.basename == "usuarios":
                # Solo pueden ver clientes relacionados con sus mantenimientos
                if (
                    hasattr(request.user, "persona_asociada")
                    and request.user.persona_asociada
                ):
                    # Verificar si el usuario es propietario de una moto con mantenimiento asignado al técnico
                    return (
                        obj.persona_asociada
                        and obj.persona_asociada.moto_set.filter(
                            mantenimiento__tecnico_asignado=request.user
                        ).exists()
                    )
                return False

            if view.basename in ["productos", "inventario"]:
                # Solo pueden ver productos/inventario usados en sus mantenimientos
                return obj.repuestos_usados.filter(
                    mantenimiento__tecnico_asignado=request.user
                ).exists()

            if view.basename == "servicios":
                # Solo pueden ver servicios de sus mantenimientos asignados
                return obj.detallemantenimiento_set.filter(
                    mantenimiento__tecnico_asignado=request.user
                ).exists()

            # Para otros casos, permitir acceso si es técnico
            return True

        if IsCliente().has_permission(request, view):
            if request.method in permissions.SAFE_METHODS:
                return IsOwner().has_object_permission(
                    request, view, obj
                ) or isinstance(obj, (Producto, Servicio))
            if request.method in ["PUT", "PATCH"]:
                return isinstance(obj, Persona) and IsOwner().has_object_permission(
                    request, view, obj
                )

        return True
