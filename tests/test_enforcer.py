"""Tests for runtime policy enforcement."""

import pytest

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, PolicySpec,
    EscalationPolicy, ModelConfig, ToolParameter,
)
from cortex_protocol.governance.enforcer import PolicyEnforcer, EnforcementResult
from cortex_protocol.governance.enforce import enforce, EnforcedAgent
from cortex_protocol.governance.audit import AuditLog
from cortex_protocol.governance.exceptions import (
    MaxTurnsExceeded,
    ApprovalRequired,
    ForbiddenActionDetected,
)


_DEFAULT_APPROVAL = ["send-email", "process-refund"]
_DEFAULT_FORBIDDEN = ["Share confidential information", "Make up facts"]
_DEFAULT_ESCALATION = EscalationPolicy(trigger="severity is critical", target="human-support")


def _spec(max_turns=5, require_approval=None, forbidden_actions=None, escalation=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(
            name="test-agent",
            description="Test",
            instructions="You are a test agent with enough words to pass linting requirements here.",
        ),
        tools=[
            ToolSpec(name="search", description="Search", parameters=ToolParameter(type="object", properties={"q": {"type": "string"}}, required=["q"])),
            ToolSpec(name="send-email", description="Send email", parameters=ToolParameter(type="object", properties={"to": {"type": "string"}}, required=["to"])),
            ToolSpec(name="process-refund", description="Refund", parameters=ToolParameter(type="object", properties={"amount": {"type": "number"}}, required=["amount"])),
        ],
        policies=PolicySpec(
            max_turns=max_turns,
            require_approval=_DEFAULT_APPROVAL if require_approval is None else require_approval,
            forbidden_actions=_DEFAULT_FORBIDDEN if forbidden_actions is None else forbidden_actions,
            escalation=escalation if escalation is not None else _DEFAULT_ESCALATION,
        ),
        model=ModelConfig(preferred="gpt-4o", fallback="claude-sonnet-4"),
    )


# ---------------------------------------------------------------------------
# max_turns
# ---------------------------------------------------------------------------

class TestMaxTurns:
    def test_increments_turn_counter(self):
        e = PolicyEnforcer(_spec(max_turns=10))
        e.increment_turn()
        assert e.turn_count == 1
        e.increment_turn()
        assert e.turn_count == 2

    def test_raises_at_limit(self):
        e = PolicyEnforcer(_spec(max_turns=3))
        e.increment_turn()  # 1
        e.increment_turn()  # 2
        e.increment_turn()  # 3
        with pytest.raises(MaxTurnsExceeded) as exc_info:
            e.increment_turn()  # 4 > 3
        assert exc_info.value.max_turns == 3
        assert exc_info.value.turn == 4

    def test_no_limit_never_raises(self):
        e = PolicyEnforcer(_spec(max_turns=None))
        for _ in range(100):
            e.increment_turn()
        assert e.turn_count == 100

    def test_audit_logged_on_increment(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(max_turns=5), audit_log=log)
        e.increment_turn()
        assert len(log.events()) == 1
        assert log.events()[0].event_type == "turn_start"

    def test_audit_logged_on_violation(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(max_turns=1), audit_log=log)
        e.increment_turn()
        with pytest.raises(MaxTurnsExceeded):
            e.increment_turn()
        violations = log.violations()
        assert len(violations) == 1
        assert violations[0].event_type == "max_turns"


# ---------------------------------------------------------------------------
# require_approval
# ---------------------------------------------------------------------------

class TestRequireApproval:
    def test_gated_tool_raises(self):
        e = PolicyEnforcer(_spec())
        with pytest.raises(ApprovalRequired) as exc_info:
            e.check_tool_call("send-email", {"to": "user@example.com"})
        assert exc_info.value.tool_name == "send-email"
        assert exc_info.value.tool_input == {"to": "user@example.com"}

    def test_ungated_tool_passes(self):
        e = PolicyEnforcer(_spec())
        result = e.check_tool_call("search", {"q": "test"})
        assert result.allowed

    def test_audit_logged_on_block(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(), audit_log=log)
        with pytest.raises(ApprovalRequired):
            e.check_tool_call("process-refund", {"amount": 100})
        assert len(log.violations()) == 1
        assert log.violations()[0].event_type == "tool_blocked"
        assert log.violations()[0].tool_name == "process-refund"

    def test_audit_logged_on_allow(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(), audit_log=log)
        e.check_tool_call("search", {"q": "hello"})
        assert len(log.events()) == 1
        assert log.events()[0].event_type == "tool_call"
        assert log.events()[0].allowed

    def test_empty_approval_list_allows_all(self):
        e = PolicyEnforcer(_spec(require_approval=[]))
        result = e.check_tool_call("send-email", {})
        assert result.allowed

    def test_none_tool_input_defaults_to_empty(self):
        e = PolicyEnforcer(_spec(require_approval=[]))
        result = e.check_tool_call("search")
        assert result.allowed


# ---------------------------------------------------------------------------
# forbidden_actions
# ---------------------------------------------------------------------------

