# Script para normalizar nombres de servicios existentes
# Ejecutar con: python manage.py shell < normalizar_servicios.py

from core.models import Servicio
from django.db.models import Count

print("=== Normalizando nombres de servicios existentes ===")

servicios = Servicio.objects.all()
contador = 0

for servicio in servicios:
    nombre_anterior = servicio.nombre
    servicio.nombre_normalizado = Servicio.normalizar_nombre(servicio.nombre)
    servicio.nombre_sin_espacios = Servicio.quitar_espacios(servicio.nombre)
    servicio.save(update_fields=['nombre_normalizado', 'nombre_sin_espacios'])
    print(f"ID {servicio.id}: '{nombre_anterior}' -> sin_espacios: '{servicio.nombre_sin_espacios}'")
    contador += 1

print(f"\n=== Total de servicios normalizados: {contador} ===")

# Verificar duplicados en nombre_sin_espacios
duplicados = Servicio.objects.values('nombre_sin_espacios').annotate(
    count=Count('id')
).filter(count__gt=1)

if duplicados:
    print("\n⚠️ Duplicados encontrados:")
    for d in duplicados:
        print(f"  - '{d['nombre_sin_espacios']}': {d['count']} registros")
else:
    print("✓ Sin duplicados")