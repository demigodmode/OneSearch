"""Windows SCM host, imported only by the Windows service manager."""

from __future__ import annotations

import asyncio
import os


def _modules():
    try:
        import win32event
        import win32serviceutil
    except ImportError as error:  # pragma: no cover - Windows-only dependency
        raise RuntimeError("pywin32 is required for the Windows service") from error
    return win32event, win32serviceutil


def service_class():
    win32event, win32serviceutil = _modules()
    from .client import AgentClient
    from .config import config_path, load_config
    from .credentials import credential_store
    from .runtime import run_runtime

    class OneSearchAgentService(win32serviceutil.ServiceFramework):
        _svc_name_ = "OneSearchAgent"
        _svc_display_name_ = "OneSearch Agent"

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        def SvcStop(self):  # noqa: N802
            self.ReportServiceStatus(3)
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self):  # noqa: N802
            config = load_config(config_path(os.environ.get("ONESEARCH_AGENT_CONFIG")))
            token = credential_store(config, docker=False).load()
            asyncio.run(run_runtime(AgentClient(config.server_url, token)))

    return OneSearchAgentService


def main():
    _, win32serviceutil = _modules()
    win32serviceutil.HandleCommandLine(service_class())


if __name__ == "__main__":  # pragma: no cover
    main()
