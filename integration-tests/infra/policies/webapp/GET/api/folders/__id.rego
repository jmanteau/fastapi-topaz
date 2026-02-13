package webapp.GET.api.folders.__id

import rego.v1
import data.webapp.common

default allowed := false

allowed if {
    common.user_sub
    input.resource.owner_id == common.user_sub
}
