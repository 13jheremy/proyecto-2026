from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from decimal import Decimal
from django.core.validators import MinValueValidator
from django.contrib.auth.models import Group, Permission
from cloudinary.models import CloudinaryField
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db.models import JSONField


# =======================================
# BASE CLASSES
# =======================================
class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(eliminado=False)


class SoftDeleteModel(models.Model):
    eliminado = models.BooleanField(default=False)
    eliminado_por = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_eliminados",
        editable=False,
        help_text="Usuario que eliminó este registro",
    )
    fecha_eliminacion = models.DateTimeField(null=True, blank=True, editable=False)
    objects = SoftDeleteManager()
    objects_all = models.Manager()  # acceso a todos (incluyendo eliminados)

    def delete(self, *args, **kwargs):
        """Soft delete por defecto"""
        # Obtener el usuario que está realizando la eliminación
        from django.db import connection

        user_id = None
        try:
            # Intentar obtener el usuario del request actual
            from django.utils import timezone
            from django.contrib.auth import get_user_model

            User = get_user_model()
            # Buscar en el connection.queries el usuario o en el stack
            if hasattr(self, "_current_user") and self._current_user:
                user_id = self._current_user.id
        except Exception:
            pass

        self.eliminado = True
        self.fecha_eliminacion = timezone.now()
        if user_id:
            try:
                self.eliminado_por_id = user_id
            except Exception:
                pass
        self.save(update_fields=["eliminado", "eliminado_por", "fecha_eliminacion"])

    class Meta:
        abstract = True


class TimestampedModel(SoftDeleteModel):
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_creados",
        editable=False,
        help_text="Usuario que creó este registro",
    )
    actualizado_por = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_actualizados",
        editable=False,
        help_text="Usuario que realizó la última actualización",
    )

    class Meta:
        abstract = True


# =======================================
# USUARIO MANAGER
# =======================================
class UsuarioManager(BaseUserManager):
    def create_user(self, correo_electronico, password=None, **extra_fields):
        if not correo_electronico:
            raise ValueError("El correo electrónico es obligatorio")
        correo_electronico = self.normalize_email(correo_electronico)
        user = self.model(correo_electronico=correo_electronico, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, correo_electronico, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields.get("is_staff"):
            raise ValueError("El superusuario debe tener is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("El superusuario debe tener is_superuser=True.")
        return self.create_user(correo_electronico, password, **extra_fields)


# =======================================
# PERSONA
# =======================================
class Persona(TimestampedModel):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    cedula = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20, blank=True)
    direccion = models.TextField(blank=True)

    usuario = models.OneToOneField(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="persona_asociada",  # Nombre de relación inversa
        help_text="Usuario asociado a esta persona (opcional)",
    )

    class Meta:
        db_table = "persona"
        verbose_name = "Persona"
        verbose_name_plural = "Personas"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"

    @property
    def tiene_usuario(self):
        return self.usuario is not None

    def clean(self):
        """Validación personalizada"""
        super().clean()
        # Validar que la cédula no esté duplicada (excepto para la misma instancia)
        if self.cedula:
            qs = Persona.objects.filter(cedula=self.cedula)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"cedula": "Ya existe una persona con esta cédula."}
                )

    def save(self, *args, **kwargs):
        """Sobrescribir save para ejecutar full_clean"""
        self.full_clean()
        super().save(*args, **kwargs)


# =======================================
# USUARIO
# =======================================
class Usuario(AbstractUser, TimestampedModel):
    correo_electronico = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    fcm_token = models.TextField(
        blank=True, null=True, help_text="Token FCM para notificaciones push"
    )
    # Campos para protección de login
    failed_login_attempts = models.PositiveIntegerField(
        default=0, help_text="Número de intentos de login fallidos"
    )
    last_failed_login = models.DateTimeField(
        blank=True, null=True, help_text="Último intento de login fallido"
    )

    groups = models.ManyToManyField(Group, related_name="usuario_set", blank=True)
    user_permissions = models.ManyToManyField(
        Permission, related_name="usuario_permissions_set", blank=True
    )

    USERNAME_FIELD = "correo_electronico"
    REQUIRED_FIELDS = ["username"]

    objects = UsuarioManager()  # Asignar el manager personalizado

    class Meta:
        db_table = "usuario"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return self.correo_electronico

    @property
    def tiene_persona(self):
        return hasattr(self, "persona_asociada") and self.persona_asociada is not None

    @property
    def persona(self):
        return getattr(self, "persona_asociada", None)

    def asociar_persona(self, persona):
        """Asociar una persona a este usuario"""
        if persona.usuario is not None and persona.usuario != self:
            raise ValueError("Esta persona ya está asociada a otro usuario")

        # Si el usuario ya tiene una persona asociada, desasociarla primero
        if self.tiene_persona:
            self.desasociar_persona()

        persona.usuario = self
        persona.save(update_fields=["usuario"])
        return persona

    def desasociar_persona(self):
        """Desasociar la persona actual del usuario"""
        if self.tiene_persona:
            persona = self.persona_asociada
            persona.usuario = None
            persona.save(update_fields=["usuario"])
            return persona
        return None


class Rol(TimestampedModel):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)

    class Meta:
        db_table = "rol"
        verbose_name = "Rol"
        verbose_name_plural = "Roles"

    def __str__(self):
        return self.nombre


