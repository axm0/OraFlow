import tomllib
from pathlib import Path

import pytest
import typer

from oraflow.credentials import (
    creds_doctor,
    get_credentials,
    list_credential_summaries,
    load_credential_profiles,
    resolve_username_password,
)


def _write_creds(path: Path) -> None:
    path.write_text(
        """
[cloud.dev]
username = "dev_user"
password = "dev_password"

[onprem.qa]
username = "qa_user"
password = "qa_password"
""".strip(),
        encoding="utf-8",
    )


def test_load_credential_profiles_parses_toml_format(tmp_path):
    path = tmp_path / "credentials.toml"
    _write_creds(path)

    profiles = load_credential_profiles(path)

    assert sorted(profiles) == ["CLOUD.DEV", "ONPREM.QA"]
    assert profiles["CLOUD.DEV"].username == "dev_user"
    assert profiles["CLOUD.DEV"].password == "dev_password"


def test_legacy_dbcreds_env_format_is_not_supported(tmp_path):
    path = tmp_path / "dbcreds.env"
    path.write_text("creds for QA:\nusername: qa_user\npassword: qa_password\n", encoding="utf-8")

    with pytest.raises(tomllib.TOMLDecodeError):
        load_credential_profiles(path)


def test_summaries_do_not_include_password_values(tmp_path):
    path = tmp_path / "credentials.toml"
    _write_creds(path)

    summaries = list_credential_summaries(path)

    assert summaries[0].has_password is True
    assert not hasattr(summaries[0], "password")


def test_get_credentials_raises_for_missing_profile(tmp_path):
    path = tmp_path / "credentials.toml"
    _write_creds(path)

    with pytest.raises(KeyError, match="Available profiles"):
        get_credentials("MISSING", path)


def test_explicit_username_password_wins_over_profile():
    username, password = resolve_username_password("explicit_user", "explicit_password", profile="DEV-CLOUD")

    assert username == "explicit_user"
    assert password == "explicit_password"


def test_creds_doctor_reports_profiles_without_passwords(tmp_path):
    path = tmp_path / "credentials.toml"
    path.write_text(
        """
[onprem]
  [onprem.qa]
  username = "qa_user"
  password = "qa_password"
""".strip(),
        encoding="utf-8",
    )

    result = creds_doctor(path)

    assert result["status"] == "OK"
    assert result["profiles"] == ["ONPREM.QA"]
    assert "qa_password" not in str(result)


def test_cli_credentials_rejects_command_line_password():
    from oraflow.cli import _credentials

    with pytest.raises(typer.Exit) as exc_info:
        _credentials("user", "secret", None)
    assert exc_info.value.exit_code == 2


