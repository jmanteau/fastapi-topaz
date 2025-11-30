.PHONY: help build up down logs restart clean db-migrate db-upgrade db-downgrade test setup reload-webapp status sync-oidc-secret

help:
	@echo "FastAPI-Topaz Test Webapp - Available Commands"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make build          - Build all Docker images"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make logs           - View logs from all services"
	@echo "  make logs-webapp    - View webapp logs only"
	@echo "  make logs-topaz     - View Topaz logs only"
	@echo "  make logs-recent    - View logs from last 2 minutes (all services)"
	@echo "  make logs-webapp-recent - View webapp logs from last 2 minutes"
	@echo "  make reload-webapp  - Reload webapp only"
	@echo "  make clean          - Stop services and remove volumes"
	@echo ""
	@echo "Database Commands:"
	@echo "  make db-migrate     - Generate new migration"
	@echo "  make db-upgrade     - Run database migrations"
	@echo "  make db-downgrade   - Rollback last migration"
	@echo "  make db-shell       - Open PostgreSQL shell"
	@echo ""
	@echo "Development Commands:"
	@echo "  make setup          - Initial setup (build + up + migrate)"
	@echo "  make test           - Run tests"
	@echo "  make shell          - Open webapp container shell"
	@echo "  make check-health   - Check health of all services"
	@echo "  make status         - Show service URLs and status"
	@echo ""
	@echo "Topaz Commands:"
	@echo "  make topaz-shell    - Open Topaz container shell"
	@echo "  make topaz-reload   - Reload Topaz policies"
	@echo ""
	@echo "Authentik Commands:"
	@echo "  make auth-password  - Get Authentik bootstrap password"
	@echo "  make auth-shell     - Open Authentik server shell"
	@echo "  make wipe-auth      - Wipe Authentik data (destructive)"
	@echo ""
	@echo "Terraform Commands:"
	@echo "  make tf-init        - Initialize Terraform"
	@echo "  make tf-plan        - Plan Terraform changes"
	@echo "  make tf-apply       - Apply Terraform (setup OIDC + users)"
	@echo "  make tf-destroy     - Destroy Terraform resources"
	@echo "  make tf-output      - Show Terraform outputs"
	@echo "  make sync-oidc-secret - Sync OIDC secret from Terraform to .env"

# Docker commands
build:
	@if [ ! -f .env ]; then \
		echo "Creating .env from templates..."; \
		cat env.authentik .env.example > .env 2>/dev/null || cat env.authentik > .env; \
	fi
	docker-compose build

up:
	@if [ ! -f .env ]; then \
		echo "Creating .env from templates..."; \
		cat env.authentik .env.example > .env 2>/dev/null || cat env.authentik > .env; \
	fi
	docker-compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@echo "Services started! Access:"
	@echo "  - Webapp: http://localhost:8000"
	@echo "  - Authentik: http://localhost:9000"
	@echo "  - Mock Location API: http://localhost:8001"

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f

logs-webapp:
	docker-compose logs -f webapp

logs-topaz:
	docker-compose logs -f topaz

logs-authentik:
	docker-compose logs -f authentik-server

logs-recent:
	docker-compose logs --since 2m

logs-webapp-recent:
	docker-compose logs --since 2m webapp

reload-webapp:
	@echo "Rebuilding and reloading webapp..."
	docker-compose build webapp
	docker-compose up -d webapp
	@echo "✓ Webapp rebuilt and reloaded"

clean:
	docker-compose down -v
	rm -f .env
	@echo "All services stopped and volumes removed"

# Database commands
db-migrate:
	docker-compose exec webapp alembic revision --autogenerate -m "$(msg)"

db-upgrade:
	docker-compose exec webapp alembic upgrade head

db-downgrade:
	docker-compose exec webapp alembic downgrade -1

db-shell:
	docker-compose exec postgres psql -U webapp -d webapp_db

# Development commands
setup: build up
	@echo "Waiting for database to be ready..."
	@sleep 5
	@echo "Running database migrations..."
	@make db-upgrade
	@echo ""
	@echo "Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Configure Authentik at http://localhost:9000"
	@echo "   - Default admin: akadmin / (check logs for password)"
	@echo "   - Create OIDC application 'webapp'"
	@echo "   - Update .env with client ID and secret"
	@echo "2. Access webapp at http://localhost:8000"

test:
	cd webapp && uv run pytest -v

shell:
	docker-compose exec webapp /bin/bash

check-health:
	@echo "Checking service health..."
	@curl -f http://localhost:8000/health && echo "✓ Webapp healthy"
	@curl -f http://localhost:8001/health && echo "✓ Mock Location API healthy"
	@curl -f http://localhost:9000/-/health/ready/ && echo "✓ Authentik healthy"

# Topaz commands
topaz-shell:
	docker-compose exec topaz /bin/sh

