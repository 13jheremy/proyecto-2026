# =======================================
# TALLER DE MOTOS - API SERIALIZERS (OPTIMIZED)
# =======================================
# Archivo completamente limpio y optimizado
# - Eliminadas duplicaciones de código
# - Estandarizados todos los serializers
# - Mejoradas las validaciones
# - Optimizado el manejo de relaciones
# - Implementado logging consistente
# =======================================

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.validators import UniqueValidator
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from datetime import timedelta
import logging

from ..models import *

logger = logging.getLogger(__name__)


# =======================================
# BASE SERIALIZER
# =======================================
class BaseModelSerializer(serializers.ModelSerializer):
    """
    Serializer base con funcionalidades comunes:
    - Validaciones estándar
    - Manejo de errores consistente
    - Logging de operaciones
    """

    def validate(self, attrs):
        """Validación base común"""
        attrs = super().validate(attrs)

        # Validar que no se esté creando un registro duplicado si tiene campo único
        # Excluir Producto del modelo ya que el nombre no es único para productos
        if (
            hasattr(self.Meta.model, "nombre")
            and "nombre" in attrs
            and self.Meta.model.__name__ != "Producto"
        ):
            if self.instance is None:  # Solo en creación
                if self.Meta.model.objects.filter(nombre=attrs["nombre"]).exists():
                    raise serializers.ValidationError(
                        {"nombre": "Ya existe un registro con este nombre."}
                    )

        return attrs

    def create(self, validated_data):
        """Creación con logging"""
        try:
            instance = super().create(validated_data)
            logger.info(f"Creado {self.Meta.model.__name__} ID={instance.id}")
            return instance
        except Exception as e:
            logger.error(f"Error creando {self.Meta.model.__name__}: {str(e)}")
            raise serializers.ValidationError(f"Error al crear: {str(e)}")

    def update(self, instance, validated_data):
        """Actualización con logging"""
        try:
            instance = super().update(instance, validated_data)
            logger.info(f"Actualizado {self.Meta.model.__name__} ID={instance.id}")
            return instance
        except Exception as e:
            logger.error(f"Error actualizando {self.Meta.model.__name__}: {str(e)}")
            raise serializers.ValidationError(f"Error al actualizar: {str(e)}")


# =======================================
# AUTHENTICATION SERIALIZERS
# =======================================
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Serializer personalizado para autenticación JWT"""

    username_field = "correo_electronico"

    def validate(self, attrs):
        correo = attrs.get("correo_electronico", "").lower().strip()
        password = attrs.get("password")

        if not correo or not password:
            raise serializers.ValidationError(
                "Correo electrónico y contraseña son requeridos"
            )

        user = authenticate(correo_electronico=correo, password=password)

        if not user:
            raise serializers.ValidationError("Usuario o contraseña incorrectos")

        if not user.is_active:
            raise serializers.ValidationError("Usuario inactivo")

        refresh = RefreshToken.for_user(user)

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "correo_electronico": user.correo_electronico,
                "tiene_persona": user.tiene_persona,
                "roles": [rol.rol.nombre for rol in user.roles.filter(activo=True)],
            },
        }


class MobileTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Serializer específico para autenticación móvil (solo clientes)"""

    username_field = "correo_electronico"

    def validate(self, attrs):
        correo = attrs.get("correo_electronico", "").lower().strip()
        password = attrs.get("password")

        if not correo or not password:
            raise serializers.ValidationError(
                "Correo electrónico y contraseña son requeridos"
            )

        user = authenticate(correo_electronico=correo, password=password)

        if not user:
            raise serializers.ValidationError("Usuario o contraseña incorrectos")

        if not user.is_active:
            raise serializers.ValidationError("Usuario inactivo")

        # Verificar que el usuario tenga rol de Cliente (solo para móvil)
        user_roles = [rol.rol.nombre for rol in user.roles.filter(activo=True)]

        # Verificar si tiene rol Cliente (case-insensitive)
        has_client_role = any(rol.lower() == "cliente" for rol in user_roles)

        if not has_client_role:
            raise serializers.ValidationError(
                {"non_field_errors": ["Acceso móvil restringido solo para clientes"]}
            )

        refresh = RefreshToken.for_user(user)

        # Normalizar roles a minúsculas para consistencia en móvil
        normalized_roles = [rol.lower() for rol in user_roles]

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "correo_electronico": user.correo_electronico,
                "tiene_persona": user.tiene_persona,
                "roles": normalized_roles,  # Roles normalizados para móvil
            },
        }


