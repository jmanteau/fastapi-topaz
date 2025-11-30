package webapp.api.documents

import future.keywords
import data.webapp.common

# Default: deny all
default allowed := false

# GET /api/documents/{id}
allowed if {
    common.can_read_document
}

# POST /api/documents
allowed if {
    # All authenticated users can create documents
    common.user_sub
}

# PUT /api/documents/{id}
allowed if {
    common.can_write_document
}

# DELETE /api/documents/{id}
allowed if {
    common.is_document_owner
}
