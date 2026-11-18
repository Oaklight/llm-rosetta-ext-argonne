"""The SSH tunnel that makes ``apps.inside.anl.gov`` reachable, as a CLI.

The Argo endpoint resolves only inside the Argonne network, and the path in
reaches a jump host that asks for Duo MFA on each new connection.  This module
owns both facts: it keeps one authenticated master connection open, and it
publishes a dynamic (SOCKS5) forward on top of it.

Why SOCKS and not a local port forward
--------------------------------------

``ssh -L 127.0.0.1:PORT:apps.inside.anl.gov:443`` would force every client to
address ``https://127.0.0.1:PORT``, while the upstream certificate names
``apps.inside.anl.gov`` — host-name verification fails, and the gateway exposes
no TLS-verify knob.  A dynamic forward sends the *hostname* to the far side
(RFC 1928, ``ATYPE_DOMAIN``); the client still connects to
``https://apps.inside.anl.gov``, so SNI and certificate verification are the
ordinary ones and the shim's ``base_url`` needs no edit.

Why the prompt lives here
-------------------------

A forward can be added to an already-authenticated session
(``ssh -O forward``), so exactly one command — :func:`command_auth` — can block
on a prompt.  Everything else runs with ``BatchMode=yes`` and fails rather than
wait, which is what makes the CLI safe to call from a launcher or a unit file.

State model
-----------

``status`` reports four states, because two of them look alike from a process
list:

===============  =========================================================
``forwarding``   master answers and the SOCKS port completes a greeting
``idle``         master answers, the SOCKS port does not — no forward yet
``wedged``       the control socket exists but does not answer
``absent``       there is no control socket
===============  =========================================================
"""

from __future__ import annotations

import argparse
import hashlib
import os
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, Sequence

__all__ = [
    "Tunnel",
    "TunnelConfig",
    "TunnelState",
    "main",
]

#: The jump host that serves outside the Argonne network, and the machine that
#: can reach the API host.  Both are vendor facts, so they are defaults here
#: rather than arguments every caller has to repeat.
DEFAULT_JUMP_HOST = "logins.cels.anl.gov"
DEFAULT_HOST = "homes.cels.anl.gov"

#: The SOCKS port.  ``1080`` is the conventional one and is often already
#: bound; a nearby fixed number keeps the printed ``proxy-url`` stable across
#: restarts, so a provider config written once keeps working.
DEFAULT_PORT = 10801
DEFAULT_BIND = "127.0.0.1"

#: How long the master stays usable after the last multiplexed session ends.
#: This is the interval the operator does not have to authenticate again.
#: Only used when the operator's own ``ssh_config`` says nothing: a
#: ``ControlPersist`` the system set is theirs, and is left alone.
DEFAULT_CONTROL_PERSIST = "8h"

#: Where this tool puts its control socket when ``ssh_config`` puts none.
#: ``%s`` is the data directory: ``$XDG_CONFIG_HOME`` or ``~/.config``.
CONTROL_SOCKET_SUBDIR = "tunnel"

#: ``sockaddr_un.sun_path`` is 108 bytes on Linux and 104 on macOS, so a
#: socket path has a hard ceiling that a deep ``$HOME`` can cross.
_MAX_SOCKET_PATH = 100

#: Watch for a link that went away without closing: a forward over a dead
#: connection still looks bound on this side.
DEFAULT_SERVER_ALIVE_INTERVAL = 15
DEFAULT_SERVER_ALIVE_COUNT_MAX = 4

#: ``ssh -O`` returns this when the command itself fails (no socket, refused).
SSH_FAILURE = 255

#: A wedged master is one that neither answers nor refuses.  Waiting longer
#: only delays the message the operator needs.
CONTROL_PROBE_TIMEOUT = 15.0


class TunnelState:
    """The four states :meth:`Tunnel.status` reports."""

    FORWARDING = "forwarding"
    IDLE = "idle"
    WEDGED = "wedged"
    ABSENT = "absent"