class CambioPasswordSerializer(serializers.Serializer):
    """Serializer para cambio de contraseña"""

    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    confirm_new_password = serializers.CharField(required=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_new_password"]:
            raise serializers.ValidationError("Las contraseñas nuevas no coinciden")
        return data

    def validate_new_password(self, value):
        """Validar fortaleza de contraseña"""
        if len(value) < 8:
            raise serializers.ValidationError(
                "La contraseña debe tener al menos 8 caracteres"
            )
        if value.isdigit():
            raise serializers.ValidationError("La contraseña no puede ser solo números")
        return value


# =======================================
# USER SERIALIZERS
# =======================================
class RolSerializer(BaseModelSerializer):
    """Serializer para Roles"""

    usuarios_count = serializers.SerializerMethodField()

    class Meta:
        model = Rol
        fields = [
            "id",
            "nombre",
            "descripcion",
            "usuarios_count",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_usuarios_count(self, obj):
        return obj.usuariorol_set.filter(activo=True).count()


class UsuarioRolSerializer(BaseModelSerializer):
    """Serializer para relación Usuario-Rol"""

    rol = RolSerializer(read_only=True)
    rol_id = serializers.IntegerField(write_only=True)
    usuario_nombre = serializers.CharField(source="usuario.username", read_only=True)
    rol_nombre = serializers.CharField(source="rol.nombre", read_only=True)

    class Meta:
        model = UsuarioRol
        fields = [
            "id",
            "usuario",
            "rol",
            "rol_id",
            "activo",
            "usuario_nombre",
            "rol_nombre",
            "fecha_registro",
            "fecha_actualizacion",
        ]


# =======================================
# PERSONA SERIALIZERS
# =======================================
class PersonaSerializer(BaseModelSerializer):
    """Serializer principal para Personas"""

    usuario_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True
    )
    usuario_correo = serializers.CharField(
        source="usuario.correo_electronico", read_only=True
    )
    nombre_completo = serializers.CharField(read_only=True)
    tiene_usuario = serializers.BooleanField(read_only=True)

    class Meta:
        model = Persona
        fields = [
            "id",
            "nombre",
            "apellido",
            "cedula",
            "telefono",
            "direccion",
            "usuario_id",
            "usuario_correo",
            "eliminado",
            "nombre_completo",
            "tiene_usuario",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def validate_cedula(self, value):
        """Validar unicidad de cédula"""
        if self.instance and self.instance.cedula == value:
            return value

        if Persona.objects.filter(cedula=value).exists():
            raise serializers.ValidationError("Ya existe una persona con esta cédula")
        return value

    def validate_usuario_id(self, value):
        """Validar que el usuario no esté ya asociado"""
        if value:
            try:
                usuario = Usuario.objects.get(id=value)
                if hasattr(usuario, "persona_asociada") and usuario.persona_asociada:
                    if not self.instance or usuario.persona_asociada != self.instance:
                        raise serializers.ValidationError(
                            "Este usuario ya tiene una persona asociada"
                        )
            except Usuario.DoesNotExist:
                raise serializers.ValidationError("Usuario no encontrado")
        return value

    def create(self, validated_data):
        usuario_id = validated_data.pop("usuario_id", None)
        persona = super().create(validated_data)

        if usuario_id:
            try:
                usuario = Usuario.objects.get(id=usuario_id)
                persona.usuario = usuario
                persona.save()
            except Usuario.DoesNotExist:
                pass

        return persona

    def update(self, instance, validated_data):
        usuario_id = validated_data.pop("usuario_id", None)
        persona = super().update(instance, validated_data)

        if usuario_id is not None:
            if usuario_id:
                try:
                    usuario = Usuario.objects.get(id=usuario_id)
                    persona.usuario = usuario
                except Usuario.DoesNotExist:
                    pass
            else:
                persona.usuario = None
            persona.save()

        return persona


class PersonaCreateSerializer(PersonaSerializer):
    """Serializer específico para crear personas"""

    usuario_data = serializers.DictField(write_only=True, required=False)

    class Meta(PersonaSerializer.Meta):
        fields = PersonaSerializer.Meta.fields + ["usuario_data"]

    def create(self, validated_data):
        usuario_data = validated_data.pop("usuario_data", None)
        persona = super().create(validated_data)

        if usuario_data:
            # Crear usuario asociado
            usuario_serializer = UsuarioCreateSerializer(data=usuario_data)
            if usuario_serializer.is_valid():
                usuario = usuario_serializer.save()
                persona.usuario = usuario
                persona.save()

        return persona


# =======================================
# USUARIO SERIALIZERS
# =======================================
class UsuarioSerializer(BaseModelSerializer):
    """Serializer principal para Usuarios"""

    persona = PersonaSerializer(source="persona_asociada", read_only=True)
    persona_id = serializers.IntegerField(
        write_only=True, required=False, allow_null=True
    )
    roles = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False)
    tiene_persona = serializers.BooleanField(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "username",
            "correo_electronico",
            "is_active",
            "persona",
            "persona_id",
            "roles",
            "password",
            "eliminado",
            "tiene_persona",
            "last_login",
            "date_joined",
        ]

    def get_roles(self, obj):
        return [
            {"id": ur.rol.id, "nombre": ur.rol.nombre, "activo": ur.activo}
            for ur in obj.roles.select_related("rol").all()
        ]

    def validate_correo_electronico(self, value):
        """Validar unicidad del correo"""
        value = value.lower().strip()
        if self.instance and self.instance.correo_electronico == value:
            return value

        if Usuario.objects.filter(correo_electronico=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este correo electrónico"
            )
        return value

    def validate_username(self, value):
        """Validar unicidad del username"""
        if self.instance and self.instance.username == value:
            return value

        if Usuario.objects.filter(username=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este nombre de usuario"
            )
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        persona_id = validated_data.pop("persona_id", None)

        usuario = super().create(validated_data)

        if password:
            usuario.set_password(password)
            usuario.save()

        if persona_id:
            try:
                persona = Persona.objects.get(id=persona_id)
                persona.usuario = usuario
                persona.save()
            except Persona.DoesNotExist:
                pass

        return usuario

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        persona_id = validated_data.pop("persona_id", None)

        usuario = super().update(instance, validated_data)

        if password:
            usuario.set_password(password)
            usuario.save()

        if persona_id is not None:
            if persona_id:
                try:
                    persona = Persona.objects.get(id=persona_id)
                    persona.usuario = usuario
                    persona.save()
                except Persona.DoesNotExist:
                    pass
            else:
                if hasattr(usuario, "persona_asociada") and usuario.persona_asociada:
                    usuario.persona_asociada.usuario = None
                    usuario.persona_asociada.save()

        return usuario


class UsuarioCreateSerializer(UsuarioSerializer):
    """Serializer específico para crear usuarios"""

    password = serializers.CharField(write_only=True, required=True)
    roles = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    def create(self, validated_data):
        roles_ids = validated_data.pop("roles", [])
        usuario = super().create(validated_data)

        # Asignar roles
        for rol_id in roles_ids:
            try:
                rol = Rol.objects.get(id=rol_id)
                UsuarioRol.objects.create(usuario=usuario, rol=rol, activo=True)
            except Rol.DoesNotExist:
                pass

        return usuario


# CREAR USUARIO COMPLETO
class UsuarioPersonaCompleteSerializer(serializers.ModelSerializer):
    """
    Serializer para crear/actualizar usuario con persona anidada completa
    SOLUCIÓN: No usar PersonaSerializer anidado para evitar problemas de validación
    """

    # Campos de persona como campos directos (no anidados)
    persona_asociada = serializers.SerializerMethodField(
        read_only=True
    )  # Solo para leer

    # Campos individuales para escribir datos de persona
    persona_nombre = serializers.CharField(write_only=True, required=False)
    persona_apellido = serializers.CharField(write_only=True, required=False)
    persona_cedula = serializers.CharField(write_only=True, required=False)
    persona_telefono = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    persona_direccion = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )

    # Otros campos
    roles = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    read_roles = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "username",
            "correo_electronico",
            "password",
            "is_active",
            "is_staff",
            "persona_asociada",  # Para leer (SerializerMethodField)
            # Campos individuales para escribir
            "persona_nombre",
            "persona_apellido",
            "persona_cedula",
            "persona_telefono",
            "persona_direccion",
            "roles",
            "eliminado",
            "read_roles",
            "tiene_persona",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        extra_kwargs = {
            "tiene_persona": {"read_only": True},
        }

    def get_persona_asociada(self, obj):
        """Devolver datos completos de la persona para lectura"""
        try:
            if obj.persona_asociada:
                return PersonaSerializer(obj.persona_asociada).data
        except Usuario.persona_asociada.RelatedObjectDoesNotExist:
            return None  # Retorna null si no hay persona asociada
        return None

    def get_read_roles(self, obj):
        return [RolSerializer(ur.rol).data for ur in obj.roles.filter(activo=True)]

    def validate_persona_cedula(self, value):
        """Validar unicidad de cédula considerando la instancia actual"""
        logger.info(f"Validando cédula: {value}")

        if not value:
            return value

        qs = Persona.objects.filter(cedula=value)

        # Si estamos actualizando y el usuario tiene persona, excluirla
        if self.instance and self.instance.tiene_persona:
            qs = qs.exclude(pk=self.instance.persona_asociada.pk)
            logger.info(
                f"Excluyendo persona actual ID: {self.instance.persona_asociada.pk}"
            )

        if qs.exists():
            logger.error(f"Ya existe persona con cédula: {value}")
            raise serializers.ValidationError("Ya existe una persona con esta cédula.")

        logger.info("✓ Cédula válida")
        return value

    def create(self, validated_data):
        logger.info("=== INICIO create ===")

        # Extraer datos de persona
        persona_data = {}
        for field in [
            "persona_nombre",
            "persona_apellido",
            "persona_cedula",
            "persona_telefono",
            "persona_direccion",
        ]:
            if field in validated_data:
                persona_field = field.replace("persona_", "")
                persona_data[persona_field] = validated_data.pop(field)

        password = validated_data.pop("password")
        roles_ids = validated_data.pop("roles", [])

        # Crear usuario
        usuario = Usuario.objects.create_user(**validated_data)
        usuario.set_password(password)
        usuario.save()

        # Crear persona si hay datos
        if persona_data:
            persona = Persona.objects.create(**persona_data)
            usuario.asociar_persona(persona)
            logger.info("✓ Persona creada y asociada")

        # Asignar roles
        for rol_id in roles_ids:
            try:
                rol = Rol.objects.get(id=rol_id)
                UsuarioRol.objects.get_or_create(
                    usuario=usuario, rol=rol, defaults={"activo": True}
                )
            except Rol.DoesNotExist:
                raise serializers.ValidationError(f"Rol con ID {rol_id} no encontrado.")

        logger.info("=== FIN create ===")
        return usuario

    def update(self, instance, validated_data):
        logger.info(f"=== INICIO update usuario {instance.username} ===")

        # Extraer datos de persona
        persona_data = {}
        for field in [
            "persona_nombre",
            "persona_apellido",
            "persona_cedula",
            "persona_telefono",
            "persona_direccion",
        ]:
            if field in validated_data:
                persona_field = field.replace("persona_", "")
                persona_data[persona_field] = validated_data.pop(field)

        logger.info(f"Datos de persona extraídos: {persona_data}")

        password = validated_data.pop("password", None)
        roles_ids = validated_data.pop("roles", None)

        # Actualizar campos del usuario
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        logger.info("✓ Usuario base actualizado")

        # Manejar persona asociada
        if persona_data:
            if instance.tiene_persona:
                logger.info("Actualizando persona existente...")
                # Actualizar persona existente
                for attr, value in persona_data.items():
                    setattr(instance.persona_asociada, attr, value)
                instance.persona_asociada.save()
                logger.info("✓ Persona existente actualizada")
            else:
                logger.info("Creando nueva persona...")
                # Crear nueva persona
                persona = Persona.objects.create(**persona_data)
                instance.asociar_persona(persona)
                logger.info("✓ Nueva persona creada y asociada")

        # Actualizar roles
        if roles_ids is not None:
            logger.info(f"Actualizando roles: {roles_ids}")
            current_roles_ids = set(
                instance.roles.filter(activo=True).values_list("rol_id", flat=True)
            )
            new_roles_ids = set(roles_ids)

            # Roles a añadir
            roles_to_add = new_roles_ids - current_roles_ids
            for rol_id in roles_to_add:
                try:
                    rol = Rol.objects.get(id=rol_id)
                    usuario_rol, created = UsuarioRol.objects.get_or_create(
                        usuario=instance, rol=rol
                    )
                    if not created:
                        usuario_rol.activo = True
                        usuario_rol.save()
                except Rol.DoesNotExist:
                    raise serializers.ValidationError(
                        f"Rol con ID {rol_id} no encontrado."
                    )

            # Roles a remover (desactivar)
            roles_to_remove = current_roles_ids - new_roles_ids
            for rol_id in roles_to_remove:
                try:
                    usuario_rol = UsuarioRol.objects.get(
                        usuario=instance, rol_id=rol_id
                    )
                    usuario_rol.activo = False
                    usuario_rol.save()
                except UsuarioRol.DoesNotExist:
                    pass

            logger.info("✓ Roles actualizados")

        logger.info("=== FIN update ===")
        return instance


