# ruff: noqa: N802
import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


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
            return (None, b"cipher")

    monkeypatch.setattr(module, "winreg", Registry())
    monkeypatch.setitem(__import__("sys").modules, "win32crypt", Crypto())
    module.persist_machine_credential("secret")
    assert calls == [("MachineCredential", 3, b"cipher")]


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
            lambda value, stopped, **kwargs: _runtime(seen, value, stopped),
        ),
    )
    module._run_service("event")
    assert seen["url"] == "http://server" and seen["token"] == "secret"
    assert seen["runtime"] is client and seen["stopped"]() and seen["entered"] and seen["exited"]


async def _runtime(seen, value, stopped):
    seen.update(runtime=value, stopped=stopped)
