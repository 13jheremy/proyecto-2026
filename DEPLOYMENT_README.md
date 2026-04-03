# 🚀 TALLER DE MOTOS - GUÍA DE DESPLIEGUE EN PRODUCCIÓN

## 📋 Requisitos Previos

### Sistema Operativo
- Ubuntu 20.04+ / CentOS 7+ / Debian 10+
- Python 3.9+
- PostgreSQL 13+
- Redis 6+
- Nginx

### Dependencias del Sistema
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3 python3-pip postgresql redis-server nginx

# CentOS/RHEL
sudo yum install python3 python3-pip postgresql-server redis nginx
```

## 🔧 Configuración del Entorno

### 1. Variables de Entorno
Crear archivo `.env` en la raíz del proyecto:

```bash
# Django
SECRET_KEY=tu-clave-secreta-muy-larga-y-segura-aqui
DEBUG=False
DJANGO_SETTINGS_MODULE=taller_motos.settings

# Base de datos
DATABASE_URL=postgresql://usuario:password@localhost:5432/taller_motos_prod

# Redis
REDIS_URL=redis://localhost:6379/1

# Servicios externos
FCM_SERVER_KEY=tu-fcm-server-key
CLOUDINARY_CLOUD_NAME=tu-cloud-name
CLOUDINARY_API_KEY=tu-api-key
CLOUDINARY_API_SECRET=tu-api-secret

# CORS
CORS_ALLOWED_ORIGINS=https://tu-dominio.com,https://www.tu-dominio.com

# SSL/HTTPS
SECURE_SSL_REDIRECT=True
```

### 2. Base de Datos
```bash
# Crear base de datos
sudo -u postgres createdb taller_motos_prod
sudo -u postgres createuser taller_user
sudo -u postgres psql -c "ALTER USER taller_user PASSWORD 'tu_password_seguro';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE taller_motos_prod TO taller_user;"

# Migraciones
python manage.py migrate
```

### 3. Usuario Administrador
```bash
python manage.py createsuperuser
```

## 🚀 Despliegue

### Opción 1: Despliegue Manual

#### 1. Instalar Dependencias
```bash
pip install -r requirements.txt
```

#### 2. Recopilar Archivos Estáticos
```bash
python manage.py collectstatic --noinput
```

#### 3. Configurar Gunicorn
Crear archivo `gunicorn.conf.py`:
```python
bind = "127.0.0.1:8000"
workers = 3
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 30
keepalive = 2
user = "www-data"
group = "www-data"
tmp_upload_dir = None
```

#### 4. Crear Servicio Systemd
```bash
sudo nano /etc/systemd/system/taller-motos.service
```

Contenido:
```ini
[Unit]
Description=Taller de Motos Django App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/ruta/a/tu/proyecto
Environment="PATH=/ruta/a/tu/venv/bin"
ExecStart=/ruta/a/tu/venv/bin/gunicorn --config gunicorn.conf.py taller_motos.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

#### 5. Configurar Nginx
```bash
sudo nano /etc/nginx/sites-available/taller-motos
```

Contenido:
```nginx
server {
    listen 80;
    server_name tu-dominio.com www.tu-dominio.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name tu-dominio.com www.tu-dominio.com;

    # SSL configuration
    ssl_certificate /ruta/a/tu/certificado.crt;
    ssl_certificate_key /ruta/a/tu/clave.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";

    # Static files
    location /static/ {
        alias /ruta/a/tu/proyecto/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Media files
    location /media/ {
        alias /ruta/a/tu/proyecto/media/;
        expires 30d;
        add_header Cache-Control "public";
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Rate limiting
        limit_req zone=api burst=20 nodelay;
    }

    # Admin
    location /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;
```

### Opción 2: Docker

#### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Recopilar static files
RUN python manage.py collectstatic --noinput

# Crear usuario no-root
RUN useradd --create-home --shell /bin/bash app
RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "taller_motos.wsgi:application"]
```

#### docker-compose.yml
```yaml
version: '3.8'

