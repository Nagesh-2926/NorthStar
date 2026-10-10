import socket

import pytest

from scripts.with_isolated_db import main, port_in_use, redacted, with_port

URL = "postgresql+psycopg://app_user:p%40ss:w0rd@127.0.0.1:5432/student_support"


def test_only_the_port_changes_and_credentials_are_preserved():
    assert with_port(URL, 5433) == "postgresql+psycopg://app_user:p%40ss:w0rd@127.0.0.1:5433/student_support"


def test_redacted_target_never_contains_credentials():
    shown = redacted(with_port(URL, 5433))
    assert shown == "127.0.0.1:5433/student_support"
    assert "app_user" not in shown and "w0rd" not in shown


def test_url_without_explicit_port_is_rejected():
    with pytest.raises(ValueError):
        with_port("postgresql+psycopg://u:p@127.0.0.1/db", 5433)


def test_legacy_port_is_refused():
    with pytest.raises(SystemExit):
        main(["--db-port", "5432", "--", "python", "-c", "pass"])


def test_busy_port_blocks_the_command(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", URL)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        busy = server.getsockname()[1]
        assert port_in_use(busy)
        assert main(["--require-free-port", str(busy), "--", "python", "-c", "raise SystemExit(9)"]) == 3
    assert "already in use" in capsys.readouterr().err


def test_child_receives_rewritten_url_only(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", URL)
    code = main(["--", "python", "-c",
                 "import os,sys; sys.exit(0 if os.environ['DATABASE_URL'].endswith(':5433/student_support') else 1)"])
    assert code == 0
    assert "w0rd" not in capsys.readouterr().out


@pytest.mark.parametrize("url", [
    URL + "?host=elsewhere", URL + "#fragment", " " + URL,
    URL.replace("5432", "notaport"), URL.replace("127.0.0.1", "example.org"),
    URL.replace("p%40ss:w0rd", "PrivateMarker@part"),
    URL.replace("student_support", "PrivateMarker/path"),
    URL.replace("postgresql+psycopg", "sqlite"),
])
def test_malformed_or_redirecting_input_is_refused_without_diagnostics_leak(url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("scripts.with_isolated_db.subprocess.call",
                        lambda *args, **kwargs: pytest.fail("command must not start"))
    assert main(["--", "python", "-c", "pass"]) == 2
    shown = capsys.readouterr()
    assert "PrivateMarker" not in shown.out + shown.err
    assert url not in shown.out + shown.err
    with pytest.raises(ValueError) as failure:
        redacted(url)
    assert "PrivateMarker" not in str(failure.value)


@pytest.mark.parametrize("port", [5432, 0, 65536, True])
def test_direct_port_rewrite_rejects_protected_or_invalid_port(port):
    with pytest.raises(ValueError):
        with_port(URL, port)


@pytest.mark.parametrize("port", ["5432", "5433"])
def test_database_ports_cannot_be_used_as_http_availability_probes(port, monkeypatch):
    monkeypatch.setattr("scripts.with_isolated_db.port_in_use",
                        lambda *args, **kwargs: pytest.fail("must not probe a database port"))
    with pytest.raises(SystemExit):
        main(["--require-free-port", port, "--", "python", "-c", "pass"])


def test_command_launch_error_is_sanitized(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", URL)
    def refuse(*args, **kwargs):
        raise OSError("PrivateMarker " + URL)
    monkeypatch.setattr("scripts.with_isolated_db.subprocess.call", refuse)
    assert main(["--", "python", "-c", "pass"]) == 2
    output = capsys.readouterr()
    assert "PrivateMarker" not in output.out + output.err
    assert URL not in output.out + output.err
