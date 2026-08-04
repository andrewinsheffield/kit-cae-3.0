# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import asyncio
from dataclasses import dataclass, field
from typing import Any

import carb.eventdispatcher
import omni.kit.app
import omni.usd
from omni.cae.testing import get_vtrt_array_as_numpy
from omni.cae.viz.controller import EVT_OPERATOR_COMPLETE
from omni.cae.viz.listener import Listener


def read_rt_array(rt_attr, label: str | None = None, *, require_populated: bool = True):
    """Read a UsdRT array attribute after an operator completion barrier."""
    label = label or str(rt_attr.GetPath() if rt_attr is not None else "RT array")
    assert rt_attr is not None, f"{label} attribute should exist"
    assert rt_attr.IsValid(), f"{label} attribute should be valid"

    values = get_vtrt_array_as_numpy(rt_attr)
    assert values is not None, f"{label} attribute should have readable CPU/GPU data"
    if require_populated:
        assert len(values) > 0, f"{label} attribute should be populated"
    return values


@dataclass
class _OperatorCompletionWaiter:
    prim_path: str
    operator: str | None = None
    allow_failure: bool = False
    max_updates: int = 100
    _stage_id: int | None = field(default=None, init=False)
    _future: asyncio.Future | None = field(default=None, init=False)
    _subscription: Any = field(default=None, init=False)
    result: dict | None = field(default=None, init=False)

    async def __aenter__(self):
        await Listener.wait_for_sync_idle()

        self._stage_id = omni.usd.get_context().get_stage_id()
        self._future = asyncio.get_event_loop().create_future()

        event_dispatcher = carb.eventdispatcher.get_eventdispatcher()
        self._subscription = event_dispatcher.observe_event(
            observer_name=f"omni.cae.viz.tests.wait_for_operator_complete:{self.prim_path}",
            event_name=f"{EVT_OPERATOR_COMPLETE}:immediate",
            filter={"prim_path": self.prim_path},
            on_event=self._on_event,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self._reset()
            return False

        assert self._future is not None
        app = omni.kit.app.get_app()
        try:
            for _ in range(self.max_updates):
                if self._future.done():
                    self.result = self._future.result()
                    # EVT_OPERATOR_COMPLETE is observed on the immediate event.
                    # Let the deferred app update run once before tests inspect
                    # Fabric/UsdRT output written by the operator.
                    await app.next_update_async()
                    return False
                await app.next_update_async()
                await asyncio.sleep(0.01)

            raise AssertionError(f"Timed out waiting for {self.operator or 'operator'} completion on {self.prim_path}")
        finally:
            self._reset()

    def _on_event(self, event):
        if self._future is None or self._future.done():
            return
        if self._stage_id is not None and event.get("stage_id") != self._stage_id:
            return
        if self.operator is not None and event.get("operator") != self.operator:
            return

        payload = event.payload
        if not self.allow_failure and not payload.get("success", False):
            self._future.set_exception(
                AssertionError(f"{payload.get('operator', 'operator')} failed for {payload.get('prim_path')}")
            )
            return

        self._future.set_result(payload)

    def _reset(self):
        if self._subscription is not None:
            self._subscription.reset()
            self._subscription = None


def wait_for_operator_complete(
    prim_path: str, *, operator: str | None = None, allow_failure: bool = False, max_updates: int = 100
):
    """Subscribe before mutating USD, then wait for the matching operator completion on context exit."""
    return _OperatorCompletionWaiter(
        prim_path=prim_path,
        operator=operator,
        allow_failure=allow_failure,
        max_updates=max_updates,
    )
