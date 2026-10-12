import re

import pytest

from renfield.paths import (
    PLACEHOLDERS,
    STAMP_FORMAT,
    PathError,
    Paths,
    make_dirs,
    render,
)


def test_the_default_layout():
    run = render(Paths(), step="review", stamp="2026-10-12T14-03-51")
    assert str(run.run_dir) == "runs/2026-10-12T14-03-51-review"
    assert str(run.prompt) == "runs/2026-10-12T14-03-51-review/prompts/review.md"
    assert str(run.transcript) == (
        "runs/2026-10-12T14-03-51-review/transcripts/review.jsonl"
    )
    assert str(run.artifacts) == "runs/2026-10-12T14-03-51-review/artifacts"
    assert str(run.record) == "runs/2026-10-12T14-03-51-review/record.json"


def test_a_step_name_with_a_dot_keeps_its_last_part():
    run = render(Paths(), step="review.deep", stamp="s")
    assert run.prompt.name == "deep.md"


def test_an_absent_stamp_is_the_time_now_in_the_documented_format():
    run = render(Paths(), step="x")
    stamp = run.run_dir.name.removesuffix("-x")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}", stamp), stamp
    assert STAMP_FORMAT == "%Y-%m-%dT%H-%M-%S"


def test_each_of_the_4_paths_is_configurable():
    run = render(
        Paths(
            run_dir="out",
            prompt="p.md",
            transcript="t.jsonl",
            artifacts="files",
            record="r.json",
        ),
        step="x",
        stamp="s",
    )
    assert str(run.run_dir) == "out"
    assert str(run.prompt) == "out/p.md"
    assert str(run.transcript) == "out/t.jsonl"
    assert str(run.artifacts) == "out/files"
    assert str(run.record) == "out/r.json"


def test_the_placeholders_are_the_2_that_the_spec_names():
    assert set(PLACEHOLDERS) == {"step", "stamp"}


def test_an_unknown_placeholder_is_an_error_and_names_the_allowed_ones():
    with pytest.raises(PathError) as caught:
        render(Paths(run_dir="runs/{stepp}"), step="x", stamp="s")
    message = str(caught.value)
    assert "run_dir" in message
    assert "stepp" in message
    assert "step" in message and "stamp" in message


@pytest.mark.parametrize("bad", ["runs/{step", "runs/step}", "runs/{{step}"])
def test_an_unbalanced_brace_is_a_path_error_and_names_the_key(bad):
    """`Formatter().parse` raises a bare ValueError for these 3 forms. The CLI
    catches PathError only, so a bare ValueError would reach a person as a
    traceback."""
    with pytest.raises(PathError) as caught:
        render(Paths(run_dir=bad), step="x", stamp="s")
    message = str(caught.value)
    assert "run_dir" in message
    assert bad in message


def test_an_absolute_value_for_a_relative_key_is_an_error():
    """pathlib drops the left side of a join with an absolute path, so a
    value of /tmp/p.md would leave run_dir with no warning."""
    with pytest.raises(PathError, match="prompt"):
        render(Paths(prompt="/tmp/p.md"), step="x", stamp="s")


def test_an_absolute_run_dir_is_allowed():
    run = render(Paths(run_dir="/tmp/out"), step="x", stamp="s")
    assert str(run.run_dir) == "/tmp/out"


def test_make_dirs_builds_the_parent_of_each_file_and_the_artifacts_folder(tmp_path):
    run = render(Paths(run_dir=str(tmp_path / "out")), step="x", stamp="s")
    make_dirs(run)
    assert run.artifacts.is_dir()
    assert run.prompt.parent.is_dir()
    assert run.transcript.parent.is_dir()
    assert run.record.parent.is_dir()
    assert not run.prompt.exists(), "make_dirs writes no file"
