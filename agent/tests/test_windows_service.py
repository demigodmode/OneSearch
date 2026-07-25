import importlib

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
