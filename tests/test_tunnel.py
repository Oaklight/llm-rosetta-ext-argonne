"""The tunnel CLI: argv composition, the four status states, and the CLI exit codes.

No test opens a connection.  The ssh side is a fake :class:`Runner` that
records argv and answers with a scripted result; the SOCKS probe is replaced
the same way.  What is being held is the *decision* each command makes —
notably that only ``auth`` may clear ``BatchMode``, and that a forward is
never added to a master that does not answer.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Sequence

import pytest

from llm_rosetta_shim_argo.tunnel import (
    SSH_FAILURE,
    Tunnel,
    TunnelConfig,
    TunnelError,
    TunnelState,
    CommandResult,
    main,
    probe_socks,
)


class FakeRunner:
    """Answers each ssh invocation from a script, recording the argv."""

    def __init__(self, results: Sequence[CommandResult] | None = None) -> None:
        self.calls: list[tuple[list[str], bool]] = []
        self._results = list(results or [])

    def __call__(
        self, argv: Sequence[str], *, interactive: bool = False
    ) -> CommandResult:
        self.calls.append((list(argv), interactive))
        if self._results:
            return self._results.pop(0)
        return CommandResult(0)

    @property
    def argvs(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]


def _alive_check() -> CommandResult:
    return CommandResult(0, "Master running (pid=123)\n")


def _absent_check() -> CommandResult:
    return CommandResult(
        SSH_FAILURE, "", "Control socket connect(/tmp/x): No such file or directory\n"
    )


def _wedged_check() -> CommandResult:
    return CommandResult(
        SSH_FAILURE, "", "Control socket connect(/tmp/x): Connection refused\n"
    )


def _stdout_of(argv, capsys) -> str:
    main(argv)
    return capsys.readouterr().out.strip()


def _tunnel(runner: FakeRunner, port_open: bool = False, **overrides) -> Tunnel:
    config = replace(TunnelConfig(user="someone", port=10801), **overrides)
    return Tunnel(config, runner=runner, prober=lambda bind, port: port_open)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_proxy_url_is_what_a_provider_config_takes():
    assert TunnelConfig().proxy_url == "socks5://127.0.0.1:10801"


def test_env_override_and_empty_means_unset():
    config = TunnelConfig.from_env(
        {
            "ARGO_TUNNEL_HOST": "homes.cels.anl.gov",
            "ARGO_TUNNEL_JUMP": "",
            "ARGO_TUNNEL_PORT": "10999",
            "ARGO_TUNNEL_USER": "abc",
        }
    )
    # An empty variable keeps the default rather than blanking it: only the
    # explicit word "none" disables the jump hop.
    assert config.jump == "logins.cels.anl.gov"
    assert config.port == 10999
    assert config.user == "abc"
    assert config.login == "abc@homes.cels.anl.gov"
    assert config.jump_login == "abc@logins.cels.anl.gov"


def test_env_can_disable_the_jump_hop():
    assert TunnelConfig.from_env({"ARGO_TUNNEL_JUMP": "none"}).jump is None


def test_a_bad_port_is_refused_rather_than_ignored():
    with pytest.raises(TunnelError) as caught:
        TunnelConfig.from_env({"ARGO_TUNNEL_PORT": "not-a-port"})
    assert "ARGO_TUNNEL_PORT" in str(caught.value)


def test_socket_path_differs_per_target_so_two_masters_never_collide():
    a = TunnelConfig(user="u", host="h1")
    b = TunnelConfig(user="u", host="h2")
    assert a.socket != b.socket
    # The port is part of the identity too: two forwards need two masters.
    assert a.socket != replace(a, port=9999).socket


def test_a_configured_socket_path_wins():
    config = TunnelConfig(control_path="/tmp/ctl")
    assert str(config.socket) == "/tmp/ctl"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check, port_open, expected",
    [
        (_absent_check(), False, TunnelState.ABSENT),
        (_wedged_check(), False, TunnelState.WEDGED),
        (_alive_check(), False, TunnelState.IDLE),
        (_alive_check(), True, TunnelState.FORWARDING),
    ],
)
def test_status_separates_the_four_states(check, port_open, expected):
    assert _tunnel(FakeRunner([check]), port_open=port_open).status() == expected


def test_an_absent_master_is_never_blamed_on_the_port():
    """The probe must not run when nothing answers: a busy port would lie."""
    probed = []
    tunnel = Tunnel(
        TunnelConfig(user="u"),
        runner=FakeRunner([_absent_check()]),
        prober=lambda bind, port: probed.append(port) or True,
    )
    assert tunnel.status() == TunnelState.ABSENT
    assert probed == []


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------


def test_auth_builds_a_master_connection_and_is_the_only_interactive_call():
    runner = FakeRunner([_absent_check(), CommandResult(0)])
    _tunnel(runner).auth()
    argv, interactive = runner.calls[-1]
    assert interactive is True
    assert "-M" in argv and "-f" in argv and "-N" in argv
    assert "BatchMode=yes" not in argv
    assert f"ControlPersist={TunnelConfig().control_persist}" in argv
    assert "--" not in argv


def test_auth_names_the_forward_options_it_will_need_later():
    runner = FakeRunner([_absent_check(), CommandResult(0)])
    _tunnel(runner).auth()
    assert "ExitOnForwardFailure=yes" in runner.argvs[-1]


def test_auth_refuses_to_ask_for_a_second_approval_over_a_live_master():
    with pytest.raises(TunnelError) as caught:
        _tunnel(FakeRunner([_alive_check()])).auth()
    assert "already answers" in str(caught.value)
    assert caught.value.hint


def test_auth_names_logout_when_the_socket_is_wedged():
    with pytest.raises(TunnelError) as caught:
        _tunnel(FakeRunner([_wedged_check()])).auth()
    assert "does not answer" in str(caught.value)
    assert "logout" in (caught.value.hint or "")


def test_auth_reports_ssh_output_on_failure():
    runner = FakeRunner(
        [_absent_check(), CommandResult(SSH_FAILURE, "", "Permission denied")]
    )
    with pytest.raises(TunnelError) as caught:
        _tunnel(runner).auth()
    assert "Permission denied" in str(caught.value)


# ---------------------------------------------------------------------------
# start / stop / logout
# ---------------------------------------------------------------------------


def test_start_adds_the_forward_with_the_full_spec():
    runner = FakeRunner([_alive_check(), CommandResult(0)])
    _tunnel(runner, port_open=False).start()
    argv = runner.argvs[-1]
    assert "-O" in argv and argv[argv.index("-O") + 1] == "forward"
    assert argv[argv.index("-D") + 1] == "127.0.0.1:10801"


def test_start_is_idempotent_when_the_forward_is_already_up():
    runner = FakeRunner([_alive_check()])
    result = _tunnel(runner, port_open=True).start()
    assert result.ok
    assert len(runner.calls) == 1  # only the check; ssh -O forward never ran


def test_start_without_a_master_tells_the_operator_what_to_run():
    with pytest.raises(TunnelError) as caught:
        _tunnel(FakeRunner([_absent_check()])).start()
    assert "auth" in (caught.value.hint or "")


def test_start_over_a_wedged_master_also_refuses():
    with pytest.raises(TunnelError):
        _tunnel(FakeRunner([_wedged_check()])).start()


def test_stop_cancels_the_same_spec_it_forwarded():
    runner = FakeRunner([_alive_check(), CommandResult(0)])
    _tunnel(runner, port_open=True).stop()
    argv = runner.argvs[-1]
    assert argv[argv.index("-O") + 1] == "cancel"
    assert argv[argv.index("-D") + 1] == "127.0.0.1:10801"


def test_stop_without_a_master_is_a_no_op():
    runner = FakeRunner([_absent_check()])
    assert _tunnel(runner).stop().ok
    assert len(runner.calls) == 1


def test_stop_on_an_idle_master_does_not_send_a_cancel():
    """A cancel for a forward that was never added answers with ssh's generic
    failure text, which cannot be told from a real failure — so it is never
    sent."""
    runner = FakeRunner([_alive_check()])
    result = _tunnel(runner, port_open=False).stop()
    assert result.ok
    assert len(runner.calls) == 1  # the check; no '-O cancel'


def test_stop_names_logout_when_the_master_is_wedged():
    with pytest.raises(TunnelError) as caught:
        _tunnel(FakeRunner([_wedged_check()])).stop()
    assert "logout" in (caught.value.hint or "")


def test_stop_reports_a_real_cancel_failure():
    runner = FakeRunner([_alive_check(), CommandResult(SSH_FAILURE, "", "boom")])
    with pytest.raises(TunnelError) as caught:
        _tunnel(runner, port_open=True).stop()
    assert "boom" in str(caught.value)


def test_logout_exits_the_master():
    runner = FakeRunner([_alive_check(), CommandResult(0)])
    _tunnel(runner).logout()
    assert runner.argvs[-1][runner.argvs[-1].index("-O") + 1] == "exit"


# ---------------------------------------------------------------------------
# argv shape
# ---------------------------------------------------------------------------


def test_every_non_interactive_command_runs_in_batch_mode():
    runner = FakeRunner([_alive_check()])
    tunnel = _tunnel(runner, port_open=True)
    tunnel.status()
    tunnel.start()
    for argv, interactive in runner.calls:
        if "-O" in argv:
            assert "BatchMode=yes" in argv
            assert interactive is False


def test_the_jump_host_is_carried_on_the_command():
    runner = FakeRunner([_alive_check()])
    _tunnel(runner, port_open=True).status()
    argv = runner.argvs[-1]
    assert argv[argv.index("-J") + 1] == "someone@logins.cels.anl.gov"


def test_no_jump_hop_means_no_j_flag():
    runner = FakeRunner([_alive_check()])
    _tunnel(runner, port_open=True, jump=None).status()
    assert "-J" not in runner.argvs[-1]


# ---------------------------------------------------------------------------
# SOCKS probe
# ---------------------------------------------------------------------------


def test_probe_reports_a_closed_port_as_false():
    # Port 1 is reserved and nothing listens on it; the probe must not raise.
    assert probe_socks("127.0.0.1", 1, timeout=0.2) is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_proxy_url_needs_no_ssh(capsys):
    assert main(["proxy-url", "--port", "10999"]) == 0
    assert capsys.readouterr().out.strip() == "socks5://127.0.0.1:10999"


def test_cli_status_exits_non_zero_unless_forwarding(monkeypatch, capsys):
    monkeypatch.setattr(
        "llm_rosetta_shim_argo.tunnel.run_subprocess", FakeRunner([_absent_check()])
    )
    assert main(["status"]) == 1
    assert "absent" in capsys.readouterr().out


def test_cli_status_json_shape(monkeypatch, capsys):
    monkeypatch.setattr(
        "llm_rosetta_shim_argo.tunnel.run_subprocess", FakeRunner([_absent_check()])
    )
    assert main(["status", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "absent"
    assert payload["proxy_url"] == "socks5://127.0.0.1:10801"


def test_an_option_before_the_subcommand_is_not_overwritten_by_it(capsys):
    """Regression: the subparser shares the parent's options, and its own
    default used to land *after* the parent parsed one, silently restoring
    ``socks5://127.0.0.1:10801`` for ``--port 10999 proxy-url``."""
    expected = "socks5://127.0.0.1:10999"
    assert _stdout_of(["proxy-url", "--port", "10999"], capsys) == expected
    assert _stdout_of(["--port", "10999", "proxy-url"], capsys) == expected


def test_json_reads_the_same_state_in_either_position(monkeypatch, capsys):
    monkeypatch.setattr(
        "llm_rosetta_shim_argo.tunnel.run_subprocess", FakeRunner([_absent_check()])
    )
    assert main(["status", "--json", "--port", "10999"]) == 1
    first = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        "llm_rosetta_shim_argo.tunnel.run_subprocess", FakeRunner([_absent_check()])
    )
    assert main(["--json", "--port", "10999", "status"]) == 1
    second = json.loads(capsys.readouterr().out)
    assert first == second
    assert first["proxy_url"] == "socks5://127.0.0.1:10999"


def test_cli_without_a_command_prints_help_and_fails(capsys):
    assert main([]) == 2
    assert "llm-rosetta-argo-tunnel" in capsys.readouterr().out


def test_cli_prints_the_hint_on_a_refused_action(monkeypatch, capsys):
    monkeypatch.setattr(
        "llm_rosetta_shim_argo.tunnel.run_subprocess", FakeRunner([_absent_check()])
    )
    assert main(["start"]) == 1
    err = capsys.readouterr().err
    assert "hint:" in err and "auth" in err