class UsuarioRol(TimestampedModel):
    usuario = models.ForeignKey(
        Usuario, on_delete=models.CASCADE, related_name="roles"
    )  # related_name para acceso inverso
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "usuario_rol"
        unique_together = ("usuario", "rol")
        verbose_name = "Usuario Rol"
        verbose_name_plural = "Usuario Roles"

    def __str__(self):
        return f"{self.usuario.username} - {self.rol.nombre}"


# =======================================
# CATEGORÍAS
# =======================================
class Categoria(TimestampedModel):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "categoria"
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"

    def __str__(self):
        return self.nombre


class CategoriaServicio(TimestampedModel):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "categoria_servicio"
        verbose_name = "Categoría de Servicio"
        verbose_name_plural = "Categorías de Servicios"

    def __str__(self):
        return self.nombre


# =======================================
# PROVEEDORES
# =======================================
class Proveedor(TimestampedModel):
    nombre = models.CharField(max_length=200)
    nombre_normalizado = models.CharField(max_length=200, unique=True, blank=True, editable=False)
    nit = models.CharField(max_length=50, unique=True, null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True)
    correo = models.EmailField(blank=True)
    direccion = models.TextField(blank=True)
    contacto_principal = models.CharField(max_length=100, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "proveedor"
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        if self.nombre:
            normalized = self.normalizar_nombre(self.nombre)
            existing = Proveedor.objects.filter(nombre_normalizado=normalized)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({'nombre': 'Ya existe un proveedor con ese nombre.'})

    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre_normalizado = self.normalizar_nombre(self.nombre)
        super().save(*args, **kwargs)

    @staticmethod
    def normalizar_nombre(texto):
        if not texto:
            return ''
        return ' '.join(texto.strip().lower().split())


# =======================================
# PRODUCTOS
# =======================================
class Producto(TimestampedModel):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    proveedor = models.ForeignKey(
        Proveedor, on_delete=models.CASCADE, blank=True, null=True
    )
    precio_compra = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    precio_venta = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    activo = models.BooleanField(default=True)
    destacado = models.BooleanField(default=False)
    imagen = CloudinaryField("imagen", blank=True, null=True)

    class Meta:
        db_table = "producto"
        verbose_name = "Producto"
        verbose_name_plural = "Productos"

    def __str__(self):
        return self.nombre

    def stock_total(self):
        from django.db.models import Sum
        result = self.lotes.aggregate(total=Sum('cantidad_disponible'))
        return result['total'] or 0


# =======================================
# LOTES (Inventario por lotes - FIFO)
# =======================================
class Lote(TimestampedModel):
    producto = models.ForeignKey(
        Producto, 
        on_delete=models.CASCADE, 
        related_name="lotes"
    )
    cantidad_disponible = models.PositiveIntegerField(default=0)
    precio_compra = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal("0.00"))]
    )
    fecha_ingreso = models.DateTimeField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "lote"
        verbose_name = "Lote"
        verbose_name_plural = "Lotes"
        ordering = ['fecha_ingreso']

    def __str__(self):
        return f"Lote {self.id} - {self.producto.nombre} - {self.cantidad_disponible} unidades"

    def actualizar_stock_inventario(self):
        try:
            inventario = self.producto.inventario
            inventario.save()
        except Inventario.DoesNotExist:
            pass

    def save(self, *args, **kwargs):
        """
        Validación para prevenir ediciones inappropriately del lote.
        
        REGLAS:
        - CREAR nuevo lote: Para nuevas compras (siempre permitido)
        - EDITAR lote: Solo para correcciones (error de digitación)
        - NO permitido editar para simular nuevas compras
        
        El sistema prioriza la trazabilidad: cada cambio real = nuevo lote
        """
        from django.utils import timezone
        
        # Si es un lote existente y se está editando
        if self.pk:
            self_updated = Lote.objects_all.filter(pk=self.pk).first()
            if self_updated:
                # Verificar si cambió quantity_disponible o precio_compra (这两种 = nueva compra)
                # Solo permitir edición si es corrección menor
                if (self.cantidad_disponible != self_updated.cantidad_disponible or 
                    self.precio_compra != self_updated.precio_compra):
                    # Verificar que no esté trying to add stock incorrectly
                    # Permitido solo si decrease (corrección de error)
                    if self.cantidad_disponible > self_updated.cantidad_disponible:
                        # Trying to add stock via edit = NO PERMITIDO
                        raise ValueError(
                            "No puedes agregar stock editando un lote existente. "
                            "Para nuevas compras, CREA un nuevo lote. "
                            "El sistema prioriza la trazabilidad: cada cambio real = nuevo lote."
                        )
        
        super().save(*args, **kwargs)
        
        # Actualizar inventario
        self.actualizar_stock_inventario()

    @classmethod
    def consumir_fifo(cls, producto, cantidad_a_vender):
        """
        Implementa FIFO - Primero en entrar, primero en salir.
        Descuenta la cantidad de los lotes más antiguos.
        Retorna el costo total calculado basándose en los lotes consumidos.
        """
        from django.db.models import Sum
        
        lotes = cls.objects.filter(
            producto=producto,
            activo=True,
            cantidad_disponible__gt=0
        ).order_by('fecha_ingreso')
        
        total_disponible = sum(l.cantidad_disponible for l in lotes)
        
        if total_disponible < cantidad_a_vender:
            raise ValueError(
                f"Stock insuficiente. Disponible: {total_disponible}, Solicitado: {cantidad_a_vender}"
            )
        
        cantidad_restante = cantidad_a_vender
        costo_total = Decimal("0.00")
        
        for lote in lotes:
            if cantidad_restante <= 0:
                break
            
            if lote.cantidad_disponible >= cantidad_restante:
                lote.cantidad_disponible -= cantidad_restante
                costo_total += lote.precio_compra * cantidad_restante
                cantidad_restante = 0
            else:
                cantidad_restante -= lote.cantidad_disponible
                costo_total += lote.precio_compra * lote.cantidad_disponible
                lote.cantidad_disponible = 0
            
            lote.save()
        
        producto.inventario.save()
        
        return costo_total