topaz-reload:
	docker-compose restart topaz
	@echo "Topaz restarted with updated policies"

# Development shortcuts
dev: up logs-webapp

stop: down

status:
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "FastAPI-Topaz POC - Service Status"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "📱 Web Services:"
	@echo "  • Webapp:          http://localhost:8000"
	@echo "  • Swagger API:     http://localhost:8000/docs"
	@echo "  • Authentik:       http://localhost:9000"
	@echo "  • Location API:    http://localhost:8001"
	@echo ""
	@echo "🔒 Authorization:"
	@echo "  • Topaz Authorizer:  grpc://localhost:8282"
	@echo "  • Topaz Gateway:     http://localhost:8383"
	@echo ""
	@echo "🗄️  Databases:"
	@echo "  • Webapp DB:         postgresql://localhost:5432/webapp_db"
	@echo "  • Authentik DB:      postgresql://localhost:5433"
	@echo ""
	@echo "🔍 Container Status:"
	@docker-compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Containers not running"
	@echo ""
	@echo "💚 Health Checks:"
	@printf "  • Webapp:           "
	@curl -sf http://localhost:8000/health >/dev/null 2>&1 && echo "✓ Healthy" || echo "✗ Unhealthy"
	@printf "  • Mock Location:    "
	@curl -sf http://localhost:8001/health >/dev/null 2>&1 && echo "✓ Healthy" || echo "✗ Unhealthy"
	@printf "  • Authentik:        "
	@curl -sf http://localhost:9000/-/health/ready/ >/dev/null 2>&1 && echo "✓ Healthy" || echo "✗ Unhealthy"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Run 'make logs' to view logs, 'make help' for more commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Authentik commands
auth-password:
	@echo "Authentik Bootstrap Password:"
	@grep '^AUTHENTIK_BOOTSTRAP_PASSWORD' env.authentik | cut -d= -f2

auth-shell:
	docker-compose exec authentik-server /bin/bash

wipe-auth:
	@echo "⚠️  WARNING: This will delete ALL Authentik data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose stop authentik-postgres authentik-redis authentik-server authentik-worker; \
		docker-compose rm -f authentik-postgres authentik-redis authentik-server authentik-worker; \
		docker volume rm $$(docker volume ls -q --filter name=authentik_postgres_data) || true; \
		docker volume rm $$(docker volume ls -q --filter name=authentik_redis) || true; \
		rm -rf ./infra/authentik/media/* ./infra/authentik/custom-templates/* ./infra/authentik/certs/* || true; \
		echo "✓ Authentik data wiped"; \
	fi

# Terraform commands
TF_DIR := infra/terraform/authentik-webapp

tf-init:
	@echo "Initializing Terraform..."
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform init

tf-plan:
	@echo "Planning Terraform changes..."
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform plan

tf-apply:
	@echo "Applying Terraform configuration..."
	@echo "This will create OIDC provider and test users in Authentik"
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform apply -auto-approve
	@echo ""
	@echo "✓ Terraform applied successfully!"
	@echo ""
	@make sync-oidc-secret
	@echo ""
	@echo "Restarting webapp..."
	@docker-compose restart webapp
	@echo ""
	@echo "========================================="
	@echo "Setup complete! Test users created:"
	@echo "  - alice@example.com / password"
	@echo "  - bob@example.com / password"
	@echo "  - charlie@example.com / password"
	@echo ""
	@echo "Access webapp: http://localhost:8000"
	@echo "========================================="

sync-oidc-secret:
	@echo "Syncing OIDC client secret from Terraform to .env..."
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && \
	CLIENT_SECRET=$$(terraform output -raw client_secret 2>/dev/null) && \
	if [ -z "$$CLIENT_SECRET" ]; then \
		echo "✗ Error: Could not get client secret from Terraform. Run 'make tf-apply' first."; \
		exit 1; \
	fi && \
	cd ../../.. && \
	sed -i.bak '/^OIDC_CLIENT_SECRET=/d' .env && \
	sed -i.bak '/^OIDC_CLIENT_ID=/d' .env && \
	rm -f .env.bak && \
	echo "OIDC_CLIENT_ID=webapp-client" >> .env && \
	echo "OIDC_CLIENT_SECRET=$$CLIENT_SECRET" >> .env && \
	echo "✓ .env updated with OIDC credentials"

tf-destroy:
	@echo "Destroying Terraform resources..."
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform destroy -auto-approve

tf-output:
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform output

# Complete setup with Terraform
setup-full: build up
	@echo "Waiting for services to be ready..."
	@sleep 15
	@echo "Running database migrations..."
	@make db-upgrade
	@echo "Waiting for Authentik to be fully ready..."
	@sleep 10
	@echo "Applying Terraform configuration..."
	@make tf-init
	@make tf-apply
	@echo ""
	@echo "========================================="
	@echo "Full setup complete!"
	@echo "========================================="
