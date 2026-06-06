from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from control.bridge import ControlAdapterError, build_control_commands, execute_control_plan
from models.action_plan import ActionPlan, ActionStep


def _sample_plan() -> ActionPlan:
    return ActionPlan(
        equipment_id="M-12345",
        generated_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        steps=[
            ActionStep(
                step_number=1,
                action="Stop machine immediately after current cycle",
                responsible_role="maintenance_technician",
                priority="P1",
                estimated_duration_minutes=5,
                sop_reference="SOP-MNT-001.md::chunk::2",
            ),
            ActionStep(
                step_number=2,
                action="Remove and inspect tool for wear",
                responsible_role="maintenance_technician",
                priority="P1",
                estimated_duration_minutes=15,
                sop_reference="SOP-MNT-001.md::chunk::3",
            ),
            ActionStep(
                step_number=3,
                action="Schedule follow-up inspection",
                responsible_role="shift_supervisor",
                priority="P2",
                estimated_duration_minutes=20,
                sop_reference="SOP-MNT-001.md::chunk::4",
            ),
        ],
        escalation_required=True,
        escalation_reason="Tool wear is above the safe operating threshold.",
    )


def test_build_control_commands_maps_safety_steps():
    commands = build_control_commands(_sample_plan())

    assert [c.command_type for c in commands] == [
        "STOP_MACHINE",
        "LOCKOUT_TAGOUT",
        "SCHEDULE_INSPECTION",
        "NOTIFY_SUPERVISOR",
    ]
    assert all(c.dry_run for c in commands)


def test_execute_control_plan_rejects_live_mode():
    with pytest.raises(ControlAdapterError, match="Live industrial control writes"):
        execute_control_plan(_sample_plan(), "cid-001", dry_run=False)


def test_execute_control_plan_invokes_cpp_adapter():
    adapter_payload = {
        "equipment_id": "M-12345",
        "command_type": "STOP_MACHINE",
        "status": "accepted",
        "dry_run": True,
        "adapter": "cpp-control-adapter-v1",
        "message": "Dry-run accepted STOP_MACHINE",
        "correlation_id": "cid-001",
    }
    completed = MagicMock(returncode=0, stdout=json.dumps(adapter_payload), stderr="")

    with patch("control.bridge.Path.exists", return_value=True), \
         patch("control.bridge.subprocess.run", return_value=completed) as run:
        result = execute_control_plan(_sample_plan(), "cid-001")

    assert result.command_count == 4
    assert result.results[0].adapter == "cpp-control-adapter-v1"
    assert run.call_count == 4
