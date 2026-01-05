_Related: [Operator workflows](OperatorWorkflows.md) • [Operator CLI](../cli/README.md)_

# RetroVue Configuration

This document describes all configuration options available in RetroVue, including environment variables, settings, and deployment configurations.

## Overview

RetroVue uses a hierarchical configuration system with environment variables, configuration files, and default values. All settings are managed through Pydantic BaseSettings for validation and type safety.

## Environment Variables

### Database Configuration

| Variable          | Default                                                          | Description                       |
| ----------------- | ---------------------------------------------------------------- | --------------------------------- |
| `DATABASE_URL`    | `postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue` | PostgreSQL connection string      |
| `ECHO_SQL`        | `false`                                                          | Enable SQL query logging          |
| `DB_POOL_SIZE`    | `5`                                                              | Database connection pool size     |
| `DB_MAX_OVERFLOW` | `10`                                                             | Maximum pool overflow connections |
| `DB_POOL_TIMEOUT` | `30`                                                             | Pool timeout in seconds           |

### Application Settings

| Variable          | Default | Description                                 |
| ----------------- | ------- | ------------------------------------------- |
| `LOG_LEVEL`       | `INFO`  | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ENV`             | `dev`   | Environment (dev, prod, test)               |
| `ALLOWED_ORIGINS` | `*`     | CORS allowed origins (comma-separated)      |

### Media Configuration

| Variable      | Default | Description                      |
| ------------- | ------- | -------------------------------- |
| `MEDIA_ROOTS` | ``      | Comma-separated media root paths |
| `PLEX_TOKEN`  | ``      | Plex server authentication token |

## Configuration Files

### 1. Environment File (.env)

Create a `.env` file in the project root:

```bash
# Database Configuration
DATABASE_URL=postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue
ECHO_SQL=false
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30

# Application Settings
LOG_LEVEL=INFO
ENV=dev
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8080

# Media Configuration
MEDIA_ROOTS=/media/movies,/media/tv,/media/music
PLEX_TOKEN=your-plex-token-here
```

### 2. Production Configuration

For production deployments:

```bash
# Production Database
DATABASE_URL=postgresql+psycopg://retrovue:secure_password@db-server:5432/retrovue_prod
ECHO_SQL=false
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_POOL_TIMEOUT=60

# Production Settings
LOG_LEVEL=WARNING
ENV=prod
ALLOWED_ORIGINS=https://retrovue.example.com,https://admin.retrovue.example.com

# Production Media
MEDIA_ROOTS=/mnt/media/movies,/mnt/media/tv
PLEX_TOKEN=production-plex-token
```

### 3. Development Configuration

For local development:

```bash
# Development Database
DATABASE_URL=postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue_dev
ECHO_SQL=true
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10

# Development Settings
LOG_LEVEL=DEBUG
ENV=dev
ALLOWED_ORIGINS=*

# Development Media
MEDIA_ROOTS=./test_media
PLEX_TOKEN=dev-plex-token
```

## Settings Implementation

### Settings Class

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Main application settings using Pydantic BaseSettings."""

    # Database settings
    database_url: str = Field(
        default="postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue",
        alias="DATABASE_URL"
    )
    echo_sql: bool = Field(default=False, alias="ECHO_SQL")
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")

    # Application settings
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    env: str = Field(default="dev", alias="ENV")
    allowed_origins: str = Field(default="*", alias="ALLOWED_ORIGINS")

    # Media settings
    media_roots: str = Field(default="", alias="MEDIA_ROOTS")
    plex_token: str = Field(default="", alias="PLEX_TOKEN")

    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()
```

### Settings Usage

```python
from retrovue.infra.settings import settings

# Access settings
database_url = settings.database_url
log_level = settings.log_level
media_roots = settings.media_roots.split(",") if settings.media_roots else []
```

## Deployment Configurations

### 1. Docker Configuration

**Dockerfile**:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN pip install -e .

# Environment variables
ENV DATABASE_URL=postgresql+psycopg://retrovue:retrovue@db:5432/retrovue
ENV LOG_LEVEL=INFO
ENV ENV=prod

