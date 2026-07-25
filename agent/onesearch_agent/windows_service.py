"""Module-level pywin32 SCM host; imports safely when pywin32 is absent."""

from __future__ import annotations

import asyncio
import os
import sys

try:  # pragma: no cover - availability is platform-specific
    import winreg

    import win32event
    import win32service
    import win32serviceutil
except ImportError:  # keep package imports safe on Linux
    win32event = win32service = win32serviceutil = winreg = None

CONFIG_VALUE = "ConfigPath"


def _parameters_key():
    if winreg is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    return r"SYSTEM\CurrentControlSet\Services\OneSearchAgent\Parameters"


def persist_config(path: str) -> None:
    key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
    try:
        winreg.SetValueEx(key, CONFIG_VALUE, 0, winreg.REG_SZ, path)
    finally:
        winreg.CloseKey(key)


def service_config() -> str | None:
    if winreg is None:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
        try:
            return winreg.QueryValueEx(key, CONFIG_VALUE)[0]
        finally:
            winreg.CloseKey(key)
    except OSError:
        return None


def clear_config() -> None:
    if winreg is None:
        return
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
    except FileNotFoundError:
        return
    except OSError as error:
        raise RuntimeError("unable to remove service configuration") from error


_ServiceBase = win32serviceutil.ServiceFramework if win32serviceutil else object


class OneSearchAgentService(_ServiceBase):
    _svc_name_ = "OneSearchAgent"
    _svc_display_name_ = "OneSearch Agent"

    def __init__(self, args):
        if win32serviceutil is None:
            raise RuntimeError("pywin32 is required for the Windows service")
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):  # noqa: N802
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):  # noqa: N802
        _run_service(self.stop_event)


def _run_service(stop_event) -> None:
    agent_client, config_path, load_config, credential_store, run_runtime = _service_dependencies()
    config = load_config(config_path(service_config() or os.environ.get("ONESEARCH_AGENT_CONFIG")))
    token = credential_store(config).load()
    asyncio.run(
        run_runtime(
            agent_client(config.server_url, token),
            stopped=lambda: win32event.WaitForSingleObject(stop_event, 0) == 0,
            wait_stopped=lambda: asyncio.to_thread(win32event.WaitForSingleObject, stop_event, -1),
        )
    )


def _service_dependencies():
    from .client import AgentClient
    from .config import config_path, load_config
    from .credentials import credential_store
    from .runtime import run_runtime

    return AgentClient, config_path, load_config, credential_store, run_runtime


def main():
    if win32serviceutil is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    arguments = sys.argv[1:]
    config = None
    if "--config" in arguments:
        index = arguments.index("--config")
        config = arguments[index + 1]
        del arguments[index : index + 2]
    result = win32serviceutil.HandleCommandLine(
        OneSearchAgentService, argv=[sys.argv[0], *arguments]
    )
    if result not in (None, 0):
        raise RuntimeError("Windows service command failed")
    if config is not None and any(command in arguments for command in ("install", "update")):
        persist_config(config)
    if "remove" in arguments:
        clear_config()


if __name__ == "__main__":  # pragma: no cover
    main()
