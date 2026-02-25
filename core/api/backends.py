# =======================================
# BACKEND CORREGIDO (backends.py)
# =======================================
from django.contrib.auth.backends import BaseBackend
from core.models import Usuario


class EmailBackend(BaseBackend):
    def authenticate(self, request, correo_electronico=None, password=None, **kwargs):
        print(f"🔍 === INICIO AUTENTICACIÓN ===")
        print(f"Email: '{correo_electronico}'")
        print(f"Password: '{password}' (tipo: {type(password)})")
        print(f"Password length: {len(password) if password else 'None'}")
        print(f"Password repr: {repr(password)}")  # Esto mostrará caracteres ocultos

        if not correo_electronico or password is None:
            print("❌ Faltan credenciales")
            return None

        try:
            correo_electronico = correo_electronico.lower().strip()
            user = Usuario.objects.get(correo_electronico=correo_electronico)

            print(f"✅ Usuario encontrado: {user.correo_electronico}")
            print(f"Usuario activo: {user.is_active}")

            # Limpiar la contraseña de caracteres invisibles
            password_clean = str(password).strip()
            print(f"Password limpio: '{password_clean}'")
            print(f"Password clean repr: {repr(password_clean)}")

            # Probar contraseña
            password_check = user.check_password(password_clean)
            print(f"Check password result: {password_check}")

            if password_check and user.is_active:
                print("✅ AUTENTICACIÓN EXITOSA")
                return user
            else:
                print(
                    f"❌ FALLÓ - Password OK: {password_check}, Usuario activo: {user.is_active}"
                )
                return None

        except Usuario.DoesNotExist:
            print("❌ Usuario no existe")
            return None
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
            return None
