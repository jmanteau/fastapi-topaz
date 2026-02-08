package webapp.PUT.api.documents.__id

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.can_write_document }
