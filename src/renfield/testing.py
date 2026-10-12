"""A fake `claude` program, for a test that must not cost money.

Each test of this package runs against this program. It records what it
received, so a test can assert the exact command and the exact environment
that `step.py` built.
"""

from __future__ import annotations

import json
from pathlib import Path

CALL_FILE = "call.json"


def fake_claude(
    tmp_path: Path,
    stream: str = "",
    exit_code: int = 0,
    sleep_s: float = 0.0,
    writes: dict[str, str] | None = None,
    before: str = "",
    on_int: str | None = None,
) -> Path:
    """Write a fake `claude` program, and give its path.

    `stream` is the text that the fake writes to its standard output, as a
    `stream-json` stream. `writes` is a map of file path to text: the fake
    writes each file, as an agent writes its output. `before` is the part of
    the stream that the fake writes before the sleep, as a model that works
    and then is killed. `on_int` is `ignore`, `stream`, or None, and it drives
    the escalation from SIGINT to SIGKILL.
    """
    path = Path(tmp_path) / "fake-claude"
    record = str(Path(tmp_path) / CALL_FILE)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, signal, sys, time\n"
        f"record = {json.dumps(record)}\n"
        "open(record, 'w').write(json.dumps({'argv': sys.argv[1:],"
        " 'env': dict(os.environ), 'cwd': os.getcwd(), 'pid': os.getpid(),"
        " 'stdin': sys.stdin.read()}))\n"
        f"for name, text in {json.dumps(writes or {})}.items():\n"
        "    open(name, 'w').write(text)\n"
        + _on_int(on_int, stream)
        + f"sys.stdout.write({json.dumps(before)})\n"
        "sys.stdout.flush()\n"
        f"time.sleep({sleep_s})\n"
        f"sys.stdout.write({json.dumps(stream)})\n"
        "sys.stdout.flush()\n"
        f"sys.exit({exit_code})\n"
    )
    path.chmod(0o755)
    return path


def _on_int(kind: str | None, stream: str) -> str:
    """Give the SIGINT handler of the fake program."""
    if kind == "ignore":
        return "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
    if kind == "stream":
        return (
            "def _answer(number, frame):\n"
            f"    sys.stdout.write({json.dumps(stream)})\n"
            "    sys.stdout.flush()\n"
            "    sys.exit(0)\n"
            "signal.signal(signal.SIGINT, _answer)\n"
        )
    return ""


def call_record(tmp_path: Path) -> dict:
    """Give what the fake program received: argv, env, cwd, pid, stdin."""
    return json.loads((Path(tmp_path) / CALL_FILE).read_text())
