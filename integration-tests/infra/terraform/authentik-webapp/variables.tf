variable "authentik_url" {
  description = "URL for the Authentik server"
  type        = string
  default     = "http://localhost:9000"
}

variable "authentik_token" {
  description = "API token for Authentik (bootstrap token from env.authentik)"
  type        = string
  sensitive   = true
}

variable "webapp_redirect_uri" {
  description = "OAuth2 redirect URI for the webapp"
  type        = string
  default     = "http://localhost:8000/auth/callback"
}

variable "test_users" {
  description = "List of test users to create"
  type = list(object({
    username = string
    name     = string
    email    = string
    password = string
  }))
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
    {
      username = "charlie"
      name     = "Charlie Brown"
      email    = "charlie@example.com"
      password = "password"
    }
  ]
}
