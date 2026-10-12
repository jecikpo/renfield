import json

from renfield.outputs import check_outputs

SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"enum": ["high", "medium", "low"]},
                },
            },
        }
    },
}


def schema_file(tmp_path, data=SCHEMA, name="verdict.schema.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def test_a_file_that_is_there_and_matches_its_schema_passes(tmp_path):
    (tmp_path / "verdict.json").write_text('{"findings": []}')
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert (ok, reason) == (True, None)


def test_a_file_the_agent_did_not_write(tmp_path):
    ok, reason = check_outputs(tmp_path, ["verdict.json"], {})
    assert ok is False
    assert reason == "the agent did not write verdict.json"


def test_a_file_of_only_whitespace_is_empty(tmp_path):
    (tmp_path / "report.md").write_text("   \n\n")
    ok, reason = check_outputs(tmp_path, ["report.md"], {})
    assert ok is False
    assert reason == "report.md is empty"


def test_a_json_file_that_does_not_parse(tmp_path):
    (tmp_path / "verdict.json").write_text("{not json")
    ok, reason = check_outputs(tmp_path, ["verdict.json"], {})
    assert ok is False
    assert reason.startswith("verdict.json is not valid JSON")


def test_a_schema_failure_names_the_place_in_the_file(tmp_path):
    (tmp_path / "verdict.json").write_text(
        json.dumps({"findings": [{"severity": "high"}, {"severity": "blocker"}]})
    )
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert reason.startswith("verdict.json: findings.1.severity:")
    assert "blocker" in reason


def test_a_missing_required_key_names_the_file(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert reason.startswith("verdict.json: ")
    assert "findings" in reason


def test_a_file_with_no_schema_needs_only_to_be_there_and_not_empty(tmp_path):
    (tmp_path / "report.md").write_text("# the report\n")
    assert check_outputs(tmp_path, ["report.md"], {}) == (True, None)


def test_the_first_problem_is_the_one_that_is_reported(tmp_path):
    (tmp_path / "second.json").write_text("{not json")
    ok, reason = check_outputs(tmp_path, ["first.md", "second.json"], {})
    assert reason == "the agent did not write first.md"


def test_a_schema_for_a_file_that_is_not_an_output_is_an_error(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"other.json": schema_file(tmp_path)}
    )
    assert ok is False
    assert "other.json" in reason


def test_a_schema_file_that_is_not_there_is_an_error(tmp_path):
    (tmp_path / "verdict.json").write_text("{}")
    ok, reason = check_outputs(
        tmp_path, ["verdict.json"], {"verdict.json": tmp_path / "gone.json"}
    )
    assert ok is False
    assert "gone.json" in reason


def test_no_output_at_all_passes(tmp_path):
    assert check_outputs(tmp_path, [], {}) == (True, None)
