package webapp.DELETE.api.folders.__id

import rego.v1
import data.webapp.common

default allowed := false

allowed if {
    common.user_sub
    input.resource.owner_id == common.user_sub
    not common.user_in_restricted_country
}
