import json

from renfield.record import (
    ESTIMATED_KINDS,
    StepRecord,
    as_dict,
    estimated,
    summary_line,
    write_record,
)


def a_record(**changes):
    values = dict(
        name="review",
        status="ok",
        provider="openrouter",
        model="deepseek/deepseek-v4.1-flash",
        effort="high",
        attempts=1,
        cost_usd=6.1630154321,
        num_turns=41,
        duration_s=318.2,
    )
    values.update(changes)
    return StepRecord(**values)


def test_a_subscription_and_an_openrouter_cost_are_estimates():
    assert set(ESTIMATED_KINDS) == {"subscription", "openrouter"}
    assert estimated("subscription") is True
    assert estimated("openrouter") is True


def test_only_an_api_key_cost_is_a_price():
    assert estimated("anthropic-api") is False


def test_the_cost_is_rounded_to_6_places_in_the_record():
    data = as_dict(a_record())
    assert data["cost_usd"] == 6.163015


def test_a_record_with_no_limit_has_no_unknown_cost_bound():
    """A killed step with no max_usd has no largest value that it could cost."""
    record = a_record(cost_known=False, cost_usd=0.0, unknown_usd=None)
    data = as_dict(record)
    assert data["cost_known"] is False
    assert data["unknown_usd"] is None


def test_a_killed_step_with_a_limit_reports_that_limit_as_the_bound():
    data = as_dict(a_record(cost_known=False, cost_usd=0.0, unknown_usd=4.0))
    assert data["unknown_usd"] == 4.0


def test_write_record_writes_valid_json_and_builds_the_folder(tmp_path):
    path = tmp_path / "deep" / "record.json"
    write_record(path, a_record())
    data = json.loads(path.read_text())
    assert data["name"] == "review"
    assert data["model"] == "deepseek/deepseek-v4.1-flash"


def test_the_summary_line_marks_an_estimated_cost(tmp_path):
    line = summary_line(a_record(cost_estimated=True))
    assert "review: ok" in line
    assert "41 turns" in line
    assert "318.2 s" in line
    assert "(estimated)" in line


def test_the_summary_line_of_a_price_does_not_say_estimated():
    line = summary_line(a_record(provider="anthropic-api", cost_estimated=False))
    assert "(estimated)" not in line


def test_the_summary_line_of_a_failed_step_names_its_class():
    line = summary_line(a_record(status="failed", error_class="rate_limited"))
    assert "failed" in line
    assert "rate_limited" in line


def test_the_summary_line_says_how_many_attempts_only_when_there_was_a_retry():
    assert "attempt" not in summary_line(a_record(attempts=1))
    assert "3 attempts" in summary_line(a_record(attempts=3))