services:
  web:
    build: .
    command: gunicorn taller_motos.wsgi:application --bind 0.0.0.0:8000
    volumes:
      - .:/app
      - static_volume:/app/static
    environment:
      - DATABASE_URL=postgresql://taller_user:password@db:5432/taller_motos_prod
      - REDIS_URL=redis://redis:6379/1
    depends_on:
      - db
      - redis
    networks:
      - webnet

  db:
    image: postgres:13
    environment:
      POSTGRES_DB: taller_motos_prod
      POSTGRES_USER: taller_user
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - webnet

  redis:
    image: redis:6-alpine
    networks:
      - webnet

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - static_volume:/app/static
    depends_on:
      - web
    networks:
      - webnet

volumes:
  postgres_data:
  static_volume:

networks:
  webnet:
```

## 🔍 Monitoreo y Mantenimiento

### Health Checks
```bash
# Verificar salud del sistema
curl https://tu-dominio.com/api/health/

# Verificar base de datos
curl https://tu-dominio.com/api/health/database/

# Verificar cache
curl https://tu-dominio.com/api/health/cache/
```

### Logs
```bash
# Ver logs de aplicación
tail -f logs/django.log

# Ver logs de API
tail -f logs/api.log

# Ver logs de seguridad
tail -f logs/security.log
```

### Métricas
```bash
# Ver métricas del sistema
curl https://tu-dominio.com/api/health/metrics/

# Ver performance
curl https://tu-dominio.com/api/monitoring/performance/

# Ver estadísticas de API
curl https://tu-dominio.com/api/monitoring/api-stats/
```

## 🔐 Seguridad

### Configuraciones Críticas
- ✅ DEBUG = False
- ✅ SECRET_KEY segura (50+ caracteres)
- ✅ HTTPS obligatorio
- ✅ Headers de seguridad configurados
- ✅ Rate limiting activo
- ✅ CORS restrictivo
- ✅ Validación de contraseñas fuerte

### Auditoría de Seguridad
```bash
# Ejecutar validación de producción
python validate_production.py
```

## 📊 Backup y Recuperación

### Backup Automático
```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"

# Backup de base de datos
pg_dump -U taller_user -h localhost taller_motos_prod > $BACKUP_DIR/db_$DATE.sql

# Backup de archivos media
tar -czf $BACKUP_DIR/media_$DATE.tar.gz /ruta/a/media/

# Backup de configuración
cp .env $BACKUP_DIR/env_$DATE.backup

# Limpiar backups antiguos (mantener 7 días)
find $BACKUP_DIR -name "*.sql" -mtime +7 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
find $BACKUP_DIR -name "*.backup" -mtime +7 -delete
```

### Recuperación
```bash
# Restaurar base de datos
psql -U taller_user -h localhost taller_motos_prod < backup.sql

# Restaurar archivos
tar -xzf media_backup.tar.gz -C /ruta/a/media/
```

## 🚨 Solución de Problemas

### Problemas Comunes

#### Error de Conexión a BD
```bash
# Verificar estado de PostgreSQL
sudo systemctl status postgresql

# Ver logs
sudo tail -f /var/log/postgresql/postgresql-13-main.log
```

#### Error de Memoria
```bash
# Verificar uso de memoria
free -h
ps aux --sort=-%mem | head

# Ajustar configuración de Gunicorn
# Reducir workers o aumentar memoria del servidor
```

#### Rate Limiting Excesivo
```bash
# Verificar configuración de Nginx
sudo nginx -t

# Revisar logs de rate limiting
tail -f /var/log/nginx/error.log | grep limit_req
```

## 📞 Contacto y Soporte

Para soporte técnico:
- Email: soporte@tallerdemotos.com
- Documentación: https://docs.tallerdemotos.com
- Issues: https://github.com/tu-organizacion/taller-motos/issues

---

## ✅ Checklist Pre-Despliegue

- [ ] Variables de entorno configuradas
- [ ] Base de datos creada y migrada
- [ ] Archivos estáticos recopilados
- [ ] Usuario administrador creado
- [ ] Configuración de Nginx verificada
- [ ] SSL/HTTPS configurado
- [ ] Firewall configurado
- [ ] Backup inicial realizado
- [ ] Validación de producción ejecutada
- [ ] Monitoreo configurado

¡Tu aplicación está lista para producción! 🎉