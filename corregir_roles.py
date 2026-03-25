# Script para corregir nombres de roles en la base de datos
# Ejecutar con: python manage.py shell < corregir_roles.py

from core.models import Rol, UsuarioRol

# Ver roles actuales
print("=== Roles actuales en la base de datos ===")
roles = Rol.objects.all()
for rol in roles:
    print(f"ID: {rol.id}, Nombre: {rol.nombre}")

# Mapeo de correcciones
correcciones = {
    "Mecánico": "Tecnico",
    "Mecanico": "Tecnico",
    "Vendedor": "Empleado",
    "Tecnico": "Tecnico",  # Ya correcto
    "Empleado": "Empleado",  # Ya correcto
    "Administrador": "Administrador",  # Ya correcto
    "Cliente": "Cliente",  # Ya correcto
}

print("\n=== Aplicando correcciones ===")
for old_name, new_name in correcciones.items():
    rol_old = Rol.objects.filter(nombre=old_name).first()
    rol_new = Rol.objects.filter(nombre=new_name).first()

    if rol_old and not rol_new:
        # Renombrar el rol
        print(f"Renombrando '{old_name}' a '{new_name}'")
        # Actualizar UsuarioRol primero
        usuario_roles = UsuarioRol.objects.filter(rol=rol_old)
        for ur in usuario_roles:
            ur.rol = rol_new
            ur.save()
        # Eliminar el rol viejo
        rol_old.delete()
        print(f"  -> {usuario_roles.count()} usuarios actualizados")
    elif rol_old and rol_new:
        # Actualizar referencias y eliminar duplicado
        print(f"Actualizando referencias de '{old_name}' a '{new_name}'")
        usuario_roles = UsuarioRol.objects.filter(rol=rol_old)
        for ur in usuario_roles:
            ur.rol = rol_new
            ur.save()
        rol_old.delete()
        print(f"  -> {usuario_roles.count()} usuarios actualizados")

print("\n=== Roles después de la corrección ===")
roles = Rol.objects.all()
for rol in roles:
    print(f"ID: {rol.id}, Nombre: {rol.nombre}")

print("\n=== Verificando roles de usuarios ===")
for ur in UsuarioRol.objects.select_related("usuario", "rol").all()[:10]:
    print(f"Usuario: {ur.usuario.username}, Rol: {ur.rol.nombre}, Activo: {ur.activo}")