class UsuarioMeSerializer(BaseModelSerializer):
    """Serializer para el usuario actual (perfil)"""

    persona = PersonaSerializer(source="persona_asociada", read_only=True)
    roles = serializers.SerializerMethodField()
    tiene_persona = serializers.BooleanField(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "username",
            "correo_electronico",
            "is_active",
            "persona",
            "roles",
            "tiene_persona",
            "last_login",
            "date_joined",
        ]

    def get_roles(self, obj):
        return [ur.rol.nombre for ur in obj.roles.filter(activo=True)]


# =======================================
# CATEGORIA SERIALIZERS
# =======================================
class CategoriaSerializer(BaseModelSerializer):
    """Serializer para Categorías de Productos"""

    productos_count = serializers.SerializerMethodField()

    class Meta:
        model = Categoria
        fields = [
            "id",
            "nombre",
            "descripcion",
            "activo",
            "productos_count",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_productos_count(self, obj):
        return obj.producto_set.filter(activo=True, eliminado=False).count()


class CategoriaServicioSerializer(BaseModelSerializer):
    """Serializer para Categorías de Servicios"""

    servicios_count = serializers.SerializerMethodField()

    class Meta:
        model = CategoriaServicio
        fields = [
            "id",
            "nombre",
            "descripcion",
            "activo",
            "servicios_count",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_servicios_count(self, obj):
        return obj.servicio_set.filter(activo=True, eliminado=False).count()


# =======================================
# PROVEEDOR SERIALIZERS
# =======================================
class ProveedorSerializer(BaseModelSerializer):
    """Serializer para Proveedores"""

    productos_count = serializers.SerializerMethodField()

    class Meta:
        model = Proveedor
        fields = [
            "id",
            "nombre",
            "nit",
            "telefono",
            "correo",
            "direccion",
            "contacto_principal",
            "activo",
            "eliminado",
            "productos_count",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_productos_count(self, obj):
        return obj.producto_set.filter(eliminado=False).count()

    def validate_nit(self, value):
        """Validar unicidad del NIT"""
        if not value:
            return value

        if self.instance and self.instance.nit == value:
            return value

        if Proveedor.objects.filter(nit=value).exists():
            raise serializers.ValidationError("Ya existe un proveedor con este NIT")
        return value


# =======================================
# PRODUCTO SERIALIZERS
# =======================================
class ProductoSerializer(BaseModelSerializer):
    """Serializer para Productos con inventario anidado"""

    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    imagen_url = serializers.SerializerMethodField()

    # Campos para inventario inicial (solo en creación)
    stock_inicial = serializers.IntegerField(
        write_only=True, required=False, default=0, min_value=0
    )
    stock_minimo = serializers.IntegerField(
        write_only=True, required=False, default=0, min_value=0
    )

    # Campos de lectura para mostrar información del inventario
    stock_actual = serializers.SerializerMethodField(read_only=True)
    inventario_stock_minimo = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Producto
        fields = [
            "id",
            "nombre",
            "codigo",
            "descripcion",
            "categoria",
            "proveedor",
            "categoria_nombre",
            "proveedor_nombre",
            "precio_compra",
            "precio_venta",
            "activo",
            "destacado",
            "imagen",
            "imagen_url",
            "stock_inicial",
            "stock_minimo",
            "stock_actual",
            "inventario_stock_minimo",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_imagen_url(self, obj):
        if obj.imagen:
            return obj.imagen.url
        return None

    def get_stock_actual(self, obj):
        """Obtener stock actual del inventario"""
        try:
            return obj.inventario.stock_actual
        except:
            return 0

    def get_inventario_stock_minimo(self, obj):
        """Obtener stock mínimo del inventario"""
        try:
            return obj.inventario.stock_minimo
        except:
            return 0

    def validate_codigo(self, value):
        """Validar unicidad del código"""
        if self.instance and self.instance.codigo == value:
            return value

        if Producto.objects.filter(codigo=value).exists():
            raise serializers.ValidationError("Ya existe un producto con este código")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Validar precios
        if "precio_compra" in attrs and "precio_venta" in attrs:
            if attrs["precio_venta"] <= attrs["precio_compra"]:
                raise serializers.ValidationError(
                    {
                        "precio_venta": "El precio de venta debe ser mayor al precio de compra"
                    }
                )

        # Validar stock inicial
        if "stock_inicial" in attrs and attrs["stock_inicial"] < 0:
            raise serializers.ValidationError(
                {"stock_inicial": "El stock inicial no puede ser negativo"}
            )

        return attrs


class ProductoPublicoSerializer(BaseModelSerializer):
    """Serializer público para Productos (catálogo)"""

    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    imagen_url = serializers.SerializerMethodField()
    stock_actual = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "id",
            "nombre",
            "descripcion",
            "categoria_nombre",
            "precio_venta",
            "destacado",
            "imagen_url",
            "stock_actual",
        ]

    def get_imagen_url(self, obj):
        if obj.imagen:
            return obj.imagen.url
        return None

    def get_stock_actual(self, obj):
        """Obtener stock actual del inventario"""
        try:
            return obj.inventario.stock_actual
        except:
            return 0


# =======================================
# SERVICIO SERIALIZERS
# =======================================
class ServicioSerializer(BaseModelSerializer):
    """Serializer para Servicios"""

    categoria_servicio_nombre = serializers.CharField(
        source="categoria_servicio.nombre", read_only=True
    )

    class Meta:
        model = Servicio
        fields = [
            "id",
            "nombre",
            "descripcion",
            "categoria_servicio",
            "categoria_servicio_nombre",
            "precio",
            "duracion_estimada",
            "activo",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def validate_precio(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio debe ser mayor a 0")
        return value

    def validate_duracion_estimada(self, value):
        if value <= 0:
            raise serializers.ValidationError("La duración debe ser mayor a 0 minutos")
        return value


# =======================================
# VEHICULO SERIALIZERS
# =======================================
class MotoSerializer(BaseModelSerializer):
    """Serializer para Motos"""

    propietario = PersonaSerializer(read_only=True)

    propietario_id = serializers.PrimaryKeyRelatedField(
        queryset=Persona.objects.all(), source="propietario", write_only=True
    )

    propietario_nombre = serializers.SerializerMethodField(read_only=True)
    propietario_cedula = serializers.SerializerMethodField(read_only=True)

    registrado_por_nombre = serializers.CharField(
        source="registrado_por.username", read_only=True
    )

    class Meta:
        model = Moto
        fields = [
            "id",
            "propietario",
            "propietario_id",
            "propietario_nombre",
            "propietario_cedula",
            "marca",
            "modelo",
            "año",
            "placa",
            "numero_chasis",
            "numero_motor",
            "color",
            "cilindrada",
            "kilometraje",
            "activo",
            "eliminado",
            "registrado_por",
            "registrado_por_nombre",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        extra_kwargs = {"propietario": {"required": False}}

    def validate_placa(self, value):
        """Validar unicidad de placa"""
        if self.instance and self.instance.placa == value:
            return value

        if Moto.objects.filter(placa=value).exists():
            raise serializers.ValidationError("Ya existe una moto con esta placa")
        return value

    def validate_numero_chasis(self, value):
        """Validar unicidad de número de chasis"""
        if self.instance and self.instance.numero_chasis == value:
            return value

        if Moto.objects.filter(numero_chasis=value).exists():
            raise serializers.ValidationError(
                "Ya existe una moto con este número de chasis"
            )
        return value

    def validate_numero_motor(self, value):
        """Validar unicidad de número de motor"""
        if self.instance and self.instance.numero_motor == value:
            return value

        if Moto.objects.filter(numero_motor=value).exists():
            raise serializers.ValidationError(
                "Ya existe una moto con este número de motor"
            )
        return value

    def get_propietario_nombre(self, obj):
        """Obtener nombre del propietario de forma segura"""
        if obj.propietario:
            return obj.propietario.nombre_completo
        return "Sin propietario asignado"

    def get_propietario_cedula(self, obj):
        """Obtener cédula del propietario de forma segura"""
        if obj.propietario:
            return obj.propietario.cedula
        return None

    def validate_año(self, value):
        current_year = timezone.now().year
        if value < 1900 or value > current_year + 1:
            raise serializers.ValidationError(
                f"El año debe estar entre 1900 y {current_year + 1}"
            )
        return value


# =======================================
# MANTENIMIENTO SERIALIZERS
# =======================================
class DetalleMantenimientoSerializer(BaseModelSerializer):
    """Serializer para Detalles de Mantenimiento"""

    servicio_nombre = serializers.CharField(source="servicio.nombre", read_only=True)

    class Meta:
        model = DetalleMantenimiento
        fields = [
            "id",
            "mantenimiento",
            "servicio",
            "servicio_nombre",
            "precio",
            "observaciones",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def validate_precio(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio debe ser mayor a 0")
        return value


class MantenimientoSerializer(BaseModelSerializer):
    """Serializer para Mantenimientos"""

    detalles = DetalleMantenimientoSerializer(many=True, read_only=True)
    moto_placa = serializers.CharField(source="moto.placa", read_only=True)
    propietario_nombre = serializers.CharField(
        source="moto.propietario.nombre_completo", read_only=True
    )
    tecnico_asignado_nombre = serializers.CharField(
        source="tecnico_asignado.username", read_only=True
    )

    class Meta:
        model = Mantenimiento
        fields = [
            "id",
            "moto",
            "moto_placa",
            "propietario_nombre",
            "tecnico_asignado",
            "tecnico_asignado_nombre",
            "fecha_ingreso",
            "fecha_entrega",
            "descripcion_problema",
            "diagnostico",
            "estado",
            "kilometraje_ingreso",
            "total",
            "eliminado",
            "detalles",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def validate_kilometraje_ingreso(self, value):
        if value < 0:
            raise serializers.ValidationError("El kilometraje no puede ser negativo")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Validar fechas
        if "fecha_ingreso" in attrs and "fecha_entrega" in attrs:
            if (
                attrs["fecha_entrega"]
                and attrs["fecha_entrega"] <= attrs["fecha_ingreso"]
            ):
                raise serializers.ValidationError(
                    {
                        "fecha_entrega": "La fecha de entrega debe ser posterior a la fecha de ingreso"
                    }
                )

        return attrs


class RecordatorioMantenimientoSerializer(BaseModelSerializer):
    """Serializer para Recordatorios de Mantenimiento"""

    moto_placa = serializers.CharField(source="moto.placa", read_only=True)
    categoria_servicio_nombre = serializers.CharField(
        source="categoria_servicio.nombre", read_only=True
    )
    es_proximo = serializers.SerializerMethodField()

    class Meta:
        model = RecordatorioMantenimiento
        fields = [
            "id",
            "moto",
            "moto_placa",
            "categoria_servicio",
            "categoria_servicio_nombre",
            "fecha_programada",
            "enviado",
            "es_proximo",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_es_proximo(self, obj):
        return obj.proximo()


class RepuestoMantenimientoSerializer(serializers.ModelSerializer):
    # Mostrar información del producto
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_codigo = serializers.CharField(source="producto.codigo", read_only=True)

    class Meta:
        model = RepuestoMantenimiento
        fields = [
            "id",
            "mantenimiento",
            "producto",
            "producto_nombre",
            "producto_codigo",
            "cantidad",
            "precio_unitario",
            "subtotal",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        read_only_fields = ["subtotal", "fecha_registro", "fecha_actualizacion"]

    def validate(self, data):
        """Validar stock del producto antes de usarlo en mantenimiento"""
        producto = data.get("producto")
        cantidad = data.get("cantidad")
        if producto and cantidad:
            if producto.stock_actual < cantidad:
                raise serializers.ValidationError(
                    {
                        "cantidad": f"Stock insuficiente. Disponible: {producto.stock_actual}"
                    }
                )
        return data

    def create(self, validated_data):
        """Descontar stock al usar repuesto"""
        producto = validated_data["producto"]
        cantidad = validated_data["cantidad"]

        # Descontar stock
        producto.stock_actual -= cantidad
        producto.save(update_fields=["stock_actual"])

        return super().create(validated_data)


# =======================================
# VENTA SERIALIZERS
# =======================================
class DetalleVentaSerializer(serializers.ModelSerializer):
    """Serializer para Detalles de Venta"""

    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_imagen = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DetalleVenta
        fields = [
            "id",
            "venta",
            "producto",
            "producto_nombre",
            "producto_imagen",
            "cantidad",
            "precio_unitario",
            "subtotal",
        ]

    def get_producto_imagen(self, obj):
        """Obtener URL de la imagen del producto"""
        if obj.producto and obj.producto.imagen:
            return obj.producto.imagen.url
        return None

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor a 0")
        return value

    def validate_precio_unitario(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio unitario debe ser mayor a 0")
        return value


class VentaSerializer(serializers.ModelSerializer):
    """Serializer para Ventas"""

    detalles = DetalleVentaSerializer(many=True, read_only=True)
    cliente_nombre = serializers.CharField(
        source="cliente.nombre_completo", read_only=True
    )
    cliente_apellido = serializers.CharField(source="cliente.apellido", read_only=True)
    cliente_cedula = serializers.CharField(source="cliente.cedula", read_only=True)
    registrado_por_nombre = serializers.SerializerMethodField(read_only=True)
    pagado = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    saldo = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = Venta
        fields = [
            "id",
            "cliente",
            "cliente_nombre",
            "cliente_apellido",
            "cliente_cedula",
            "fecha_venta",
            "subtotal",
            "impuesto",
            "total",
            "estado",
            "eliminado",
            "registrado_por",
            "registrado_por_nombre",
            "pagado",
            "saldo",
            "detalles",
            "pagos",
        ]
        read_only_fields = ["fecha_venta", "pagado", "saldo"]

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Validar montos
        if "subtotal" in attrs and attrs["subtotal"] < 0:
            raise serializers.ValidationError(
                {"subtotal": "El subtotal no puede ser negativo"}
            )

        if "impuesto" in attrs and attrs["impuesto"] < 0:
            raise serializers.ValidationError(
                {"impuesto": "El impuesto no puede ser negativo"}
            )

        if "total" in attrs and attrs["total"] < 0:
            raise serializers.ValidationError(
                {"total": "El total no puede ser negativo"}
            )

        return attrs

    def get_registrado_por_nombre(self, obj):
        """Obtener nombre completo del usuario que registró la venta"""
        if obj.registrado_por:
            # Intentar obtener el nombre desde la persona asociada
            try:
                if (
                    hasattr(obj.registrado_por, "persona_asociada")
                    and obj.registrado_por.persona_asociada
                ):
                    return obj.registrado_por.persona_asociada.nombre_completo
            except:
                pass

            # Intentar obtener desde la relación inversa persona
            try:
                persona = obj.registrado_por.persona
                if persona:
                    return persona.nombre_completo
            except:
                pass

            # Fallback al correo electrónico
            return obj.registrado_por.correo_electronico
        return None

    def create(self, validated_data):
        """Crear venta y asignar usuario registrador"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["registrado_por"] = request.user
        return super().create(validated_data)


class VentaPOSSerializer(serializers.ModelSerializer):
    """Serializer específico para ventas desde POS"""

    items = serializers.ListField(write_only=True)
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    metodo_pago = serializers.CharField(max_length=20, default="efectivo")

    class Meta:
        model = Venta
        fields = ["cliente_id", "subtotal", "impuesto", "total", "items", "metodo_pago"]

    def validate_items(self, items):
        if not items or len(items) == 0:
            raise serializers.ValidationError("Debe incluir al menos un producto")

        for item in items:
            required_fields = ["producto_id", "cantidad", "precio_unitario", "subtotal"]
            for field in required_fields:
                if field not in item:
                    raise serializers.ValidationError(
                        f"Campo {field} requerido en items"
                    )

        return items


class ProductoPOSSerializer(serializers.ModelSerializer):
    """Serializer optimizado para búsquedas en POS"""

    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    disponible = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "id",
            "nombre",
            "codigo",
            "precio_venta",
            "categoria_nombre",
            "disponible",
        ]

    def get_disponible(self, obj):
        # Check if product has inventory record
        if hasattr(obj, "inventario"):
            return obj.inventario.stock_actual > 0
        return False


# =======================================
# PAGO SERIALIZERS
# =======================================
class PagoSerializer(serializers.ModelSerializer):
    """Serializer para Pagos"""

    venta_id = serializers.IntegerField(source="venta.id", read_only=True)
    cliente_nombre = serializers.CharField(
        source="venta.cliente.nombre_completo", read_only=True
    )
    registrado_por_nombre = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Pago
        fields = [
            "id",
            "venta",
            "venta_id",
            "cliente_nombre",
            "fecha_pago",
            "metodo",
            "monto",
            "registrado_por",
            "registrado_por_nombre",
        ]
        read_only_fields = ["registrado_por", "fecha_pago"]

    def validate_monto(self, value):
        """Validar que el monto sea positivo"""
        if value <= 0:
            raise serializers.ValidationError("El monto debe ser mayor a 0")
        return value

    def validate(self, attrs):
        """Validaciones adicionales"""
        attrs = super().validate(attrs)

        venta = attrs.get("venta")
        monto = attrs.get("monto")

        if venta and monto:
            # Verificar que el pago no exceda el saldo pendiente
            saldo_pendiente = venta.saldo
            if monto > saldo_pendiente:
                raise serializers.ValidationError(
                    {
                        "monto": f"El monto no puede exceder el saldo pendiente de Bs. {saldo_pendiente:.2f}"
                    }
                )

        return attrs

    def get_registrado_por_nombre(self, obj):
        """Obtener nombre completo del usuario que registró el pago"""
        if obj.registrado_por:
            # Intentar obtener el nombre desde la persona asociada
            try:
                if (
                    hasattr(obj.registrado_por, "persona_asociada")
                    and obj.registrado_por.persona_asociada
                ):
                    return obj.registrado_por.persona_asociada.nombre_completo
            except:
                pass

            # Intentar obtener desde la relación inversa persona
            try:
                persona = obj.registrado_por.persona
                if persona:
                    return persona.nombre_completo
            except:
                pass

            # Fallback al correo electrónico
            return obj.registrado_por.correo_electronico
        return None

    def create(self, validated_data):
        """Crear pago y actualizar estado de la venta si es necesario"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["registrado_por"] = request.user

        pago = super().create(validated_data)

        # Actualizar estado de la venta si está completamente pagada
        venta = pago.venta
        if venta.saldo <= 0:
            venta.estado = "PAGADA"
            venta.save(update_fields=["estado"])

        return pago


# Now add pagos field to VentaSerializer after PagoSerializer is defined
VentaSerializer._declared_fields["pagos"] = PagoSerializer(many=True, read_only=True)
VentaSerializer.Meta.fields.append("pagos")


# =======================================
# INVENTARIO SERIALIZERS
# =======================================
class InventarioSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.SerializerMethodField(read_only=True)
    producto_codigo = serializers.SerializerMethodField(read_only=True)
    stock_actual = serializers.IntegerField(required=True, min_value=0)
    stock_minimo = serializers.IntegerField(required=True, min_value=0)

    def get_producto_nombre(self, obj):
        return obj.producto.nombre if obj.producto else "Producto no disponible"

    def get_producto_codigo(self, obj):
        return obj.producto.codigo if obj.producto else "N/A"

    class Meta:
        model = Inventario
        fields = [
            "id",
            "producto",
            "producto_nombre",
            "producto_codigo",
            "stock_actual",
            "stock_minimo",
            "activo",
            "eliminado",
        ]
        read_only_fields = ["producto"]

    def validate_stock_actual(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError(
                "El stock actual debe ser un número no negativo"
            )
        return value

    def validate_stock_minimo(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError(
                "El stock mínimo debe ser un número no negativo"
            )
        return value

    def validate(self, data):
        # Validar que stock_actual no sea menor que 0
        if "stock_actual" in data and data["stock_actual"] < 0:
            raise serializers.ValidationError(
                {"stock_actual": "El stock actual no puede ser negativo"}
            )

        # Validar que stock_minimo no sea menor que 0
        if "stock_minimo" in data and data["stock_minimo"] < 0:
            raise serializers.ValidationError(
                {"stock_minimo": "El stock mínimo no puede ser negativo"}
            )

        return data


class InventarioMovimientoSerializer(serializers.ModelSerializer):
    usuario_nombre = serializers.CharField(
        source="usuario.correo_electronico", read_only=True
    )
    producto_nombre = serializers.CharField(
        source="inventario.producto.nombre", read_only=True
    )
    producto_codigo = serializers.CharField(
        source="inventario.producto.codigo", read_only=True
    )

    class Meta:
        model = InventarioMovimiento
        fields = [
            "id",
            "inventario",
            "producto_nombre",
            "producto_codigo",
            "tipo",
            "cantidad",
            "motivo",
            "usuario",
            "usuario_nombre",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        read_only_fields = ["usuario"]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["usuario"] = request.user
        return super().create(validated_data)


# =======================================
# RECORDATORIO SERIALIZERS
# =======================================
class RecordatorioMantenimientoSerializer(serializers.ModelSerializer):
    # Campos de lectura con información anidada
    moto = MotoSerializer(read_only=True)
    categoria_servicio = CategoriaServicioSerializer(read_only=True)

    # Campos de escritura con IDs
    moto_id = serializers.IntegerField(write_only=True)
    categoria_servicio_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = RecordatorioMantenimiento
        fields = [
            "id",
            "moto",
            "categoria_servicio",
            "moto_id",
            "categoria_servicio_id",
            "fecha_programada",
            "enviado",
            "activo",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        read_only_fields = ["id", "eliminado", "fecha_registro", "fecha_actualizacion"]

    def create(self, validated_data):
        # Extraer IDs y mapear a campos de modelo
        moto_id = validated_data.pop("moto_id")
        categoria_servicio_id = validated_data.pop("categoria_servicio_id")

        # Excluir campos que no pertenecen al modelo
        validated_data.pop("usuario", None)  # Remover usuario si existe

        # Obtener instancias
        moto = Moto.objects.get(id=moto_id)
        categoria_servicio = CategoriaServicio.objects.get(id=categoria_servicio_id)

        # Crear recordatorio
        recordatorio = RecordatorioMantenimiento.objects.create(
            moto=moto, categoria_servicio=categoria_servicio, **validated_data
        )

        return recordatorio

    def update(self, instance, validated_data):
        # Extraer IDs si están presentes
        moto_id = validated_data.pop("moto_id", None)
        categoria_servicio_id = validated_data.pop("categoria_servicio_id", None)

        # Actualizar relaciones si se proporcionaron IDs
        if moto_id is not None:
            instance.moto = Moto.objects.get(id=moto_id)
        if categoria_servicio_id is not None:
            instance.categoria_servicio = CategoriaServicio.objects.get(
                id=categoria_servicio_id
            )

        # Actualizar otros campos
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
