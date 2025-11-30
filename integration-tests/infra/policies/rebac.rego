package webapp.check

import future.keywords
import data.webapp.common

# ReBAC permission checks for documents

# allowed: Main decision point that routes to specific permission checks
# This is called by require_rebac_allowed with input.resource.relation
default allowed := false

allowed if {
    input.resource.relation == "can_read"
    can_read
}

allowed if {
    input.resource.relation == "can_write"
    can_write
}

allowed if {
    input.resource.relation == "can_share"
    can_share
}

allowed if {
    input.resource.relation == "can_delete"
    can_delete
}

# can_read: User can read document
default can_read := false

can_read if {
    input.resource.object_type == "document"
    common.can_read_document
}

# can_write: User can write/update document
default can_write := false

can_write if {
    input.resource.object_type == "document"
    common.can_write_document
}

# can_share: Only owner can share document
default can_share := false

can_share if {
    input.resource.object_type == "document"
    common.is_document_owner
    not common.user_in_restricted_country
}

# can_delete: Only owner can delete document
default can_delete := false

can_delete if {
    input.resource.object_type == "document"
    common.is_document_owner
    not common.user_in_restricted_country
}
