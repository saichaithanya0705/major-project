"""
Process-wide resource leases for live multi-agent execution.

The scheduler chooses safe batches within one plan. ResourceCoordinator extends
that safety across concurrent plans in the same process.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from models.orchestrator_contracts import ResourceLock, normalize_resource_locks


class ResourceCoordinator:
    def __init__(self) -> None:
        self._locks = {resource: asyncio.Lock() for resource in ResourceLock}

    async def acquire(self, resources: tuple[ResourceLock, ...]) -> "ResourceLease":
        ordered = tuple(sorted(normalize_resource_locks(resources), key=lambda item: item.value))
        acquired: list[ResourceLock] = []
        try:
            for resource in ordered:
                await self._locks[resource].acquire()
                acquired.append(resource)
        except BaseException:
            for resource in reversed(acquired):
                self._locks[resource].release()
            raise
        return ResourceLease(self, tuple(acquired))

    def held_resources(self) -> tuple[ResourceLock, ...]:
        return tuple(resource for resource, lock in self._locks.items() if lock.locked())

    def _release(self, resources: tuple[ResourceLock, ...]) -> None:
        for resource in reversed(resources):
            lock = self._locks[resource]
            if lock.locked():
                lock.release()


@dataclass(frozen=True, slots=True)
class ResourceLease:
    coordinator: ResourceCoordinator
    resources: tuple[ResourceLock, ...]

    async def __aenter__(self) -> "ResourceLease":
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.coordinator._release(self.resources)
