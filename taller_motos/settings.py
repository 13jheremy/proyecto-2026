# =======================================
# TALLER DE MOTOS - DJANGO SETTINGS (OPTIMIZED)
# =======================================
# Configuración optimizada para seguridad y rendimiento
# - Variables de entorno para configuración sensible
# - Configuración de seguridad mejorada
# - Logging estructurado
# - Configuración de cache y rendimiento
# =======================================

from pathlib import Path
import os
from datetime import timedelta
from decouple import config
import cloudinary

# =========================
# BASE CONFIGURATION
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

# DEBUG debe ser False en producción
DEBUG = config("DEBUG", default=True, cast=bool)

# =========================
# LOGGING IMPORTS AND FORMATTERS
# =========================
import logging

# Formatter seguro para desarrollo
LOGGING_FORMATTER_VERBOSE = {
    "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
    "style": "{",
}

LOGGING_FORMATTER_SIMPLE = {
    "format": "{levelname} {message}",
    "style": "{",
}

# Formatter JSON solo si python-json-logger está disponible
try:
    from pythonjsonlogger import jsonlogger

    LOGGING_FORMATTER_JSON = {
        "format": '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
        '"module": "%(module)s", "message": "%(message)s"}',
        "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
    }
    JSON_AVAILABLE = True
except ModuleNotFoundError:
    JSON_AVAILABLE = False
    LOGGING_FORMATTER_JSON = LOGGING_FORMATTER_VERBOSE  # fallback

# =========================
# LOGGING CONFIGURATION
# =========================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": LOGGING_FORMATTER_VERBOSE,
        "simple": LOGGING_FORMATTER_SIMPLE,
        "json": LOGGING_FORMATTER_JSON,
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if DEBUG else "simple",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "django.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "security.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "api_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "api.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "json" if JSON_AVAILABLE and not DEBUG else "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"] if not DEBUG else ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "security_file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "django.security": {
            "handlers": ["console", "security_file"],
            "level": "INFO",
            "propagate": False,
        },
        "core": {
            "handlers": ["console", "file", "api_file"] if not DEBUG else ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
        "core.api": {
            "handlers": ["console", "api_file"] if not DEBUG else ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}

# Usar variable de entorno para SECRET_KEY en producción
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-xfb(c+85v10xp-%-qs+s%-r7uia6nv4$%q+$=z(pz#&)%s8z7&",
)

# Hosts permitidos - configurar apropiadamente en producción
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="*").split(",")

# =========================
# AUTHENTICATION & JWT
# =========================
AUTH_USER_MODEL = "core.Usuario"

AUTHENTICATION_BACKENDS = [
    "core.api.backends.EmailBackend",  # Tu backend personalizado
    "django.contrib.auth.backends.ModelBackend",  # Backend por defecto
]


# JWT Configuration optimizada
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("JWT_ACCESS_TOKEN_MINUTES", default=60, cast=int)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("JWT_REFRESH_TOKEN_DAYS", default=7, cast=int)
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# =========================
# INSTALLED APPS
# =========================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # REST
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    # Core
    "core.apps.CoreConfig",
    # CORS
    "corsheaders",
    # Cloudinary
    "cloudinary",
    "cloudinary_storage",
]

# =========================
# MIDDLEWARE
# =========================
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # debe ir arriba
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Security middlewares personalizados
    "core.api.security_middleware.SecurityHeadersMiddleware",
    "core.api.security_middleware.SQLInjectionProtectionMiddleware",
    "core.api.security_middleware.RequestSizeLimitMiddleware",
    "core.api.security_middleware.IPBlocklistMiddleware",
    "core.api.security_middleware.UserAgentValidationMiddleware",
    "core.api.security_middleware.RequestLoggingMiddleware",
]


ROOT_URLCONF = "taller_motos.urls"
WSGI_APPLICATION = "taller_motos.wsgi.application"

# =========================
# TEMPLATES
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",  # necesario para admin
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# =========================
# DATABASE CONFIGURATION
# =========================
import os
import dj_database_url

if os.environ.get("DATABASE_URL"):
    # 👉 Producción (Render)
    DATABASES = {
        "default": dj_database_url.parse(
            os.environ.get("DATABASE_URL"), conn_max_age=600, ssl_require=True
        )
    }
else:
    # 👉 Local
    DATABASES = {
        "default": {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'mototaller',
            'USER': 'mototaller_user',
            'PASSWORD': 'yH1td9Ck7VZhAgq3f8kKrHB0iMICck8S',
            'HOST': 'dpg-d784b6ea2pns73debon0-a.oregon-postgres.render.com',
            'PORT': '5432',
        }
    }

