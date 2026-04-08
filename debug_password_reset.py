"""
Script de debug para verificar usuarios y configuración de email.
Uso: python manage.py shell < debug_password_reset.py
"""

from django.conf import settings
from django.contrib.auth import get_user_model

print("\n" + "="*70)
print("DEBUG: PASSWORD RESET CONFIGURATION")
print("="*70)

# 1. Verificar configuración de email
print("\n📧 EMAIL CONFIGURATION:")
print("-"*70)
email_config = {
    'EMAIL_BACKEND': getattr(settings, 'EMAIL_BACKEND', 'Not set'),
    'EMAIL_HOST': getattr(settings, 'EMAIL_HOST', 'Not set'),
    'EMAIL_PORT': getattr(settings, 'EMAIL_PORT', 'Not set'),
    'EMAIL_USE_TLS': getattr(settings, 'EMAIL_USE_TLS', 'Not set'),
    'EMAIL_HOST_USER': getattr(settings, 'EMAIL_HOST_USER', 'Not set'),
    'DEFAULT_FROM_EMAIL': getattr(settings, 'DEFAULT_FROM_EMAIL', 'Not set'),
    'FRONTEND_URL': getattr(settings, 'FRONTEND_URL', 'Not set'),
}

for key, value in email_config.items():
    is_set = value != 'Not set' and value != ''
    status = "✓" if is_set else "✗"
    masked_value = f"***{'*' * max(0, len(str(value)) - 4)}***" if key == 'EMAIL_HOST_PASSWORD' and is_set else value
    print(f"{status} {key:30s}: {masked_value}")

# 2. Verificar usuarios en la BD
print("\n\n👥 USERS IN DATABASE:")
print("-"*70)
User = get_user_model()
users = User.objects.all()

if not users.exists():
    print("✗ No users found in database!")
else:
    print(f"✓ Found {users.count()} user(s):\n")
    for user in users[:10]:  # Mostrar primeros 10
        email_field = getattr(user, 'correo_electronico', getattr(user, 'email', 'N/A'))
        username = getattr(user, 'username', 'N/A')
        is_active = getattr(user, 'is_active', 'N/A')
        print(f"  • Username: {username}")
        print(f"    Email: {email_field}")
        print(f"    Active: {is_active}")
        print()

# 3. Buscar usuario específico (para testing)
print("\n🔍 SEARCH USER BY EMAIL:")
print("-"*70)
email_to_search = "admin@example.com"  # Cambiar según necesites
try:
    test_user = User.objects.get(correo_electronico=email_to_search)
    print(f"✓ Found user with email {email_to_search}:")
    print(f"  Username: {test_user.username}")
    print(f"  Email: {test_user.correo_electronico}")
    print(f"  Active: {test_user.is_active}")
except User.DoesNotExist:
    print(f"✗ No user found with email: {email_to_search}")
    print(f"\nTip: Use the correct user email from the list above.")

# 4. Ver qué campo de email está siendo usado
print("\n\n📋 USER MODEL EMAIL FIELDS:")
print("-"*70)
user_fields = User._meta.get_fields()
email_related_fields = [f for f in user_fields if 'email' in f.name.lower() or 'correo' in f.name.lower()]
if email_related_fields:
    print("Fields containing 'email' or 'correo':")
    for field in email_related_fields:
        print(f"  • {field.name} ({field.get_internal_type()})")
else:
    print("No email-related fields found!")
    print("\nAll available fields:")
    for field in user_fields:
        if not field.name.startswith('_'):
            print(f"  • {field.name}")

print("\n" + "="*70)
print("END DEBUG")
print("="*70 + "\n")
