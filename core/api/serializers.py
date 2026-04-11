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
        import logging

        logger = logging.getLogger(__name__)

        correo = attrs.get("correo_electronico", "").lower().strip()
        password = attrs.get("password")

        if not correo or not password:
            raise serializers.ValidationError(
                "Correo electrónico y contraseña son requeridos"
            )

        # First check if user exists
        try:
            user = Usuario.objects.get(correo_electronico=correo)
        except Usuario.DoesNotExist:
            raise serializers.ValidationError("Usuario no existe")

        # Then check password
        password_check = user.check_password(password)

        if not password_check:
            raise serializers.ValidationError("Credenciales erroneas")

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
        import logging

        logger = logging.getLogger(__name__)

        correo = attrs.get("correo_electronico", "").lower().strip()
        password = attrs.get("password")

        if not correo or not password:
            raise serializers.ValidationError(
                "Correo electrónico y contraseña son requeridos"
            )

        # First check if user exists
        try:
            user = Usuario.objects.get(correo_electronico=correo)
        except Usuario.DoesNotExist:
            raise serializers.ValidationError("Usuario no existe")

        # Then check password
        password_check = user.check_password(password)

        if not password_check:
            raise serializers.ValidationError("Credenciales erroneas")

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
    # Campos de auditoría
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

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
            # Campos de auditoría
            "creado_por",
            "actualizado_por",
            "eliminado_por",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
        ]

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            # Obtener nombre completo si tiene persona asociada
            nombre_completo = None
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                nombre_completo = user.persona_asociada.nombre_completo
            return {
                "id": user.id,
                "nombre": nombre_completo or user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            # Obtener nombre completo si tiene persona asociada
            nombre_completo = None
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                nombre_completo = user.persona_asociada.nombre_completo
            return {
                "id": user.id,
                "nombre": nombre_completo or user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            # Obtener nombre completo si tiene persona asociada
            nombre_completo = None
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                nombre_completo = user.persona_asociada.nombre_completo
            return {
                "id": user.id,
                "nombre": nombre_completo or user.username,
                "correo": user.correo_electronico,
            }
        return None

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

    # Campo para vincular a una persona existente
    persona_id = serializers.IntegerField(write_only=True, required=False)

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
            "persona_id",  # Para vincular a persona existente
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

    def validate_username(self, value):
        """Validar unicidad del username"""
        if not value:
            return value

        # Si es actualización y el username no cambió, permitir
        if self.instance and self.instance.username == value:
            return value

        if Usuario.objects.filter(username=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este nombre de usuario."
            )

        return value

    def validate_correo_electronico(self, value):
        """Validar unicidad del correo electrónico"""
        if not value:
            return value

        # Si es actualización y el correo no cambió, permitir
        if self.instance and self.instance.correo_electronico == value:
            return value

        if Usuario.objects.filter(correo_electronico=value).exists():
            raise serializers.ValidationError(
                "Ya existe un usuario con este correo electrónico."
            )

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

        # Extraer persona_id para vincular a persona existente
        persona_id = validated_data.pop("persona_id", None)

        password = validated_data.pop("password")
        roles_ids = validated_data.pop("roles", [])

        # Crear usuario
        usuario = Usuario.objects.create_user(**validated_data)
        usuario.set_password(password)
        usuario.save()

        # Manejar persona asociada
        if persona_id:
            # Vincular a persona existente
            try:
                persona = Persona.objects.get(id=persona_id)
                usuario.asociar_persona(persona)
                logger.info(f"✓ Persona ID {persona_id} vinculada al usuario")
            except Persona.DoesNotExist:
                logger.warning(f"Persona ID {persona_id} no encontrada")
        elif persona_data:
            # Crear nueva persona si hay datos
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

    # Campos de auditoría (Trazabilidad)
    creado_por_nombre = serializers.SerializerMethodField(read_only=True)
    actualizado_por_nombre = serializers.SerializerMethodField(read_only=True)
    eliminado_por_nombre = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Categoria
        fields = [
            "id",
            "nombre",
            "descripcion",
            "activo",
            "eliminado",
            "productos_count",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
            "creado_por",
            "creado_por_nombre",
            "actualizado_por",
            "actualizado_por_nombre",
            "eliminado_por",
            "eliminado_por_nombre",
        ]

    def get_productos_count(self, obj):
        return obj.producto_set.filter(activo=True, eliminado=False).count()

    def get_creado_por_nombre(self, obj):
        if obj.creado_por:
            if hasattr(obj.creado_por, "persona") and obj.creado_por.persona:
                return (
                    f"{obj.creado_por.persona.nombre} {obj.creado_por.persona.apellido}"
                )
            return obj.creado_por.username
        return None

    def get_actualizado_por_nombre(self, obj):
        if obj.actualizado_por:
            if hasattr(obj.actualizado_por, "persona") and obj.actualizado_por.persona:
                return f"{obj.actualizado_por.persona.nombre} {obj.actualizado_por.persona.apellido}"
            return obj.actualizado_por.username
        return None

    def get_eliminado_por_nombre(self, obj):
        if obj.eliminado_por:
            if hasattr(obj.eliminado_por, "persona") and obj.eliminado_por.persona:
                return f"{obj.eliminado_por.persona.nombre} {obj.eliminado_por.persona.apellido}"
            return obj.eliminado_por.username
        return None


class CategoriaServicioSerializer(BaseModelSerializer):
    """Serializer para Categorías de Servicios"""

    servicios_count = serializers.SerializerMethodField()

    # Campos de auditoría (Trazabilidad)
    creado_por_nombre = serializers.SerializerMethodField(read_only=True)
    actualizado_por_nombre = serializers.SerializerMethodField(read_only=True)
    eliminado_por_nombre = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CategoriaServicio
        fields = [
            "id",
            "nombre",
            "descripcion",
            "activo",
            "eliminado",
            "servicios_count",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
            "creado_por",
            "creado_por_nombre",
            "actualizado_por",
            "actualizado_por_nombre",
            "eliminado_por",
            "eliminado_por_nombre",
        ]

    def get_servicios_count(self, obj):
        return obj.servicio_set.filter(activo=True, eliminado=False).count()

    def get_creado_por_nombre(self, obj):
        if obj.creado_por:
            if hasattr(obj.creado_por, "persona") and obj.creado_por.persona:
                return (
                    f"{obj.creado_por.persona.nombre} {obj.creado_por.persona.apellido}"
                )
            return obj.creado_por.username
        return None

    def get_actualizado_por_nombre(self, obj):
        if obj.actualizado_por:
            if hasattr(obj.actualizado_por, "persona") and obj.actualizado_por.persona:
                return f"{obj.actualizado_por.persona.nombre} {obj.actualizado_por.persona.apellido}"
            return obj.actualizado_por.username
        return None

    def get_eliminado_por_nombre(self, obj):
        if obj.eliminado_por:
            if hasattr(obj.eliminado_por, "persona") and obj.eliminado_por.persona:
                return f"{obj.eliminado_por.persona.nombre} {obj.eliminado_por.persona.apellido}"
            return obj.eliminado_por.username
        return None


# =======================================
# PROVEEDOR SERIALIZERS
# =======================================
class ProveedorSerializer(BaseModelSerializer):
    """Serializer para Proveedores"""

    productos_count = serializers.SerializerMethodField()

    # Campos de auditoría (Trazabilidad)
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

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
            "fecha_eliminacion",
            "creado_por",
            "actualizado_por",
            "eliminado_por",
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

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "username": user.username,
                    "nombre_completo": user.persona_asociada.nombre_completo,
                }
            return {
                "id": user.id,
                "username": user.username,
                "nombre_completo": user.username,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "username": user.username,
                    "nombre_completo": user.persona_asociada.nombre_completo,
                }
            return {
                "id": user.id,
                "username": user.username,
                "nombre_completo": user.username,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "username": user.username,
                    "nombre_completo": user.persona_asociada.nombre_completo,
                }
            return {
                "id": user.id,
                "username": user.username,
                "nombre_completo": user.username,
            }
        return None


# =======================================
# PRODUCTO SERIALIZERS
# =======================================
class ProductoSerializer(BaseModelSerializer):
    """Serializer para Productos con inventario anidado"""

    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    proveedor_nombre = serializers.CharField(source="proveedor.nombre", read_only=True)
    imagen_url = serializers.SerializerMethodField()

    # Campos de auditoría
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

    # Campos para inventario inicial (solo en creación)
    stock_inicial = serializers.IntegerField(
        write_only=True, required=False, default=0, min_value=0
    )

    # Ahora stock_minimo es un campo del modelo, pero mantenemos para compatibilidad
    stock_minimo = serializers.IntegerField(
        write_only=True, required=False, default=0, min_value=0
    )

    # Campos de lectura para mostrar información del inventario
    inventario_stock = serializers.SerializerMethodField(read_only=True)
    inventario_stock_minimo = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Producto
        fields = [
            "id",
            "nombre",
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
            "inventario_stock",
            "inventario_stock_minimo",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
            "creado_por",
            "actualizado_por",
            "eliminado_por",
        ]

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_imagen_url(self, obj):
        if obj.imagen:
            return obj.imagen.url
        return None

    def get_inventario_stock(self, obj):
        """Obtener stock actual del inventario"""
        try:
            return obj.inventario.stock_actual
        except Inventario.DoesNotExist:
            return 0

    def get_inventario_stock_minimo(self, obj):
        """Obtener stock mínimo del inventario"""
        try:
            return obj.inventario.stock_minimo
        except Inventario.DoesNotExist:
            return 0

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

    categoria = serializers.PrimaryKeyRelatedField(read_only=True)
    categoria_nombre = serializers.CharField(source="categoria.nombre", read_only=True)
    imagen_url = serializers.SerializerMethodField()
    stock_actual = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            "id",
            "nombre",
            "descripcion",
            "categoria",
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
        except Inventario.DoesNotExist:
            return 0


# =======================================
# SERVICIO SERIALIZERS
# =======================================
class ServicioSerializer(BaseModelSerializer):
    """Serializer para Servicios"""

    categoria_servicio_nombre = serializers.CharField(
        source="categoria_servicio.nombre", read_only=True
    )

    # Campos de auditoría
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

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
            "fecha_eliminacion",
            "creado_por",
            "actualizado_por",
            "eliminado_por",
        ]

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

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

    # Campos de auditoría
    creado_por_nombre = serializers.SerializerMethodField(read_only=True)
    actualizado_por_nombre = serializers.SerializerMethodField(read_only=True)
    eliminado_por_nombre = serializers.SerializerMethodField(read_only=True)

    def get_creado_por_nombre(self, obj):
        if obj.creado_por:
            if hasattr(obj.creado_por, "persona") and obj.creado_por.persona:
                return (
                    f"{obj.creado_por.persona.nombre} {obj.creado_por.persona.apellido}"
                )
            return obj.creado_por.username
        return None

    def get_actualizado_por_nombre(self, obj):
        if obj.actualizado_por:
            if hasattr(obj.actualizado_por, "persona") and obj.actualizado_por.persona:
                return f"{obj.actualizado_por.persona.nombre} {obj.actualizado_por.persona.apellido}"
            return obj.actualizado_por.username
        return None

    def get_eliminado_por_nombre(self, obj):
        if obj.eliminado_por:
            if hasattr(obj.eliminado_por, "persona") and obj.eliminado_por.persona:
                return f"{obj.eliminado_por.persona.nombre} {obj.eliminado_por.persona.apellido}"
            return obj.eliminado_por.username
        return None

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
            "fecha_eliminacion",
            "creado_por",
            "creado_por_nombre",
            "actualizado_por",
            "actualizado_por_nombre",
            "eliminado_por",
            "eliminado_por_nombre",
        ]
        extra_kwargs = {"propietario": {"required": False}}

    def to_internal_value(self, data):
        """Debug: mostrar datos recibidos en el serializer"""
        logger = logging.getLogger(__name__)
        logger.info(f"DEBUG MOTO SERIALIZER: data recibida = {data}")
        return super().to_internal_value(data)

    def validate(self, attrs):
        """Debug: mostrar datos validados"""
        logger = logging.getLogger(__name__)
        logger.info(f"DEBUG MOTO SERIALIZER: attrs validados = {attrs}")
        return super().validate(attrs)

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
    """
    Serializer para Detalles de Mantenimiento.

    Representa los servicios realizados en un mantenimiento.
    """

    servicio_nombre = serializers.SerializerMethodField()
    categoria_servicio = serializers.SerializerMethodField()
    es_cambio_aceite = serializers.SerializerMethodField()

    class Meta:
        model = DetalleMantenimiento
        fields = [
            "id",
            "mantenimiento",
            "servicio",
            "servicio_nombre",
            "categoria_servicio",
            "precio",
            "observaciones",
            "tipo_aceite",
            "km_proximo_cambio",
            "es_cambio_aceite",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
            # Agregar campo servicio completo para Flutter
            "servicio_data",
        ]

    def get_servicio_nombre(self, obj):
        """Obtener nombre del servicio, manejando casos nulos"""
        if hasattr(obj, "servicio") and obj.servicio:
            return obj.servicio.nombre
        return "Servicio eliminado"

    def get_categoria_servicio(self, obj):
        """Obtener categoría del servicio, manejando casos nulos"""
        if (
            hasattr(obj, "servicio")
            and obj.servicio
            and hasattr(obj.servicio, "categoria_servicio")
            and obj.servicio.categoria_servicio
        ):
            return obj.servicio.categoria_servicio.nombre
        return None

    def get_servicio(self, obj):
        """Retorna el objeto servicio completo para el frontend"""
        if hasattr(obj, "servicio") and obj.servicio:
            from .serializers import ServicioSerializer

            return ServicioSerializer(obj.servicio).data
        return None

    def get_es_cambio_aceite(self, obj):
        return obj.es_cambio_aceite()

    def validate_precio(self, value):
        if value <= 0:
            raise serializers.ValidationError("El precio debe ser mayor a 0")
        return value