EXPOSE 8080
CMD ["python", "-m", "retrovue.api.main"]
```

**docker-compose.yml**:

```yaml
version: "3.8"

services:
  retrovue:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql+psycopg://retrovue:retrovue@db:5432/retrovue
      - LOG_LEVEL=INFO
      - ENV=prod
      - MEDIA_ROOTS=/media/movies,/media/tv
    volumes:
      - ./media:/media
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=retrovue
      - POSTGRES_USER=retrovue
      - POSTGRES_PASSWORD=retrovue
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### 2. Kubernetes Configuration

**configmap.yaml**:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: retrovue-config
data:
  LOG_LEVEL: "INFO"
  ENV: "prod"
  ALLOWED_ORIGINS: "https://retrovue.example.com"
  MEDIA_ROOTS: "/media/movies,/media/tv"
```

**secret.yaml**:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: retrovue-secrets
type: Opaque
data:
  DATABASE_URL: cG9zdGdyZXNxbCtwc3ljb3BnOi8vcmV0cm92dWU6c2VjdXJlX3Bhc3N3b3JkQGJkLXNlcnZlcjo1NDMyL3JldHJvdnVlX3Byb2Q=
  PLEX_TOKEN: cHJvZHVjdGlvbi1wbGV4LXRva2Vu
```

**deployment.yaml**:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: retrovue
spec:
  replicas: 3
  selector:
    matchLabels:
      app: retrovue
  template:
    metadata:
      labels:
        app: retrovue
    spec:
      containers:
        - name: retrovue
          image: retrovue:latest
          ports:
            - containerPort: 8080
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: retrovue-secrets
                  key: DATABASE_URL
            - name: PLEX_TOKEN
              valueFrom:
                secretKeyRef:
                  name: retrovue-secrets
                  key: PLEX_TOKEN
          envFrom:
            - configMapRef:
                name: retrovue-config
          volumeMounts:
            - name: media-storage
              mountPath: /media
      volumes:
        - name: media-storage
          persistentVolumeClaim:
            claimName: media-pvc
```

### 3. Systemd Service

**/etc/systemd/system/retrovue.service**:

```ini
[Unit]
Description=Retrovue Media Server
After=network.target postgresql.service

[Service]
Type=simple
User=retrovue
Group=retrovue
WorkingDirectory=/opt/retrovue
Environment=DATABASE_URL=postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue
Environment=LOG_LEVEL=INFO
Environment=ENV=prod
Environment=MEDIA_ROOTS=/media/movies,/media/tv
Environment=PLEX_TOKEN=your-plex-token
ExecStart=/opt/retrovue/venv/bin/python -m retrovue.api.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Logging Configuration

### 1. Log Levels

```python
# Development
LOG_LEVEL=DEBUG

# Production
LOG_LEVEL=WARNING

# Testing
LOG_LEVEL=ERROR
```

### 2. Log Format

```python
# JSON logging (production)
{
  "timestamp": "2024-01-15T14:30:00.000Z",
  "level": "info",
  "service": "retrovue",
  "env": "prod",
  "request_id": "123e4567-e89b-12d3-a456-426614174000",
  "message": "Request completed",
  "method": "GET",
  "path": "/api/assets",
  "status_code": 200,
  "process_time_ms": 45.2
}
```

### 3. Secret Redaction

```python
# Automatically redacted fields
PLEX_TOKEN=***REDACTED***
DATABASE_URL=postgresql+psycopg://***:***@localhost:5432/retrovue
```

## Database Configuration

### 1. Connection Pooling

```python
# Development
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT=10

# Production
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_POOL_TIMEOUT=60
```

### 2. Connection String Examples

```bash
# Local development
DATABASE_URL=postgresql+psycopg://retrovue:retrovue@localhost:5432/retrovue

# Production with SSL
DATABASE_URL=postgresql+psycopg://retrovue:secure_password@db-server:5432/retrovue?sslmode=require

# Cloud database
DATABASE_URL=postgresql+psycopg://retrovue:password@retrovue-db.cluster-xyz.us-east-1.rds.amazonaws.com:5432/retrovue
```

