# How to Set Up Local Development

Configure the example application development environment.

## Prerequisites

- Docker and Docker Compose
- Make
- Python 3.11+
- Terraform (for OIDC setup)
- uv (Python package manager)

## Quick Setup

```bash
cd integration-tests
make setup-full
```

This starts all services and configures OIDC automatically.

## Manual Setup

### 1. Start Infrastructure

```bash
make build
make up
```

Wait ~15 seconds for services to initialize.

### 2. Run Database Migrations

```bash
make db-upgrade
```

### 3. Configure OIDC

```bash
make tf-init
make tf-apply
```

### 4. Verify Services

```bash
make check-health
```

## Service URLs

| Service | URL | Description |
|---------|-----|-------------|
| Webapp | http://localhost:8000 | Application |
| Authentik | http://authentik-server:9000 | OIDC admin |
| Topaz | http://localhost:8282 | Authorization API |
| Mock Location | http://localhost:8001 | Geographic API |

## Development Workflow

### Make Changes to Webapp

```bash
# Edit code in webapp/app/
# Rebuild and restart
docker-compose build webapp
docker-compose up -d webapp
```

### Modify Policies

```bash
# Edit files in policies/
# Restart Topaz
docker-compose restart topaz
```

### View Logs

```bash
make logs-webapp
make logs-topaz
make logs-authentik
```

### Run Tests

```bash
# Unit tests
cd webapp
uv run pytest tests/ -v

# Integration tests
cd integration-tests
uv run pytest tests/ -v
```

## Useful Commands

```bash
# Restart all
make restart

# Clean restart
make clean && make setup-full

# Database shell
make db-shell

# Authentik admin password
make auth-password
```

## See Also

- [Setup Tutorial](../../tutorials/example-app/01-setup.md) - Complete setup guide
- [Authentik Setup](authentik-setup.md) - OIDC configuration details
