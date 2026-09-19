from unittest.mock import patch

import pytest
from pydantic import SecretStr

from proxmox_mcp.cli import main


@pytest.fixture(autouse=True)
def preserve_pytest_logging():
    # The real CLI deliberately replaces root handlers. Exercise that behavior
    # in a subprocess below, not against pytest's own capture handlers.
    with patch("proxmox_mcp.cli.logging.basicConfig"):
        yield


@pytest.mark.parametrize("args", [["--version"], ["--help"]])
def test_cli_help(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 0
    assert capsys.readouterr().out


@pytest.mark.parametrize("args", [[], ["--port", "0"], ["--env-file", "/does/not/exist"]])
def test_cli_invalid_configuration(args, capsys):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    assert not capsys.readouterr().out


def test_cli_does_not_leak_invalid_secret(monkeypatch, capsys):
    monkeypatch.setenv("PROXMOX_URL", "https://pve.example.test")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "mcp@pve!test")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "SUPERSECRET\n")
    with pytest.raises(SystemExit):
        main([])
    assert "SUPERSECRET" not in capsys.readouterr().err


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
def test_cli_runs_selected_transport(settings, transport):
    settings = settings.model_copy(update={"http_token": SecretStr("a" * 43)})
    with (
        patch("proxmox_mcp.cli.Settings", return_value=settings),
        patch("proxmox_mcp.cli.create_server") as create,
    ):
        main(["--transport", transport, "--port", "8765"])
        create.return_value.run.assert_called_once_with(transport=transport)
        assert create.return_value.settings.port == 8765


def test_cli_warns_insecure_tls(settings, caplog):
    with (
        patch(
            "proxmox_mcp.cli.Settings",
            return_value=settings.model_copy(update={"verify_ssl": False}),
        ),
        patch("proxmox_mcp.cli.create_server"),
    ):
        main([])
    assert "TLS verification is disabled" in caplog.text


def test_cli_ca_failure(settings, capsys):
    with (
        patch("proxmox_mcp.cli.Settings", return_value=settings),
        patch("proxmox_mcp.cli.create_server", side_effect=OSError("private path")),
        pytest.raises(SystemExit),
    ):
        main([])
    error = capsys.readouterr().err
    assert "PROXMOX_CA_BUNDLE" in error
    assert "private path" not in error


def test_http_cli_requires_separate_token(settings, capsys):
    with patch("proxmox_mcp.cli.Settings", return_value=settings), pytest.raises(SystemExit) as exc:
        main(["--transport", "streamable-http"])
    assert exc.value.code == 2
    assert "PROXMOX_HTTP_TOKEN" in capsys.readouterr().err


@pytest.mark.parametrize("stage", ["create", "run"])
def test_unexpected_cli_errors_are_sanitized(settings, capsys, stage):
    with (
        patch("proxmox_mcp.cli.Settings", return_value=settings),
        patch("proxmox_mcp.cli.create_server") as create,
    ):
        if stage == "create":
            create.side_effect = RuntimeError("SENSITIVE")
        else:
            create.return_value.run.side_effect = RuntimeError("SENSITIVE")
        with pytest.raises(SystemExit) as exc:
            main([])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "SENSITIVE" not in captured.err
