"""Module-level pywin32 SCM host; imports safely when pywin32 is absent."""

from __future__ import annotations

import asyncio
import os
import sys

from . import __version__
from .update import UpdateError
from .update_report import UpdateReporter
from .update_runtime import stage_and_launch, write_healthy_marker

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
FAILURE_ACTION_RESET_SECONDS = 86400
FAILURE_ACTION_DELAYS_MS = (5000, 15000, 60000)


def _parameters_key():
    if winreg is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    return r"SYSTEM\CurrentControlSet\Services\OneSearchAgent\Parameters"


def _protect_parameters_key(key) -> None:
    """Replace inherited access with SYSTEM and local Administrators only."""
    try:
        import ntsecuritycon
        import win32security

        dacl = win32security.ACL()
        for sid_type in (
            win32security.WinLocalSystemSid,
            win32security.WinBuiltinAdministratorsSid,
        ):
            sid = win32security.CreateWellKnownSid(sid_type, None)
            dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.KEY_ALL_ACCESS, sid)
        win32security.SetSecurityInfo(
            key,
            win32security.SE_REGISTRY_KEY,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
    except Exception as error:
        raise RuntimeError("unable to protect service credential registry key") from error


def persist_config(path: str) -> None:
    key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
    try:
        _protect_parameters_key(key)
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

        protected = win32crypt.CryptProtectData(token.encode(), None, None, None, None, 4)
        if not isinstance(protected, bytes):
            raise TypeError("unexpected CryptProtectData result")
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, _parameters_key())
        try:
            _protect_parameters_key(key)
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
        result = win32crypt.CryptUnprotectData(protected, None, None, None, 0)
        if not (isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], bytes)):
            raise TypeError("unexpected CryptUnprotectData result")
        token = result[1].decode()
        if not token:
            raise ValueError()
        return token
    except Exception as error:
        raise RuntimeError("machine credential is unavailable") from error


def _service_command(command: str):
    return win32serviceutil.HandleCommandLine(OneSearchAgentService, argv=[sys.argv[0], command])


def _command_succeeded(result) -> bool:
    return result in (None, 0)


def _service_state():
    """Return the SCM state, or None when the service is absent."""
    try:
        return win32serviceutil.QueryServiceStatus(OneSearchAgentService._svc_name_)[1]
    except AttributeError:  # lightweight test doubles and unsupported pywin32 builds
        return None
    except Exception as error:
        if getattr(error, "winerror", None) == 1060:
            return None
        raise RuntimeError("unable to query Windows service state") from error


def _failure_action_value():
    return {
        "ResetPeriod": FAILURE_ACTION_RESET_SECONDS,
        "RebootMsg": None,
        "Command": None,
        "Actions": tuple(
            (win32service.SC_ACTION_RESTART, delay) for delay in FAILURE_ACTION_DELAYS_MS
        ),
    }


def _failure_action_service(access):
    manager = service = None
    try:
        manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        service = win32service.OpenService(manager, OneSearchAgentService._svc_name_, access)
        return manager, service
    except Exception:
        if service is not None:
            win32service.CloseServiceHandle(service)
        if manager is not None:
            win32service.CloseServiceHandle(manager)
        raise


def _close_failure_action_handles(manager, service) -> None:
    if service is not None:
        win32service.CloseServiceHandle(service)
    if manager is not None:
        win32service.CloseServiceHandle(manager)


def _snapshot_failure_actions():
    """Read the exact SCM policy so an existing service can be restored."""
    manager = service = None
    try:
        manager, service = _failure_action_service(win32service.SERVICE_QUERY_CONFIG)
        return win32service.QueryServiceConfig2(
            service, win32service.SERVICE_CONFIG_FAILURE_ACTIONS
        )
    finally:
        _close_failure_action_handles(manager, service)


def _configure_failure_actions() -> None:
    manager = service = None
    try:
        manager, service = _failure_action_service(win32service.SERVICE_CHANGE_CONFIG)
        win32service.ChangeServiceConfig2(
            service, win32service.SERVICE_CONFIG_FAILURE_ACTIONS, _failure_action_value()
        )
    finally:
        _close_failure_action_handles(manager, service)


def _restore_failure_actions(snapshot) -> None:
    manager = service = None
    try:
        manager, service = _failure_action_service(win32service.SERVICE_CHANGE_CONFIG)
        win32service.ChangeServiceConfig2(
            service, win32service.SERVICE_CONFIG_FAILURE_ACTIONS, snapshot
        )
    finally:
        _close_failure_action_handles(manager, service)


def install_service(config: str, token: str) -> None:
    """Stage protected state, install, and start with rollback on failure."""
    if win32serviceutil is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    existed_before = _service_state() is not None
    failure_snapshot = _snapshot_failure_actions() if existed_before else None
    snapshot = _snapshot_parameters()
    installed = False
    failure_actions_attempted = False
    try:
        persist_config(config)
        persist_machine_credential(token)
        result = win32serviceutil.HandleCommandLine(
            OneSearchAgentService, argv=[sys.argv[0], "--startup", "auto", "install"]
        )
        if not _command_succeeded(result):
            raise RuntimeError("Windows service command failed")
        installed = True
        failure_actions_attempted = True
        _configure_failure_actions()
        start_result = _service_command("start")
        if not _command_succeeded(start_result) and start_result != 1056:
            raise RuntimeError("Windows service start failed")
    except Exception as error:
        policy_rollback_error = None
        if existed_before and failure_actions_attempted:
            try:
                _restore_failure_actions(failure_snapshot)
            except Exception as restore_error:
                policy_rollback_error = restore_error
        if installed and not existed_before:
            try:
                if not _command_succeeded(_service_command("remove")):
                    raise RuntimeError("Windows service rollback failed")
            except Exception as rollback_error:
                raise RuntimeError(
                    "Windows service start failed; service remains installed with protected credentials"
                ) from rollback_error
        _restore_parameters(snapshot)
        if policy_rollback_error is not None:
            raise RuntimeError(
                "Windows service failure policy rollback failed"
            ) from policy_rollback_error
        raise RuntimeError("Windows service installation failed") from error


def remove_service() -> None:
    if win32serviceutil is None:
        raise RuntimeError("pywin32 is required for the Windows service")
    snapshot = _snapshot_parameters()
    try:
        # 1062 is ERROR_SERVICE_NOT_ACTIVE and is safe to continue from.
        stopped = _service_command("stop")
        if not _command_succeeded(stopped) and stopped != 1062:
            raise RuntimeError("Windows service stop failed")
        _delete_value(CONFIG_VALUE)
        _delete_value(TOKEN_VALUE)
        if not _command_succeeded(_service_command("remove")):
            raise RuntimeError("Windows service removal failed")
    except Exception as error:
        _restore_parameters(snapshot)
        raise RuntimeError("Windows service removal failed") from error


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
    auto_update = getattr(config, "auto_update", False)
    reporter = UpdateReporter(
        auto_update=auto_update,
        platform="win32-x64",
        version=__version__,
        state_dir=getattr(config, "state_dir", __import__("pathlib").Path(".")),
        clock=__import__("time").time,
    )
    if auto_update:
        try:
            stage_and_launch(
                config=config, platform="win32-x64", version=__version__,
                current_binary=__import__("pathlib").Path(sys.executable), managed=True,
            )
        except (UpdateError, OSError, RuntimeError) as error:
            reporter.record_install_error(error)
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
                on_healthy_heartbeat=lambda version, timestamp: write_healthy_marker(
                    config.state_dir, version, timestamp
                ),
                update_reporter=reporter,
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
