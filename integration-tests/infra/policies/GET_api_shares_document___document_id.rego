package webapp.GET.api.shares.document.__document_id

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.user_sub }
