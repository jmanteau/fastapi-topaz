package webapp.common

import future.keywords
import rego.v1

# Helper to get user sub from resource context (since "user" key is reserved by Aserto SDK)
user_sub := input.resource.current_user.sub

# Restricted countries
restricted_countries := {"CN", "KP", "IR"}

# Check if user is in restricted country
user_in_restricted_country if {
    input.resource.user_location.country_code
    restricted_countries[input.resource.user_location.country_code]
}

# Check if user is document owner
is_document_owner if {
    user_sub
    input.resource.owner_id == user_sub
}

# Check if document is public
is_public_document if {
    input.resource.is_public == true
}

# Check if user has share permission
has_share_permission(permission) if {
    user_sub
    some share in input.resource.shares
    share.user_id == user_sub
    share.permission == permission
}

# User can read document if:
# - Not in restricted country, AND
# - Is owner
can_read_document if {
    not user_in_restricted_country
    is_document_owner
}

# Or if public document
can_read_document if {
    not user_in_restricted_country
    is_public_document
}

# Or if has read permission
can_read_document if {
    not user_in_restricted_country
    has_share_permission("read")
}

# Or if has write permission (implies read)
can_read_document if {
    not user_in_restricted_country
    has_share_permission("write")
}

# User can write document if:
# - Not in restricted country, AND
# - Is owner
can_write_document if {
    not user_in_restricted_country
    is_document_owner
}

# Or has write share
can_write_document if {
    not user_in_restricted_country
    has_share_permission("write")
}
