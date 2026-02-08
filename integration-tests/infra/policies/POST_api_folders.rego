package webapp.POST.api.folders

import rego.v1
import data.webapp.common

default allowed := false

allowed if {
    common.user_sub
    not common.user_in_restricted_country
}