class TunnelError(Exception):
    """An operation could not complete, with the advice the operator needs.

    Attributes:
        hint: One command or fix to print after the message, or ``None``.
    """

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class TunnelConfig:
    """Everything the tunnel needs to know about *where* it connects.

    Attributes:
        host: The machine the forward is made from — the one that can reach
            the API host.
        jump: The externally reachable hop, or ``None`` for a direct
            connection (a host already inside the network).
        user: The account name used on both hops.
        bind: Address the SOCKS port listens on.  ``127.0.0.1`` unless a
            container on the same host has to reach it.
        port: TCP port of the SOCKS listener.
        control_path: The multiplexing socket, when one is named outright.
            ``None`` means "whatever the operator's ``ssh_config`` says, else
            this tool's own location" — see :attr:`socket`.
        control_persist: How long the master outlives its last session, when
            one is named outright.  ``None`` means "``ssh_config``'s value,
            else :data:`DEFAULT_CONTROL_PERSIST`" — see
            :meth:`effective_control_persist`.
        state_dir: Where this tool keeps its socket and its small state file.
            ``None`` means ``$XDG_CONFIG_HOME/llm-rosetta-gateway``, else
            ``~/.config/llm-rosetta-gateway``.
        ssh: The ``ssh`` executable.
        ssh_config: An extra ssh config file to read.  ``ssh`` reads
            ``~/.ssh/config`` on its own; this is for a deployment that keeps
            its settings elsewhere.
    """

    host: str = DEFAULT_HOST
    jump: str | None = DEFAULT_JUMP_HOST
    user: str | None = None
    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    control_path: Path | None = None
    control_persist: str | None = None
    state_dir: Path | None = None
    ssh: str = "ssh"
    ssh_config: Path | None = None

    # -- identity -----------------------------------------------------------

    @property
    def login(self) -> str:
        """``user@host`` when a user is configured, else ``host``."""
        return f"{self.user}@{self.host}" if self.user else self.host

    @property
    def jump_login(self) -> str | None:
        """The jump host in ``-J`` form, carrying the same user."""
        if self.jump is None:
            return None
        return f"{self.user}@{self.jump}" if self.user else self.jump

    # -- placement ----------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        """This tool's own state directory.

        The gateway's data directory is the natural home for a socket that
        exists to serve it, and it is the one location an operator already
        knows how to back up, move or remove.  ``$XDG_CONFIG_HOME`` is
        honoured because that is where the gateway puts its config.
        """
        if self.state_dir is not None:
            return Path(self.state_dir).expanduser()
        base = os.environ.get("XDG_CONFIG_HOME", "").strip()
        root = Path(base).expanduser() if base else Path.home() / ".config"
        return root / "llm-rosetta-gateway"

    def _socket_name(self) -> str:
        """A file name that is unique to this target.

        Short on purpose: the full path must fit in ``sun_path``.  The digest
        covers everything that makes two tunnels different — the target, the
        jump hop, the login and the port — so two configurations never share
        a name.
        """
        identity = f"{self.login}|{self.jump or ''}|{self.port}|{self.bind}"
        return "ssh-" + hashlib.sha256(identity.encode()).hexdigest()[:12]

    @property
    def socket(self) -> Path:
        """The control socket path this tool uses.

        Resolution order, widest first — the operator's own setup wins:

        1. an explicitly configured path (:attr:`control_path`);
        2. ``ControlPath`` from ``ssh_config``, with ssh's tokens expanded by
           ssh itself, when it names one;
        3. this tool's own location under :attr:`data_dir`.

        The second case is why the path is read from ``ssh -G`` rather than
        computed: a system ``ControlMaster auto`` with
        ``ControlPath ~/.ssh/cm-%C`` is a deliberate choice, and a tool that
        invented its own path would leave that master unmanaged — status would
        report ``absent`` while an authenticated session sat right there.

        Returns:
            The socket path.  A path that would exceed the ``sun_path`` limit
            is replaced by a hashed one under the same directory.
        """
        if self.control_path is not None:
            return Path(self.control_path).expanduser()

        system = self.ssh_config_path("controlpath")
        if system:
            path = Path(os.path.expanduser(system))
            if len(str(path)) <= _MAX_SOCKET_PATH:
                return path
            # Too deep for a Unix socket: keep the operator's directory, since
            # the permission on it is the part that matters, and shorten the
            # name.
            return path.parent / self._socket_name()

        directory = self.data_dir / CONTROL_SOCKET_SUBDIR
        candidate = directory / self._socket_name()
        if len(str(candidate)) > _MAX_SOCKET_PATH:
            # A deep home is not the operator's fault and not something we can
            # fix by asking; the run directory is short and per-user.
            fallback = Path("/tmp") / f"argo-tunnel-{os.getuid()}"
            return fallback / self._socket_name()
        return candidate

    def ssh_config_path(self, keyword: str) -> str | None:
        """Ask ssh what *keyword* resolves to for this target.

        ``ssh -G`` prints the effective configuration after every file and
        every ``-o`` has been applied, which is the only reliable way to see a
        system-wide choice.  The probe runs at most once per process per
        configuration.

        Args:
            keyword: A lowercase directive name, e.g. ``"controlpath"``.

        Returns:
            The value, or ``None`` when ssh says nothing useful — the binary
            is missing, the target does not resolve, or the value is ssh's own
            "unset" spelling.
        """
        resolved = _resolved_ssh_config(self)
        return resolved.get(keyword) or None

    def effective_control_persist(self) -> str:
        """How long the master survives, as this run should set it.

        Order: an explicitly configured value, then ``ssh_config``'s, then
        :data:`DEFAULT_CONTROL_PERSIST`.  ``ssh_config``'s ``ControlPersist``
        is honoured for the same reason ``ControlPath`` is: it is the
        operator's statement about how long their own session stays good for,
        and this tool's job is to reuse that session, not to overrule it.

        Returns:
            An ssh ``ControlPersist`` value: a time with a unit, or ``"yes"``.
        """
        if self.control_persist is not None:
            return self.control_persist
        system = self.ssh_config_path("controlpersist")
        # ``ssh -G`` prints ``controlpersist no`` when nobody configured one —
        # it is the default, not a choice — so it means "unset" here.  A
        # configured value comes back normalised to seconds (``4h`` → 14400),
        # which ``-o`` accepts unchanged.
        if system and system.lower() != "no":
            return system
        return DEFAULT_CONTROL_PERSIST

    @property
    def proxy_url(self) -> str:
        """The value an operator pastes into a provider's ``proxy`` field."""
        return f"socks5://{self.bind}:{self.port}"

    @property
    def forward_spec(self) -> str:
        """The ``-D`` argument, in the form ssh expects."""
        return f"{self.bind}:{self.port}"

    # -- construction -------------------------------------------------------

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> TunnelConfig:
        """Build a config from ``ARGO_TUNNEL_*`` variables.

        Args:
            env: The environment to read; defaults to :data:`os.environ`.

        Returns:
            The merged config.  An empty variable counts as unset, so a
            deployment can blank a default rather than unset it.

        Raises:
            TunnelError: ``ARGO_TUNNEL_PORT`` is not a port number.
        """
        source = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = source.get(name, "").strip()
            return value or None

        config = cls()
        if host := get("ARGO_TUNNEL_HOST"):
            config = replace(config, host=host)
        if jump := get("ARGO_TUNNEL_JUMP"):
            config = replace(config, jump=None if jump.lower() == "none" else jump)
        if user := get("ARGO_TUNNEL_USER"):
            config = replace(config, user=user)
        if bind := get("ARGO_TUNNEL_BIND"):
            config = replace(config, bind=bind)
        if port := get("ARGO_TUNNEL_PORT"):
            try:
                config = replace(config, port=int(port))
            except ValueError as exc:
                raise TunnelError(
                    f"ARGO_TUNNEL_PORT is not a port number: {port!r}"
                ) from exc
        if socket_path := get("ARGO_TUNNEL_SOCKET"):
            config = replace(config, control_path=Path(socket_path).expanduser())
        if persist := get("ARGO_TUNNEL_CONTROL_PERSIST"):
            config = replace(config, control_persist=persist)
        if state_dir := get("ARGO_TUNNEL_STATE_DIR"):
            config = replace(config, state_dir=Path(state_dir).expanduser())
        return config


