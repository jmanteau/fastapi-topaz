package webapp.POST.api.documents

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.user_sub }
