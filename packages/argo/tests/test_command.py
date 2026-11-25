"""``llm-rosetta argo tunnel``: the extension's command (#1704).

The manifest lists the verb, ``commands.py`` maps it to a callable, and the
dispatcher calls that callable with the arguments after the verb.
"""

from __future__ import annotations

from pathlib import Path

from llm_rosetta_ext.argo import commands, tunnel

_FOLDER = Path(__file__).resolve().parents[1]


def test_the_manifest_lists_the_verb_commands_exposes():
    text = (_FOLDER / "plugin.yaml").read_text(encoding="utf-8")
    assert "commands:\n    tunnel:" in text
    assert set(commands.COMMANDS) == {"tunnel"}


def test_the_old_console_script_and_dispatcher_entry_point_are_gone():
    text = (_FOLDER / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" not in text
    assert "llm_rosetta.commands" not in text


def test_the_command_takes_the_arguments_after_the_verb_and_returns_the_exit_code():
    run = commands.COMMANDS["tunnel"]
    assert run(["proxy-url", "--port", "43210"]) == 0
    assert run([]) == 2


def test_usage_names_the_dispatcher_spelling_and_restores_the_standalone_one(capsys):
    commands.COMMANDS["tunnel"]([])
    assert "llm-rosetta argo tunnel" in capsys.readouterr().out
    assert tunnel.PROG == "argo-tunnel"


def test_the_help_summary_is_in_the_manifest_not_the_docstring():
    text = (_FOLDER / "plugin.yaml").read_text(encoding="utf-8")
    assert "Open and manage the SSH tunnel" in text.split("commands:")[1]