# =======================================
# SERVICIOS
# =======================================
class Servicio(TimestampedModel):
    nombre = models.CharField(max_length=200)
    nombre_normalizado = models.CharField(max_length=200, unique=True, blank=True, editable=False)
    descripcion = models.TextField(blank=True)
    categoria_servicio = models.ForeignKey(CategoriaServicio, on_delete=models.CASCADE)
    precio = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    duracion_estimada = models.PositiveIntegerField(help_text="Duración en minutos")
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "servicio"
        verbose_name = "Servicio"
        verbose_name_plural = "Servicios"

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        if self.nombre:
            normalized = self.normalizar_nombre(self.nombre)
            # Verificar duplicado excluyendo el registro actual
            existing = Servicio.objects.filter(nombre_normalizado=normalized)
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({'nombre': 'Ya existe un servicio con ese nombre.'})

    def save(self, *args, **kwargs):
        if self.nombre:
            self.nombre_normalizado = self.normalizar_nombre(self.nombre)
        super().save(*args, **kwargs)

    @staticmethod
    def normalizar_nombre(texto):
        if not texto:
            return ''
        return ' '.join(texto.strip().lower().split())


# =======================================
# MOTO
# =======================================
class Moto(TimestampedModel):
    propietario = models.ForeignKey(Persona, on_delete=models.CASCADE)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    año = models.PositiveIntegerField()
    placa = models.CharField(max_length=10, unique=True)
    numero_chasis = models.CharField(max_length=50, unique=True)
    numero_motor = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=30)
    cilindrada = models.PositiveIntegerField()
    kilometraje = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)
    registrado_por = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="motos_registradas",
        editable=False,
    )

    def save(self, *args, **kwargs):
        # Guardar usuario que está haciendo la acción
        if hasattr(self, "_current_user") and not self.registrado_por:
            self.registrado_por = self._current_user
        super().save(*args, **kwargs)


