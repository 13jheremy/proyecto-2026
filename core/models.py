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
    objects = SoftDeleteManager()
    objects_all = models.Manager()  # acceso a todos (incluyendo eliminados)

    def delete(self, *args, **kwargs):
        """Soft delete por defecto"""
        self.eliminado = True
        self.save(update_fields=["eliminado"])

    def delete_real(self, *args, **kwargs):
        """Eliminar físicamente, saltando soft delete"""
        super().delete(*args, **kwargs)

    class Meta:
        abstract = True


class TimestampedModel(SoftDeleteModel):
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

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


# =======================================
# PRODUCTOS
# =======================================
class Producto(TimestampedModel):
    nombre = models.CharField(max_length=200)
    codigo = models.CharField(max_length=50, unique=True)
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
        return f"{self.codigo} - {self.nombre}"


# =======================================
# SERVICIOS
# =======================================
class Servicio(TimestampedModel):
    nombre = models.CharField(max_length=200)
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
    ESTADO_CHOICES = [
        ("pendiente", "Pendiente"),
        ("en_proceso", "En Proceso"),
        ("completado", "Completado"),
        ("cancelado", "Cancelado"),
    ]

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
    total = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        db_table = "mantenimiento"
        verbose_name = "Mantenimiento"
        verbose_name_plural = "Mantenimientos"

    def __str__(self):
        return f"Mantenimiento {self.id} - {self.moto.placa}"


class DetalleMantenimiento(TimestampedModel):
    mantenimiento = models.ForeignKey(
        Mantenimiento, on_delete=models.CASCADE, related_name="detalles"
    )
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    observaciones = models.TextField(blank=True)

    class Meta:
        db_table = "detalle_mantenimiento"
        verbose_name = "Detalle de Mantenimiento"
        verbose_name_plural = "Detalles de Mantenimiento"


class RecordatorioMantenimiento(TimestampedModel):
    moto = models.ForeignKey(
        Moto, on_delete=models.CASCADE, related_name="recordatorios"
    )
    categoria_servicio = models.ForeignKey(CategoriaServicio, on_delete=models.CASCADE)
    fecha_programada = models.DateField()
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

    class Meta:
        db_table = "recordatorio_mantenimiento"
        verbose_name = "Recordatorio de Mantenimiento"
        verbose_name_plural = "Recordatorios de Mantenimiento"

    def __str__(self):
        return (
            f"{self.moto} - {self.categoria_servicio.nombre} ({self.fecha_programada})"
        )

    def proximo(self, dias_antes=7):
        """
        Indica si el mantenimiento es próximo dentro de 'dias_antes' días.
        Devuelve un diccionario con:
            - 'alerta': True/False si está dentro del rango de alerta
            - 'dias_faltantes': días que faltan para la fecha programada
        """
        hoy = timezone.now().date()
        inicio_alerta = self.fecha_programada - timezone.timedelta(days=dias_antes)
        dias_faltantes = (self.fecha_programada - hoy).days

        alerta = inicio_alerta <= hoy <= self.fecha_programada

        return {
            "alerta": alerta,
            "dias_faltantes": max(dias_faltantes, 0),  # no devolver negativos
        }


