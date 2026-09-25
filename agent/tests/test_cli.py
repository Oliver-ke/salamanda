import pytest

from loop_agent.__main__ import parse_args


def test_run_requires_issue():
    with pytest.raises(SystemExit):
        parse_args(["run"])
    assert parse_args(["run", "--issue", "7"]).issue == 7


def test_serve_defaults_to_8080():
    assert parse_args(["serve"]).port == 8080
