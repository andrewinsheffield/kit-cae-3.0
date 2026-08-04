# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

"""Extensible materialization and sampling of raw scientific arrays."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

import warp as wp
from pxr import Usd
from warp_simdata.usd import SciArrayValueRequest, scoped_sci_array_value_resolver
from warp_simdata.usd import utils as simusd_utils

__all__ = [
    "ArrayValueProvider",
    "ArrayValueProviderRegistration",
    "effective_array_time_sample",
    "get_array_time_samples",
    "materialize_array",
    "register_array_value_provider",
]


class ArrayValueProvider(Protocol):
    """Provide a virtual raw value and its USD time samples for an array."""

    def can_handle(self, prim: Usd.Prim, instance_name: str) -> bool:
        """Return whether this provider owns the named array."""

    def resolve(self, request: SciArrayValueRequest) -> wp.array:
        """Materialize the requested array on ``request.device``."""

    def get_time_samples(self, prim: Usd.Prim, instance_name: str) -> tuple[float, ...]:
        """Return ordered times at which the array value changes."""


@dataclass(frozen=True)
class _ProviderEntry:
    priority: int
    sequence: int
    registration_id: int
    provider: ArrayValueProvider


_LOCK = RLock()
_PROVIDERS: list[_ProviderEntry] = []
_NEXT_REGISTRATION_ID = 0
_NEXT_SEQUENCE = 0


class ArrayValueProviderRegistration:
    """Lifetime token for a registered array-value provider."""

    def __init__(self, registration_id: int):
        self._registration_id: int | None = registration_id

    def close(self) -> None:
        """Unregister the provider. Repeated calls are harmless."""
        registration_id = self._registration_id
        if registration_id is None:
            return
        self._registration_id = None
        with _LOCK:
            _PROVIDERS[:] = [entry for entry in _PROVIDERS if entry.registration_id != registration_id]


def register_array_value_provider(
    provider: ArrayValueProvider,
    *,
    priority: int = 0,
) -> ArrayValueProviderRegistration:
    """Register a raw-array provider and return its lifetime token.

    Higher-priority providers are considered first. Providers at the same
    priority retain registration order.
    """
    global _NEXT_REGISTRATION_ID, _NEXT_SEQUENCE

    with _LOCK:
        registration_id = _NEXT_REGISTRATION_ID
        _NEXT_REGISTRATION_ID += 1
        sequence = _NEXT_SEQUENCE
        _NEXT_SEQUENCE += 1
        _PROVIDERS.append(
            _ProviderEntry(
                priority=priority,
                sequence=sequence,
                registration_id=registration_id,
                provider=provider,
            )
        )
        _PROVIDERS.sort(key=lambda entry: (-entry.priority, entry.sequence))
    return ArrayValueProviderRegistration(registration_id)


def _providers_snapshot() -> tuple[_ProviderEntry, ...]:
    with _LOCK:
        return tuple(_PROVIDERS)


def _find_provider(prim: Usd.Prim, instance_name: str) -> ArrayValueProvider | None:
    for entry in _providers_snapshot():
        if entry.provider.can_handle(prim, instance_name):
            return entry.provider
    return None


def _resolve_array(request: SciArrayValueRequest) -> wp.array | None:
    provider = _find_provider(request.prim, request.instance_name)
    return provider.resolve(request) if provider is not None else None


def materialize_array(
    prim: Usd.Prim,
    instance_name: str,
    *,
    device: str,
    time_code: Usd.TimeCode,
) -> wp.array:
    """Materialize a raw scientific array through providers or authored USD."""
    with scoped_sci_array_value_resolver(_resolve_array):
        return simusd_utils.get_sci_array(
            prim,
            instance_name,
            time_code,
            device=device,
        )


def get_array_time_samples(prim: Usd.Prim, instance_name: str) -> tuple[float, ...]:
    """Return the samples for a virtual or authored scientific array."""
    provider = _find_provider(prim, instance_name)
    if provider is not None:
        return tuple(sorted({float(value) for value in provider.get_time_samples(prim, instance_name)}))

    attr = prim.GetAttribute(f"omni:sci:array:{instance_name}:value")
    return tuple(float(value) for value in attr.GetTimeSamples()) if attr else ()


def effective_array_time_sample(
    prim: Usd.Prim,
    instance_name: str,
    time_code: Usd.TimeCode,
) -> float | None:
    """Return the held sample used by an array, or ``None`` when static."""
    samples = get_array_time_samples(prim, instance_name)
    if not samples:
        return None
    if time_code.IsDefault() or time_code.IsEarliestTime():
        return samples[0]

    requested = time_code.GetValue()
    earlier = [sample for sample in samples if sample <= requested]
    return earlier[-1] if earlier else samples[0]
