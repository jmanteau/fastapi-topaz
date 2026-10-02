package webapp.GET.files

import rego.v1
import data.webapp.common

# Static mount /files: any authenticated user
default allowed := false

allowed if { common.user_sub }
