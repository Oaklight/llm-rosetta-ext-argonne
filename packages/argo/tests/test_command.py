"""``argo-tunnel`` is also a command of the ``llm-rosetta`` dispatcher.

The dispatcher calls ``main(argv)`` with the arguments after the command name
and uses the callable's first docstring line as the help summary.
"""

from __future__ import annotations

import re
from pathlib import Path

from llm_rosetta_ext.argo import tunnel

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_the_command_group_and_the_console_script_name_the_same_callable():
    text = _PYPROJECT.read_text(encoding="utf-8")
    target = '"llm_rosetta_ext.argo.tunnel:main"'
    assert re.search(
        r"\[project\.scripts\]\s+argo-tunnel = " + re.escape(target), text
    )
    assert re.search(
        r"\[project\.entry-points\.\"llm_rosetta\.commands\"\]\s+argo-tunnel = "
        + re.escape(target),
        text,
    )


def test_main_takes_the_arguments_after_the_command_name_and_returns_the_exit_code():
    assert tunnel.main(["proxy-url", "--port", "43210"]) == 0
    assert tunnel.main([]) == 2


def test_the_first_docstring_line_is_the_help_summary():
    first = (tunnel.main.__doc__ or "").strip().splitlines()[0]
    assert "tunnel" in first.lower()