class MantenimientoSerializer(BaseModelSerializer):
    """
    Serializer para Mantenimientos.

    Incluye todos los campos del modelo más campos calculados
    y validaciones específicas para el flujo de estados.
    """

    detalles = DetalleMantenimientoSerializer(many=True, read_only=True)
    # Usar string reference para evitar error de dependencia circular
    repuestos = serializers.SerializerMethodField()

    def get_repuestos(self, obj):
        from .serializers import RepuestoMantenimientoSerializer

        # Pasar el contexto de la request para generar URLs absolutas de imágenes
        context = self.context if hasattr(self, "context") else {}
        return RepuestoMantenimientoSerializer(
            obj.repuestos.all(), many=True, context=context
        ).data

    # Campos de información de la moto (para lectura)
    # Estos campos son de solo lectura porque el objeto moto se serializa completo
    moto_placa = serializers.CharField(source="moto.placa", read_only=True)
    moto_marca = serializers.CharField(source="moto.marca", read_only=True)
    moto_modelo = serializers.CharField(source="moto.modelo", read_only=True)
    moto_año = serializers.IntegerField(source="moto.año", read_only=True)
    moto_color = serializers.CharField(source="moto.color", read_only=True)
    moto_cilindrada = serializers.IntegerField(source="moto.cilindrada", read_only=True)
    propietario_nombre = serializers.CharField(
        source="moto.propietario.nombre_completo", read_only=True
    )
    propietario_cedula = serializers.CharField(
        source="moto.propietario.cedula", read_only=True
    )

    # Include full moto object with propietario for frontend (read & write)
    moto = serializers.PrimaryKeyRelatedField(
        queryset=Moto.objects.all(),
        required=True,
        help_text="ID de la moto o objeto moto",
    )
    # Campo para mostrar la moto completa (solo lectura)
    moto_data = serializers.SerializerMethodField()

    def get_moto_data(self, obj):
        """Retorna el objeto moto completo con propietario para el frontend"""
        if hasattr(obj, "moto") and obj.moto:
            # Evitar dependencia circular usando solo campos básicos
            return {
                "id": obj.moto.id,
                "placa": obj.moto.placa,
                "marca": obj.moto.marca,
                "modelo": obj.moto.modelo,
                "año": obj.moto.año,
                "color": obj.moto.color,
                "cilindrada": obj.moto.cilindrada,
                "kilometraje": obj.moto.kilometraje,
                "propietario": (
                    {
                        "id": obj.moto.propietario.id,
                        "nombre_completo": obj.moto.propietario.nombre_completo,
                        "cedula": obj.moto.propietario.cedula,
                        "telefono": obj.moto.propietario.telefono,
                    }
                    if hasattr(obj.moto, "propietario") and obj.moto.propietario
                    else None
                ),
            }
        return None

    tecnico_asignado_nombre = serializers.CharField(
        source="tecnico_asignado.username", read_only=True
    )
    tecnico_asignado_persona_nombre = serializers.SerializerMethodField(read_only=True)
    tecnico_asignado_cedula = serializers.SerializerMethodField(read_only=True)

    def get_tecnico_asignado_persona_nombre(self, obj):
        """Obtener el nombre completo del técnico asignado a través de su persona asociada"""
        if (
            obj.tecnico_asignado
            and hasattr(obj.tecnico_asignado, "persona_asociada")
            and obj.tecnico_asignado.persona_asociada
        ):
            return obj.tecnico_asignado.persona_asociada.nombre_completo
        return None

    def get_tecnico_asignado_cedula(self, obj):
        """Obtener la cédula del técnico asignado a través de su persona asociada"""
        if (
            obj.tecnico_asignado
            and hasattr(obj.tecnico_asignado, "persona_asociada")
            and obj.tecnico_asignado.persona_asociada
        ):
            return obj.tecnico_asignado.persona_asociada.cedula
        return None

    completado_por_nombre = serializers.CharField(
        source="completado_por.username", read_only=True
    )

    # Campos de auditoría (Trazabilidad)
    creado_por_nombre = serializers.SerializerMethodField(read_only=True)
    actualizado_por_nombre = serializers.SerializerMethodField(read_only=True)
    eliminado_por_nombre = serializers.SerializerMethodField(read_only=True)

    def get_creado_por_nombre(self, obj):
        """Obtener nombre del usuario que creó el mantenimiento"""
        if hasattr(obj, "creado_por") and obj.creado_por:
            # Primero buscar en persona_asociada
            if (
                hasattr(obj.creado_por, "persona_asociada")
                and obj.creado_por.persona_asociada
            ):
                return obj.creado_por.persona_asociada.nombre_completo
            # Luego buscar en persona
            if hasattr(obj.creado_por, "persona") and obj.creado_por.persona:
                return (
                    f"{obj.creado_por.persona.nombre} {obj.creado_por.persona.apellido}"
                )
            # Finalmente usar username
            return obj.creado_por.username
        return None

    def get_actualizado_por_nombre(self, obj):
        """Obtener nombre del usuario que actualizó el mantenimiento"""
        if hasattr(obj, "actualizado_por") and obj.actualizado_por:
            # Primero buscar en persona_asociada
            if (
                hasattr(obj.actualizado_por, "persona_asociada")
                and obj.actualizado_por.persona_asociada
            ):
                return obj.actualizado_por.persona_asociada.nombre_completo
            # Luego buscar en persona
            if hasattr(obj.actualizado_por, "persona") and obj.actualizado_por.persona:
                return f"{obj.actualizado_por.persona.nombre} {obj.actualizado_por.persona.apellido}"
            # Finalmente usar username
            return obj.actualizado_por.username
        return None

    def get_eliminado_por_nombre(self, obj):
        """Obtener nombre del usuario que eliminó el mantenimiento"""
        if hasattr(obj, "eliminado_por") and obj.eliminado_por:
            # Primero buscar en persona_asociada
            if (
                hasattr(obj.eliminado_por, "persona_asociada")
                and obj.eliminado_por.persona_asociada
            ):
                return obj.eliminado_por.persona_asociada.nombre_completo
            # Luego buscar en persona
            if hasattr(obj.eliminado_por, "persona") and obj.eliminado_por.persona:
                return f"{obj.eliminado_por.persona.nombre} {obj.eliminado_por.persona.apellido}"
            # Finalmente usar username
            return obj.eliminado_por.username
        return None

    # Campos calculados
    servicios_count = serializers.SerializerMethodField()
    repuestos_count = serializers.SerializerMethodField()
    tiene_items = serializers.SerializerMethodField()
    puede_completarse = serializers.SerializerMethodField()

    # Campos para creación (usando ListField para datos anidados)
    servicios = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    repuestos_data = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    recordatorio = serializers.DictField(required=False, write_only=True)

    # Kilometraje de salida (para actualizar al completar)
    kilometraje_salida = serializers.IntegerField(required=False, write_only=True)

    class Meta:
        model = Mantenimiento
        fields = [
            "id",
            "moto",
            "moto_data",
            "moto_placa",
            "moto_marca",
            "moto_modelo",
            "moto_año",
            "moto_color",
            "moto_cilindrada",
            "propietario_nombre",
            "propietario_cedula",
            "tecnico_asignado",
            "tecnico_asignado_nombre",
            "tecnico_asignado_persona_nombre",
            "tecnico_asignado_cedula",
            "fecha_ingreso",
            "fecha_entrega",
            "descripcion_problema",
            "diagnostico",
            "estado",
            "tipo",
            "prioridad",
            "kilometraje_ingreso",
            "kilometraje_salida",
            "costo_adicional",
            "total",
            "completado_por",
            "completado_por_nombre",
            "fecha_completado",
            "eliminado",
            "eliminado_por",
            "eliminado_por_nombre",
            "fecha_eliminacion",
            "detalles",
            "repuestos",
            "servicios_count",
            "repuestos_count",
            "tiene_items",
            "puede_completarse",
            # Campos para creación
            "servicios",
            "repuestos_data",
            "recordatorio",
            # Campos de auditoría
            "fecha_registro",
            "fecha_actualizacion",
            "creado_por",
            "creado_por_nombre",
            "actualizado_por",
            "actualizado_por_nombre",
        ]
        read_only_fields = [
            "moto_placa",
            "moto_marca",
            "moto_modelo",
            "moto_año",
            "moto_color",
            "moto_cilindrada",
            "propietario_nombre",
            "propietario_cedula",
            "total",
            "completado_por",
            "fecha_completado",
            "servicios_count",
            "repuestos_count",
            "tiene_items",
            "puede_completarse",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_servicios_count(self, obj):
        return obj.detalles.count()

    def get_repuestos_count(self, obj):
        return obj.repuestos.count()

    def get_tiene_items(self, obj):
        return obj.tiene_items()

    def get_puede_completarse(self, obj):
        return obj.puede_completarse()

    def validate_kilometraje_ingreso(self, value):
        if value is None:
            return value
        if value < 0:
            raise serializers.ValidationError("El kilometraje no puede ser negativo")
        return value

    def validate_estado(self, value):
        """Valida que el estado sea válido"""
        estados_validos = [choice[0] for choice in Mantenimiento.ESTADO_CHOICES]
        if value not in estados_validos:
            raise serializers.ValidationError(
                f"Estado inválido. Estados válidos: {estados_validos}"
            )
        return value

    def validate_tipo(self, value):
        """Valida que el tipo sea válido"""
        tipos_validos = [choice[0] for choice in Mantenimiento.TIPO_CHOICES]
        if value not in tipos_validos:
            raise serializers.ValidationError(
                f"Tipo inválido. Tipos válidos: {tipos_validos}"
            )
        return value

    def validate_prioridad(self, value):
        """Valida que la prioridad sea válida"""
        prioridades_validas = [choice[0] for choice in Mantenimiento.PRIORIDAD_CHOICES]
        if value not in prioridades_validas:
            raise serializers.ValidationError(
                f"Prioridad inválida. Prioridades válidas: {prioridades_validas}"
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)

        # Validar que la moto esté presente en creación
        if not self.instance and not attrs.get("moto"):
            raise serializers.ValidationError({"moto": "Debes seleccionar una moto"})

        # Validar fechas - solo si ambas están presentes
        if "fecha_ingreso" in attrs and attrs.get("fecha_entrega"):
            if attrs["fecha_entrega"] <= attrs["fecha_ingreso"]:
                raise serializers.ValidationError(
                    {
                        "fecha_entrega": "La fecha de entrega debe ser posterior a la fecha de ingreso"
                    }
                )

        # Validar kilometraje vs moto actual - solo en create o si se envía el objeto moto
        km_ingreso = attrs.get("kilometraje_ingreso")
        moto = attrs.get("moto")

        # Solo validar kilometraje si es un create (no instance) o si tenemos el objeto moto completo
        if not self.instance and moto and km_ingreso is not None:
            # Es un create - podemos validar normalmente
            if hasattr(moto, "kilometraje"):
                km_actual = moto.kilometraje or 0
                if km_ingreso < km_actual:
                    raise serializers.ValidationError(
                        {
                            "kilometraje_ingreso": f"El kilometraje de ingreso ({km_ingreso}) "
                            f"no puede ser menor al kilometraje actual de la moto ({km_actual})"
                        }
                    )
        elif self.instance and moto and km_ingreso is not None:
            # Es un update - usar la moto de la instancia si el moto enviado es solo un ID
            if hasattr(moto, "kilometraje"):
                # El moto enviado es un objeto completo
                km_actual = moto.kilometraje or 0
                if km_ingreso < km_actual:
                    raise serializers.ValidationError(
                        {
                            "kilometraje_ingreso": f"El kilometraje de ingreso ({km_ingreso}) "
                            f"no puede ser menor al kilometraje actual de la moto ({km_actual})"
                        }
                    )
            else:
                # El moto enviado es un ID - usar la moto de la instancia
                if hasattr(self.instance.moto, "kilometraje"):
                    km_actual = self.instance.moto.kilometraje or 0
                    if km_ingreso < km_actual:
                        raise serializers.ValidationError(
                            {
                                "kilometraje_ingreso": f"El kilometraje de ingreso ({km_ingreso}) "
                                f"no puede ser menor al kilometraje actual de la moto ({km_actual})"
                            }
                        )

        # Validar transición de estado si es update
        if self.instance and "estado" in attrs:
            nuevo_estado = attrs["estado"]
            if nuevo_estado and self.instance.estado != nuevo_estado:
                if not self.instance.puede_cambiar_a(nuevo_estado):
                    raise serializers.ValidationError(
                        {
                            "estado": f"No se puede cambiar de '{self.instance.estado}' a '{nuevo_estado}'. "
                            f"Flujo válido: pendiente → en_proceso → completado"
                        }
                    )

        # Validar que tenga items si intenta completar
        if self.instance and attrs.get("estado") == "completado":
            if not self.instance.tiene_items():
                raise serializers.ValidationError(
                    {
                        "estado": "No se puede completar un mantenimiento sin servicios ni repuestos"
                    }
                )

        return attrs

    def create(self, validated_data):
        # Extract servicios, repuestos, recordatorio from validated_data
        servicios_data = validated_data.pop("servicios", [])
        repuestos_data = validated_data.pop("repuestos_data", [])
        recordatorio_data = validated_data.pop("recordatorio", None)
        kilometraje_salida = validated_data.pop("kilometraje_salida", None)

        # Create Mantenimiento instance
        instance = super().create(validated_data)

        # Guardar kilometraje de salida si se proporciona
        if kilometraje_salida:
            instance.kilometraje_salida = kilometraje_salida

        # Create detalles from servicios
        from decimal import Decimal

        for servicio_data in servicios_data:
            # Support both 'servicio' and 'servicio_id' keys
            servicio_id = (
                servicio_data.get("servicio")
                or servicio_data.get("servicio_id")
                or servicio_data.get("id")
            )
            if not servicio_id:
                logger.warning(f"Servicio sin ID encontrado en datos: {servicio_data}")
                continue

            precio = Decimal(str(servicio_data.get("precio", 0)))
            tipo_aceite = servicio_data.get("tipo_aceite")
            km_proximo_cambio = servicio_data.get("km_proximo_cambio")
            observaciones = servicio_data.get("observaciones", "")

            # Get the servicio object
            from core.models import Servicio

            try:
                servicio_obj = Servicio.objects.get(id=servicio_id)
            except Servicio.DoesNotExist:
                continue

            # Create detalle
            DetalleMantenimiento.objects.create(
                mantenimiento=instance,
                servicio=servicio_obj,
                precio=precio,
                observaciones=observaciones,
                tipo_aceite=tipo_aceite,
                km_proximo_cambio=km_proximo_cambio,
            )

        # Create repuestos
        for repuesto_data in repuestos_data:
            from core.services import MantenimientoService

            try:
                MantenimientoService.agregar_repuesto(
                    instance,
                    repuesto_data,
                    validar_stock=False,  # Permitir crear aunque haya problemas de stock
                )
            except Exception as e:
                logger.warning(f"Error al agregar repuesto: {e}")

        # Calcular total automáticamente
        instance.calcular_total()

        # Create recordatorio if provided
        if recordatorio_data:
            from core.models import (
                RecordatorioMantenimiento,
                CategoriaServicio,
                Servicio,
            )

            # Get categoria_servicio ID from recordatorio_data or determine from servicios
            categoria_servicio_id = recordatorio_data.get("categoria_servicio")
            categoria_servicio = None

            if categoria_servicio_id:
                # Buscar por ID si se proporciona
                try:
                    categoria_servicio = CategoriaServicio.objects.get(
                        id=categoria_servicio_id
                    )
                except CategoriaServicio.DoesNotExist:
                    categoria_servicio = None
            else:
                # 自动获取第一个服务的类别（当用户选择"cambio de aceite"时）
                for servicio_data in servicios_data:
                    servicio_id = (
                        servicio_data.get("servicio")
                        or servicio_data.get("servicio_id")
                        or servicio_data.get("id")
                    )
                    if servicio_id:
                        try:
                            servicio_obj = Servicio.objects.get(id=servicio_id)
                            categoria_servicio = servicio_obj.categoria_servicio
                            break  # Usar la primera categoría encontrada
                        except Servicio.DoesNotExist:
                            continue

            # Solo crear recordatorio si tenemos la categoría de servicio
            if categoria_servicio:
                RecordatorioMantenimiento.objects.create(
                    moto=instance.moto,
                    categoria_servicio=categoria_servicio,
                    tipo=recordatorio_data.get("tipo", "km"),
                    km_proximo=recordatorio_data.get("km_proximo"),
                    fecha_programada=recordatorio_data.get("fecha_programada"),
                )

        return instance

    def update(self, instance, validated_data):
        # Extraer datos especiales
        kilometraje_salida = validated_data.pop("kilometraje_salida", None)
        nuevo_estado = validated_data.get("estado")

        # Extraer servicios y repuestos si se proporcionan
        servicios_data = validated_data.pop("servicios", [])
        repuestos_data = validated_data.pop("repuestos_data", [])
        recordatorio_data = validated_data.pop("recordatorio", None)

        # Guardar estado anterior
        estado_anterior = instance.estado

        # Actualizar instancia
        instance = super().update(instance, validated_data)

        # Procesar servicios si se proporcionan
        if servicios_data:
            from core.models import Servicio, DetalleMantenimiento
            from decimal import Decimal

            # Eliminar servicios existentes
            instance.detalles.all().delete()

            for servicio_data in servicios_data:
                servicio_id = (
                    servicio_data.get("servicio")
                    or servicio_data.get("servicio_id")
                    or servicio_data.get("id")
                )
                if not servicio_id:
                    continue

                precio = Decimal(str(servicio_data.get("precio", 0)))
                tipo_aceite = servicio_data.get("tipo_aceite")
                km_proximo_cambio = servicio_data.get("km_proximo_cambio")
                observaciones = servicio_data.get("observaciones", "")

                try:
                    servicio_obj = Servicio.objects.get(id=servicio_id)
                    DetalleMantenimiento.objects.create(
                        mantenimiento=instance,
                        servicio=servicio_obj,
                        precio=precio,
                        observaciones=observaciones,
                        tipo_aceite=tipo_aceite,
                        km_proximo_cambio=km_proximo_cambio,
                    )
                except Servicio.DoesNotExist:
                    pass

        # Procesar repuestos si se proporcionan
        if repuestos_data:
            from core.services import MantenimientoService

            # Eliminar repuestos existentes
            instance.repuestos.all().delete()

            for repuesto_data in repuestos_data:
                try:
                    MantenimientoService.agregar_repuesto(
                        instance,
                        repuesto_data,
                        validar_stock=False,
                    )
                except Exception as e:
                    logger.warning(f"Error al agregar repuesto: {e}")

        # Recalcular total
        instance.calcular_total()

        # Si cambió a completado, actualizar kilometraje de la moto
        if nuevo_estado == "completado" and estado_anterior != "completado":
            instance.fecha_completado = timezone.now()
            if self.context.get("request"):
                instance.completado_por = self.context["request"].user

            if kilometraje_salida:
                instance.kilometraje_salida = kilometraje_salida
                instance.moto.kilometraje = kilometraje_salida
                instance.moto.save(update_fields=["kilometraje"])

            instance.save(
                update_fields=[
                    "fecha_completado",
                    "completado_por",
                    "kilometraje_salida",
                ]
            )

        return instance

    def _calculate_total(self, mantenimiento, detalles_data):
        """Calculate total from servicios and repuestos"""
        from decimal import Decimal

        total = Decimal("0.00")

        # Add from detalles (servicios)
        for detalle_data in detalles_data:
            precio = detalle_data.get("precio", Decimal("0.00"))
            total += precio

        # Add from repuestos if any
        for detalle in mantenimiento.detalles.all():
            for repuesto in detalle.repuestos.all():
                total += repuesto.subtotal

        return total


class RecordatorioMantenimientoSerializer(BaseModelSerializer):
    """
    Serializer para Recordatorios de Mantenimiento.

    Gestiona los recordatorios de mantenimiento programados
    por kilometraje o fecha.
    """

    moto_placa = serializers.CharField(source="moto.placa", read_only=True)
    moto_marca = serializers.CharField(source="moto.marca", read_only=True)
    moto_modelo = serializers.CharField(source="moto.modelo", read_only=True)
    categoria_servicio_nombre = serializers.CharField(
        source="categoria_servicio.nombre", read_only=True
    )
    info_proximo = serializers.SerializerMethodField()
    esta_vencido = serializers.SerializerMethodField()

    class Meta:
        model = RecordatorioMantenimiento
        fields = [
            "id",
            "moto",
            "moto_placa",
            "moto_marca",
            "moto_modelo",
            "categoria_servicio",
            "categoria_servicio_nombre",
            "tipo",
            "fecha_programada",
            "km_proximo",
            "enviado",
            "activo",
            "notas",
            "info_proximo",
            "esta_vencido",
            "registrado_por",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_info_proximo(self, obj):
        return obj.proximo()

    def get_esta_vencido(self, obj):
        return obj.esta_vencido()


class RepuestoMantenimientoSerializer(serializers.ModelSerializer):
    """
    Serializer para Repuestos de Mantenimiento.

    Gestiona el uso de repuestos en un mantenimiento,
    incluyendo control de stock.
    """

    # Mostrar información del producto
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_imagen = serializers.SerializerMethodField()
    stock_disponible = serializers.SerializerMethodField()
    tiene_stock_suficiente = serializers.SerializerMethodField()

    class Meta:
        model = RepuestoMantenimiento
        fields = [
            "id",
            "mantenimiento",
            "producto",
            "producto_nombre",
            "producto_imagen",
            "cantidad",
            "precio_unitario",
            "subtotal",
            "permitir_sin_stock",
            "stock_disponible",
            "tiene_stock_suficiente",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
        ]
        read_only_fields = [
            "subtotal",
            "stock_disponible",
            "tiene_stock_suficiente",
            "fecha_registro",
            "fecha_actualizacion",
        ]

    def get_producto_imagen(self, obj):
        """Obtener la URL de la imagen del producto"""
        if obj.producto and obj.producto.imagen:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.producto.imagen.url)
            return obj.producto.imagen.url
        return None

    def get_stock_disponible(self, obj):
        try:
            return obj.producto.inventario.stock_actual
        except (Inventario.DoesNotExist, AttributeError):
            return 0

    def get_tiene_stock_suficiente(self, obj):
        return obj.tiene_stock_suficiente()

    def validate(self, data):
        """Validar stock del producto antes de usarlo en mantenimiento"""
        producto = data.get("producto")
        cantidad = data.get("cantidad", 1)
        permitir_sin_stock = data.get("permitir_sin_stock", False)

        if producto and cantidad:
            # Verificar stock disponible
            try:
                inventario = producto.inventario
                stock_disponible = inventario.stock_actual
            except Inventario.DoesNotExist:
                stock_disponible = 0

            # Validar solo si no se permite usar sin stock
            if not permitir_sin_stock and stock_disponible < cantidad:
                raise serializers.ValidationError(
                    {
                        "cantidad": f"Stock insuficiente. Disponible: {stock_disponible}, "
                        f"Solicitado: {cantidad}. "
                        f"Use permitir_sin_stock=True para forzar el uso."
                    }
                )
        return data


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
    creado_por_nombre = serializers.SerializerMethodField(read_only=True)
    actualizado_por_nombre = serializers.SerializerMethodField(read_only=True)
    eliminado_por_nombre = serializers.SerializerMethodField(read_only=True)
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
            "descuento",
            "impuesto",
            "total",
            "notas",
            "estado",
            "eliminado",
            "creado_por",
            "creado_por_nombre",
            "registrado_por",
            "registrado_por_nombre",
            "actualizado_por",
            "actualizado_por_nombre",
            "eliminado_por",
            "eliminado_por_nombre",
            "fecha_eliminacion",
            "fecha_registro",
            "fecha_actualizacion",
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

    def get_creado_por_nombre(self, obj):
        """Obtener nombre completo del usuario que creó la venta"""
        if obj.creado_por:
            # Intentar obtener el nombre desde la persona asociada
            try:
                if (
                    hasattr(obj.creado_por, "persona_asociada")
                    and obj.creado_por.persona_asociada
                ):
                    return obj.creado_por.persona_asociada.nombre_completo
            except:
                pass

            # Intentar obtener desde la relación inversa persona
            try:
                persona = obj.creado_por.persona
                if persona:
                    return persona.nombre_completo
            except:
                pass

            # Fallback al correo electrónico
            return obj.creado_por.correo_electronico
        return None

    def get_actualizado_por_nombre(self, obj):
        """Obtener nombre completo del usuario que actualizó la venta"""
        if obj.actualizado_por:
            try:
                if (
                    hasattr(obj.actualizado_por, "persona_asociada")
                    and obj.actualizado_por.persona_asociada
                ):
                    return obj.actualizado_por.persona_asociada.nombre_completo
            except:
                pass

            try:
                persona = obj.actualizado_por.persona
                if persona:
                    return persona.nombre_completo
            except:
                pass

            return obj.actualizado_por.correo_electronico
        return None

    def get_eliminado_por_nombre(self, obj):
        """Obtener nombre completo del usuario que eliminó la venta"""
        if obj.eliminado_por:
            try:
                if (
                    hasattr(obj.eliminado_por, "persona_asociada")
                    and obj.eliminado_por.persona_asociada
                ):
                    return obj.eliminado_por.persona_asociada.nombre_completo
            except:
                pass

            try:
                persona = obj.eliminado_por.persona
                if persona:
                    return persona.nombre_completo
            except:
                pass

            return obj.eliminado_por.correo_electronico
        return None

    def create(self, validated_data):
        """Crear venta y asignar usuario registrador"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            validated_data["registrado_por"] = request.user
            validated_data["creado_por"] = request.user
        return super().create(validated_data)


class VentaPOSSerializer(serializers.ModelSerializer):
    """Serializer específico para ventas desde POS"""

    items = serializers.ListField(write_only=True, required=False)
    productos = serializers.ListField(write_only=True, required=False)
    cliente_id = serializers.IntegerField(required=False, allow_null=True)
    metodo_pago = serializers.CharField(max_length=20, default="efectivo")
    descuento = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, default=Decimal("0.00")
    )
    notas = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    class Meta:
        model = Venta
        fields = [
            "cliente_id",
            "subtotal",
            "descuento",
            "impuesto",
            "total",
            "notas",
            "items",
            "productos",
            "metodo_pago",
        ]

    def validate(self, attrs):
        # Aceptar tanto "items" como "productos" del frontend
        items = attrs.get("items")
        productos = attrs.get("productos")

        if not items and not productos:
            raise serializers.ValidationError("Debe incluir al menos un producto")

        # Unir las listas si existen ambas
        final_items = items or []
        if productos:
            final_items = productos

        if not final_items or len(final_items) == 0:
            raise serializers.ValidationError("Debe incluir al menos un producto")

        for item in final_items:
            # Aceptar tanto "producto_id" como "id" como identificador del producto
            has_producto = "producto_id" in item or "id" in item
            if not has_producto:
                raise serializers.ValidationError(
                    f"Campo producto_id o id requerido en items"
                )

            required_fields = ["cantidad", "precio_unitario", "subtotal"]
            for field in required_fields:
                if field not in item:
                    raise serializers.ValidationError(
                        f"Campo {field} requerido en items"
                    )

        # Guardar los items normalizados
        attrs["items"] = final_items
        if "productos" in attrs:
            del attrs["productos"]

        return attrs

    def validate_items(self, items):
        if not items or len(items) == 0:
            raise serializers.ValidationError("Debe incluir al menos un producto")

        for item in items:
            # Aceptar tanto "producto_id" como "id" como identificador del producto
            has_producto = "producto_id" in item or "id" in item
            if not has_producto:
                raise serializers.ValidationError(
                    f"Campo producto_id o id requerido en items"
                )

            required_fields = ["cantidad", "precio_unitario", "subtotal"]
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
    producto_imagen = serializers.SerializerMethodField(read_only=True)
    stock_actual = serializers.IntegerField(required=True, min_value=0)
    stock_minimo = serializers.IntegerField(required=True, min_value=0)

    # Campos de auditoría
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

    def get_producto_nombre(self, obj):
        return obj.producto.nombre if obj.producto else "Producto no disponible"

    def get_producto_imagen(self, obj):
        if obj.producto and obj.producto.imagen:
            return obj.producto.imagen.url
        return None

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    class Meta:
        model = Inventario
        fields = [
            "id",
            "producto",
            "producto_nombre",
            "producto_imagen",
            "stock_actual",
            "stock_minimo",
            "activo",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
            "creado_por",
            "actualizado_por",
            "eliminado_por",
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

    # Campos de auditoría
    creado_por = serializers.SerializerMethodField(read_only=True)
    actualizado_por = serializers.SerializerMethodField(read_only=True)
    eliminado_por = serializers.SerializerMethodField(read_only=True)

    def get_creado_por(self, obj):
        if obj.creado_por:
            user = obj.creado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_actualizado_por(self, obj):
        if obj.actualizado_por:
            user = obj.actualizado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    def get_eliminado_por(self, obj):
        if obj.eliminado_por:
            user = obj.eliminado_por
            if hasattr(user, "persona_asociada") and user.persona_asociada:
                return {
                    "id": user.id,
                    "nombre": user.persona_asociada.nombre_completo,
                    "correo": user.correo_electronico,
                }
            return {
                "id": user.id,
                "nombre": user.username,
                "correo": user.correo_electronico,
            }
        return None

    class Meta:
        model = InventarioMovimiento
        fields = [
            "id",
            "inventario",
            "producto_nombre",
            "tipo",
            "cantidad",
            "motivo",
            "usuario",
            "usuario_nombre",
            "eliminado",
            "fecha_registro",
            "fecha_actualizacion",
            "fecha_eliminacion",
            "creado_por",
            "actualizado_por",
            "eliminado_por",
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
            "tipo",
            "fecha_programada",
            "km_proximo",
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


# =======================================
# LOTES - INVENTARIO POR LOTES (FIFO)
# =======================================
class LoteSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source="producto.nombre", read_only=True)
    producto_categoria = serializers.CharField(source="producto.categoria.nombre", read_only=True)

    class Meta:
        model = Lote
        fields = [
            "id",
            "producto",
            "producto_nombre",
            "producto_categoria",
            "cantidad_disponible",
            "precio_compra",
            "fecha_ingreso",
            "activo",
        ]
        read_only_fields = ["fecha_ingreso"]

    def validate_cantidad_disponible(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("La cantidad debe ser mayor o igual a 0")
        return value

    def validate_precio_compra(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("El precio de compra debe ser mayor o igual a 0")
        return value


class LoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lote
        fields = [
            "producto",
            "cantidad_disponible",
            "precio_compra",
            "activo",
        ]

    def create(self, validated_data):
        lote = super().create(validated_data)
        lote.actualizar_stock_inventario()
        return lote

    def update(self, instance, validated_data):
        old_cantidad = instance.cantidad_disponible
        instance = super().update(instance, validated_data)
        instance.actualizar_stock_inventario()
        return instance


# =======================================
# VENTAS - PRECIOS ESPECIALES POR CLIENTE
# =======================================
