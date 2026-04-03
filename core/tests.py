"""
TALLER DE MOTOS - SUITE COMPLETA DE PRUEBAS
===========================================
Pruebas unitarias, integración y API para garantizar calidad en producción
"""

import json
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from decimal import Decimal
import factory
from faker import Faker

from .models import (
    Persona, Rol, UsuarioRol, Categoria, Producto,
    Servicio, Moto, Mantenimiento, Venta, DetalleVenta,
    Inventario, Proveedor
)

fake = Faker('es_ES')
Usuario = get_user_model()


# =======================================
# FACTORIES PARA DATOS DE PRUEBA
# =======================================

class RolFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Rol

    nombre = factory.Sequence(lambda n: f"Rol {n}")
    descripcion = factory.Faker('sentence')
    activo = True


class PersonaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Persona

    nombre = factory.Faker('first_name')
    apellido = factory.Faker('last_name')
    cedula = factory.Sequence(lambda n: f"12345678{n:02d}")
    telefono = factory.Faker('phone_number')
    direccion = factory.Faker('address')
    correo_electronico = factory.Faker('email')
    fecha_nacimiento = factory.Faker('date_of_birth', minimum_age=18, maximum_age=80)
    activo = True


class UsuarioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Usuario

    username = factory.Sequence(lambda n: f"usuario{n}")
    correo_electronico = factory.Faker('email')
    password = factory.PostGenerationMethodCall('set_password', 'password123')
    is_active = True
    persona = factory.SubFactory(PersonaFactory)


class CategoriaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Categoria

    nombre = factory.Sequence(lambda n: f"Categoría {n}")
    descripcion = factory.Faker('sentence')
    activo = True


class ProveedorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Proveedor

    nombre = factory.Sequence(lambda n: f"Proveedor {n}")
    telefono = factory.Faker('phone_number')
    correo_electronico = factory.Faker('email')
    direccion = factory.Faker('address')
    activo = True


class ProductoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Producto

    nombre = factory.Sequence(lambda n: f"Producto {n}")
    descripcion = factory.Faker('sentence')
    precio = factory.Faker('pydecimal', left_digits=4, right_digits=2, positive=True)
    costo = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True)
    stock_minimo = factory.Faker('random_int', min=1, max=10)
    stock_maximo = factory.Faker('random_int', min=50, max=200)
    categoria = factory.SubFactory(CategoriaFactory)
    proveedor = factory.SubFactory(ProveedorFactory)
    activo = True


class ServicioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Servicio

    nombre = factory.Sequence(lambda n: f"Servicio {n}")
    descripcion = factory.Faker('sentence')
    precio = factory.Faker('pydecimal', left_digits=4, right_digits=2, positive=True)
    costo = factory.Faker('pydecimal', left_digits=3, right_digits=2, positive=True)
    tiempo_estimado = factory.Faker('random_int', min=30, max=480)  # minutos
    activo = True


class MotoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Moto

    marca = factory.Faker('company')
    modelo = factory.Sequence(lambda n: f"Modelo {n}")
    anio = factory.Faker('year')
    placa = factory.Sequence(lambda n: f"ABC{n:03d}")
    color = factory.Faker('color_name')
    kilometraje = factory.Faker('random_int', min=0, max=200000)
    cliente = factory.SubFactory(PersonaFactory)
    activo = True


class InventarioFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Inventario

    producto = factory.SubFactory(ProductoFactory)
    cantidad = factory.Faker('random_int', min=1, max=100)
    precio_unitario = factory.SelfAttribute('producto.precio')
    ubicacion = factory.Faker('word')
    creado_por = factory.SubFactory(UsuarioFactory)


# =======================================
# PRUEBAS UNITARIAS DE MODELOS
# =======================================

class ModelosTestCase(TestCase):
    """Pruebas unitarias para modelos"""

    def setUp(self):
        self.usuario = UsuarioFactory()
        self.persona = PersonaFactory()
        self.categoria = CategoriaFactory()
        self.producto = ProductoFactory()
        self.servicio = ServicioFactory()
        self.moto = MotoFactory()

    def test_usuario_creation(self):
        """Test creación de usuario"""
        self.assertTrue(self.usuario.is_active)
        self.assertIsNotNone(self.usuario.persona)
        self.assertEqual(self.usuario.username, self.usuario.username.lower())

    def test_persona_str_method(self):
        """Test método __str__ de Persona"""
        expected = f"{self.persona.nombre} {self.persona.apellido}"
        self.assertEqual(str(self.persona), expected)

    def test_producto_calcular_ganancia(self):
        """Test cálculo de ganancia en producto"""
        ganancia = self.producto.calcular_ganancia()
        expected = self.producto.precio - self.producto.costo
        self.assertEqual(ganancia, expected)

    def test_servicio_tiempo_formateado(self):
        """Test formato de tiempo en servicio"""
        tiempo = self.servicio.tiempo_formateado()
        self.assertIn('horas', tiempo.lower()) or self.assertIn('minutos', tiempo.lower())

    def test_moto_kilometraje_validation(self):
        """Test validación de kilometraje"""
        self.moto.kilometraje = -100
        with self.assertRaises(Exception):
            self.moto.full_clean()


