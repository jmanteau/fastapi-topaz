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


@dataclass(frozen=True)
class AuthorizationError(Exception):
    policy_instance_name: str
    policy_path: str
