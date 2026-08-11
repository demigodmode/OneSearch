# ruff: noqa: N802
import importlib
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def disable_live_failure_policy(monkeypatch, request):
    """Service-install unit tests never touch the host SCM."""
    if request.node.name.startswith("test_failure_"):
        return
    module = importlib.import_module("onesearch_agent.windows_service")
    monkeypatch.setattr(module, "_snapshot_failure_actions", lambda: None, raising=False)
    monkeypatch.setattr(module, "_configure_failure_actions", lambda: None, raising=False)
    monkeypatch.setattr(module, "_restore_failure_actions", lambda value: None, raising=False)


def test_windows_service_module_import_is_lazy_off_windows():
    module = importlib.import_module("onesearch_agent.windows_service")
    assert module.OneSearchAgentService.__module__ == "onesearch_agent.windows_service"
    assert callable(module.main)


def test_windows_service_reports_missing_pywin32_safely(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    monkeypatch.setattr(module, "win32serviceutil", None)
    try:
        module.main()
    except RuntimeError as error:
        assert "pywin32" in str(error)
    else:
        raise AssertionError("expected pywin32 error")


def test_registry_config_persist_read_and_absent_cleanup(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []

    class Registry:
        HKEY_LOCAL_MACHINE = 1
        REG_SZ = 1

        def CreateKey(self, hive, path):
            calls.append(("create", path))
            return "key"

        def SetValueEx(self, key, name, zero, kind, value):
            calls.append(("set", name, value))

        def CloseKey(self, key):
            calls.append(("close", key))

        def OpenKey(self, hive, path):
            return "key"

        def QueryValueEx(self, key, name):
            return ("C:/agent.toml", 1)

        def DeleteKey(self, hive, path):
            calls.append(("delete", path))
            raise FileNotFoundError()

    monkeypatch.setattr(module, "winreg", Registry())
    monkeypatch.setattr(module, "_protect_parameters_key", lambda key: calls.append(("acl", key)))
    module.persist_config("C:/agent.toml")
    assert module.service_config() == "C:/agent.toml"
    module.clear_config()
    assert ("set", "ConfigPath", "C:/agent.toml") in calls


def test_registry_cleanup_error_is_safe(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")

    class Registry:
        HKEY_LOCAL_MACHINE = 1

        def DeleteKey(self, *args):
            raise OSError("denied")

    monkeypatch.setattr(module, "winreg", Registry())
    with pytest.raises(RuntimeError, match="unable to remove service configuration"):
        module.clear_config()


def test_parameters_dacl_is_protected_and_limited_to_system_and_admins(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    captured = {}

    class Acl:
        def __init__(self):
            self.aces = []

        def AddAccessAllowedAce(self, revision, access, sid):
            self.aces.append((revision, access, sid))

    security = SimpleNamespace(
        ACL=Acl,
        ACL_REVISION=2,
        WinLocalSystemSid="SYSTEM",
        WinBuiltinAdministratorsSid="ADMINS",
        SE_REGISTRY_KEY=4,
        DACL_SECURITY_INFORMATION=8,
        PROTECTED_DACL_SECURITY_INFORMATION=16,
        CreateWellKnownSid=lambda sid, domain: sid,
        SetSecurityInfo=lambda key, kind, flags, owner, group, dacl, sacl: captured.update(
            key=key, kind=kind, flags=flags, aces=dacl.aces
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "win32security", security)
    monkeypatch.setitem(
        __import__("sys").modules, "ntsecuritycon", SimpleNamespace(KEY_ALL_ACCESS=99)
    )
    module._protect_parameters_key("key")
    assert captured["flags"] == 24
    assert captured["aces"] == [(2, 99, "SYSTEM"), (2, 99, "ADMINS")]


def test_machine_credential_uses_binary_dpapi(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []

    class Registry:
        HKEY_LOCAL_MACHINE = 1
        REG_BINARY = 3

        def CreateKey(self, *args):
            return "key"

        def SetValueEx(self, key, name, zero, kind, value):
            calls.append((name, kind, value))

        def CloseKey(self, key):
            pass

    class Crypto:
        def CryptProtectData(self, value, *args):
            return b"cipher"

    monkeypatch.setattr(module, "winreg", Registry())
    monkeypatch.setattr(module, "_protect_parameters_key", lambda key: None)
    monkeypatch.setitem(__import__("sys").modules, "win32crypt", Crypto())
    module.persist_machine_credential("secret")
    assert calls == [("MachineCredential", 3, b"cipher")]


def test_machine_credential_decrypts_and_redacts_failures(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")

    class Registry:
        HKEY_LOCAL_MACHINE = 1

        def OpenKey(self, *args):
            return "key"

        def QueryValueEx(self, key, name):
            return (b"cipher", 3)

        def CloseKey(self, key):
            pass

    class Crypto:
        def CryptUnprotectData(self, *args):
            return (None, b"secret")

    monkeypatch.setattr(module, "winreg", Registry())
    monkeypatch.setitem(__import__("sys").modules, "win32crypt", Crypto())
    assert module.machine_credential() == "secret"
    monkeypatch.setitem(
        __import__("sys").modules,
        "win32crypt",
        type(
            "C", (), {"CryptUnprotectData": lambda *args: (_ for _ in ()).throw(OSError("secret"))}
        )(),
    )
    with pytest.raises(RuntimeError) as error:
        module.machine_credential()
    assert "secret" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI only")
def test_live_machine_dpapi_roundtrip():
    win32crypt = pytest.importorskip("win32crypt")
    protected = win32crypt.CryptProtectData(b"roundtrip", None, None, None, None, 4)
    assert isinstance(protected, bytes)
    result = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
    assert isinstance(result, tuple)
    assert result[1] == b"roundtrip"


@pytest.mark.parametrize("result", [None, 0, 1060])
def test_install_service_result_controls_rollback(monkeypatch, result):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(
            HandleCommandLine=lambda *args, **kwargs: calls.append(kwargs["argv"]) or result
        ),
    )
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append(("config", value)))
    monkeypatch.setattr(
        module, "persist_machine_credential", lambda value: calls.append(("token", value))
    )
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: {"old": 1})
    monkeypatch.setattr(
        module, "_restore_parameters", lambda value: calls.append(("restore", value))
    )
    if result in (None, 0):
        module.install_service("C:/agent.toml", "secret")
    else:
        with pytest.raises(RuntimeError):
            module.install_service("C:/agent.toml", "secret")
    assert all("secret" not in str(item) for item in calls if isinstance(item, list))
    assert (("restore", {"old": 1}) in calls) is (result not in (None, 0))


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"ConfigPath": ("old", 1)},
        {"MachineCredential": (b"old", 3)},
        {"ConfigPath": ("old", 1), "MachineCredential": (b"old", 3)},
    ],
)
def test_install_exception_restores_each_prior_owned_state(monkeypatch, snapshot):
    module = importlib.import_module("onesearch_agent.windows_service")
    restored = []
    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(
            HandleCommandLine=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("failed"))
        ),
    )
    monkeypatch.setattr(module, "persist_config", lambda value: None)
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: None)
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: snapshot)
    monkeypatch.setattr(module, "_restore_parameters", lambda value: restored.append(value))
    with pytest.raises(RuntimeError):
        module.install_service("C:/agent.toml", "secret")
    assert restored == [snapshot]


