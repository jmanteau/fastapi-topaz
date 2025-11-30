# How to Configure Authentik OIDC

Configure OIDC authentication using Authentik and Terraform automation.

## Automated Setup (Recommended)

```bash
make tf-init
make tf-apply
```

Terraform creates:
- OIDC provider
- OAuth2 application
- Test users (alice, bob, charlie)
- Updates `.env` with client secret

## Manual Setup

### 1. Access Authentik Admin

```bash
make auth-password
```

Open http://authentik-server:9000 and login as `akadmin`.

### 2. Create OIDC Provider

1. Admin > Providers > Create
2. Select OAuth2/OpenID Provider
3. Configure:
   - Name: webapp-provider
   - Authorization flow: default-provider-authorization-implicit-consent
   - Client type: Confidential
   - Client ID: webapp
   - Redirect URIs: http://localhost:8000/auth/callback

### 3. Create Application

1. Admin > Applications > Create
2. Configure:
   - Name: FastAPI Topaz Webapp
   - Slug: webapp
   - Provider: webapp-provider
   - Launch URL: http://localhost:8000

### 4. Create Test Users

1. Directory > Users > Create
2. For each user:
   - Username: alice, bob, charlie
   - Email: alice@example.com, etc.
   - Password: password

### 5. Update .env

```bash
OIDC_CLIENT_ID=webapp
OIDC_CLIENT_SECRET=<from provider>
OIDC_ISSUER=http://authentik-server:9000/application/o/webapp/
```

### 6. Restart Webapp

```bash
docker-compose restart webapp
```

## Terraform Configuration

### Provider Setup

File: `terraform/authentik-webapp/providers.tf`

```hcl
terraform {
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = "~> 2024.0"
    }
  }
}

provider "authentik" {
  url   = "http://localhost:9000"
  token = var.authentik_token
}
```

### Add Users

File: `terraform/authentik-webapp/variables.tf`

```hcl
variable "test_users" {
  default = [
    {
      username = "alice"
      name     = "Alice Smith"
      email    = "alice@example.com"
      password = "password"
    },
    {
      username = "bob"
      name     = "Bob Jones"
      email    = "bob@example.com"
      password = "password"
    },
  ]
}
```

Apply changes:
```bash
make tf-apply
```

## Bootstrap Token

The bootstrap token enables Terraform API access:

```bash
# env.authentik
AUTHENTIK_BOOTSTRAP_TOKEN=changeme-bootstrap-token
AUTHENTIK_BOOTSTRAP_PASSWORD=adminpass
```

Terraform uses this token:
```bash
export TF_VAR_authentik_token=$(grep AUTHENTIK_BOOTSTRAP_TOKEN env.authentik | cut -d= -f2)
```

## Troubleshooting

### Cannot connect to Authentik

```bash
curl http://localhost:9000/-/health/ready/
```

### Token invalid

```bash
grep AUTHENTIK_BOOTSTRAP_TOKEN env.authentik
make tf-init
```

### Reset Authentik

```bash
make wipe-auth
make up
make tf-apply
```

## Security Notes

For production:
1. Generate strong random secrets
2. Enable HTTPS
3. Use environment variable injection
4. Rotate bootstrap token
5. Restrict admin access

## See Also

- [Setup Tutorial](../../tutorials/example-app/01-setup.md) - Complete setup
- [Authentication Tutorial](../../tutorials/example-app/02-authentication.md) - SSO flow
- [SSO Concepts](../../explanation/sso-concepts.md) - OIDC architecture
