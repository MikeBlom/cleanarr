from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class TaskDefinition:
    name: str
    display_name: str
    description: str
    icon: str  # Font Awesome class (without fa-solid prefix)
    func: Callable  # (db: Session, set_progress: Callable[[int, int], None]) -> str


TASK_REGISTRY: dict[str, TaskDefinition] = {}


def register_task(
    name: str, display_name: str, description: str, icon: str
) -> Callable:
    """Decorator to register a system task."""

    def decorator(func: Callable) -> Callable:
        TASK_REGISTRY[name] = TaskDefinition(
            name=name,
            display_name=display_name,
            description=description,
            icon=icon,
            func=func,
        )
        return func

    return decorator