def test_install_start_failure_removes_service_then_restores_snapshot(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    snapshot = {"ConfigPath": ("old", 1)}

    def command(command):
        calls.append(command)
        return 1 if command == "start" else 0

    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(HandleCommandLine=lambda *args, **kwargs: command(kwargs["argv"][-1])),
    )
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append("config"))
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: calls.append("token"))
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: snapshot)
    monkeypatch.setattr(
        module, "_restore_parameters", lambda value: calls.append(("restore", value))
    )
    with pytest.raises(RuntimeError):
        module.install_service("C:/agent.toml", "secret")
    assert calls == ["config", "token", "install", "start", "remove", ("restore", snapshot)]


def test_install_start_rollback_failure_retains_staged_values(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []

    def command(command):
        calls.append(command)
        return 1 if command in {"start", "remove"} else 0

    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(HandleCommandLine=lambda *args, **kwargs: command(kwargs["argv"][-1])),
    )
    monkeypatch.setattr(module, "persist_config", lambda value: None)
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: None)
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: {})
    restore = Mock()
    monkeypatch.setattr(module, "_restore_parameters", restore)
    with pytest.raises(RuntimeError, match="remains installed"):
        module.install_service("C:/agent.toml", "secret")
    assert calls == ["install", "start", "remove"]
    restore.assert_not_called()


@pytest.mark.parametrize(
    "state,start,removed", [(4, 1056, False), (1, 0, False), (4, 1, False), (None, 1, True)]
)
def test_install_state_matrix_preserves_existing_service(monkeypatch, state, start, removed):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []

    def command(name):
        calls.append(name)
        return start if name == "start" else 0

    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(HandleCommandLine=lambda *a, **k: command(k["argv"][-1])),
    )
    monkeypatch.setattr(module, "_service_state", lambda: state)
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: {"old": 1})
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append("config"))
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: calls.append("token"))
    monkeypatch.setattr(module, "_restore_parameters", lambda value: calls.append("restore"))
    if start in (0, 1056):
        module.install_service("config", "secret")
    else:
        with pytest.raises(RuntimeError):
            module.install_service("config", "secret")
    assert ("remove" in calls) is removed
    assert ("restore" in calls) is (start not in (0, 1056))


