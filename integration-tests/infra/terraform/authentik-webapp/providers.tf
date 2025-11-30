terraform {
  required_providers {
    authentik = {
      source  = "goauthentik/authentik"
      version = ">= 2025.2.0"
    }
  }
}

provider "authentik" {
  url   = var.authentik_url
  token = var.authentik_token
}
