from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WardProfile:
    name: str
    capacity: int
    base_occupancy: int
    nurses: int
    doctors: int
    ventilators: int
    monitors: int


WARD_PROFILES = [
    WardProfile("ICU", 24, 12, 10, 4, 10, 18),
    WardProfile("Emergency", 32, 16, 12, 4, 4, 16),
    WardProfile("General", 60, 30, 16, 5, 2, 20),
    WardProfile("Surgery", 28, 14, 9, 3, 6, 14),
    WardProfile("Maternity", 22, 10, 7, 2, 1, 10),
]