def test_install_query_error_mutates_nothing(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    monkeypatch.setattr(module, "win32serviceutil", SimpleNamespace())
    monkeypatch.setattr(
        module, "_service_state", lambda: (_ for _ in ()).throw(RuntimeError("query"))
    )
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append("config"))
    with pytest.raises(RuntimeError):
        module.install_service("config", "secret")
    assert calls == []


def test_failure_actions_restart_with_bounded_delays_and_close_handles(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    service = SimpleNamespace(
        SC_MANAGER_CONNECT=1,
        SERVICE_CHANGE_CONFIG=2,
        SERVICE_QUERY_CONFIG=4,
        SERVICE_CONFIG_FAILURE_ACTIONS=5,
        SC_ACTION_RESTART=1,
        OpenSCManager=lambda machine, database, access: calls.append(("manager", access)) or "scm",
        OpenService=lambda scm, name, access: calls.append(("service", name, access)) or "service",
        ChangeServiceConfig2=lambda handle, level, value: calls.append(
            ("change", handle, level, value)
        ),
        CloseServiceHandle=lambda handle: calls.append(("close", handle)),
    )
    monkeypatch.setattr(module, "win32service", service)

    module._configure_failure_actions()

    assert calls == [
        ("manager", 1),
        ("service", "OneSearchAgent", 2),
        (
            "change",
            "service",
            5,
            {
                "ResetPeriod": 86400,
                "RebootMsg": None,
                "Command": None,
                "Actions": ((1, 5000), (1, 15000), (1, 60000)),
            },
        ),
        ("close", "service"),
        ("close", "scm"),
    ]


def test_failure_policy_error_removes_new_service_and_restores_existing_policy(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    snapshot = {"ResetPeriod": 123, "RebootMsg": None, "Command": None, "Actions": ((1, 999),)}
    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(
            HandleCommandLine=lambda *args, **kwargs: calls.append(kwargs["argv"][-1]) or 0
        ),
    )
    monkeypatch.setattr(module, "_service_state", lambda: 4)
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: {"old": 1})
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append("config"))
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: calls.append("token"))
    monkeypatch.setattr(
        module, "_restore_parameters", lambda value: calls.append(("parameters", value))
    )
    monkeypatch.setattr(module, "_snapshot_failure_actions", lambda: snapshot)
    monkeypatch.setattr(
        module,
        "_configure_failure_actions",
        lambda: (_ for _ in ()).throw(OSError("policy failure")),
    )
    monkeypatch.setattr(
        module, "_restore_failure_actions", lambda value: calls.append(("policy", value))
    )

    with pytest.raises(RuntimeError, match="installation failed"):
        module.install_service("config", "secret")

    assert calls == ["config", "token", "install", ("policy", snapshot), ("parameters", {"old": 1})]
    assert all("secret" not in str(item) for item in calls)


def test_successful_install_configures_failure_actions_before_start(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(
            HandleCommandLine=lambda *args, **kwargs: calls.append(kwargs["argv"][-1]) or 0
        ),
    )
    monkeypatch.setattr(module, "_service_state", lambda: None)
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: {})
    monkeypatch.setattr(module, "persist_config", lambda value: calls.append("config"))
    monkeypatch.setattr(module, "persist_machine_credential", lambda value: calls.append("token"))
    monkeypatch.setattr(
        module, "_configure_failure_actions", lambda: calls.append("failure-actions")
    )

    module.install_service("config", "secret")

    assert calls == ["config", "token", "install", "failure-actions", "start"]


@pytest.mark.parametrize("stop_result", [None, 0, 1062])
def test_remove_stops_then_clears_owned_values_then_removes(monkeypatch, stop_result):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    snapshot = {"ConfigPath": ("old", 1), "MachineCredential": (b"old", 3)}

    def command(command):
        calls.append(command)
        return stop_result if command == "stop" else 0

    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(HandleCommandLine=lambda *args, **kwargs: command(kwargs["argv"][-1])),
    )
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: snapshot)
    monkeypatch.setattr(module, "_delete_value", lambda name: calls.append(("delete", name)))
    module.remove_service()
    assert calls == ["stop", ("delete", "ConfigPath"), ("delete", "MachineCredential"), "remove"]


