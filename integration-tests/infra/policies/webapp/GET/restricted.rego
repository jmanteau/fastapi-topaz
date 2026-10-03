package webapp.GET.restricted

import rego.v1

# Static mount /restricted: denied to everyone, so e2e can prove the
# middleware evaluates the mount's own policy
default allowed := false
