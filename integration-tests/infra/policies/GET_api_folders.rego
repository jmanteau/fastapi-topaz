package webapp.GET.api.folders

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.user_sub }