# =======================================
# MANTENIMIENTO
# =======================================
class Mantenimiento(TimestampedModel):
    # Estados del mantenimiento (flujo obligatorio: pendiente -> en_proceso -> completado)
    ESTADO_CHOICES = [
        ("pendiente", "Pendiente"),
        ("en_proceso", "En Proceso"),
        ("completado", "Completado"),
        ("cancelado", "Cancelado"),
    ]

    # Tipo de mantenimiento
    TIPO_CHOICES = [
        ("preventivo", "Preventivo"),
        ("correctivo", "Correctivo"),
    ]

    # Prioridad del mantenimiento
    PRIORIDAD_CHOICES = [
        ("baja", "Baja"),
        ("media", "Media"),
        ("alta", "Alta"),
    ]

    # Campos principales
    moto = models.ForeignKey(Moto, on_delete=models.CASCADE)
    tecnico_asignado = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mantenimientos_asignados",
        help_text="Técnico asignado al mantenimiento",
    )
    fecha_ingreso = models.DateTimeField()
    fecha_entrega = models.DateTimeField(blank=True, null=True)
    descripcion_problema = models.TextField()
    diagnostico = models.TextField(blank=True)
    estado = models.CharField(
        max_length=20, choices=ESTADO_CHOICES, default="pendiente"
    )
    kilometraje_ingreso = models.PositiveIntegerField()

    # Campos nuevos: tipo y prioridad
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="correctivo")
    prioridad = models.CharField(
        max_length=10, choices=PRIORIDAD_CHOICES, default="media"
    )

    # Total calculado automáticamente
    total = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    # Costo adicional (para gastos extras como mano de obra adicional, materiales, etc.)
    costo_adicional = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Costo adicional por servicios extras o materiales no incluidos en repuestos",
    )

    # Auditoría adicional: usuario que completó el mantenimiento
    completado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mantenimientos_completados",
        help_text="Usuario que completó el mantenimiento",
    )
    fecha_completado = models.DateTimeField(null=True, blank=True)

    # Campos para eliminación lógica (soft delete)
    eliminado = models.BooleanField(default=False)
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mantenimientos_eliminados",
    )
    fecha_eliminacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mantenimiento"
        verbose_name = "Mantenimiento"
        verbose_name_plural = "Mantenimientos"
        ordering = ["-fecha_ingreso"]

    def __str__(self):
        return f"Mantenimiento {self.id} - {self.moto.placa}"

    def clean(self):
        """Validaciones personalizadas del modelo"""
        super().clean()

        # Validar que no haya mantenimiento sin moto
        # Usar moto_id para evitar RelatedObjectDoesNotExist
        if not self.moto_id:
            raise ValidationError("El mantenimiento debe estar asociado a una moto")

        # Validar que el kilometraje no sea menor al anterior
        # Usar moto_id para evitar RelatedObjectDoesNotExist
        if self.kilometraje_ingreso and self.moto_id:
            km_actual_moto = self.moto.kilometraje or 0
            # Si es un mantenimiento nuevo o el km cambió
            if not self.pk or self.kilometraje_ingreso < km_actual_moto:
                # Permitir si es el primer mantenimiento o si es un mantenimiento mayor
                # Pero dar advertencia
                pass  # La validación principal se hace en el save o a nivel de form

    def save(self, *args, **kwargs):
        """Guardar con validaciones"""
        # Validar kilometraje al crear
        # Usar moto_id para evitar RelatedObjectDoesNotExist
        if not self.pk and self.moto_id:
            # Obtener kilometraje directamente de la moto usando el ID
            try:
                from core.models import Moto

                moto = Moto.objects.get(id=self.moto_id)
                km_actual = moto.kilometraje or 0
                if self.kilometraje_ingreso < km_actual:
                    raise ValidationError(
                        f"El kilometraje de ingreso ({self.kilometraje_ingreso}) "
                        f"no puede ser menor al kilometraje actual de la moto ({km_actual})"
                    )
            except Moto.DoesNotExist:
                pass  # Si la moto no existe, el validador del serializer manejará el error

        super().save(*args, **kwargs)

    # =======================================
    # MÉTODOS DE LÓGICA DE NEGOCIO
    # =======================================

    def calcular_total(self):
        """
        Calcula automáticamente el total del mantenimiento sumando:
        - Precios de todos los servicios (DetalleMantenimiento)
        - Subtotales de todos los repuestos (RepuestoMantenimiento)
        - Costo adicional
        """
        from decimal import Decimal

        # Sumar precios de servicios
        total_servicios = sum(Decimal(str(d.precio)) for d in self.detalles.all())

        # Sumar subtotales de repuestos
        total_repuestos = sum(Decimal(str(r.subtotal)) for r in self.repuestos.all())

        # Agregar costo adicional
        costo_adicional = (
            Decimal(str(self.costo_adicional))
            if self.costo_adicional
            else Decimal("0.00")
        )

        self.total = total_servicios + total_repuestos + costo_adicional
        self.save(update_fields=["total"])
        return self.total

    def tiene_items(self):
        """
        Verifica si el mantenimiento tiene servicios o repuestos.
        Retorna True si tiene al menos uno.
        """
        return self.detalles.exists() or self.repuestos.exists()

    def puede_cambiar_a(self, nuevo_estado):
        """
        Valida si la transición de estado es válida.

        Flujo obligatorio:
        pendiente -> en_proceso -> completado

        Cualquier estado puede pasar a cancelado.
        """
        transiciones_validas = {
            "pendiente": ["en_proceso", "cancelado"],
            "en_proceso": ["completado", "cancelado"],
            "completado": [],  # No se puede cambiar desde completado
            "cancelado": [],  # No se puede cambiar desde cancelado
        }

        return nuevo_estado in transiciones_validas.get(self.estado, [])

    def cambiar_estado(self, nuevo_estado, usuario=None):
        """
        Cambia el estado del mantenimiento con validaciones.

        Args:
            nuevo_estado: El nuevo estado a establecer
            usuario: El usuario que realiza el cambio

        Returns:
            dict: {success: bool, message: str, mantenimiento: Mantenimiento}
        """
        from django.utils import timezone

        # Validar transición
        if not self.puede_cambiar_a(nuevo_estado):
            return {
                "success": False,
                "message": f"No se puede cambiar de '{self.estado}' a '{nuevo_estado}'. "
                f"Flujo válido: pendiente → en_proceso → completado",
                "mantenimiento": self,
            }

        # Validar que tenga servicios o repuestos al completar
        if nuevo_estado == "completado" and not self.tiene_items():
            return {
                "success": False,
                "message": "No se puede completar un mantenimiento sin servicios ni repuestos",
                "mantenimiento": self,
            }

        # Guardar estado anterior
        estado_anterior = self.estado

        # Realizar el cambio
        self.estado = nuevo_estado

        # Si se completa, registrar fecha y usuario
        if nuevo_estado == "completado":
            self.fecha_completado = timezone.now()
            if usuario:
                self.completado_por = usuario
            # Actualizar kilometraje de la moto si hay uno de salida
            if hasattr(self, "kilometraje_salida") and self.kilometraje_salida:
                self.moto.kilometraje = self.kilometraje_salida
                self.moto.save(update_fields=["kilometraje"])

        self.save(update_fields=["estado", "fecha_completado", "completado_por"])

        return {
            "success": True,
            "message": f"Estado cambiado de '{estado_anterior}' a '{nuevo_estado}'",
            "mantenimiento": self,
        }

    def puede_completarse(self):
        """
        Verifica si el mantenimiento puede ser completado.
        """
        return self.tiene_items() and self.estado == "en_proceso"