@dataclass(frozen=True)
class CommandResult:
    """What a subprocess said, in the three pieces callers branch on."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """Whether the command exited successfully."""
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout and stderr together, for messages."""
        return (self.stdout + self.stderr).strip()


class Runner(Protocol):
    """Runs an argv and reports its result.  Injected so tests never SSH."""

    def __call__(
        self, argv: Sequence[str], *, interactive: bool = False
    ) -> CommandResult:
        """Execute *argv*.

        Args:
            argv: The command, already split.
            interactive: When true, the child inherits the terminal so a
                prompt can be answered.  When false, stdin is closed and ssh
                runs in batch mode, so it fails instead of waiting.
        """


def run_subprocess(argv: Sequence[str], *, interactive: bool = False) -> CommandResult:
    """Execute *argv* as the real :class:`Runner`.

    A timeout is reported as :data:`SSH_FAILURE` with a message on stderr, so
    a hung control socket becomes a state rather than a hung CLI.
    """
    try:
        completed = subprocess.run(
            list(argv),
            check=False,
            text=True,
            capture_output=not interactive,
            stdin=None if interactive else subprocess.DEVNULL,
            timeout=None if interactive else CONTROL_PROBE_TIMEOUT,
        )
    except FileNotFoundError as exc:
        return CommandResult(SSH_FAILURE, "", f"cannot run {argv[0]}: {exc}")
    except subprocess.TimeoutExpired:
        return CommandResult(
            SSH_FAILURE,
            "",
            f"timed out after {CONTROL_PROBE_TIMEOUT:.0f}s waiting for {argv[0]}",
        )
    return CommandResult(
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
    )