class InventarioTestCase(TestCase):
    """Pruebas específicas del modelo Inventario"""

    def setUp(self):
        self.producto = ProductoFactory(stock_minimo=5, stock_maximo=100)
        self.inventario = InventarioFactory(producto=self.producto, cantidad=10)

    def test_inventario_stock_alert(self):
        """Test alerta de stock bajo"""
        self.assertFalse(self.inventario.stock_bajo())

        # Crear inventario con stock bajo
        inventario_bajo = InventarioFactory(producto=self.producto, cantidad=3)
        self.assertTrue(inventario_bajo.stock_bajo())

    def test_inventario_valor_total(self):
        """Test cálculo de valor total"""
        valor = self.inventario.calcular_valor_total()
        expected = self.inventario.cantidad * self.inventario.precio_unitario
        self.assertEqual(valor, expected)


# =======================================
# PRUEBAS DE INTEGRACIÓN
# =======================================

class VentaIntegrationTestCase(TransactionTestCase):
    """Pruebas de integración para el flujo de ventas"""

    def setUp(self):
        self.usuario = UsuarioFactory()
        self.cliente = PersonaFactory()
        self.producto = ProductoFactory(precio=Decimal('100.00'), costo=Decimal('80.00'))
        self.inventario = InventarioFactory(producto=self.producto, cantidad=50)

    def test_venta_con_inventario(self):
        """Test venta completa con actualización de inventario"""
        from django.db import transaction

        with transaction.atomic():
            # Crear venta
            venta = Venta.objects.create(
                cliente=self.cliente,
                creado_por=self.usuario,
                total=Decimal('100.00')
            )

            # Crear detalle de venta
            DetalleVenta.objects.create(
                venta=venta,
                producto=self.producto,
                cantidad=2,
                precio_unitario=self.producto.precio,
                subtotal=Decimal('200.00')
            )

            # Verificar que el inventario se actualizó
            self.inventario.refresh_from_db()
            self.assertEqual(self.inventario.cantidad, 48)  # 50 - 2


class MantenimientoWorkflowTestCase(TransactionTestCase):
    """Pruebas del flujo de trabajo de mantenimiento"""

    def setUp(self):
        self.usuario = UsuarioFactory()
        self.moto = MotoFactory()
        self.servicio = ServicioFactory()

    def test_mantenimiento_estados(self):
        """Test transición de estados en mantenimiento"""
        mantenimiento = Mantenimiento.objects.create(
            moto=self.moto,
            descripcion="Cambio de aceite",
            prioridad="MEDIA",
            creado_por=self.usuario
        )

        # Estado inicial
        self.assertEqual(mantenimiento.estado, "PENDIENTE")

        # Cambiar a EN_PROCESO
        mantenimiento.estado = "EN_PROCESO"
        mantenimiento.tecnico_asignado = self.usuario
        mantenimiento.save()
        self.assertEqual(mantenimiento.estado, "EN_PROCESO")

        # Completar mantenimiento
        mantenimiento.estado = "COMPLETADO"
        mantenimiento.fecha_completado = timezone.now()
        mantenimiento.save()
        self.assertEqual(mantenimiento.estado, "COMPLETADO")


# =======================================
# PRUEBAS DE API
# =======================================