## Media Configuration

### 1. Media Roots

```bash
# Single path
MEDIA_ROOTS=/media

# Multiple paths
MEDIA_ROOTS=/media/movies,/media/tv,/media/music

# Network paths
MEDIA_ROOTS=/mnt/nas/movies,/mnt/nas/tv
```

### 2. Plex Integration

```bash
# Plex server configuration
PLEX_TOKEN=your-plex-token-here

# Multiple Plex servers (future)
PLEX_SERVERS=server1:token1,server2:token2
```

## Security Configuration

### 1. CORS Settings

```bash
# Development (permissive)
ALLOWED_ORIGINS=*

# Production (restrictive)
ALLOWED_ORIGINS=https://retrovue.example.com,https://admin.retrovue.example.com

# Multiple environments
ALLOWED_ORIGINS=https://retrovue.example.com,https://staging.retrovue.example.com
```

### 2. Secret Management

```bash
# Use environment variables for secrets
export PLEX_TOKEN="your-secret-token"
export DATABASE_URL="postgresql+psycopg://user:password@host:5432/db"

# Or use a secrets file (not in version control)
echo "PLEX_TOKEN=your-secret-token" > .env.secrets
```

## Performance Configuration

### 1. Database Optimization

```bash
# Connection pooling
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30
DB_POOL_TIMEOUT=60

# Query optimization
ECHO_SQL=false  # Disable in production
```

### 2. Logging Optimization

```bash
# Production logging
LOG_LEVEL=WARNING

# Development logging
LOG_LEVEL=DEBUG
```

## Monitoring Configuration

### 1. Health Checks

```bash
# Health check endpoint
curl http://localhost:8080/api/healthz

# Metrics endpoint
curl http://localhost:8080/api/metrics
```

### 2. Logging Integration

```bash
# Structured logging for log aggregation
LOG_LEVEL=INFO

# JSON format for log parsing
LOG_FORMAT=json
```

## Troubleshooting

### Common Configuration Issues

**1. Database Connection**

```bash
# Check database connectivity
python -c "from retrovue.infra.settings import settings; print(settings.database_url)"

# Test connection
python -c "from retrovue.infra.db import engine; print(engine.execute('SELECT 1').scalar())"
```

**2. Media Path Access**

```bash
# Check media root access
python -c "from retrovue.infra.settings import settings; import os; print([os.path.exists(p) for p in settings.media_roots.split(',')])"
```

**3. Plex Token Validation**

```bash
# Test Plex token
curl -H "X-Plex-Token: $PLEX_TOKEN" "http://plex-server:32400/status/sessions"
```

### Configuration Validation

```python
# Validate configuration
from retrovue.infra.settings import settings

def validate_config():
    """Validate configuration settings."""
    errors = []

    # Check database URL format
    if not settings.database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
        errors.append("Invalid DATABASE_URL format")

    # Check log level
    if settings.log_level not in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
        errors.append("Invalid LOG_LEVEL")

    # Check environment
    if settings.env not in ['dev', 'prod', 'test']:
        errors.append("Invalid ENV")

    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")

    print("Configuration is valid")

if __name__ == "__main__":
    validate_config()
```

## Best Practices

### 1. Environment Separation

- **Development**: Use local database and permissive CORS
- **Staging**: Use staging database with production-like settings
- **Production**: Use secure database with restrictive CORS

### 2. Secret Management

- **Never commit secrets** to version control
- **Use environment variables** for sensitive data
- **Rotate secrets regularly** in production
- **Use secret management services** for complex deployments

### 3. Configuration Validation

- **Validate settings** at startup
- **Use type hints** for configuration
- **Provide clear error messages** for invalid settings
- **Test configuration** in different environments

### 4. Documentation

- **Document all settings** with examples
- **Provide configuration templates** for common scenarios
- **Include troubleshooting guides** for common issues
- **Update documentation** when adding new settings

---

_This configuration system provides flexible and secure settings management for RetroVue across all deployment scenarios._
