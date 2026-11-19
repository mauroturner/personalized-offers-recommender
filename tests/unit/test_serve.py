"""``serve-crm`` (U13; AC20; plan section 18; decision D27; risk item 2): the stand-in listens on 127.0.0.1 only, on a port from 1 to 65535, with a token from the environment; whatever else is
exit 2 before a file is made or a server starts. U19 puts the command in the command line; the function it calls is here."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from personaloffers.crm import serve

TOKEN = "serve-token"


@pytest.fixture
def configured(quick_cfg, tmp_path, monkeypatch):
    """The configuration the command loads, with the file of the CRM in the test's folder and the token in the environment."""
    from personaloffers import config as config_module

    cfg = dataclasses.replace(quick_cfg, paths=dataclasses.replace(quick_cfg.paths, crm_db=tmp_path / "crm" / "standin.sqlite"))
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    monkeypatch.setenv(cfg.crm.token_env, TOKEN)
    runs = []
    monkeypatch.setattr(serve, "_run_server", lambda app, host, port, verbose: runs.append((app, host, port, verbose)))
    return cfg, runs


def test_serve_crm_refuses_any_host_but_localhost(configured, capsys):
    cfg, runs = configured
    for host in ("0.0.0.0", "localhost", "::1", "::", "192.168.1.5", "127.0.0.2", "", " 127.0.0.1", "127.0.0.1 ", "example.com", "127.0.0.1.evil.com"):
        assert serve.serve_crm(["--host", host]) == 2, host
        assert "127.0.0.1" in capsys.readouterr().err
    assert runs == [] and not cfg.paths.crm_db.exists() and not cfg.paths.crm_db.parent.exists(), "no server and no file"
    assert serve.serve_crm(["--host", "127.0.0.1"]) == 0 and runs[-1][1] == "127.0.0.1"
    assert serve.serve_crm([]) == 0 and runs[-1][1] == "127.0.0.1", "the default is the local one"


def test_serve_crm_refuses_a_port_out_of_range_and_takes_the_ends_of_it(configured, capsys):
    cfg, runs = configured
    for port in ("0", "-1", "65536", "99999", "x", "1.5", ""):
        assert serve.serve_crm(["--port", port]) == 2, port
        capsys.readouterr()
    assert runs == [] and not cfg.paths.crm_db.parent.exists()
    assert serve.serve_crm(["--port", "1"]) == 0 and runs[-1][2] == 1
    assert serve.serve_crm(["--port", "65535"]) == 0 and runs[-1][2] == 65535
    assert serve.serve_crm([]) == 0 and runs[-1][2] == 8001, "the plan's port"


def test_serve_crm_hands_the_server_the_app_of_the_configuration_with_its_token(configured):
    from fastapi.testclient import TestClient

    cfg, runs = configured
    assert serve.serve_crm(["-v"]) == 0
    app, host, port, verbose = runs[-1]
    assert (host, port, verbose) == ("127.0.0.1", 8001, True) and cfg.paths.crm_db.is_file()
    client = TestClient(app)
    assert client.get("/health").status_code == 401 and client.get("/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert serve.serve_crm([]) == 0 and runs[-1][3] is False


def test_serve_crm_without_the_token_does_not_start_and_says_which_variable(configured, monkeypatch, capsys):
    cfg, runs = configured
    monkeypatch.delenv(cfg.crm.token_env)
    assert serve.serve_crm([]) == 2
    err = capsys.readouterr().err
    assert cfg.crm.token_env in err and "token" in err and TOKEN not in err
    assert runs == [] and not cfg.paths.crm_db.exists()


def test_serve_crm_with_a_configuration_that_is_not_there_or_not_valid_is_exit_2_and_writes_nothing(configured, tmp_path, monkeypatch, capsys):
    cfg, runs = configured
    from personaloffers import config as config_module

    def refuse(path=None):
        raise FileNotFoundError("no está config/nope.toml")

    monkeypatch.setattr(config_module, "load_config", refuse)
    assert serve.serve_crm(["--config", str(tmp_path / "nope.toml")]) == 2
    assert "nope.toml" in capsys.readouterr().err and runs == [] and not cfg.paths.crm_db.parent.exists()


def test_the_option_that_is_not_one_is_exit_2_and_help_is_exit_0(configured, capsys):
    cfg, runs = configured
    assert serve.serve_crm(["--nope"]) == 2
    assert serve.serve_crm(["--help"]) == 0 and "--host" in capsys.readouterr().out
    assert runs == []


def test_the_server_is_uvicorn_on_the_given_host_and_port_and_the_output_is_quiet_unless_asked(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    serve._run_server(object(), "127.0.0.1", 8123, False)
    serve._run_server(object(), "127.0.0.1", 8124, True)
    assert calls == [{"host": "127.0.0.1", "port": 8123, "log_level": "warning"}, {"host": "127.0.0.1", "port": 8124, "log_level": "info"}]
    assert Path(serve.__file__).name == "serve.py"
