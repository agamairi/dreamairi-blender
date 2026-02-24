"""Strict multi-turn agent controller (PLAN -> TOOL_CALL -> VERIFY -> ITERATE)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, List, Optional

from ..core.errors import ERROR_MODEL, ERROR_VALIDATION
from ..llm.contract import AgentEnvelope, ContractError, parse_agent_response
from ..providers.base import Provider, ProviderMessage, ProviderRequest
from ..tools.registry import ToolExecutionContext, ToolResult, agent_registry
from ..util.cancel import CancellationToken
from ..util.logging import LogBuffer


@dataclass
class AgentState:
    status: str = "Idle"
    step: int = 0
    max_steps: int = 0
    last_tool: str = ""
    last_error: str = ""
    last_error_type: str = ""
    plan_text: str = ""
    tools_text: str = ""
    results_text: str = ""


@dataclass
class AgentResult:
    success: bool
    summary: str
    operations: int
    error_type: str = ""


class AgentController:
    def __init__(
        self,
        provider: Provider,
        model: str,
        system_prompt: str,
        cancel_token: CancellationToken,
        log_buffer: Optional[LogBuffer] = None,
        tool_executor: Optional[Any] = None,
        tool_context: Optional[ToolExecutionContext] = None,
        model_timeout_seconds: float = 60.0,
        max_model_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        require_plan_first: bool = True,
        max_tool_calls_per_turn: int = 6,
        max_noop_steps: int = 4,
        max_identical_call_batches: int = 3,
    ) -> None:
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.cancel_token = cancel_token
        self.log_buffer = log_buffer
        self.messages: List[ProviderMessage] = []
        self.state = AgentState()
        self.tool_executor = tool_executor or agent_registry.execute
        self.tool_context = tool_context
        self.model_timeout_seconds = model_timeout_seconds
        self.max_model_retries = max(0, max_model_retries)
        self.retry_backoff_seconds = max(0.1, retry_backoff_seconds)
        self.require_plan_first = require_plan_first
        self.max_tool_calls_per_turn = max(1, max_tool_calls_per_turn)
        self.max_noop_steps = max(1, max_noop_steps)
        self.max_identical_call_batches = max(1, max_identical_call_batches)

    def _log(self, text: str) -> None:
        if self.log_buffer:
            self.log_buffer.append(text)

    def _append_plan(self, step: int, steps: List[str]) -> None:
        lines = [f"[Step {step}] PLAN"]
        for item in steps:
            lines.append(f"- {item}")
        if self.state.plan_text:
            self.state.plan_text += "\n"
        self.state.plan_text += "\n".join(lines)

    def _append_tool_call(self, step: int, tool: str, args: dict) -> None:
        entry = {"step": step, "tool": tool, "args": args}
        if self.state.tools_text:
            self.state.tools_text += "\n"
        self.state.tools_text += json.dumps(entry, ensure_ascii=True)

    def _append_tool_result(self, step: int, tool: str, result: ToolResult) -> None:
        entry = {
            "step": step,
            "tool": tool,
            "success": result.success,
            "error_type": result.error_type or "",
            "message": result.message,
            "data": result.data or {},
        }
        if self.state.results_text:
            self.state.results_text += "\n"
        self.state.results_text += json.dumps(entry, ensure_ascii=True)

    def _provider_request(self) -> ProviderRequest:
        return ProviderRequest(
            model=self.model,
            system_prompt=self.system_prompt,
            messages=self.messages,
            timeout_seconds=self.model_timeout_seconds,
        )

    def _call_model_with_retry(self, step: int) -> str:
        last_error = ""
        for attempt in range(self.max_model_retries + 1):
            if self.cancel_token and self.cancel_token.is_cancelled():
                raise RuntimeError("Cancelled")
            try:
                self._log(f"[step {step}] model call attempt={attempt + 1}")
                return self.provider.send_chat(self._provider_request(), self.cancel_token)
            except Exception as exc:
                last_error = str(exc)
                if attempt >= self.max_model_retries:
                    break
                sleep_for = self.retry_backoff_seconds * (2 ** attempt)
                self._log(f"[step {step}] model call failed: {exc}; retrying in {sleep_for:.1f}s")
                time.sleep(sleep_for)
        raise RuntimeError(last_error or "Model call failed")

    def _send_validation_feedback(self, details: str) -> None:
        payload = {
            "event": "response_validation_error",
            "error_type": ERROR_VALIDATION,
            "details": details,
            "expected_envelopes": ["PLAN", "TOOL_CALL", "FINAL"],
        }
        self.messages.append(ProviderMessage(role="user", content=json.dumps(payload, ensure_ascii=True)))

    def _execute_tool(self, name: str, args: dict) -> ToolResult:
        try:
            return self.tool_executor(name, args, self.tool_context)
        except TypeError:
            return self.tool_executor(name, args)

    def run(self, user_prompt: str, max_iterations: int = 20) -> AgentResult:
        self.messages = [ProviderMessage(role="user", content=user_prompt)]
        self.state.status = "Thinking"
        self.state.max_steps = max_iterations
        self._log("Agent run started.")

        saw_plan = not self.require_plan_first
        operations = 0
        noop_steps = 0
        identical_batches = 0
        previous_signature = ""

        for step in range(1, max_iterations + 1):
            self.state.step = step
            if self.cancel_token and self.cancel_token.is_cancelled():
                self.state.status = "Cancelled"
                return AgentResult(False, "Cancelled by user", operations, error_type=ERROR_MODEL)

            self.state.status = "Thinking"
            raw_text: str
            try:
                raw_text = self._call_model_with_retry(step)
            except Exception as exc:
                self.state.status = "Error"
                self.state.last_error = str(exc)
                self.state.last_error_type = ERROR_MODEL
                self._log(f"[step {step}] model error: {exc}")
                return AgentResult(False, f"Model error: {exc}", operations, error_type=ERROR_MODEL)

            self.messages.append(ProviderMessage(role="assistant", content=raw_text))

            try:
                envelope: AgentEnvelope = parse_agent_response(raw_text)
            except ContractError as exc:
                self.state.last_error = str(exc)
                self.state.last_error_type = ERROR_VALIDATION
                self._log(f"[step {step}] invalid envelope: {exc}")
                self._send_validation_feedback(str(exc))
                noop_steps += 1
                if noop_steps >= self.max_noop_steps:
                    self.state.status = "Error"
                    return AgentResult(
                        False,
                        "Model repeatedly returned invalid envelopes.",
                        operations,
                        error_type=ERROR_VALIDATION,
                    )
                continue

            if envelope.response_type == "PLAN":
                saw_plan = True
                self._append_plan(step, envelope.plan_steps)
                self._log(f"[step {step}] plan received with {len(envelope.plan_steps)} steps")
                self.state.status = "Plan received"
                noop_steps += 1
                self.messages.append(
                    ProviderMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "event": "plan_received",
                                "next": "Send TOOL_CALL envelope to execute the plan.",
                            },
                            ensure_ascii=True,
                        ),
                    )
                )
                if noop_steps >= self.max_noop_steps:
                    self.state.status = "Error"
                    return AgentResult(
                        False,
                        "Agent stalled after repeated non-executing plan turns.",
                        operations,
                        error_type=ERROR_MODEL,
                    )
                continue

            if envelope.response_type == "TOOL_CALL":
                if self.require_plan_first and not saw_plan:
                    self.state.last_error = "Plan required before tool calls (Fast mode disabled)."
                    self.state.last_error_type = ERROR_VALIDATION
                    self._send_validation_feedback(self.state.last_error)
                    noop_steps += 1
                    continue

                calls = envelope.tool_calls
                if len(calls) > self.max_tool_calls_per_turn:
                    self.state.last_error = (
                        f"Too many tool calls in one turn: {len(calls)} > {self.max_tool_calls_per_turn}"
                    )
                    self.state.last_error_type = ERROR_VALIDATION
                    self._send_validation_feedback(self.state.last_error)
                    noop_steps += 1
                    continue

                signature = json.dumps(
                    [{"tool": call.tool, "args": call.args} for call in calls],
                    sort_keys=True,
                    ensure_ascii=True,
                )
                if signature == previous_signature:
                    identical_batches += 1
                else:
                    identical_batches = 0
                    previous_signature = signature
                if identical_batches >= self.max_identical_call_batches:
                    self.state.status = "Error"
                    self.state.last_error = "Repeated identical tool batches detected."
                    self.state.last_error_type = ERROR_MODEL
                    return AgentResult(False, self.state.last_error, operations, error_type=ERROR_MODEL)

                self.state.status = f"Running {len(calls)} tool(s)"
                tool_results = []
                any_success = False
                for call in calls:
                    if self.cancel_token and self.cancel_token.is_cancelled():
                        self.state.status = "Cancelled"
                        return AgentResult(False, "Cancelled by user", operations, error_type=ERROR_MODEL)
                    self.state.last_tool = call.tool
                    self._append_tool_call(step, call.tool, call.args)
                    self._log(f"[step {step}] running tool '{call.tool}'")
                    result = self._execute_tool(call.tool, call.args)
                    if result.success:
                        any_success = True
                    else:
                        self.state.last_error = result.message
                        self.state.last_error_type = result.error_type
                    self._append_tool_result(step, call.tool, result)
                    tool_results.append({"tool": call.tool, "args": call.args, "result": result.to_dict()})
                    operations += 1
                    if not result.success:
                        self._log(f"[step {step}] tool '{call.tool}' failed: {result.message}")
                        break

                noop_steps = 0 if any_success else noop_steps + 1
                self.messages.append(
                    ProviderMessage(
                        role="user",
                        content=json.dumps(
                            {"event": "tool_results", "step": step, "results": tool_results},
                            ensure_ascii=True,
                        ),
                    )
                )
                if noop_steps >= self.max_noop_steps:
                    self.state.status = "Error"
                    return AgentResult(
                        False,
                        "Agent stopped after repeated non-progressing tool calls.",
                        operations,
                        error_type=ERROR_MODEL,
                    )
                continue

            if envelope.response_type == "FINAL":
                if self.require_plan_first and not saw_plan:
                    self.state.last_error = "Final response is not allowed before a PLAN when Fast mode is disabled."
                    self.state.last_error_type = ERROR_VALIDATION
                    self._send_validation_feedback(self.state.last_error)
                    noop_steps += 1
                    continue
                self.state.status = "Done"
                self._log(f"[step {step}] final received")
                return AgentResult(True, envelope.final_message, operations, error_type="")

            self.state.last_error = f"Unhandled envelope type '{envelope.response_type}'."
            self.state.last_error_type = ERROR_VALIDATION
            self._send_validation_feedback(self.state.last_error)
            noop_steps += 1

        self.state.status = "Error"
        self.state.last_error = "Exceeded max steps"
        self.state.last_error_type = ERROR_MODEL
        return AgentResult(False, "Exceeded max steps", operations, error_type=ERROR_MODEL)