@pytest.mark.parametrize("failure", ["stop", "delete", "remove"])
def test_remove_failure_restores_exact_snapshot(monkeypatch, failure):
    module = importlib.import_module("onesearch_agent.windows_service")
    calls = []
    snapshot = {"ConfigPath": ("old", 1), "MachineCredential": (b"old", 3)}

    def command(command):
        calls.append(command)
        return 5 if command == failure else 0

    monkeypatch.setattr(
        module,
        "win32serviceutil",
        SimpleNamespace(HandleCommandLine=lambda *args, **kwargs: command(kwargs["argv"][-1])),
    )
    monkeypatch.setattr(module, "_snapshot_parameters", lambda: snapshot)
    monkeypatch.setattr(
        module,
        "_delete_value",
        lambda name: (_ for _ in ()).throw(OSError())
        if failure == "delete"
        else calls.append(("delete", name)),
    )
    monkeypatch.setattr(
        module, "_restore_parameters", lambda value: calls.append(("restore", value))
    )
    with pytest.raises(RuntimeError):
        module.remove_service()
    assert calls[-1] == ("restore", snapshot)


def test_service_class_exposes_scm_stop_and_runtime_methods():
    module = importlib.import_module("onesearch_agent.windows_service")
    assert module.OneSearchAgentService._svc_name_ == "OneSearchAgent"
    assert callable(module.OneSearchAgentService.SvcStop)
    assert callable(module.OneSearchAgentService.SvcDoRun)


def test_svc_stop_reports_pending_and_signals_event(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    signal = Mock()
    monkeypatch.setattr(module, "win32event", SimpleNamespace(SetEvent=signal))
    monkeypatch.setattr(module, "win32service", SimpleNamespace(SERVICE_STOP_PENDING=3))
    fake = SimpleNamespace(stop_event="event", ReportServiceStatus=Mock())
    module.OneSearchAgentService.SvcStop(fake)
    fake.ReportServiceStatus.assert_called_once_with(3)
    signal.assert_called_once_with("event")


def test_svc_do_run_delegates_to_service_helper(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    helper = Mock()
    monkeypatch.setattr(module, "_run_service", helper)
    module.OneSearchAgentService.SvcDoRun(SimpleNamespace(stop_event="event"))
    helper.assert_called_once_with("event")


def test_run_service_wires_config_token_client_and_stop_predicate(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    config = SimpleNamespace(server_url="http://server")
    store = SimpleNamespace(load=Mock(return_value="secret"))

    class Client:
        async def __aenter__(self):
            seen["entered"] = True
            return self

        async def __aexit__(self, *args):
            seen["exited"] = True

    client = Client()
    seen = {}
    monkeypatch.setattr(module, "service_config", lambda: "C:/agent.toml")
    monkeypatch.setattr(module, "machine_credential", lambda: "secret")
    monkeypatch.setattr(
        module, "win32event", SimpleNamespace(WaitForSingleObject=lambda event, zero: 0)
    )
    monkeypatch.setattr(
        module,
        "_service_dependencies",
        lambda: (
            lambda url, token: (seen.update(url=url, token=token) or client),
            lambda value: value,
            lambda value: config,
            lambda value: store,
            lambda value, stopped, **kwargs: _runtime(seen, value, stopped, **kwargs),
        ),
    )
    module._run_service("event")
    assert seen["url"] == "http://server" and seen["token"] == "secret"
    assert seen["runtime"] is client and seen["stopped"]() and seen["entered"] and seen["exited"]


@pytest.mark.parametrize("auto_update", [False, True])
def test_run_service_reports_updates_for_local_preference_without_windows_host(monkeypatch, tmp_path, auto_update):
    module = importlib.import_module("onesearch_agent.windows_service")
    config = SimpleNamespace(server_url="http://server", auto_update=auto_update, state_dir=tmp_path)
    seen = {}

    class Reporter:
        def __init__(self, **kwargs): seen["reporter_args"] = kwargs

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    async def runtime(client, **kwargs): seen.update(client=client, **kwargs)

    monkeypatch.setattr(module, "service_config", lambda: "C:/agent.toml")
    monkeypatch.setattr(module, "machine_credential", lambda: "secret")
    monkeypatch.setattr(module, "win32event", SimpleNamespace(WaitForSingleObject=lambda *_: 0))
    monkeypatch.setattr(module, "UpdateReporter", Reporter, raising=False)
    monkeypatch.setattr(module, "stage_and_launch", lambda **kwargs: seen.update(stage=kwargs))
    monkeypatch.setattr(module, "_service_dependencies", lambda: (lambda *_: Client(), lambda value: value, lambda value: config, lambda value: None, runtime))

    module._run_service("event")

    assert seen["reporter_args"]["auto_update"] is auto_update
    assert isinstance(seen["update_reporter"], Reporter)
    assert ("stage" in seen) is auto_update


async def _runtime(seen, value, stopped, **kwargs):
    seen.update(runtime=value, stopped=stopped, **kwargs)
