"""Tests for operations module."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from compose_farm.cli import lifecycle
from compose_farm.config import Config, Host
from compose_farm.executor import CommandResult
from compose_farm.operations import (
    PreflightResult,
    _migrate_stack,
    _stop_stacks_on_hosts,
    _up_stack_simple,
    build_discovery_results,
    build_up_cmd,
)


@pytest.fixture
def basic_config(tmp_path: Path) -> Config:
    """Create a basic test config."""
    compose_dir = tmp_path / "compose"
    stack_dir = compose_dir / "test-service"
    stack_dir.mkdir(parents=True)
    (stack_dir / "docker-compose.yml").write_text("services: {}")
    return Config(
        compose_dir=compose_dir,
        hosts={
            "host1": Host(address="localhost"),
            "host2": Host(address="localhost"),
        },
        stacks={"test-service": "host2"},
    )


class TestMigrationCommands:
    """Tests for migration command sequence."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> Config:
        """Create a test config."""
        compose_dir = tmp_path / "compose"
        stack_dir = compose_dir / "test-service"
        stack_dir.mkdir(parents=True)
        (stack_dir / "docker-compose.yml").write_text("services: {}")
        return Config(
            compose_dir=compose_dir,
            hosts={
                "host1": Host(address="localhost"),
                "host2": Host(address="localhost"),
            },
            stacks={"test-service": "host2"},
        )

    async def test_migration_uses_pull_ignore_buildable(self, config: Config) -> None:
        """Migration should use 'pull --ignore-buildable' to skip buildable images."""
        commands_called: list[str] = []

        async def mock_run_compose_step(
            cfg: Config,
            stack: str,
            command: str,
            *,
            raw: bool,
            host: str | None = None,
        ) -> CommandResult:
            commands_called.append(command)
            return CommandResult(
                stack=stack,
                exit_code=0,
                success=True,
            )

        with patch(
            "compose_farm.operations._run_compose_step",
            side_effect=mock_run_compose_step,
        ):
            await _migrate_stack(
                config,
                "test-service",
                current_host="host1",
                target_host="host2",
                prefix="[test]",
                raw=False,
            )

        # Migration should call pull with --ignore-buildable, then build, then down
        assert "pull --ignore-buildable" in commands_called
        assert "build" in commands_called
        assert "down" in commands_called
        # pull should come before build
        pull_idx = commands_called.index("pull --ignore-buildable")
        build_idx = commands_called.index("build")
        assert pull_idx < build_idx

    async def test_migration_dispatches_hooks_in_order(self, config: Config) -> None:
        """Migration dispatches lifecycle hooks in the expected order."""
        events_called: list[str] = []

        async def mock_dispatch_hook(
            cfg: Config,
            event: object,
            stack: str,
            *,
            source_host: str | None = None,
            target_host: str | None = None,
            metadata: dict[str, str] | None = None,
        ) -> None:
            _ = (cfg, stack, source_host, target_host, metadata)
            events_called.append(str(event))

        async def mock_run_compose_step(
            cfg: Config,
            stack: str,
            command: str,
            *,
            raw: bool,
            host: str | None = None,
        ) -> CommandResult:
            _ = (cfg, stack, command, raw, host)
            return CommandResult(stack="test-service", exit_code=0, success=True)

        with (
            patch("compose_farm.operations._dispatch_hook", side_effect=mock_dispatch_hook),
            patch("compose_farm.operations._run_compose_step", side_effect=mock_run_compose_step),
        ):
            result = await _migrate_stack(
                config,
                "test-service",
                current_host="host1",
                target_host="host2",
                prefix="[test]",
                raw=False,
            )

        assert result is None
        assert events_called == [
            "pre_migrate",
            "pre_stop_source",
            "post_stop_source",
            "pre_start_target",
        ]

    async def test_migration_dispatches_failure_hook_on_failed_down(self, config: Config) -> None:
        """Failed down step dispatches migrate_failed hook."""
        events_called: list[str] = []

        async def mock_dispatch_hook(
            cfg: Config,
            event: object,
            stack: str,
            *,
            source_host: str | None = None,
            target_host: str | None = None,
            metadata: dict[str, str] | None = None,
        ) -> None:
            _ = (cfg, stack, source_host, target_host, metadata)
            events_called.append(str(event))

        async def mock_run_compose_step(
            cfg: Config,
            stack: str,
            command: str,
            *,
            raw: bool,
            host: str | None = None,
        ) -> CommandResult:
            _ = (cfg, stack, raw, host)
            return CommandResult(
                stack="test-service",
                exit_code=1 if command == "down" else 0,
                success=command != "down",
            )

        with (
            patch("compose_farm.operations._dispatch_hook", side_effect=mock_dispatch_hook),
            patch("compose_farm.operations._run_compose_step", side_effect=mock_run_compose_step),
        ):
            result = await _migrate_stack(
                config,
                "test-service",
                current_host="host1",
                target_host="host2",
                prefix="[test]",
                raw=False,
            )

        assert result is not None
        assert events_called[-1] == "migrate_failed"


class TestBuildUpCmd:
    """Tests for build_up_cmd helper."""

    def test_basic(self) -> None:
        """Basic up command without flags."""
        assert build_up_cmd() == "up -d"

    def test_with_pull(self) -> None:
        """Up command with pull flag."""
        assert build_up_cmd(pull=True) == "up -d --pull always"

    def test_with_build(self) -> None:
        """Up command with build flag."""
        assert build_up_cmd(build=True) == "up -d --build"

    def test_with_pull_and_build(self) -> None:
        """Up command with both flags."""
        assert build_up_cmd(pull=True, build=True) == "up -d --pull always --build"

    def test_with_service(self) -> None:
        """Up command targeting a specific service."""
        assert build_up_cmd(service="web") == "up -d web"

    def test_with_all_options(self) -> None:
        """Up command with all options."""
        assert (
            build_up_cmd(pull=True, build=True, service="web") == "up -d --pull always --build web"
        )