#: ``ssh -G`` answers are cached per target: the resolution is a property of
#: the configuration, not of the call, and ``status`` asks for two keys.
_SSH_G_CACHE: dict[tuple[str, ...], dict[str, str]] = {}


def _resolved_ssh_config(config: TunnelConfig) -> dict[str, str]:
    """The effective ssh configuration for this target, as ``ssh -G`` sees it.

    ``ssh -G`` prints the configuration ssh would use without connecting, so it
    is the only way to read a system-wide ``ControlMaster``/``ControlPath``/
    ``ControlPersist`` — the values the operator set in ``~/.ssh/config`` or
    ``/etc/ssh/ssh_config``.

    Args:
        config: Supples the target, the jump hop and any extra config file.

    Returns:
        Lowercase directive → value.  An empty mapping when ssh cannot be
        asked; every caller then falls back to this tool's own default.
    """
    key = (config.ssh, config.login, config.jump or "", str(config.ssh_config or ""))
    cached = _SSH_G_CACHE.get(key)
    if cached is not None:
        return cached

    argv = [config.ssh]
    if config.ssh_config:
        argv += ["-F", str(config.ssh_config)]
    argv += ["-G"]
    if config.jump:
        argv += ["-J", config.jump_login or config.jump]
    argv.append(config.login)

    resolved: dict[str, str] = {}
    try:
        done = subprocess.run(
            argv, check=False, text=True, capture_output=True, stdin=subprocess.DEVNULL
        )
    except OSError:
        _SSH_G_CACHE[key] = resolved
        return resolved
    if done.returncode != 0:
        _SSH_G_CACHE[key] = resolved
        return resolved
    for line in done.stdout.splitlines():
        name, _, value = line.partition(" ")
        if name and value:
            resolved[name.lower()] = value.strip()
    _SSH_G_CACHE[key] = resolved
    return resolved


def probe_socks(bind: str, port: int, *, timeout: float = 3.0) -> bool:
    """Whether a SOCKS5 server answers on *bind*:*port*.

    Only the method-negotiation greeting is sent: enough to prove the port is
    a live SOCKS listener rather than any process that happens to hold it, and
    cheap enough to run on every ``status``.

    Args:
        bind: Address to connect to.
        port: Port to connect to.
        timeout: Seconds to wait for the greeting.

    Returns:
        ``True`` when the peer answers the greeting with a supported method.
    """
    try:
        with socket.create_connection((bind, port), timeout=timeout) as sock:
            sock.sendall(struct.pack("BBB", 0x05, 0x01, 0x00))
            reply = sock.recv(2)
    except OSError:
        return False
    return len(reply) == 2 and reply[0] == 0x05 and reply[1] != 0xFF


