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
TOKEN_VALUE = "MachineCredential"
_MISSING = object()


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


def _raw_value(name):
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
        try:
            return winreg.QueryValueEx(key, name)
        finally:
            winreg.CloseKey(key)
    except OSError:
        return _MISSING


def _delete_value(name):
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key(), 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, name)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return


def _snapshot_parameters():
    return {CONFIG_VALUE: _raw_value(CONFIG_VALUE), TOKEN_VALUE: _raw_value(TOKEN_VALUE)}


def _restore_parameters(snapshot) -> None:
    for name, value in snapshot.items():
        if value is _MISSING:
            _delete_value(name)
        else:
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
            try:
                winreg.SetValueEx(key, name, 0, value[1], value[0])
            finally:
                winreg.CloseKey(key)


def persist_machine_credential(token: str) -> None:
    if not token or winreg is None:
        raise RuntimeError("machine credential storage is unavailable")
    try:
        import win32crypt

        protected = win32crypt.CryptProtectData(token.encode(), None, None, None, None, 4)[1]
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
        try:
            winreg.SetValueEx(key, TOKEN_VALUE, 0, winreg.REG_BINARY, protected)
        finally:
            winreg.CloseKey(key)
    except Exception as error:
        raise RuntimeError("machine credential storage is unavailable") from error


def machine_credential() -> str:
    try:
        import win32crypt

        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
        try:
            protected = winreg.QueryValueEx(key, TOKEN_VALUE)[0]
        finally:
            winreg.CloseKey(key)
        token = win32crypt.CryptUnprotectData(protected, None, None, None, 0)[1].decode()
        if not token:
            raise ValueError()
        return token
    except Exception as error:
        raise RuntimeError("machine credential is unavailable") from error


def install_service(config: str, token: str) -> None:
    """Register SCM service after writing machine credential in-process."""
    if win32serviceutil is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    snapshot = _snapshot_parameters()
    try:
        persist_config(config)
        persist_machine_credential(token)
        result = win32serviceutil.HandleCommandLine(
            OneSearchAgentService, argv=[sys.argv[0], "--startup", "auto", "install"]
        )
        if result not in (None, 0):
            raise RuntimeError("Windows service command failed")
    except Exception as error:
        _restore_parameters(snapshot)
        raise RuntimeError("Windows service installation failed") from error


def remove_service() -> None:
    if win32serviceutil is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    result = win32serviceutil.HandleCommandLine(OneSearchAgentService, argv=[sys.argv[0], "remove"])
    if result not in (None, 0):
        raise RuntimeError("Windows service command failed")
    _delete_value(CONFIG_VALUE)
    _delete_value(TOKEN_VALUE)


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
    token = machine_credential()

    async def run():
        async with agent_client(config.server_url, token) as client:

            async def wait_stopped():
                while win32event.WaitForSingleObject(stop_event, 0) != 0:
                    await asyncio.sleep(0.1)

            await run_runtime(
                client,
                stopped=lambda: win32event.WaitForSingleObject(stop_event, 0) == 0,
                wait_stopped=wait_stopped,
            )

    asyncio.run(run())


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
