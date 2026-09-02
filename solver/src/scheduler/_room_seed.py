"""Construct a useful physical-room incumbent for the room solve stage."""

from __future__ import annotations

from collections import defaultdict

from .instance import OFF_CAMPUS, is_placeholder
from .model import AssignmentKey, BuiltModel


def seed_physical_rooms(built: BuiltModel, values: list[float]) -> list[float]:
    """Greedily move off-campus assignments into available physical rooms."""
    seeded = list(values)
    overlaps: dict[str, set[str]] = defaultdict(set)
    for first, second in built.instance.overlapping_timeslots:
        overlaps[first].add(second)
        overlaps[second].add(first)

    occupied: dict[tuple[str, str], set[str]] = defaultdict(set)
    off_campus: list[tuple[int, AssignmentKey, list[tuple[str, int]]]] = []
    for key, variable in built.assign.items():
        if seeded[variable] < 0.5:
            continue
        semester, slot, room = key.semester, key.timeslot, key.classroom
        if room != OFF_CAMPUS:
            if not is_placeholder(slot):
                occupied[(room, semester)].add(slot)
            continue
        if is_placeholder(slot):
            continue

        candidates = [
            (candidate, candidate_variable)
            for candidate in sorted(built.instance.classroom_capacity)
            if (
                candidate_variable := built.assign.get(
                    AssignmentKey(
                        key.professor,
                        key.course,
                        key.section,
                        key.semester,
                        key.time_of_day,
                        key.timeslot,
                        candidate,
                    )
                )
            )
            is not None
        ]
        off_campus.append((variable, key, candidates))

    off_campus.sort(key=lambda item: (len(item[2]), item[1]))
    for old_variable, key, candidates in off_campus:
        semester, slot = key.semester, key.timeslot
        for room, new_variable in candidates:
            used = occupied[(room, semester)]
            if slot in used or overlaps[slot].intersection(used):
                continue
            seeded[new_variable] = seeded[old_variable]
            seeded[old_variable] = 0.0
            used.add(slot)
            break

    return seeded
