package webapp.DELETE.api.documents.__id

import rego.v1
import data.webapp.common

default allowed := false

allowed if { common.is_document_owner }
