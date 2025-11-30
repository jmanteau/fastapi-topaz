package webapp

import future.keywords
import data.webapp.common

# Display state map for UI elements

# Document actions visibility/enablement

# View button - visible and enabled if can read
GET.api.documents.__id.visible := common.can_read_document
GET.api.documents.__id.enabled := common.can_read_document

# Edit button - visible and enabled if can write
PUT.api.documents.__id.visible := common.can_write_document
PUT.api.documents.__id.enabled := common.can_write_document

# Delete button - visible and enabled if owner
DELETE.api.documents.__id.visible := common.is_document_owner
DELETE.api.documents.__id.enabled if {
    common.is_document_owner
    not common.user_in_restricted_country
}

# Share button - visible and enabled if owner
POST.api.shares.visible := common.is_document_owner
POST.api.shares.enabled if {
    common.is_document_owner
    not common.user_in_restricted_country
}

# Create document button - always visible, enabled if not restricted
POST.api.documents.visible := true
POST.api.documents.enabled if {
    not common.user_in_restricted_country
}
