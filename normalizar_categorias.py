# Script para normalizar nombres de categorías existentes
# Ejecutar con: python manage.py shell < normalizar_categorias.py

from core.models import Categoria, CategoriaServicio
from django.db.models import Count

def normalizar_modelo(modelo, nombre_modelo):
    print(f"\n=== Normalizando {nombre_modelo} ===")
    registros = modelo.objects_all.all()
    contador = 0

    for reg in registros:
        nombre_anterior = reg.nombre
        reg.nombre_normalizado = modelo.normalizar_nombre(reg.nombre)
        reg.save(update_fields=['nombre_normalizado'])
        print(f"ID {reg.id}: '{nombre_anterior}' -> '{reg.nombre_normalizado}'")
        contador += 1

    print(f"Total normalizados: {contador}")

    # Verificar duplicados
    duplicados = modelo.objects.values('nombre_normalizado').annotate(
        count=Count('id')
    ).filter(count__gt=1)

    if duplicados:
        print("⚠️ Duplicados encontrados:")
        for d in duplicados:
            print(f"  - '{d['nombre_normalizado']}': {d['count']} registros")
    else:
        print("✓ Sin duplicados")

# Normalizar ambas categorías
normalizar_modelo(Categoria, "Categoría de Productos")
normalizar_modelo(CategoriaServicio, "Categoría de Servicios")

print("\n=== Proceso completado ===")