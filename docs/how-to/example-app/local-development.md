# How to Set Up Local Development

Configure the example application development environment.

All commands run from the repository root.

## Prerequisites

- Docker with Docker Compose, **or** Podman (with `docker-compose` or `podman compose`)
- Make
- Python 3.11+
- Terraform **or** OpenTofu (for OIDC setup)
- uv (Python package manager)
- `127.0.0.1 authentik-server` in your hosts file. See [Hosts File Configuration](../../tutorials/example-app/01-setup.md#hosts-file-configuration).

Check them:

```bash
make int-doctor
```

`int-doctor` prints the compose command, Terraform binary, and `DOCKER_HOST` it detected, then fails with a fix-it message if anything is missing.

### Podman and OpenTofu

The Makefile detects these, so no shell setup is needed:

- **Compose**: tries `docker compose`, then `docker-compose`, then `podman compose`.
- **Terraform**: uses `terraform`, otherwise `tofu`.
- **Podman socket**: if `DOCKER_HOST` is unset and no Docker daemon answers, it points `DOCKER_HOST` at the Podman machine socket.

If detection picks the wrong thing, copy `local.mk.example` to `local.mk` (gitignored) and set `COMPOSE`, `TF`, or `DOCKER_HOST`.

## Quick Setup

```bash
make int-setup
```

This checks prerequisites, generates TLS certificates, builds and starts all services, runs migrations, and configures OIDC with Terraform.

## Manual Setup

### 1. Start Infrastructure

```bash
make int-certs
make int-build
make int-up
```

Wait ~15 seconds for services to initialize.

### 2. Run Database Migrations

```bash
make int-db-upgrade
```

### 3. Configure OIDC

```bash
make int-tf-init
make int-tf-apply
```

`int-tf-apply` writes `integration-tests/.env.oidc` and recreates the webapp container so it picks up the new client credentials.

### 4. Verify Services

```bash
make int-status
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
# Edit code in integration-tests/webapp/app/
make int-restart-webapp
```

### Modify Policies

```bash
# Edit files in integration-tests/infra/policies/
make int-topaz-reload
```

### View Logs

```bash
make int-logs-webapp
make int-logs-topaz
make int-logs-authentik
```

### Run Tests

```bash
# Library unit tests
make test

# End-to-end tests against the running stack
make e2e

# Live Topaz tests
make live-test
```

## Useful Commands

```bash
# Restart all
make int-restart

# Clean restart
make int-clean && make int-setup

# Database shell
make int-db-shell

# Authentik admin password
make int-auth-password
```

## See Also

- [Setup Tutorial](../../tutorials/example-app/01-setup.md) - Complete setup guide
- [Authentik Setup](authentik-setup.md) - OIDC configuration details
- [Troubleshooting](../troubleshooting.md#integration-environment) - Integration environment issues
