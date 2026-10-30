import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infrastructure" / "create_staging_secret.py"
PASSWORD = "p@ss:w/rd?#%"  # every reserved character the URI must encode
ENCODED = "p%40ss%3Aw%2Frd%3F%23%25"


@pytest.fixture
def script(monkeypatch):
    spec = importlib.util.spec_from_file_location("create_staging_secret", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: PASSWORD)
    return module


class FakeGcloud:
    """subprocess.run stand-in for gcloud: records argv, env and stdin of every call."""

    def __init__(self, exists=False, versions="", labels=None, add_fails=False, echo_input=False):
        self.calls, self.exists, self.versions = [], exists, versions
        self.labels, self.add_fails, self.echo_input = labels or {"env": "staging"}, add_fails, echo_input

    def __call__(self, argv, input=None, capture_output=True, text=True, env=None):
        self.calls.append({"argv": argv, "input": input, "env": env})
        out, err, code = "", "", 0
        if argv[1:4] == ["config", "get-value", "account"]:
            out = "paulinoliliptec@gmail.com\n"
        elif "describe" in argv:
            if self.exists:
                out = f'{{"name": "projects/1/secrets/mongodb-uri-staging", "createTime": "t", "labels": {self.labels}}}'
                out = out.replace("'", '"')
            else:
                err, code = "ERROR: NOT_FOUND: Secret not found", 1
        elif "create" in argv:
            self.exists = True
        elif "add" in argv:
            if self.add_fails:
                err, code = "ERROR: PERMISSION_DENIED" + (f" input={input}" if self.echo_input else ""), 1
            else:
                self.versions = "1\tENABLED\t2026-10-30T10:00:00Z"
        elif "list" in argv:
            out = self.versions
        return subprocess.CompletedProcess(argv, code, out, err)

    def commands(self):
        return [c["argv"][2:5] for c in self.calls if c["argv"][0] == "gcloud" and len(c["argv"]) > 4]


def _run(script, monkeypatch, fake, problem=None, typed="add"):
    checked = []
    monkeypatch.setattr(script.subprocess, "run", fake)
    monkeypatch.setattr(script, "check_user", lambda uri: checked.append(uri) or problem)
    monkeypatch.setattr("builtins.input", lambda prompt: typed)
    return script.main(), checked


def _no_leak(fake, capsys):
    for call in fake.calls:
        assert not any(PASSWORD in a or ENCODED in a for a in call["argv"])  # never on a command line
        if call["env"] is not None:
            assert not any(PASSWORD in v or ENCODED in v for v in call["env"].values())
    assert PASSWORD not in os.environ.values()
    out = capsys.readouterr()
    assert PASSWORD not in out.out + out.err and ENCODED not in out.out + out.err
    return out


def test_the_uri_is_encoded_and_points_only_to_the_staging_cluster_and_database(script):
    uri = script.build_uri(PASSWORD)
    assert uri.startswith(f"mongodb+srv://habita-staging-app:{ENCODED}@habita-ai-m0.mhbehnn.mongodb.net/")
    assert "/habita_ai_staging?authSource=admin&" in uri and PASSWORD not in uri


def test_the_secret_is_created_empty_then_given_the_uri_on_stdin_with_gcloud_logging_off(script, monkeypatch, capsys):
    fake = FakeGcloud()
    code, checked = _run(script, monkeypatch, fake)
    assert code == 0 and checked == [script.build_uri(PASSWORD)]
    create = next(c for c in fake.calls if "create" in c["argv"])
    add = next(c for c in fake.calls if "add" in c["argv"])
    assert create["input"] is None and "--data-file=-" not in create["argv"]
    assert add["input"] == script.build_uri(PASSWORD) and "--data-file=-" in add["argv"]
    assert fake.calls.index(create) < fake.calls.index(add)
    for call in (create, add):
        assert call["env"]["CLOUDSDK_CORE_LOG_HTTP"] == "false"
        assert call["env"]["CLOUDSDK_CORE_DISABLE_FILE_LOGGING"] == "true"
    assert "ready" in _no_leak(fake, capsys).out