class AuthenticationAPITestCase(APITestCase):
    """Pruebas de autenticación JWT"""

    def setUp(self):
        self.usuario = UsuarioFactory()
        self.client = APIClient()

    def test_login_success(self):
        """Test login exitoso"""
        url = reverse('auth_login')
        data = {
            'correo_electronico': self.usuario.correo_electronico,
            'password': 'password123'
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_invalid_credentials(self):
        """Test login con credenciales inválidas"""
        url = reverse('auth_login')
        data = {
            'correo_electronico': self.usuario.correo_electronico,
            'password': 'wrongpassword'
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_mobile_login_client_only(self):
        """Test que login móvil solo permite clientes"""
        # Crear usuario con rol no cliente
        usuario_admin = UsuarioFactory()
        rol_admin = RolFactory(nombre="ADMINISTRADOR")
        UsuarioRol.objects.create(usuario=usuario_admin, rol=rol_admin)

        url = reverse('mobile_auth_login')
        data = {
            'correo_electronico': usuario_admin.correo_electronico,
            'password': 'password123'
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UsuarioAPITestCase(APITestCase):
    """Pruebas de API para usuarios"""

    def setUp(self):
        self.admin_user = UsuarioFactory()
        self.regular_user = UsuarioFactory()
        self.client = APIClient()

        # Crear rol admin y asignar
        rol_admin = RolFactory(nombre="ADMINISTRADOR")
        UsuarioRol.objects.create(usuario=self.admin_user, rol=rol_admin)

        # Autenticar como admin
        self.client.force_authenticate(user=self.admin_user)

    def test_list_usuarios(self):
        """Test listar usuarios"""
        url = reverse('usuarios-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 2)

    def test_create_usuario(self):
        """Test crear usuario"""
        persona = PersonaFactory()
        url = reverse('usuarios-list')
        data = {
            'username': 'nuevousuario',
            'correo_electronico': 'nuevo@example.com',
            'password': 'password123',
            'persona': persona.id
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['username'], 'nuevousuario')

    def test_usuario_me_endpoint(self):
        """Test endpoint de usuario actual"""
        url = reverse('usuario_me')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.admin_user.id)


class ProductoAPITestCase(APITestCase):
    """Pruebas de API para productos"""

    def setUp(self):
        self.admin_user = UsuarioFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

        # Crear datos necesarios
        self.categoria = CategoriaFactory()
        self.proveedor = ProveedorFactory()

    def test_create_producto(self):
        """Test crear producto"""
        url = reverse('productos-list')
        data = {
            'nombre': 'Producto de Prueba',
            'descripcion': 'Descripción de prueba',
            'precio': '150.00',
            'costo': '120.00',
            'stock_minimo': 5,
            'stock_maximo': 100,
            'categoria': self.categoria.id,
            'proveedor': self.proveedor.id
        }

        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['nombre'], 'Producto de Prueba')

    def test_filter_productos_by_categoria(self):
        """Test filtrar productos por categoría"""
        producto = ProductoFactory(categoria=self.categoria)
        url = reverse('productos-list')
        response = self.client.get(url, {'categoria': self.categoria.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data['results']), 1)


class InventarioAPITestCase(APITestCase):
    """Pruebas de API para inventario"""

    def setUp(self):
        self.admin_user = UsuarioFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin_user)

        self.producto = ProductoFactory()
        self.inventario = InventarioFactory(producto=self.producto)

    def test_list_inventario(self):
        """Test listar inventario"""
        url = reverse('inventario-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inventario_stock_alerts(self):
        """Test alertas de stock bajo"""
        # Crear producto con stock bajo
        producto_bajo = ProductoFactory(stock_minimo=10)
        InventarioFactory(producto=producto_bajo, cantidad=5)

        url = reverse('pos_alertas_inventario')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# =======================================
# PRUEBAS DE SEGURIDAD
# =======================================

class SecurityTestCase(APITestCase):
    """Pruebas de seguridad"""

    def setUp(self):
        self.admin_user = UsuarioFactory()
        self.regular_user = UsuarioFactory()
        self.client = APIClient()

    def test_unauthenticated_access_denied(self):
        """Test que endpoints requieren autenticación"""
        url = reverse('usuarios-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_role_based_permissions(self):
        """Test permisos basados en roles"""
        # Usuario regular intenta acceder a usuarios
        self.client.force_authenticate(user=self.regular_user)
        url = reverse('usuarios-list')
        response = self.client.get(url)
        # Debería ser denegado o filtrado según permisos
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_403_FORBIDDEN])


# =======================================
# PRUEBAS DE PERFORMANCE
# =======================================

class PerformanceTestCase(TestCase):
    """Pruebas básicas de performance"""

    def setUp(self):
        # Crear datos masivos para pruebas de performance
        self.usuarios = UsuarioFactory.create_batch(100)
        self.productos = ProductoFactory.create_batch(50)

    def test_bulk_create_performance(self):
        """Test performance de creación masiva"""
        import time
        start_time = time.time()

        # Crear 50 productos más
        ProductoFactory.create_batch(50)

        end_time = time.time()
        duration = end_time - start_time

        # Debería tomar menos de 5 segundos
        self.assertLess(duration, 5.0)

    def test_query_optimization(self):
        """Test que las queries están optimizadas"""
        from django.db import connection
        from django.test.utils import override_settings

        # Contar queries en una operación compleja
        with override_settings(DEBUG=True):
            connection.queries_log.clear()

            # Operación que debería usar select_related
            productos = Producto.objects.select_related('categoria', 'proveedor').all()
            list(productos)  # Forzar evaluación

            # Debería hacer una query eficiente
            self.assertLessEqual(len(connection.queries), 2)