class DetalleMantenimiento(TimestampedModel):
    """
    Detalle de un mantenimiento que registra los servicios realizados.

    Utilizado para:
    - Registrar servicios (cambio de aceite, revisión, etc.)
    - Generar recordatorios automáticos basados en el servicio
    """

    TIPO_ACEITE_CHOICES = [
        ("mineral", "Mineral"),
        ("semisintetico", "Semisintético"),
        ("sintetico", "Sintético"),
    ]

    mantenimiento = models.ForeignKey(
        Mantenimiento, on_delete=models.CASCADE, related_name="detalles"
    )
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    observaciones = models.TextField(blank=True)

    # Campos para cambios de aceite y generación de recordatorios
    tipo_aceite = models.CharField(
        max_length=20, choices=TIPO_ACEITE_CHOICES, null=True, blank=True
    )
    km_proximo_cambio = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "detalle_mantenimiento"
        verbose_name = "Detalle de Mantenimiento"
        verbose_name_plural = "Detalles de Mantenimiento"

    def __str__(self):
        return f"{self.servicio.nombre} - Mantenimiento {self.mantenimiento_id}"

    def es_cambio_aceite(self):
        """Verifica si este detalle es un cambio de aceite"""
        nombre_servicio = self.servicio.nombre.lower()
        return "aceite" in nombre_servicio or "oil" in nombre_servicio

    def generar_recordatorios(self):
        """
        Genera recordatorios automáticos SOLO para servicios específicos:
        - Cambio de aceite y filtros: por KM (usa km_proximo_cambio del usuario) y por fecha (desde fecha_entrega)
        - Mantenimiento general: por fecha (60 días / 2 meses desde fecha_entrega)

        Otros servicios NO generan recordatorios automáticos.
        """
        from django.utils import timezone
        from datetime import timedelta

        moto = self.mantenimiento.moto
        km_actual = self.mantenimiento.kilometraje_ingreso or 0
        categoria = self.servicio.categoria_servicio
        nombre_categoria = categoria.nombre.lower()

        # Categorías válidas para recordatorios automáticos
        CATEGORIAS_VALIDAS = ["cambio de aceite y filtros", "mantenimiento general"]

        # Solo crear recordatorios para las categorías específicas
        if nombre_categoria not in CATEGORIAS_VALIDAS:
            return

        # Usar fecha de entrega si existe, si no usar fecha de ingreso
        if self.mantenimiento.fecha_entrega:
            fecha_base = self.mantenimiento.fecha_entrega.date()
        else:
            fecha_base = self.mantenimiento.fecha_ingreso.date()

        if nombre_categoria == "cambio de aceite y filtros":
            # Para cambio de aceite: crear recordatorio por KM y por FECHA
            # Intervalos según tipo de aceite
            KM_INTERVALS = {
                "sintetico": 6000,
                "semisintetico": 4000,
                "mineral": 2000,
            }
            DIAS_INTERVALS = {
                "sintetico": 180,
                "semisintetico": 90,
                "mineral": 30,
            }

            # Usar km_proximo_cambio del usuario si existe, si no calcular automáticamente
            if self.km_proximo_cambio:
                km_proximo = self.km_proximo_cambio
            else:
                km_interval = KM_INTERVALS.get(self.tipo_aceite, 4000)
                km_proximo = km_actual + km_interval

            # Fecha basada en tipo de aceite desde fecha de entrega
            dias_interval = DIAS_INTERVALS.get(self.tipo_aceite, 90)
            fecha_proxima = fecha_base + timedelta(days=dias_interval)

            # Crear/actualizar recordatorio por KM
            self._crear_o_actualizar_recordatorio(
                moto=moto, categoria=categoria, tipo="km", km_proximo=km_proximo
            )

            # Crear/actualizar recordatorio por FECHA
            self._crear_o_actualizar_recordatorio(
                moto=moto,
                categoria=categoria,
                tipo="fecha",
                fecha_programada=fecha_proxima,
            )

        elif nombre_categoria == "mantenimiento general":
            # Para mantenimiento general: crear recordatorio por FECHA (2 meses / 60 días desde fecha_entrega)
            dias_interval = 60  # 2 meses
            fecha_proxima = fecha_base + timedelta(days=dias_interval)

            self._crear_o_actualizar_recordatorio(
                moto=moto,
                categoria=categoria,
                tipo="fecha",
                fecha_programada=fecha_proxima,
            )

    def _crear_o_actualizar_recordatorio(self, moto, categoria, tipo, **kwargs):
        """
        Crea o actualiza un recordatorio para evitar duplicados.
        """
        # Buscar recordatorio existente activo del mismo tipo
        existente = RecordatorioMantenimiento.objects.filter(
            moto=moto, categoria_servicio=categoria, tipo=tipo, activo=True
        ).first()

        if existente:
            # Actualizar existente
            if tipo == "km" and "km_proximo" in kwargs:
                existente.km_proximo = kwargs["km_proximo"]
            elif tipo == "fecha" and "fecha_programada" in kwargs:
                existente.fecha_programada = kwargs["fecha_programada"]
            existente.enviado = False  # Resetear flag de enviado
            existente.save()
        else:
            # Crear nuevo
            RecordatorioMantenimiento.objects.create(
                moto=moto, categoria_servicio=categoria, tipo=tipo, **kwargs
            )

    def save(self, *args, **kwargs):
        """Guardar y generar recordatorios automáticamente"""
        # Primero guardar la instancia
        super().save(*args, **kwargs)

        # Luego generar recordatorios
        try:
            self.generar_recordatorios()
        except Exception as e:
            # Loguear error pero no interrumpir el guardado
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error al generar recordatorios: {e}")


