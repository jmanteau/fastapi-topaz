package webapp.GET.api.folders.__parent_id.subfolders.__child_id

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.user_sub }
