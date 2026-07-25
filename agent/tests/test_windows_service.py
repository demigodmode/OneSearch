import importlib


def test_windows_service_module_import_is_lazy_off_windows():
    module = importlib.import_module("onesearch_agent.windows_service")
    assert callable(module.service_class) and callable(module.main)


def test_windows_service_reports_missing_pywin32_safely(monkeypatch):
    module = importlib.import_module("onesearch_agent.windows_service")
    monkeypatch.setattr(
        module,
        "_modules",
        lambda: (_ for _ in ()).throw(RuntimeError("pywin32 is required for the Windows service")),
    )
    try:
        module.main()
    except RuntimeError as error:
        assert "pywin32" in str(error)
    else:
        raise AssertionError("expected pywin32 error")