class RecordatorioMantenimiento(TimestampedModel):
    """
    Recordatorio para mantenimientos programados.

    Tipos de recordatorio:
    - km: Por kilometraje (ej: cambio de aceite cada 5000 km)
    - fecha: Por fecha (ej: revisión cada 6 meses)

    El sistema puede generar recordatorios automáticamente desde los servicios
    realizados en mantenimientos.
    """

    TIPO_RECORDATORIO_CHOICES = [
        ("km", "Por Kilometraje"),
        ("fecha", "Por Fecha"),
    ]

    moto = models.ForeignKey(
        Moto, on_delete=models.CASCADE, related_name="recordatorios"
    )
    categoria_servicio = models.ForeignKey(CategoriaServicio, on_delete=models.CASCADE)

    tipo = models.CharField(
        max_length=10, choices=TIPO_RECORDATORIO_CHOICES, default="fecha"
    )

    # Para fecha
    fecha_programada = models.DateField(null=True, blank=True)

    # Para KM
    km_proximo = models.PositiveIntegerField(null=True, blank=True)

    enviado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    registrado_por = models.ForeignKey(
        "Usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recordatorios_registrados",
        editable=False,
        help_text="Usuario que registró el recordatorio",
    )

    # Notas adicionales
    notas = models.TextField(blank=True, help_text="Notas adicionales del recordatorio")

    class Meta:
        db_table = "recordatorio_mantenimiento"
        verbose_name = "Recordatorio de Mantenimiento"
        verbose_name_plural = "Recordatorios de Mantenimiento"
        ordering = ["fecha_programada", "km_proximo"]
        indexes = [
            models.Index(fields=["moto", "activo"]),
            models.Index(fields=["fecha_programada"]),
        ]

    def __str__(self):
        if self.tipo == "km":
            return (
                f"{self.moto.placa} - {self.categoria_servicio.nombre} "
                f"(@ {self.km_proximo} km)"
            )
        return (
            f"{self.moto.placa} - {self.categoria_servicio.nombre} "
            f"({self.fecha_programada})"
        )

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.tipo == "km" and not self.km_proximo:
            raise ValidationError(
                "Debe definir km_proximo para recordatorios por kilometraje"
            )

        if self.tipo == "fecha" and self.fecha_programada:
            raise ValidationError(
                "Debe definir fecha_programada para recordatorios por fecha"
            )

    def proximo(self, dias_antes=7):
        """
        Indica si el mantenimiento es próximo dentro de 'dias_antes' días (para tipo='fecha')
        o si el km próximo está cerca del km actual de la moto (para tipo='km').

        Args:
            dias_antes: Días de anticipación para activar alerta

        Returns:
            dict: {
                'alerta': bool,
                'dias_faltantes': int,
                'km_faltantes': int,
                'mensaje': str
            }
        """
        resultado = {
            "alerta": False,
            "dias_faltantes": 0,
            "km_faltantes": 0,
            "mensaje": "",
        }

        if self.tipo == "fecha" and self.fecha_programada:
            hoy = timezone.now().date()
            inicio_alerta = self.fecha_programada - timezone.timedelta(days=dias_antes)
            dias_faltantes = (self.fecha_programada - hoy).days

            resultado["dias_faltantes"] = max(dias_faltantes, 0)
            resultado["alerta"] = inicio_alerta <= hoy <= self.fecha_programada

            if dias_faltantes < 0:
                resultado["mensaje"] = (
                    f"Recordatorio vencido hace {abs(dias_faltantes)} días"
                )
            elif dias_faltantes == 0:
                resultado["mensaje"] = "Recordatorio para hoy"
            else:
                resultado["mensaje"] = f"Faltan {dias_faltantes} días"

        elif self.tipo == "km" and self.km_proximo and self.moto:
            km_actual = getattr(self.moto, "kilometraje", 0) or 0
            km_faltantes = self.km_proximo - km_actual

            # Alerta si faltan menos de 500 km
            resultado["km_faltantes"] = max(km_faltantes, 0)
            resultado["alerta"] = 0 < km_faltantes <= 500

            if km_faltantes < 0:
                resultado["mensaje"] = (
                    f"Kilometraje excedido por {abs(km_faltantes)} km"
                )
            elif km_faltantes == 0:
                resultado["mensaje"] = "Kilometraje alcanzado exactamente"
            else:
                resultado["mensaje"] = f"Faltan {km_faltantes} km"

        return resultado

    def esta_vencido(self):
        """Verifica si el recordatorio está vencido"""
        if self.tipo == "fecha" and self.fecha_programada:
            return timezone.now().date() > self.fecha_programada
        elif self.tipo == "km" and self.km_proximo and self.moto:
            return self.moto.kilometraje >= self.km_proximo
        return False

    def marcar_enviado(self):
        """Marca el recordatorio como enviado"""
        self.enviado = True
        self.save(update_fields=["enviado"])

    def desactivar(self):
        """Desactiva el recordatorio"""
        self.activo = False
        self.save(update_fields=["activo"])


