import subprocess
import pytest
from jd2candidates import treg


def _fake(stdout, stderr, rc=0):
    return lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_call_parses_json_and_charge(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake('{"elements":[{"geoId":"1"}]}', "treg: charged $0.0064 · call id abc\n"))
    data, usd = treg.call("harvestapi.linkedin.user.profile", {"url": "x"})
    assert data["elements"][0]["geoId"] == "1"
    assert usd == 0.0064


def test_call_charge_defaults_to_zero(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake("{}", ""))
    assert treg.call("t", {}) == ({}, 0.0)


def test_call_raises_on_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake("", "treg: insufficient funds", rc=1))
    with pytest.raises(treg.TregError, match="insufficient funds"):
        treg.call("t", {})


def test_call_builds_argv(monkeypatch):
    seen = {}
    def run(argv, **k):
        seen["argv"] = argv
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    treg.call("tool.x", {"a": "1", "b": "two words"})
    assert seen["argv"] == ["treg", "call", "tool.x", "-p", "a=1", "-p", "b=two words"]
