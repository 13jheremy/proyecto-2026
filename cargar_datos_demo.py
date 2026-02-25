import random
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from core.models import (
    Persona,
    Usuario,
    Rol,
    UsuarioRol,
    Categoria,
    CategoriaServicio,
    Proveedor,
    Producto,
    Servicio,
    Moto,
    Mantenimiento,
    DetalleMantenimiento,
    RecordatorioMantenimiento,
    Venta,
    DetalleVenta,
    InventarioMovimiento,
)

# =====================================
# CONFIGURACIÓN
# =====================================
PASSWORD = make_password("123456")  # 🔑 Se encripta la contraseña
N = 20  # Cantidad de registros

# =====================================
# PERSONAS
# =====================================
personas = []
for i in range(1, N + 1):
    p = Persona.objects.create(
        nombre=f"Nombre{i}",
        apellido=f"Apellido{i}",
        cedula=f"CI{i:04d}",
        telefono=f"7000{i:04d}",
        direccion=f"Dirección {i}",
    )
    personas.append(p)

print(f"✅ Creadas {len(personas)} personas")

# =====================================
# USUARIOS
# =====================================
usuarios = []
for i, persona in enumerate(personas, start=1):
    u = Usuario.objects.create(
        username=f"cliente{i}",
        correo_electronico=f"cliente{i}@gmail.com",
        password=PASSWORD,
        persona=persona,
        is_active=True,
    )
    usuarios.append(u)

print(f"✅ Creados {len(usuarios)} usuarios")

# =====================================
# ROLES
# =====================================
roles = []
roles_nombres = ["Administrador", "Cliente", "Mecánico", "Vendedor"]
for i, nombre in enumerate(roles_nombres, start=1):
    r = Rol.objects.create(nombre=nombre, descripcion=f"Rol {nombre}")
    roles.append(r)

# completar hasta 20 roles ficticios
for i in range(len(roles_nombres) + 1, N + 1):
    r = Rol.objects.create(nombre=f"Rol{i}", descripcion=f"Rol genérico {i}")
    roles.append(r)

print(f"✅ Creados {len(roles)} roles")

# =====================================
# USUARIO-ROL
# =====================================
for u in usuarios:
    UsuarioRol.objects.create(usuario=u, rol=random.choice(roles), activo=True)

print("✅ Relacionados usuarios con roles")

# =====================================
# CATEGORÍAS
# =====================================
categorias = [
    Categoria.objects.create(nombre=f"Categoría{i}", descripcion=f"Desc cat {i}")
    for i in range(1, N + 1)
]
cat_servicios = [
    CategoriaServicio.objects.create(
        nombre=f"CatServ{i}", descripcion=f"Desc cat serv {i}"
    )
    for i in range(1, N + 1)
]

print(
    f"✅ {len(categorias)} categorías de productos y {len(cat_servicios)} categorías de servicios"
)

# =====================================
# PROVEEDORES
# =====================================
proveedores = []
for i in range(1, N + 1):
    pr = Proveedor.objects.create(
        nombre=f"Proveedor {i}",
        ruc=f"RUC{i:04d}",
        telefono=f"7600{i:04d}",
        correo=f"proveedor{i}@mail.com",
        direccion=f"Dirección proveedor {i}",
        contacto_principal=f"Contacto {i}",
    )
    proveedores.append(pr)

print(f"✅ {len(proveedores)} proveedores")

# =====================================
# PRODUCTOS
# =====================================
productos = []
for i in range(1, N + 1):
    p = Producto.objects.create(
        nombre=f"Producto {i}",
        codigo=f"P{i:04d}",
        descripcion=f"Descripción producto {i}",
        categoria=random.choice(categorias),
        proveedor=random.choice(proveedores),
        precio_compra=round(random.uniform(10, 100), 2),
        precio_venta=round(random.uniform(101, 200), 2),
        stock_minimo=5,
        stock_actual=random.randint(10, 100),
        activo=True,
    )
    productos.append(p)

print(f"✅ {len(productos)} productos")

# =====================================
# SERVICIOS
# =====================================
servicios = []
for i in range(1, N + 1):
    s = Servicio.objects.create(
        nombre=f"Servicio {i}",
        descripcion=f"Descripción servicio {i}",
        categoria_servicio=random.choice(cat_servicios),
        precio=round(random.uniform(50, 300), 2),
        duracion_estimada=random.randint(30, 120),
        activo=True,
    )
    servicios.append(s)

print(f"✅ {len(servicios)} servicios")

# =====================================
# MOTOS
# =====================================
motos = []
for i in range(1, N + 1):
    m = Moto.objects.create(
        propietario=random.choice(personas),
        marca=f"Marca{i}",
        modelo=f"Modelo{i}",
        año=2010 + (i % 15),
        placa=f"PLACA{i:04d}",
        numero_chasis=f"CHASIS{i:05d}",
        numero_motor=f"MOTOR{i:05d}",
        color="Negro",
        cilindrada=125 + (i % 300),
        kilometraje=1000 * i,
    )
    motos.append(m)

print(f"✅ {len(motos)} motos")

# =====================================
# MANTENIMIENTOS
# =====================================
mantenimientos = []
for i in range(1, N + 1):
    m = Mantenimiento.objects.create(
        moto=random.choice(motos),
        fecha_ingreso=timezone.now(),
        descripcion_problema=f"Problema {i}",
        diagnostico=f"Diagnóstico {i}",
        estado="pendiente",
        kilometraje_ingreso=5000 + i * 100,
        total=0,
    )
    mantenimientos.append(m)

print(f"✅ {len(mantenimientos)} mantenimientos")

# Detalles de mantenimiento
for m in mantenimientos:
    for _ in range(2):
        DetalleMantenimiento.objects.create(
            mantenimiento=m,
            servicio=random.choice(servicios),
            precio=random.uniform(50, 150),
            observaciones="OK",
        )

print("✅ Detalles de mantenimientos")

# =====================================
# RECORDATORIOS
# =====================================
for i in range(1, N + 1):
    RecordatorioMantenimiento.objects.create(
        moto=random.choice(motos),
        categoria_servicio=random.choice(cat_servicios),
        fecha_programada=timezone.now().date(),
        enviado=False,
    )

print(f"✅ {N} recordatorios")

# =====================================
# VENTAS
# =====================================
ventas = []
for i in range(1, N + 1):
    v = Venta.objects.create(
        cliente=random.choice(personas),
        fecha_venta=timezone.now(),
        subtotal=100,
        impuesto=15,
        total=115,
        estado="completada",
    )
    ventas.append(v)

print(f"✅ {len(ventas)} ventas")

# Detalles de ventas
for v in ventas:
    for _ in range(2):
        DetalleVenta.objects.create(
            venta=v,
            producto=random.choice(productos),
            cantidad=random.randint(1, 5),
            precio_unitario=50,
            subtotal=100,
        )

print("✅ Detalles de ventas")

# =====================================
# INVENTARIO
# =====================================
for i in range(1, N + 1):
    InventarioMovimiento.objects.create(
        producto=random.choice(productos),
        tipo=random.choice(["entrada", "salida", "ajuste"]),
        cantidad=random.randint(1, 50),
        motivo=f"Movimiento {i}",
        usuario=random.choice(usuarios),
    )

print(f"✅ {N} movimientos de inventario")