class RepuestoMantenimiento(TimestampedModel):
    """
    Repuesto utilizado en un mantenimiento.

    Gestiona automáticamente:
    - Cálculo de subtotal
    - Control de stock (reducción al agregar, restauración al eliminar)
    - Movimientos de inventario
    """

    mantenimiento = models.ForeignKey(
        Mantenimiento, on_delete=models.CASCADE, related_name="repuestos"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name="repuestos_usados"
    )
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    # Configuración para validar stock (opcional)
    permitir_sin_stock = models.BooleanField(
        default=False,
        help_text="Permitir usar repuesto aunque no haya stock disponible",
    )

    class Meta:
        db_table = "repuesto_mantenimiento"
        verbose_name = "Repuesto de Mantenimiento"
        verbose_name_plural = "Repuestos de Mantenimiento"

    def __str__(self):
        return f"{self.producto.nombre} x{self.cantidad} (Mantenimiento {self.mantenimiento_id})"

    def clean(self):
        """Validaciones personalizadas"""
        super().clean()

        # Verificar stock si no se permite usar sin stock
        if not self.permitir_sin_stock:
            try:
                inventario = self.producto.inventario
                if inventario.stock_actual < self.cantidad:
                    raise ValidationError(
                        f"Stock insuficiente. Disponible: {inventario.stock_actual}, "
                        f"Solicitado: {self.cantidad}"
                    )
            except Inventario.DoesNotExist:
                raise ValidationError("El producto no tiene inventario configurado")

    def tiene_stock_suficiente(self):
        """Verifica si hay stock suficiente"""
        try:
            inventario = self.producto.inventario
            return inventario.stock_actual >= self.cantidad
        except Inventario.DoesNotExist:
            return False

    def save(self, *args, **kwargs):
        """
        Calcular subtotal automáticamente y actualizar stock.

        Proceso:
        1. Calcular subtotal
        2. Validar stock (si aplica)
        3. Guardar registro
        4. Actualizar stock y crear movimiento
        """
        from decimal import Decimal

        # Calcular subtotal
        self.subtotal = Decimal(str(self.cantidad)) * Decimal(str(self.precio_unitario))

        # Si es una nueva instancia, actualizar stock
        is_new = self.pk is None
        if is_new:
            super().save(*args, **kwargs)
            self._actualizar_stock("salida")
        else:
            super().save(*args, **kwargs)

    def _actualizar_stock(self, tipo_movimiento):
        """
        Actualiza el stock del producto usando FIFO y crea el movimiento de inventario.

        Args:
            tipo_movimiento: 'salida' para reducir, 'entrada' para restaurar
        """
        try:
            if tipo_movimiento == "salida":
                # Usar FIFO para reducir stock
                try:
                    costo = Lote.consumir_fifo(self.producto, self.cantidad)
                    motivo = f"Mantenimiento #{self.mantenimiento_id} - FIFO (costo: {costo})"
                except ValueError as e:
                    # Stock insuficiente
                    motivo = f"Mantenimiento #{self.mantenimiento_id} - Stock insuficiente"
                except Exception as e:
                    motivo = f"Mantenimiento #{self.mantenimiento_id}"
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error en _actualizar_stock (salida): {e}")
            else:
                # Restaurar stock - crear lote de devolución
                try:
                    lote, created = Lote.objects.get_or_create(
                        producto=self.producto,
                        activo=True,
                        defaults={
                            'cantidad_disponible': self.cantidad,
                            'precio_compra': self.precio_unitario,
                        }
                    )
                    if not created:
                        lote.cantidad_disponible += self.cantidad
                        lote.save()
                    motivo = f"Cancelación mantenimiento #{self.mantenimiento_id}"
                except Exception as e:
                    motivo = f"Cancelación mantenimiento #{self.mantenimiento_id}"
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error en _actualizar_stock (entrada): {e}")

            # Crear movimiento de inventario
            try:
                inventario = self.producto.inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo=tipo_movimiento,
                    cantidad=self.cantidad,
                    motivo=motivo,
                    usuario=getattr(self.mantenimiento, "creado_por", None),
                )
            except Inventario.DoesNotExist:
                pass

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Error en _actualizar_stock para producto {self.producto_id}: {e}"
            )

    def delete(self, *args, **kwargs):
        """
        Eliminar repuesto y restaurar stock.
        """
        # Restaurar stock antes de eliminar
        self._actualizar_stock("entrada")
        super().delete(*args, **kwargs)


# =======================================
# CONFIGURACIONES (SINGLETON)
# =======================================


# =======================================
# VENTAS
# =======================================
class Venta(models.Model):
    cliente = models.ForeignKey("Persona", on_delete=models.CASCADE)
    fecha_venta = models.DateTimeField(auto_now_add=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    impuesto = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=10, decimal_places=2)
    notas = models.TextField(blank=True, default="")
    estado = models.CharField(
        max_length=20,
        choices=[
            ("PENDIENTE", "Pendiente"),
            ("PAGADA", "Pagada"),
            ("ANULADA", "Anulada"),
        ],
        default="PENDIENTE",
    )
    eliminado = models.BooleanField(default=False)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_creadas",
    )
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_registradas",
    )
    # Campos de trazabilidad/auditoría
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_actualizadas",
    )
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_eliminadas",
    )
    fecha_eliminacion = models.DateTimeField(null=True, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "venta"
        verbose_name = "Venta"
        verbose_name_plural = "Ventas"

    def __str__(self):
        return f"Venta {self.id} - {self.cliente}"

    @property
    def pagado(self):
        """Suma de pagos registrados"""
        return sum(p.monto for p in self.pagos.all())

    @property
    def saldo(self):
        """Monto pendiente de pago"""
        return self.total - self.pagado


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="detalles")
    producto = models.ForeignKey("Producto", on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "detalle_venta"
        verbose_name = "Detalle de Venta"
        verbose_name_plural = "Detalles de Venta"

    def save(self, *args, **kwargs):
        # Calcular subtotal automáticamente
        self.subtotal = self.cantidad * self.precio_unitario

        # Solo guardar el detalle, NO actualizar stock aquí
        # El stock se actualiza cuando se registra el pago
        super().save(*args, **kwargs)

    def descontar_stock(self):
        """Descuenta el stock usando método FIFO cuando se confirma el pago"""
        try:
            costo = Lote.consumir_fifo(self.producto, self.cantidad)
            
            # Crear movimiento de inventario
            try:
                inventario = self.producto.inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="salida",
                    cantidad=self.cantidad,
                    motivo=f"Venta #{self.venta.id} - FIFO (costo: {costo})",
                    usuario=getattr(self.venta, "registrado_por", None),
                )
            except Inventario.DoesNotExist:
                pass
            
            return True
        except ValueError as e:
            # Stock insuficiente
            try:
                inventario = self.producto.inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="salida",
                    cantidad=self.cantidad,
                    motivo=f"Venta #{self.venta.id} - Stock insuficiente",
                    usuario=getattr(self.venta, "registrado_por", None),
                )
            except Inventario.DoesNotExist:
                pass
            return False
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error en descontar_stock FIFO: {e}")
            return False

    def restaurar_stock(self):
        """Restaura el stock cuando se cancela una venta pagada - crea un lote de devolución"""
        try:
            # Crear un lote especial para la devolución (con precio de venta como referencia)
            lote, created = Lote.objects.get_or_create(
                producto=self.producto,
                activo=True,
                defaults={
                    'cantidad_disponible': self.cantidad,
                    'precio_compra': self.precio_unitario,  # Usar precio de venta como referencia
                }
            )
            if not created:
                lote.cantidad_disponible += self.cantidad
                lote.save()
            
            # Crear movimiento de inventario
            try:
                inventario = self.producto.inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="entrada",
                    cantidad=self.cantidad,
                    motivo=f"Cancelación venta #{self.venta.id}",
                    usuario=getattr(self.venta, "registrado_por", None),
                )
            except Inventario.DoesNotExist:
                pass
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error en restaurar_stock: {e}")

    def delete(self, *args, **kwargs):
        # Solo restaurar stock si la venta estaba pagada
        if self.venta.estado == "PAGADA":
            self.restaurar_stock()

        super().delete(*args, **kwargs)

    def __str__(self):
        return f"Detalle {self.id} - Venta {self.venta.id}"


