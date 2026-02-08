package webapp.GET.api.documents.__id

import rego.v1
import data.webapp.common

default allowed := false

# Allow when document exists and user can read it
allowed if { common.can_read_document }

# Allow when document not found (let route handler return 404)
allowed if {
    common.user_sub
    not input.resource.owner_id
}
