from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.config import get_settings
from models.action_plan import ActionPlan
from models.control_command import ControlCommand, ControlExecutionResult, ControlPlanResult

_ACTION_STOP_HINTS = ("stop", "shutdown", "halt", "pause", "emergency")
_ACTION_LOTO_HINTS = ("lockout", "tagout", "isolate", "remove", "inspect")


class ControlAdapterError(RuntimeError):
    pass


def build_control_commands(action_plan: ActionPlan, *, dry_run: bool = True) -> list[ControlCommand]:
    commands: list[ControlCommand] = []
    emitted: set[str] = set()

    for step in action_plan.steps:
        action = step.action.lower()
        command_type = None
        if step.priority == "P1" and any(hint in action for hint in _ACTION_STOP_HINTS):
            command_type = "STOP_MACHINE"
        elif step.priority == "P1" and any(hint in action for hint in _ACTION_LOTO_HINTS):
            command_type = "LOCKOUT_TAGOUT"
        elif step.priority in ("P1", "P2"):
            command_type = "SCHEDULE_INSPECTION"

        if command_type and command_type not in emitted:
            emitted.add(command_type)
            commands.append(ControlCommand(
                equipment_id=action_plan.equipment_id,
                command_type=command_type,
                source_step_number=step.step_number,
                priority=step.priority,
                reason=step.action,
                dry_run=dry_run,
            ))

    if action_plan.escalation_required:
        commands.append(ControlCommand(
            equipment_id=action_plan.equipment_id,
            command_type="NOTIFY_SUPERVISOR",
            source_step_number=None,
            priority="P1",
            reason=action_plan.escalation_reason or "Action plan requires human escalation.",
            dry_run=dry_run,
        ))

    return commands


def execute_control_plan(
    action_plan: ActionPlan,
    correlation_id: str,
    *,
    dry_run: bool = True,
) -> ControlPlanResult:
    if not dry_run:
        raise ControlAdapterError("Live industrial control writes are not supported by this demo adapter.")

    commands = build_control_commands(action_plan, dry_run=dry_run)
    results = [_execute_command(command, correlation_id) for command in commands]
    return ControlPlanResult(
        correlation_id=correlation_id,
        dry_run=dry_run,
        command_count=len(results),
        results=results,
    )


def _execute_command(command: ControlCommand, correlation_id: str) -> ControlExecutionResult:
    adapter_path = Path(get_settings().control_adapter_path)
    if not adapter_path.exists():
        raise ControlAdapterError(
            f"C++ control adapter not found at {adapter_path}. Run ./scripts/build_control_adapter.sh first."
        )

    args = [
        str(adapter_path),
        "--equipment-id", command.equipment_id,
        "--command", command.command_type,
        "--priority", command.priority,
        "--reason", command.reason,
        "--correlation-id", correlation_id,
        "--dry-run",
    ]
    if command.source_step_number is not None:
        args.extend(["--source-step", str(command.source_step_number)])

    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ControlAdapterError(completed.stderr.strip() or "C++ control adapter failed.")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ControlAdapterError(f"C++ control adapter returned invalid JSON: {completed.stdout}") from exc

    return ControlExecutionResult.model_validate(payload)
