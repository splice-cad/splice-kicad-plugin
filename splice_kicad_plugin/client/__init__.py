"""Client submodule — talks to Splice's working-plan endpoint over HTTPS,
or to the running desktop app's local handoff listener over loopback."""

from .desktop_handoff import (
    DesktopTarget,
    discovery_paths,
    post_to_desktop,
    select_target,
)
from .splice_api import SpliceClient, WorkingPlanResponse

__all__ = [
    "DesktopTarget",
    "SpliceClient",
    "WorkingPlanResponse",
    "discovery_paths",
    "post_to_desktop",
    "select_target",
]
