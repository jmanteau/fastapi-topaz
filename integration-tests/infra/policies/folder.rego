package webapp.api.folders

import future.keywords
import data.webapp.common

# Default: deny all
default allowed := false

# GET /api/folders (list - no id in path)
allowed if {
    # All authenticated users can list their folders
    common.user_sub
    not input.resource.id  # Only for list endpoint without ID
}

# POST /api/folders
allowed if {
    # All authenticated users can create folders
    common.user_sub
    not common.user_in_restricted_country
    not input.resource.owner_id  # Only for create endpoint (no existing owner)
}

# GET /api/folders/{id}
allowed if {
    # Only owner can access folder
    common.user_sub
    input.resource.owner_id == common.user_sub
}

# PUT /api/folders/{id}
allowed if {
    # Only owner can update folder
    common.user_sub
    input.resource.owner_id == common.user_sub
    not common.user_in_restricted_country
}

# DELETE /api/folders/{id}
allowed if {
    # Only owner can delete folder
    common.user_sub
    input.resource.owner_id == common.user_sub
    not common.user_in_restricted_country
}
