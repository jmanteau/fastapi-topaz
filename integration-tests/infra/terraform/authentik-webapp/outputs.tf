output "client_id" {
  description = "OAuth2 client ID for the webapp"
  value       = authentik_provider_oauth2.webapp.client_id
}

output "client_secret" {
  description = "OAuth2 client secret for the webapp"
  value       = authentik_provider_oauth2.webapp.client_secret
  sensitive   = true
}

output "issuer_url" {
  description = "OIDC issuer URL"
  value       = "http://localhost:9000/application/o/webapp/"
}

output "test_users" {
  description = "Test user credentials"
  value = {
    for username, user in authentik_user.test_users :
    username => {
      email    = user.email
      name     = user.name
      password = "(configured in variables)"
    }
  }
}

output "application_slug" {
  description = "Application slug for accessing via Authentik"
  value       = authentik_application.webapp.slug
}

output "setup_complete" {
  description = "Setup completion message"
  value       = <<-EOT

    ========================================
    Authentik Setup Complete!
    ========================================

    Application URL: http://localhost:9000/if/flow/default-authentication-flow/?next=/application/o/${authentik_application.webapp.slug}/

    OAuth2 Configuration:
    - Client ID: ${authentik_provider_oauth2.webapp.client_id}
    - Client Secret: <run 'terraform output -raw client_secret' to view>
    - Issuer: http://localhost:9000/application/o/webapp/
    - Redirect URI: ${var.webapp_redirect_uri}

    Test Users Created:
    ${join("\n", [for u in var.test_users : "  - ${u.username} (${u.email}) - password: ${u.password}"])}

    Next Steps:
    1. Copy client secret to .env:
       echo "OIDC_CLIENT_SECRET=$(terraform output -raw client_secret)" >> ../../.env

    2. Restart webapp:
       cd ../.. && docker-compose restart webapp

    3. Access webapp at http://localhost:8000

    ========================================
  EOT
}