class RepuestoMantenimiento(TimestampedModel):
    mantenimiento = models.ForeignKey(
        Mantenimiento, on_delete=models.CASCADE, related_name="repuestos"
    )
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name="repuestos_usados"
    )
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = "repuesto_mantenimiento"
        verbose_name = "Repuesto de Mantenimiento"
        verbose_name_plural = "Repuestos de Mantenimiento"

    def save(self, *args, **kwargs):
        """Calcular subtotal automáticamente y actualizar stock"""
        self.subtotal = self.cantidad * self.precio_unitario

        # Si es una nueva instancia, actualizar stock
        is_new = self.pk is None
        if is_new:
            super().save(*args, **kwargs)
            # Reducir stock del producto usado en mantenimiento
            try:
                inventario = self.producto.inventario
                if inventario.stock_actual >= self.cantidad:
                    inventario.stock_actual -= self.cantidad
                    inventario.save(update_fields=["stock_actual"])

                    # Crear movimiento de inventario
                    InventarioMovimiento.objects.create(
                        inventario=inventario,
                        tipo="salida",
                        cantidad=self.cantidad,
                        motivo=f"Mantenimiento #{self.mantenimiento.id}",
                        usuario=getattr(self.mantenimiento, "registrado_por", None),
                    )
                else:
                    # Si no hay suficiente stock, usar lo disponible y registrar el problema
                    InventarioMovimiento.objects.create(
                        inventario=inventario,
                        tipo="salida",
                        cantidad=self.cantidad,
                        motivo=f"Mantenimiento #{self.mantenimiento.id} - Stock insuficiente",
                        usuario=getattr(self.mantenimiento, "registrado_por", None),
                    )
                    inventario.stock_actual = max(
                        0, inventario.stock_actual - self.cantidad
                    )
                    inventario.save(update_fields=["stock_actual"])
            except Inventario.DoesNotExist:
                # Si no existe inventario para el producto, no hacer nada
                pass
        else:
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Restaurar stock cuando se elimina el repuesto del mantenimiento
        try:
            inventario = self.producto.inventario
            inventario.stock_actual += self.cantidad
            inventario.save(update_fields=["stock_actual"])

            # Crear movimiento de inventario
            InventarioMovimiento.objects.create(
                inventario=inventario,
                tipo="entrada",
                cantidad=self.cantidad,
                motivo=f"Cancelación mantenimiento #{self.mantenimiento.id}",
                usuario=getattr(self.mantenimiento, "registrado_por", None),
            )
        except Inventario.DoesNotExist:
            pass

        super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.producto.nombre} x{self.cantidad} (Mantenimiento {self.mantenimiento.id})"


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
    impuesto = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=10, decimal_places=2)
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
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_registradas",
    )

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
        """Descuenta el stock cuando se confirma el pago"""
        try:
            inventario = self.producto.inventario
            if inventario.stock_actual >= self.cantidad:
                inventario.stock_actual -= self.cantidad
                inventario.save(update_fields=["stock_actual"])

                # Crear movimiento de inventario
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="salida",
                    cantidad=self.cantidad,
                    motivo=f"Venta #{self.venta.id} - Pago confirmado",
                    usuario=getattr(self.venta, "registrado_por", None),
                )
                return True
            else:
                # Si no hay suficiente stock, registrar el problema pero permitir la venta
                InventarioMovimiento.objects.create(
                    inventario=inventario,
                    tipo="salida",
                    cantidad=self.cantidad,
                    motivo=f"Venta #{self.venta.id} - Stock insuficiente al pagar",
                    usuario=getattr(self.venta, "registrado_por", None),
                )
                inventario.stock_actual = max(
                    0, inventario.stock_actual - self.cantidad
                )
                inventario.save(update_fields=["stock_actual"])
                return False
        except Inventario.DoesNotExist:
            # Si no existe inventario para el producto, no hacer nada
            return True

    def restaurar_stock(self):
        """Restaura el stock cuando se cancela una venta pagada"""
        try:
            inventario = self.producto.inventario
            inventario.stock_actual += self.cantidad
            inventario.save(update_fields=["stock_actual"])

            # Crear movimiento de inventario
            InventarioMovimiento.objects.create(
                inventario=inventario,
                tipo="entrada",
                cantidad=self.cantidad,
                motivo=f"Cancelación venta #{self.venta.id}",
                usuario=getattr(self.venta, "registrado_por", None),
            )
        except Inventario.DoesNotExist:
            pass

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
        if is_new and not (
            "Venta #" in self.motivo
            or "Mantenimiento #" in self.motivo
            or "Cancelación" in self.motivo
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


# Modelo de Usuario ya incluye fcm_token para notificaciones push
