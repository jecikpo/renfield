import json
from pathlib import Path

import pytest

from renfield.record import StepRecord, as_dict, summary_line, write_record
from renfield.stream import describe_event, read_stream

FIXTURES = Path(__file__).parent / "fixtures" / "stream"


def lines_of(name):
    return (FIXTURES / name).read_text().splitlines(keepends=True)


def test_a_success_gives_the_cost_and_the_tokens():
    result = read_stream(lines_of("success.jsonl"))
    assert result.ok is True
    assert result.error_class is None
    assert result.cost_usd > 0
    assert result.num_turns > 0
    assert result.cost_known is True


def test_an_auth_failure_is_not_a_success_although_its_subtype_says_so():
    """The measured trap. The event holds subtype success and is_error true."""
    raw = [line for line in lines_of("auth-401.jsonl") if line.strip()]
    # The fixture holds a plain-text warning of the child before the events.
    events = [json.loads(line) for line in raw if line.startswith("{")]
    result_event = [e for e in events if e.get("type") == "result"][0]
    assert result_event["subtype"] == "success", "the fixture lost its trap"
    assert result_event["is_error"] is True

    result = read_stream(raw)
    assert result.ok is False
    assert result.error_class == "auth"


def test_a_login_message_is_an_auth_failure():
    result = read_stream(lines_of("auth-not-logged-in.jsonl"))
    assert result.error_class == "auth"


def test_an_exhausted_budget_has_its_own_class():
    result = read_stream(lines_of("budget-exhausted.jsonl"))
    assert result.error_class == "budget"


def test_a_stream_with_no_result_event_is_transient_and_unmeasured():
    result = read_stream(lines_of("timeout-killed.jsonl"))
    assert result.error_class == "transient"
    assert result.cost_known is False
    assert result.cost_usd == 0.0


def test_the_tool_calls_are_counted_by_name():
    result = read_stream(lines_of("tool-call.jsonl"))
    assert sum(result.tool_calls.values()) >= 1
    assert all(isinstance(name, str) for name in result.tool_calls)


def test_a_line_that_is_not_json_is_ignored():
    stream = ["a warning of the child\n", *lines_of("success.jsonl")]
    assert read_stream(stream).ok is True


def test_a_rate_limit_reads_the_status_and_not_the_subtype():
    event = {"type": "result", "subtype": "success", "is_error": True,
             "api_error_status": 429, "result": "whatever"}
    result = read_stream([json.dumps(event) + "\n"])
    assert result.error_class == "rate_limited"


def test_a_session_limit_in_the_text_is_a_rate_limit():
    event = {"type": "result", "subtype": "success", "is_error": True,
             "result": "You've hit your session limit · resets 4:40pm"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "rate_limited"


@pytest.mark.parametrize("status", [500, 503, 599])
def test_a_server_failure_is_transient_and_gets_a_retry(status):
    event = {"type": "result", "subtype": "error", "is_error": True,
             "api_error_status": status, "result": "x"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "transient"


def test_a_client_failure_that_is_not_401_403_or_429_is_transient():
    """There is no class for a 4xx that the measured set does not hold, and
    `transient` gets a retry. A retry of a 400 costs 1 call and fails again.
    Open item: measure a 400 before you give it a class of its own."""
    event = {"type": "result", "subtype": "error", "is_error": True,
             "api_error_status": 400, "result": "bad request"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "transient"


def test_describe_event_gives_a_line_for_a_tool_call_and_none_otherwise():
    call = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b/plan.md"}}]}}
    assert describe_event(call) == "Read(plan.md)"
    assert describe_event({"type": "result"}) is None


def test_a_long_argument_is_cut_and_marked():
    call = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "x" * 200}}]}}
    line = describe_event(call)
    assert len(line) < 80
    assert line.endswith("…)")


def test_a_field_with_an_unexpected_type_does_not_lose_the_cost():
    """Measured: a result event with "num_turns": "many" raised ValueError
    in read_stream, and run_step recorded cost_usd 0.0 for an event that
    held 2.5 USD."""
    event = {"type": "result", "subtype": "success", "is_error": False,
             "total_cost_usd": 2.5, "num_turns": "many",
             "usage": "none", "duration_ms": [1]}
    result = read_stream([json.dumps(event) + "\n"])
    assert result.cost_usd == 2.5
    assert result.num_turns == 0
    assert result.input_tokens == 0
    assert result.duration_s == 0.0


def test_a_thinking_event_with_a_bad_estimate_does_not_raise():
    lines = [json.dumps({"subtype": "thinking_tokens", "estimated_tokens": "x"}) + "\n"]
    assert read_stream(lines).thinking_tokens == 0


def test_a_403_status_is_an_auth_failure():
    event = {"type": "result", "subtype": "error", "is_error": True,
             "api_error_status": 403, "result": "forbidden"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "auth"


def test_a_usage_limit_in_the_text_is_a_rate_limit():
    event = {"type": "result", "subtype": "success", "is_error": True,
             "result": "You have reached your usage limit"}
    assert read_stream([json.dumps(event) + "\n"]).error_class == "rate_limited"


def test_a_result_with_is_error_false_is_ok_whatever_its_subtype_says():
    """docs/design.md section 7: the classifier reads is_error first. A
    reader of the subtype would call this event a failure."""
    event = {"type": "result", "subtype": "error_max_turns",
             "is_error": False, "total_cost_usd": 0.3}
    result = read_stream([json.dumps(event) + "\n"])
    assert result.ok is True
    assert result.error_class is None


def test_a_nan_cost_is_unmeasured_in_the_result_the_line_and_the_file(tmp_path):
    """json.loads accepts NaN, so a provider can send it. Measured: the
    summary line said "nan USD" while record.json said 0.0."""
    text = '{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": NaN}\n'
    result = read_stream([text])
    assert result.cost_usd == 0.0
    assert result.cost_known is False

    record = StepRecord(name="s", status="ok", cost_usd=result.cost_usd,
                        cost_known=result.cost_known)
    assert "nan" not in summary_line(record).lower()
    path = tmp_path / "record.json"
    write_record(path, record)
    assert json.loads(path.read_text())["cost_known"] is False
