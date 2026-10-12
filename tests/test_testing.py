import json
import subprocess
from pathlib import Path

from renfield.testing import call_record, fake_claude

SUCCESS = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False,
     "total_cost_usd": 0.5, "num_turns": 3, "duration_ms": 1200,
     "usage": {"input_tokens": 10, "output_tokens": 20}}
) + "\n"


def test_the_fake_records_what_it_received(tmp_path):
    program = fake_claude(tmp_path, stream=SUCCESS)
    done = subprocess.run(
        [str(program), "-p", "--model", "x"],
        input="the prompt",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "SECRET": "shh"},
    )
    assert done.returncode == 0
    assert done.stdout == SUCCESS
    call = call_record(tmp_path)
    assert call["argv"] == ["-p", "--model", "x"]
    assert call["stdin"] == "the prompt"
    assert call["env"]["SECRET"] == "shh"
    assert call["cwd"] == str(tmp_path)


def test_the_fake_writes_the_files_of_the_test(tmp_path):
    program = fake_claude(tmp_path, writes={"verdict.json": '{"ok": true}'})
    subprocess.run([str(program)], input="", capture_output=True, text=True,
                   cwd=str(tmp_path))
    assert json.loads((tmp_path / "verdict.json").read_text()) == {"ok": True}


def test_the_fake_gives_the_exit_code_of_the_test(tmp_path):
    program = fake_claude(tmp_path, stream="", exit_code=3)
    done = subprocess.run([str(program)], input="", capture_output=True, text=True,
                          cwd=str(tmp_path))
    assert done.returncode == 3
