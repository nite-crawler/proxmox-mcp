import pytest
from pydantic import ValidationError

from proxmox_mcp.config import Settings


def make_settings(**overrides):
    return Settings(
        **{
            "url": "https://pve.example.test:8006",
            "token_id": "mcp@pve!test",
            "token_secret": "test-only-secret",
            **overrides,
        }
    )


@pytest.mark.parametrize("suffix", ["", "/", "/api2/json", "/api2/json/"])
def test_normalize_url(suffix):
    settings = make_settings(url="https://pve.example.test:8006" + suffix)
    assert settings.url == "https://pve.example.test:8006/api2/json"
    assert settings.read_only and settings.verify_ssl and not settings.allow_destructive


@pytest.mark.parametrize(
    "url",
    [
        "http://pve:8006",
        "https://",
        "https://user:secret@pve",
        "https://pve/evil",
        "https://pve?token=secret",
        "https://pve/#fragment",
        "https://pve:99999",
        "https://pve:notaport",
        "file:///etc/passwd",
    ],
)
def test_reject_unsafe_urls(url):
    with pytest.raises(ValidationError):
        make_settings(url=url)


@pytest.mark.parametrize("token_id", ["root", "root@pam", "user@pve!x\r\nX: evil", "u@r!a/b"])
def test_reject_invalid_token_id(token_id):
    with pytest.raises(ValidationError):
        make_settings(token_id=token_id)


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "a",
        "a" * 15,
        "secret\r\nHeader:value",
        "has space" * 3,
        "é" * 16,
        "\x00" * 16,
        "\x7f" * 16,
    ],
)
def test_reject_invalid_secret(secret):
    with pytest.raises(ValidationError):
        make_settings(token_secret=secret)


@pytest.mark.parametrize("secret", ["x" * 16, "00000000-0000-4000-8000-000000000001"])
def test_valid_secret_length_boundaries(secret):
    assert make_settings(token_secret=secret).token_secret.get_secret_value() == secret


@pytest.mark.parametrize(
    "options",
    [
        {"allow_destructive": True},
        {"ca_bundle": "/tmp/ca.pem", "verify_ssl": False},
        {"timeout": 0},
        {"timeout": 301},
        {"timeout": float("nan")},
        {"operation_timeout": 0},
        {"operation_timeout": float("inf")},
        {"max_response_bytes": 1023},
        {"max_request_bytes": 0},
        {"max_concurrent_requests": 0},
        {"max_concurrent_requests": 65},
        {"http_token": "short"},
        {"http_token": "a" * 32 + "\r\n"},
        {"http_token": "a" * 32, "token_secret": "a" * 32},
        {"output_fields": {"unknown": ["name"]}},
        {"output_fields": {"guest_config": ["*"]}},
    ],
)
def test_invalid_options(options):
    with pytest.raises(ValidationError):
        make_settings(**options)


def test_secrets_hidden():
    assert "test-only-secret" not in repr(make_settings())
    with pytest.raises(ValidationError) as exc:
        make_settings(token_secret="SECRET\n")
    assert "SECRET" not in str(exc.value)


def test_env_file_explicit_and_environment_wins(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text(
        "PROXMOX_URL=https://pve.example.test:8006\n"
        "PROXMOX_TOKEN_ID=mcp@pve!test\nPROXMOX_TOKEN_SECRET=test-only-secret\n"
        "PROXMOX_READ_ONLY=false\n"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError):
        Settings()
    assert not Settings(_env_file=config).read_only
    monkeypatch.setenv("PROXMOX_READ_ONLY", "true")
    assert Settings(_env_file=config).read_only


def test_output_policy_from_environment(monkeypatch):
    monkeypatch.setenv("PROXMOX_OUTPUT_FIELDS", '{"guest_config":["name","cores"]}')
    monkeypatch.setenv("PROXMOX_ALLOW_RAW_CONFIG", "true")
    settings = make_settings()
    assert settings.output_fields == {"guest_config": ("name", "cores")}
    assert settings.allow_raw_config
    assert not settings.allow_task_logs


@pytest.mark.parametrize("fields", [[], ["status"], ["exitstatus"], ["Status", "exitstatus"]])
def test_task_status_policy_cannot_hide_completion_fields(fields):
    with pytest.raises(ValidationError, match="must include status and exitstatus"):
        make_settings(output_fields={"task_status": fields})


def test_task_status_policy_environment_validation(monkeypatch):
    monkeypatch.setenv("PROXMOX_OUTPUT_FIELDS", '{"task_status":["status"]}')
    with pytest.raises(ValidationError, match="must include status and exitstatus"):
        make_settings()
    monkeypatch.setenv("PROXMOX_OUTPUT_FIELDS", '{"task_status":["status","exitstatus"]}')
    assert make_settings().output_fields["task_status"] == ("status", "exitstatus")