class Pago(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name="pagos")
    fecha_pago = models.DateTimeField(auto_now_add=True)
    metodo = models.CharField(
        max_length=50,
        choices=[
            ("EFECTIVO", "Efectivo"),
            ("TARJETA", "Tarjeta"),
            ("TRANSFERENCIA", "Transferencia"),
            ("OTRO", "Otro"),
        ],
        default="EFECTIVO",
    )
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_registrados",
    )

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        if is_new:
            # Cuando se registra un pago, verificar si la venta está completamente pagada
            venta = self.venta
            total_pagado = sum(p.monto for p in venta.pagos.all())

            if total_pagado >= venta.total:
                # Venta completamente pagada - descontar stock y cambiar estado
                if venta.estado == "PENDIENTE":
                    for detalle in venta.detalles.all():
                        detalle.descontar_stock()
                    venta.estado = "PAGADA"
                    venta.save(update_fields=["estado"])

    class Meta:
        db_table = "pago"
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"Pago {self.id} - Venta {self.venta.id} - {self.monto}"

    def delete(self, *args, **kwargs):
        venta = self.venta
        super().delete(*args, **kwargs)

        # Después de eliminar el pago, verificar si la venta sigue pagada
        total_pagado = sum(p.monto for p in venta.pagos.all())

        if total_pagado < venta.total and venta.estado == "PAGADA":
            # La venta ya no está completamente pagada - restaurar stock y cambiar estado
            for detalle in venta.detalles.all():
                detalle.restaurar_stock()
            venta.estado = "PENDIENTE"
            venta.save(update_fields=["estado"])


# =======================================
# INVENTARIO
# =======================================
class Inventario(TimestampedModel):
    producto = models.OneToOneField(
        Producto, on_delete=models.CASCADE, related_name="inventario"
    )
    stock_actual = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        db_table = "inventario"
        verbose_name = "Inventario"
        verbose_name_plural = "Inventarios"

    def __str__(self):
        return f"{self.producto.nombre} - Stock: {self.stock_actual}"

    def save(self, *args, **kwargs):
        if self.producto_id:
            from django.db.models import Sum
            result = Lote.objects.filter(
                producto=self.producto, 
                activo=True
            ).aggregate(total=Sum('cantidad_disponible'))
            self.stock_actual = result['total'] or 0
        super().save(*args, **kwargs)


class InventarioMovimiento(TimestampedModel):
    TIPO_CHOICES = [
        ("entrada", "Entrada"),
        ("salida", "Salida"),
        ("ajuste", "Ajuste"),
    ]

    inventario = models.ForeignKey(
        Inventario, on_delete=models.CASCADE, related_name="movimientos"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    cantidad = models.PositiveIntegerField()
    motivo = models.CharField(max_length=200)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        db_table = "inventario_movimiento"
        verbose_name = "Movimiento de Inventario"
        verbose_name_plural = "Movimientos de Inventario"

    def save(self, *args, **kwargs):
        # Verificar si es un movimiento creado manualmente (no desde DetalleVenta o RepuestoMantenimiento)
        is_new = self.pk is None

        # Guardar primero el movimiento
        super().save(*args, **kwargs)

        # Solo actualizar stock si es un movimiento manual (entrada, salida o ajuste directo)
        # Los movimientos desde ventas y mantenimientos ya actualizan el stock en sus propios modelos
        # Tambien ignoramos "Stock inicial" porque ya se manejó en perform_create
        if is_new and not (
            "Venta #" in self.motivo
            or "Mantenimiento #" in self.motivo
            or "Cancelación" in self.motivo
            or "Stock inicial" in self.motivo
        ):
            if self.tipo == "entrada":
                self.inventario.stock_actual += self.cantidad
            elif self.tipo == "salida":
                self.inventario.stock_actual -= self.cantidad
            elif self.tipo == "ajuste":
                self.inventario.stock_actual = self.cantidad  # stock real tras ajuste

            self.inventario.save(update_fields=["stock_actual"])


# =======================================
# RECORDATORIOS
# =======================================


# =======================================
# VENTAS - PRECIOS ESPECIALES POR CLIENTE
# =======================================


# Modelo de Usuario ya incluye fcm_token para notificaciones push
