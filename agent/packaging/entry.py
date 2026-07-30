from __future__ import annotations

import sys

from onesearch_agent.cli import main
from onesearch_agent.packaging import should_launch_windows_service
from onesearch_agent.windows_service import main as windows_service_main

if __name__ == "__main__":
    # SCM invokes the frozen executable without Click subcommands.
    if should_launch_windows_service(sys.platform, sys.argv[1:]):
        windows_service_main()
    else:
        main()
