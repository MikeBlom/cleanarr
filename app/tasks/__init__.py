"""System tasks: registry, runner, and task implementations."""

from .registry import TASK_REGISTRY  # noqa: F401
from .runner import is_task_running, trigger_task  # noqa: F401

# Import task modules to trigger @register_task decorators
from . import sync_plex_paths  # noqa: F401
