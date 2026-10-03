from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Obj",
]


@dataclass
class Obj:
    object_id: str
    object_type: str
