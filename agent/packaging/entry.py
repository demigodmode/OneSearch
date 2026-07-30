from __future__ import annotations

import sys

from onesearch_agent.cli import main
from onesearch_agent.windows_service import main as windows_service_main

if __name__ == "__main__":
    # SCM invokes the frozen executable without Click subcommands.
    if sys.platform == "win32" and not any(arg in sys.argv[1:] for arg in ("run", "enroll", "config", "update", "service")):
        windows_service_main()
    else:
        main()
