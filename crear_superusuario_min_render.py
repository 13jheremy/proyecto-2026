import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "taller_motos.settings")
django.setup()

from core.models import Usuario

USERNAME = "adminuser"
CORREO_ELECTRONICO = "admin@gmail.com"
PASSWORD = "admin1234"

# Crear superusuario
if not Usuario.objects.filter(correo_electronico=CORREO_ELECTRONICO).exists():
    Usuario.objects.create_superuser(
        correo_electronico=CORREO_ELECTRONICO,
        username=USERNAME,
        password=PASSWORD,
        is_staff=True,
        is_superuser=True
    )
    print("Superusuario creado correctamente")
else:
    print("El superusuario ya existe")