def test_an_existing_secret_with_a_version_is_described_and_never_touched(script, monkeypatch, capsys):
    fake = FakeGcloud(exists=True, versions="1\tENABLED\tt")
    code, checked = _run(script, monkeypatch, fake)
    assert code == 2 and not checked
    assert not any("create" in c["argv"] or "add" in c["argv"] for c in fake.calls)
    out = _no_leak(fake, capsys).out
    assert "already exists" in out and "1\tENABLED" in out and "Nothing changed" in out


def test_an_interrupted_run_can_add_the_first_version_only_when_confirmed(script, monkeypatch, capsys):
    fake = FakeGcloud(exists=True)
    code, _ = _run(script, monkeypatch, fake, typed="no")
    assert code == 2 and not any("add" in c["argv"] for c in fake.calls)
    fake = FakeGcloud(exists=True)
    code, _ = _run(script, monkeypatch, fake, typed="add")
    assert code == 0 and not any("create" in c["argv"] for c in fake.calls)
    assert any("add" in c["argv"] for c in fake.calls)


def test_an_empty_secret_without_the_staging_label_is_not_resumed(script, monkeypatch):
    fake = FakeGcloud(exists=True, labels={"env": "preview"})
    code, checked = _run(script, monkeypatch, fake, typed="add")
    assert code == 2 and not checked and not any("add" in c["argv"] for c in fake.calls)


def test_a_user_beyond_staging_is_refused_before_anything_is_created(script, monkeypatch, capsys):
    fake = FakeGcloud()
    code, _ = _run(script, monkeypatch, fake, problem="Staging MongoDB user must be limited to habita_ai_staging; ...")
    assert code == 1 and not any("create" in c["argv"] or "add" in c["argv"] for c in fake.calls)
    assert "Nothing was created" in _no_leak(fake, capsys).err


def test_a_failed_version_says_so_and_does_not_echo_the_uri(script, monkeypatch, capsys):
    fake = FakeGcloud(add_fails=True, echo_input=True)  # a hypothetical gcloud error quoting its input
    code, _ = _run(script, monkeypatch, fake)
    err = _no_leak(fake, capsys).err
    assert code == 1 and "exists but has no version" in err and "withheld" in err and "PERMISSION_DENIED" not in err


def test_an_unconfirmed_version_is_not_reported_as_ready(script, monkeypatch, capsys):
    fake = FakeGcloud()
    original = fake.__call__

    def failing_list(argv, **kw):
        result = original(argv, **kw)
        if "--filter=state:ENABLED" in argv:
            result.returncode, result.stderr = 1, "ERROR: transient"
        return result
    code, _ = _run(script, monkeypatch, failing_list)
    out = _no_leak(fake, capsys)
    assert code == 1 and "could not be confirmed" in out.err and "ready" not in out.out


def test_the_wrong_gcloud_account_stops_before_the_prompt(script, monkeypatch):
    prompted = []
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt: prompted.append(1) or PASSWORD)
    monkeypatch.setattr(script.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "someone@else\n", ""))
    assert script.main() == 1 and not prompted


def test_without_a_terminal_the_password_is_not_read(script, monkeypatch):
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(script.Stop, match="interactive terminal"):
        script.read_password()


def test_a_driver_error_is_reported_without_the_uri(script):
    problem = script.check_user("mongodb://habita-staging-app:secretpw@127.0.0.1:1/", timeout_ms=300)
    assert problem.startswith("cannot authenticate") and "secretpw" not in problem


def test_resuming_stops_if_a_version_appeared_meanwhile(script, monkeypatch):
    fake = FakeGcloud(exists=True)
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt: setattr(fake, "versions", "1\tENABLED\tt") or PASSWORD)
    code, _ = _run(script, monkeypatch, fake, typed="add")
    assert code == 1 and not any("add" in c["argv"] for c in fake.calls)