class TestForbiddenActions:
    def test_clean_response_passes(self):
        e = PolicyEnforcer(_spec())
        result = e.check_response("Here is the search result you asked for.")
        assert result.allowed
        assert len(result.violations) == 0

    def test_violation_advisory_by_default(self):
        e = PolicyEnforcer(_spec())
        result = e.check_response("I will share confidential information with you now.")
        assert result.allowed  # advisory = still allowed
        assert len(result.violations) == 1

    def test_violation_blocking_when_strict(self):
        e = PolicyEnforcer(_spec(), strict_forbidden=True)
        with pytest.raises(ForbiddenActionDetected) as exc_info:
            e.check_response("Let me make up facts for this answer.")
        assert "Make up facts" in exc_info.value.action or "make up facts" in exc_info.value.action.lower()

    def test_case_insensitive_match(self):
        e = PolicyEnforcer(_spec())
        result = e.check_response("SHARE CONFIDENTIAL INFORMATION right away!")
        assert len(result.violations) == 1

    def test_multiple_violations_detected(self):
        e = PolicyEnforcer(_spec())
        result = e.check_response("I will share confidential information and also make up facts.")
        assert len(result.violations) == 2

    def test_audit_logged_on_violation(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(), audit_log=log)
        e.check_response("share confidential information here")
        forbidden_events = [ev for ev in log.events() if ev.event_type == "forbidden_action"]
        assert len(forbidden_events) == 1

    def test_audit_logged_on_clean(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(), audit_log=log)
        e.check_response("All good here.")
        assert len(log.events()) == 1
        assert log.events()[0].event_type == "response"

    def test_no_forbidden_actions_always_passes(self):
        e = PolicyEnforcer(_spec(forbidden_actions=[]))
        result = e.check_response("Anything goes here.")
        assert result.allowed
        assert len(result.violations) == 0


# ---------------------------------------------------------------------------
# escalation
# ---------------------------------------------------------------------------

class TestEscalation:
    def test_trigger_matched(self):
        e = PolicyEnforcer(_spec())
        result = e.check_escalation({"status": "severity is critical, system down"})
        assert "human-support" in result.detail

    def test_trigger_not_matched(self):
        e = PolicyEnforcer(_spec())
        result = e.check_escalation({"status": "all systems normal"})
        assert "No escalation" in result.detail

    def test_no_escalation_configured(self):
        e = PolicyEnforcer(_spec(escalation=EscalationPolicy(trigger="", target="")))
        result = e.check_escalation({"status": "anything"})
        assert result.allowed

    def test_escalation_is_advisory(self):
        e = PolicyEnforcer(_spec())
        result = e.check_escalation({"status": "critical failure"})
        assert result.allowed  # never blocking

    def test_audit_logged_on_match(self):
        log = AuditLog()
        e = PolicyEnforcer(_spec(), audit_log=log)
        e.check_escalation({"status": "severity critical"})
        esc_events = [ev for ev in log.events() if ev.event_type == "escalation"]
        assert len(esc_events) == 1


# ---------------------------------------------------------------------------
# run_id and multi-run
# ---------------------------------------------------------------------------

class TestRunId:
    def test_unique_per_instance(self):
        e1 = PolicyEnforcer(_spec())
        e2 = PolicyEnforcer(_spec())
        assert e1.run_id != e2.run_id

    def test_run_id_in_exceptions(self):
        e = PolicyEnforcer(_spec(max_turns=1))
        e.increment_turn()
        with pytest.raises(MaxTurnsExceeded) as exc_info:
            e.increment_turn()
        assert exc_info.value.run_id == e.run_id

    def test_multiple_runs_same_log(self):
        log = AuditLog()
        e1 = PolicyEnforcer(_spec(), audit_log=log)
        e2 = PolicyEnforcer(_spec(), audit_log=log)
        e1.increment_turn()
        e2.increment_turn()
        assert len(log.events()) == 2
        run_ids = {ev.run_id for ev in log.events()}
        assert len(run_ids) == 2


# ---------------------------------------------------------------------------
# enforce() convenience wrapper
# ---------------------------------------------------------------------------

class TestEnforceWrapper:
    def test_wraps_callable(self):
        def my_agent(msg):
            return f"Echo: {msg}"

        safe = enforce(my_agent, _spec(max_turns=10))
        assert isinstance(safe, EnforcedAgent)
        result = safe("hello")
        assert result == "Echo: hello"

    def test_max_turns_enforced(self):
        call_count = 0
        def my_agent(msg):
            nonlocal call_count
            call_count += 1
            return "ok"

        safe = enforce(my_agent, _spec(max_turns=2))
        safe("msg1")  # turn 1
        safe("msg2")  # turn 2
        with pytest.raises(MaxTurnsExceeded):
            safe("msg3")  # turn 3 > limit

    def test_forbidden_actions_checked(self):
        def bad_agent(msg):
            return "I will share confidential information"

        safe = enforce(bad_agent, _spec(), strict_forbidden=True)
        with pytest.raises(ForbiddenActionDetected):
            safe("test")

    def test_audit_dir_creates_file(self, tmp_path):
        def my_agent(msg):
            return "ok"

        safe = enforce(my_agent, _spec(), audit_dir=tmp_path)
        safe("test")
        log_files = list(tmp_path.glob("*.jsonl"))
        assert len(log_files) == 1

    def test_enforcer_accessible(self):
        def my_agent(msg):
            return "ok"

        safe = enforce(my_agent, _spec())
        assert safe.enforcer is not None
        assert safe.enforcer.turn_count == 0
        safe("hello")
        assert safe.enforcer.turn_count == 1

    def test_with_yaml_path(self, tmp_path):
        import yaml
        spec = _spec()
        yaml_path = tmp_path / "agent.yaml"
        yaml_path.write_text(spec.to_yaml())

        def my_agent(msg):
            return "ok"

        safe = enforce(my_agent, str(yaml_path))
        result = safe("hello")
        assert result == "ok"


# ---------------------------------------------------------------------------
# EnforcementResult
# ---------------------------------------------------------------------------

class TestEnforcementResult:
    def test_allowed_result(self):
        e = PolicyEnforcer(_spec())
        result = e.increment_turn()
        assert isinstance(result, EnforcementResult)
        assert result.allowed
        assert result.run_id == e.run_id

    def test_tool_call_result(self):
        e = PolicyEnforcer(_spec())
        result = e.check_tool_call("search", {"q": "test"})
        assert result.allowed
        assert result.event_type == "tool_call"
