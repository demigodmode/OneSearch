import importlib


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