class Tunnel:
    """The operations the CLI exposes, over an injected runner.

    Attributes:
        config: Where the tunnel connects.
        runner: How a command is executed.
        prober: How the SOCKS port is checked; injectable for tests.
    """

    def __init__(
        self,
        config: TunnelConfig,
        runner: Runner = run_subprocess,
        prober: Any = probe_socks,
    ) -> None:
        self.config = config
        self.runner = runner
        self.prober = prober

    # -- argv builders ------------------------------------------------------

    def _transport_args(self, *, batch: bool = True) -> list[str]:
        """Options every command shares: the socket and the hop.

        ``BatchMode=yes`` is the difference between "fail" and "sit at a
        prompt" for the non-interactive commands, so it is set here once and
        cleared only by :meth:`auth`.
        """
        argv = [self.config.ssh]
        # ``-F`` here and in the ``ssh -G`` probe: the socket and the persist
        # value are read from one configuration file, and the connection must
        # be made under the same one, or the master would land somewhere the
        # probe never looked.
        if self.config.ssh_config:
            argv += ["-F", str(self.config.ssh_config)]
        if batch:
            argv += ["-o", "BatchMode=yes"]
        argv += ["-S", str(self.config.socket)]
        if self.config.jump:
            argv += ["-J", self.config.jump_login or self.config.jump]
        return argv

    def _forward_args(self) -> list[str]:
        """The forwarding options and the link watchdog."""
        return [
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            f"ServerAliveInterval={DEFAULT_SERVER_ALIVE_INTERVAL}",
            "-o",
            f"ServerAliveCountMax={DEFAULT_SERVER_ALIVE_COUNT_MAX}",
        ]

    # -- state --------------------------------------------------------------

    def master_state(self) -> str:
        """Ask the control socket whether a master is there.

        Returns:
            :attr:`TunnelState.IDLE`-family values are not used here: the
            result is ``"alive"``, :attr:`TunnelState.ABSENT` or
            :attr:`TunnelState.WEDGED`.
        """
        argv = self._transport_args() + ["-O", "check", self.config.login]
        result = self.runner(argv)
        if result.returncode == 0:
            return "alive"
        # ssh says "No such file or directory" for a socket that was never
        # there.  Anything else — refused, timeout, garbage — means the file
        # exists but the master behind it does not answer.
        if "no such file" in result.output.lower():
            return TunnelState.ABSENT
        return TunnelState.WEDGED

    def status(self) -> str:
        """The single state a caller acts on.

        Returns:
            One of :class:`TunnelState`.  The forward is probed only when the
            master answers, so an absent master is never reported as a port
            problem.
        """
        master = self.master_state()
        if master != "alive":
            return master
        if self.prober(self.config.bind, self.config.port):
            return TunnelState.FORWARDING
        return TunnelState.IDLE

    # -- commands -----------------------------------------------------------

    def auth(self) -> CommandResult:
        """Open the master connection.  The only step that may prompt.

        Returns:
            The result of the foreground ssh call.

        Raises:
            TunnelError: A master already answers, or ssh failed.  Re-running
                auth over a live master would ask for a second Duo approval
                for no benefit.
        """
        state = self.master_state()
        if state == "alive":
            raise TunnelError(
                f"a master already answers on {self.config.socket}",
                hint="nothing to do; run 'status' to see the forward",
            )
        if state == TunnelState.WEDGED:
            raise TunnelError(
                f"the control socket {self.config.socket} exists but does not answer",
                hint="run 'logout' to clear it, then 'auth' again",
            )
        self.config.socket.parent.mkdir(parents=True, exist_ok=True)
        # ``-M`` only marks this connection as a master.  When the operator's
        # ssh_config already says ``ControlMaster auto`` that is redundant but
        # harmless; what must not be forced is ``ControlPath`` — it is passed
        # through ``-S`` on every command, so the master and the clients can
        # never disagree about which socket is in play.
        argv = self._transport_args(batch=False) + [
            "-M",
            "-N",
            "-f",
            "-o",
            f"ControlPersist={self.config.effective_control_persist()}",
        ]
        argv += self._forward_args()
        argv.append(self.config.login)
        result = self.runner(argv, interactive=True)
        if not result.ok:
            raise TunnelError(
                f"ssh could not open the master connection: {result.output}"
            )
        return result

    def start(self) -> CommandResult:
        """Publish the SOCKS forward on the existing master.

        Returns:
            The result of the ``ssh -O forward`` call; a forward that was
            already up returns a synthetic success without touching ssh.

        Raises:
            TunnelError: No master answers, so there is nothing to forward
                over and the caller must authenticate first.
        """
        state = self.status()
        if state == TunnelState.FORWARDING:
            return CommandResult(0, "forward already up")
        if state in (TunnelState.ABSENT, TunnelState.WEDGED):
            raise TunnelError(
                f"no master connection on {self.config.socket}",
                hint="run 'llm-rosetta-argo-tunnel auth' first",
            )
        argv = (
            self._transport_args()
            + self._forward_args()
            + [
                "-O",
                "forward",
                "-D",
                self.config.forward_spec,
                self.config.login,
            ]
        )
        result = self.runner(argv)
        if not result.ok:
            raise TunnelError(f"ssh could not add the forward: {result.output}")
        return result

    def stop(self) -> CommandResult:
        """Cancel the SOCKS forward and leave the master authenticated.

        The state is read first rather than asking ssh to cancel blind: ssh
        answers a cancel for a forward that was never added with a message
        that is also its generic failure text, so the only reliable way to
        tell "already stopped" from "the cancel failed" is to not send it.

        Returns:
            The result of the ``ssh -O cancel`` call; a tunnel that is not
            forwarding is a no-op.
        """
        state = self.status()
        if state == TunnelState.ABSENT:
            return CommandResult(0, "no master")
        if state == TunnelState.IDLE:
            return CommandResult(0, "forward was not up")
        if state == TunnelState.WEDGED:
            raise TunnelError(
                f"the control socket {self.config.socket} does not answer",
                hint="run 'logout' to clear it",
            )
        argv = self._transport_args() + [
            "-O",
            "cancel",
            "-D",
            self.config.forward_spec,
            self.config.login,
        ]
        result = self.runner(argv)
        if not result.ok:
            raise TunnelError(f"ssh could not cancel the forward: {result.output}")
        return result

    def logout(self) -> CommandResult:
        """Drop the master, and with it any forward on it.

        Returns:
            The result of ``ssh -O exit``; no master is a no-op.
        """
        if self.master_state() != "alive":
            return CommandResult(0, "no master")
        argv = self._transport_args() + ["-O", "exit", self.config.login]
        result = self.runner(argv)
        if not result.ok:
            raise TunnelError(f"ssh could not close the master: {result.output}")
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    epilog = (
        "Environment: ARGO_TUNNEL_HOST, ARGO_TUNNEL_JUMP (or 'none'), "
        "ARGO_TUNNEL_USER, ARGO_TUNNEL_BIND, ARGO_TUNNEL_PORT, "
        "ARGO_TUNNEL_SOCKET, ARGO_TUNNEL_CONTROL_PERSIST, ARGO_TUNNEL_STATE_DIR."
    )
    # The connection options are accepted before *and* after the subcommand.
    # A launcher writes them once at the end of the line ("start --port N"),
    # while a script may prefer them up front; one parser serving both beats
    # a rule the operator has to remember.
    # ``SUPPRESS``, not ``None``: a subparser built from the same parent would
    # otherwise write its own default over a value the operator gave *before*
    # the subcommand, so ``--port 9 status`` would report port 10801.  With no
    # default, an option that was never given leaves no attribute at all, and
    # :func:`_config_from_args` reads each one through ``getattr``.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--host",
        default=argparse.SUPPRESS,
        help=f"machine the forward is made from (default: {DEFAULT_HOST})",
    )
    common.add_argument(
        "--jump",
        default=argparse.SUPPRESS,
        help=f"externally reachable hop, or 'none' (default: {DEFAULT_JUMP_HOST})",
    )
    common.add_argument(
        "--user", default=argparse.SUPPRESS, help="account name on both hops"
    )
    common.add_argument(
        "--bind",
        default=argparse.SUPPRESS,
        help=f"SOCKS bind address (default: {DEFAULT_BIND})",
    )
    common.add_argument(
        "--port",
        type=int,
        default=argparse.SUPPRESS,
        help=f"SOCKS port (default: {DEFAULT_PORT})",
    )
    common.add_argument(
        "--control-persist",
        default=argparse.SUPPRESS,
        help=(
            "how long the master survives idle; defaults to the operator's "
            f"ssh_config ControlPersist, else {DEFAULT_CONTROL_PERSIST}"
        ),
    )
    common.add_argument(
        "--state-dir",
        default=argparse.SUPPRESS,
        help=(
            "where this tool keeps its socket when ssh_config names none "
            "(default: $XDG_CONFIG_HOME/llm-rosetta-gateway)"
        ),
    )
    common.add_argument(
        "--ssh-config",
        default=argparse.SUPPRESS,
        help="extra ssh config file to read (ssh reads ~/.ssh/config itself)",
    )
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="report status as JSON instead of one line",
    )

    parser = argparse.ArgumentParser(
        prog="llm-rosetta-argo-tunnel",
        description=(
            "Own the SSH master connection and the SOCKS5 forward that make "
            "the Argo API host reachable."
        ),
        epilog=epilog,
        parents=[common],
    )

    sub = parser.add_subparsers(dest="command")
    sub.add_parser(
        "auth",
        parents=[common],
        help="open the master connection (this is the MFA prompt)",
    )
    sub.add_parser(
        "start", parents=[common], help="publish the SOCKS forward on the master"
    )
    sub.add_parser("stop", parents=[common], help="cancel the forward, keep the master")
    sub.add_parser(
        "status", parents=[common], help="report forwarding / idle / wedged / absent"
    )
    sub.add_parser("logout", parents=[common], help="drop the master")
    sub.add_parser(
        "proxy-url",
        parents=[common],
        help="print the socks5:// URL for a provider config",
    )
    return parser


