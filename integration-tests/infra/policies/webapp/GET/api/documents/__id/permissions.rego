package webapp.GET.api.documents.__id.permissions

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.user_sub }