# =========================
# PASSWORD VALIDATORS
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# INTERNATIONALIZATION
# =========================
LANGUAGE_CODE = "es"
TIME_ZONE = "America/La_Paz"
USE_I18N = True
USE_TZ = True

# =========================
# STATIC & MEDIA
# =========================
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

# =========================
# CLOUDINARY
# =========================
# settings.py
CLOUDINARY_CLOUD_NAME = config("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = config("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = config("CLOUDINARY_API_SECRET")

cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,
    secure=True,
)

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
    "API_KEY": CLOUDINARY_API_KEY,
    "API_SECRET": CLOUDINARY_API_SECRET,
}

# =========================
# CORS CONFIGURATION
# =========================
CORS_ALLOW_CREDENTIALS = True

# En producción, especificar dominios exactos
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = config(
        "CORS_ALLOWED_ORIGINS",
        default="https://proyecto-2026-ts4b.onrender.com,https://frontend-proyecto-2026.vercel.app",  # Añade tu URL de Vercel aquí
    ).split(",")

CORS_ALLOWED_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "ngrok-skip-browser-warning",
]

CORS_ALLOWED_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"https://.*\.vercel\.app",
]

# =========================
# AUTO FIELD
# =========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =========================
# SECURITY SETTINGS
# =========================
if not DEBUG:
    # Configuraciones de seguridad para producción
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_SECONDS = 31536000  # 1 año
    SECURE_REDIRECT_EXEMPT = []
    SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"

# Configuraciones de seguridad adicionales (siempre activas)
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# =========================
# RATE LIMITING CONFIGURATION
# =========================
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "core.api.pagination.UsuarioPagination",
    "PAGE_SIZE": config("PAGE_SIZE", default=20, cast=int),
    "DEFAULT_THROTTLE_CLASSES": [
        "core.api.throttling.CustomUserRateThrottle",
        "core.api.throttling.CustomAnonRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": "1000/hour",
        "anon": "100/hour",
        "auth": "5/minute",
        "api": "500/hour",
        "pos": "2000/hour",
    },
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}

# =========================
# CORS CONFIGURATION
# =========================
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=lambda v: [s.strip() for s in v.split(",")]
)

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# =========================
# DATA VALIDATION SETTINGS
# =========================
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_NUMBER_FILES = 10
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5MB

# Validaciones de contraseña
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# =========================
# SECURITY CONFIGURATIONS
# =========================

# Configuraciones de seguridad adicionales
BLOCKED_IPS = config(
    "BLOCKED_IPS",
    default="",
    cast=lambda v: [ip.strip() for ip in v.split(",") if ip.strip()]
)

MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB

# Configuraciones de rate limiting avanzadas
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "user": config("THROTTLE_USER_RATE", default="1000/hour"),
    "anon": config("THROTTLE_ANON_RATE", default="100/hour"),
    "auth": config("THROTTLE_AUTH_RATE", default="5/minute"),
    "api": config("THROTTLE_API_RATE", default="500/hour"),
    "pos": config("THROTTLE_POS_RATE", default="2000/hour"),
}

# =========================
# CACHE CONFIGURATION
# =========================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
        "TIMEOUT": 300,  # 5 minutos
        "OPTIONS": {
            "MAX_ENTRIES": 1000,
        },
    }
}

# =========================
# SESSION CONFIGURATION
# =========================
SESSION_COOKIE_AGE = 86400  # 24 horas
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# =========================
# FIREBASE CONFIGURATION
# =========================
FIREBASE_CREDENTIALS_PATH = config(
    "FIREBASE_CREDENTIALS_PATH", default=str(BASE_DIR / "firebase-service-account.json")
)
FIREBASE_CREDENTIALS_JSON = config("FIREBASE_CREDENTIALS", default="")

# =========================
# CELERY CONFIGURATION
# =========================
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default="redis://localhost:6379/0"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "America/Bogota"
CELERY_ENABLE_UTC = True

# =========================
# EMAIL CONFIGURATION
# =========================
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@tallermotos.com")

# Frontend URL for password reset links
FRONTEND_URL = config("FRONTEND_URL", default="http://localhost:5173")

# =========================
# PERFORMANCE SETTINGS
# =========================
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# Crear directorio de logs si no existe
os.makedirs(BASE_DIR / "logs", exist_ok=True)
