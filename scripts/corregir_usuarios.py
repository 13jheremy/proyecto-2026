# scripts/corregir_usuarios.py
from django.contrib.auth import get_user_model
from core.models import Persona

Usuario = get_user_model()

def corregir_usuarios_sin_persona():
    usuarios_sin_persona = Usuario.objects.filter(persona__isnull=True)
    print(f"Encontrados {usuarios_sin_persona.count()} usuarios sin persona")

    for usuario in usuarios_sin_persona:
        persona = Persona.objects.create(
            usuario=usuario,
            ci=f'USER_{usuario.id:04d}',
            nombres=usuario.first_name or usuario.username,
            apellido_paterno=usuario.last_name or 'Sin Apellido',
        )
        print(f"Persona creada: {persona} para usuario {usuario.username}")

    usuarios_sin_persona_final = Usuario.objects.filter(persona__isnull=True).count()
    total_usuarios = Usuario.objects.count()

    print("\nResultado final:")
    print(f"   - Total usuarios: {total_usuarios}")
    print(f"   - Usuarios sin persona: {usuarios_sin_persona_final}")
    print("Problema solucionado!" if usuarios_sin_persona_final == 0 else "Aún hay problemas")


# Llamada directa
corregir_usuarios_sin_persona()