def _config_from_args(args: argparse.Namespace) -> TunnelConfig:
    """Merge the command line over the environment.

    Every option is read through ``getattr`` because the parser suppresses
    unset defaults: an absent option and an option given before the
    subcommand must both end up as "no override", and the subparser must not
    be able to blank the one that came first.

    Args:
        args: The parsed namespace.

    Returns:
        The effective config.

    Raises:
        TunnelError: ``--port`` is not a port number.
    """
    config = TunnelConfig.from_env()
    overrides: dict[str, Any] = {}
    if host := getattr(args, "host", None):
        overrides["host"] = host
    if jump := getattr(args, "jump", None):
        overrides["jump"] = None if jump.lower() == "none" else jump
    if user := getattr(args, "user", None):
        overrides["user"] = user
    if bind := getattr(args, "bind", None):
        overrides["bind"] = bind
    if (port := getattr(args, "port", None)) is not None:
        overrides["port"] = port
    if persist := getattr(args, "control_persist", None):
        overrides["control_persist"] = persist
    if state_dir := getattr(args, "state_dir", None):
        overrides["state_dir"] = Path(state_dir).expanduser()
    if ssh_config := getattr(args, "ssh_config", None):
        overrides["ssh_config"] = Path(ssh_config).expanduser()
    return replace(config, **overrides) if overrides else config


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv``.

    Returns:
        A process exit code: ``0`` success, ``1`` the operation did not
        complete, ``2`` a usage error.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        config = _config_from_args(args)
    except TunnelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return 1

    tunnel = Tunnel(config)

    if args.command == "proxy-url":
        print(config.proxy_url)
        return 0

    if args.command == "status":
        state = tunnel.status()
        if getattr(args, "json", False):
            import json

            print(
                json.dumps(
                    {
                        "state": state,
                        "proxy_url": config.proxy_url,
                        "socket": str(config.socket),
                        "host": config.host,
                        "jump": config.jump,
                    }
                )
            )
        else:
            print(f"{state}\t{config.proxy_url}\t{config.socket}")
        # A forwarding tunnel is the only state a caller can act on.
        return 0 if state == TunnelState.FORWARDING else 1

    actions = {
        "auth": tunnel.auth,
        "start": tunnel.start,
        "stop": tunnel.stop,
        "logout": tunnel.logout,
    }
    try:
        result = actions[args.command]()
    except TunnelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        return 1
    if result.stdout.strip():
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
