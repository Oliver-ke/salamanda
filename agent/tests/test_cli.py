import pytest

from loop_agent.__main__ import parse_args


def test_run_requires_issue():
    with pytest.raises(SystemExit):
        parse_args(["run"])
    assert parse_args(["run", "--issue", "7"]).issue == 7


def test_serve_defaults_to_8080():
    assert parse_args(["serve"]).port == 8080


def test_serve_runs_one_job_per_container(monkeypatch):
    import loop_agent.__main__ as cli

    seen = {}

    class FakeServer:
        def __init__(self, handle, on_done, **kwargs):
            seen.update(kwargs)

        def serve_forever(self):
            seen["served"] = True

    monkeypatch.setattr(cli.Config, "from_env", classmethod(lambda cls: type("C", (), {"repo": "o/r"})()))
    monkeypatch.setattr(cli, "build_deps", lambda config: object())
    monkeypatch.setattr(cli, "JobServer", FakeServer)
    assert cli.main(["serve", "--port", "9"]) == 0
    assert seen == {"expected_repo": "o/r", "port": 9, "once": True, "served": True}
