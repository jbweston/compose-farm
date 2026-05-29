"""Tests for shared CLI helpers."""

from pathlib import Path
from unittest.mock import patch

from compose_farm.cli.common import maybe_regenerate_traefik
from compose_farm.config import Config, Host


def _make_config(tmp_path: Path) -> Config:
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()

    config_path = tmp_path / "compose-farm.yaml"
    config_path.write_text("")

    return Config(
        compose_dir=compose_dir,
        hosts={"host1": Host(address="localhost")},
        stacks={"traefik": "host1"},
        traefik_file=Path("/var/lib/stacks/traefik/persist/dynamic.d/compose-farm.yml"),
        config_path=config_path,
    )


def test_maybe_regenerate_traefik_warns_on_permission_error(tmp_path: Path) -> None:
    """Permission errors when writing traefik_file should not crash lifecycle commands."""
    cfg = _make_config(tmp_path)

    with (
        patch(
            "compose_farm.traefik.generate_traefik_config",
            return_value=({}, []),
        ),
        patch(
            "compose_farm.traefik.render_traefik_config",
            return_value="http: {}\n",
        ),
        patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")),
        patch("compose_farm.cli.common.print_warning") as mock_warning,
    ):
        maybe_regenerate_traefik(cfg)

    mock_warning.assert_called_once()
    assert "Failed to update traefik config" in mock_warning.call_args[0][0]
