# Script para normalizar nombres de proveedores existentes
# Ejecutar con: python manage.py shell < normalizar_proveedores.py

from core.models import Proveedor

print("=== Normalizando nombres de proveedores existentes ===")

proveedores = Proveedor.objects_all.all()
contador = 0

for proveedor in proveedores:
    nombre_anterior = proveedor.nombre
    proveedor.nombre_normalizado = Proveedor.normalizar_nombre(proveedor.nombre)
    proveedor.save(update_fields=['nombre_normalizado'])
    print(f"ID {proveedor.id}: '{nombre_anterior}' -> '{proveedor.nombre_normalizado}'")
    contador += 1

print(f"\n=== Total de proveedores normalizados: {contador} ===")

# Verificar duplicados
print("\n=== Verificando duplicados en nombre_normalizado ===")
from django.db.models import Count
duplicados = Proveedor.objects.values('nombre_normalizado').annotate(
    count=Count('id')
).filter(count__gt=1)

if duplicados:
    print("Se encontraron duplicados:")
    for d in duplicados:
        print(f"  - '{d['nombre_normalizado']}': {d['count']} registros")
else:
    print("No se encontraron duplicados. Todo OK!")