class TestLifecycleHooks:
    """Tests for non-migration hook dispatch in operations."""

    async def test_up_stack_simple_dispatches_hooks(self, basic_config: Config) -> None:
        """Simple up emits pre_up and post_up on success."""
        events_called: list[str] = []

        async def mock_dispatch_hook(
            cfg: Config,
            event: object,
            stack: str,
            *,
            source_host: str | None = None,
            target_host: str | None = None,
            metadata: dict[str, str] | None = None,
        ) -> None:
            _ = (cfg, stack, source_host, target_host, metadata)
            events_called.append(str(event))

        with (
            patch("compose_farm.operations._dispatch_hook", side_effect=mock_dispatch_hook),
            patch(
                "compose_farm.operations.check_stack_requirements",
                return_value=PreflightResult([], [], []),
            ),
            patch(
                "compose_farm.operations.run_compose",
                return_value=CommandResult(stack="test-service", exit_code=0, success=True),
            ),
        ):
            result = await _up_stack_simple(basic_config, "test-service", raw=False)

        assert result.success
        assert events_called == ["pre_up", "post_up"]

    async def test_stop_stacks_dispatches_down_hooks(self, basic_config: Config) -> None:
        """Stopping stacks emits pre_down and post_down hooks."""
        events_called: list[str] = []

        async def mock_dispatch_hook(
            cfg: Config,
            event: object,
            stack: str,
            *,
            source_host: str | None = None,
            target_host: str | None = None,
            metadata: dict[str, str] | None = None,
        ) -> None:
            _ = (cfg, stack, source_host, target_host, metadata)
            events_called.append(str(event))

        with (
            patch("compose_farm.operations._dispatch_hook", side_effect=mock_dispatch_hook),
            patch(
                "compose_farm.operations.run_compose_on_host",
                return_value=CommandResult(stack="test-service@host2", exit_code=0, success=True),
            ),
        ):
            results = await _stop_stacks_on_hosts(
                basic_config,
                {"test-service": ["host2"]},
            )

        assert len(results) == 1
        assert results[0].success
        assert events_called == ["pre_down", "post_down"]


class TestUpdateCommandSequence:
    """Tests for update command sequence."""

    def test_update_delegates_to_up_with_pull_and_build(self) -> None:
        """Update command should delegate to up with pull=True and build=True."""
        source = inspect.getsource(lifecycle.update)

        # Verify update calls up with pull=True and build=True
        assert "up(" in source
        assert "pull=True" in source
        assert "build=True" in source


class TestBuildDiscoveryResults:
    """Tests for build_discovery_results function."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> Config:
        """Create a test config with multiple stacks."""
        compose_dir = tmp_path / "compose"
        for stack in ["plex", "jellyfin", "sonarr"]:
            (compose_dir / stack).mkdir(parents=True)
            (compose_dir / stack / "docker-compose.yml").write_text("services: {}")

        return Config(
            compose_dir=compose_dir,
            hosts={
                "host1": Host(address="localhost"),
                "host2": Host(address="localhost"),
            },
            stacks={"plex": "host1", "jellyfin": "host1", "sonarr": "host2"},
        )

    def test_discovers_correctly_running_stacks(self, config: Config) -> None:
        """Stacks running on correct hosts are discovered."""
        running_on_host = {
            "host1": {"plex", "jellyfin"},
            "host2": {"sonarr"},
        }

        discovered, strays, duplicates = build_discovery_results(config, running_on_host)

        assert discovered == {"plex": "host1", "jellyfin": "host1", "sonarr": "host2"}
        assert strays == {}
        assert duplicates == {}

    def test_detects_stray_stacks(self, config: Config) -> None:
        """Stacks running on wrong hosts are marked as strays."""
        running_on_host = {
            "host1": set(),
            "host2": {"plex"},  # plex should be on host1
        }

        discovered, strays, _duplicates = build_discovery_results(config, running_on_host)

        assert "plex" not in discovered
        assert strays == {"plex": ["host2"]}

    def test_detects_duplicates(self, config: Config) -> None:
        """Single-host stacks running on multiple hosts are duplicates."""
        running_on_host = {
            "host1": {"plex"},
            "host2": {"plex"},  # plex running on both hosts
        }

        discovered, strays, duplicates = build_discovery_results(
            config, running_on_host, stacks=["plex"]
        )

        # plex is correctly running on host1
        assert discovered == {"plex": "host1"}
        # plex is also a stray on host2
        assert strays == {"plex": ["host2"]}
        # plex is a duplicate (single-host stack on multiple hosts)
        assert duplicates == {"plex": ["host1", "host2"]}

    def test_filters_to_requested_stacks(self, config: Config) -> None:
        """Only returns results for requested stacks."""
        running_on_host = {
            "host1": {"plex", "jellyfin"},
            "host2": {"sonarr"},
        }

        discovered, _strays, _duplicates = build_discovery_results(
            config, running_on_host, stacks=["plex"]
        )

        # Only plex should be in results
        assert discovered == {"plex": "host1"}
        assert "jellyfin" not in discovered
        assert "sonarr" not in discovered
