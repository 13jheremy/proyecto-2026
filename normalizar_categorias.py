# Script para normalizar nombres de categorías (nombre_sin_espacios)
# Ejecutar con: python manage.py shell < normalizar_categorias.py

from core.models import Categoria, CategoriaServicio
from django.db.models import Count

def normalizar_modelo(modelo, nombre_modelo):
    print(f"\n=== Normalizando {nombre_modelo} ===")
    registros = modelo.objects.all()
    contador = 0

    for reg in registros:
        nombre_anterior = reg.nombre
        reg.nombre_normalizado = modelo.normalizar_nombre(reg.nombre)
        reg.nombre_sin_espacios = modelo.quitar_espacios(reg.nombre)
        reg.save(update_fields=['nombre_normalizado', 'nombre_sin_espacios'])
        print(f"ID {reg.id}: '{nombre_anterior}' -> normalizado: '{reg.nombre_normalizado}', sin_espacios: '{reg.nombre_sin_espacios}'")
        contador += 1

    print(f"Total normalizados: {contador}")

    # Verificar duplicados en nombre_sin_espacios
    duplicados = modelo.objects.values('nombre_sin_espacios').annotate(
        count=Count('id')
    ).filter(count__gt=1)

    if duplicados:
        print("⚠️ Duplicados encontrados en nombre_sin_espacios:")
        for d in duplicados:
            print(f"  - '{d['nombre_sin_espacios']}': {d['count']} registros")
    else:
        print("✓ Sin duplicados en nombre_sin_espacios")

# Normalizar ambas categorías
normalizar_modelo(Categoria, "Categoría de Productos")
normalizar_modelo(CategoriaServicio, "Categoría de Servicios")

print("\n=== Proceso completado ===")