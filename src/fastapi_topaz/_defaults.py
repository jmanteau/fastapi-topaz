from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from aserto.client import Identity, ResourceContext

__all__ = [
    "AuthorizationError",
    "IdentityMapper",
    "Obj",
    "ObjectMapper",
    "ResourceMapper",
    "StringMapper",
]


@dataclass
class Obj:
    object_id: str
    object_type: str


IdentityMapper = Callable[[], Identity]
StringMapper = Callable[[], str]
ObjectMapper = Callable[[], Obj]
ResourceMapper = Callable[[], ResourceContext]


# Not frozen: Python assigns __traceback__ / __context__ on raised exceptions
# (e.g. when re-raised through a @contextmanager); eq=False keeps identity hashing
@dataclass(eq=False)
class AuthorizationError(Exception):
    policy_instance_name: str
    policy_path: str
