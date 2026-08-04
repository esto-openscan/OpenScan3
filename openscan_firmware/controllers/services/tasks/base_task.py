from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from openscan_firmware.models.task import Task

logger = logging.getLogger(__name__)


class BaseTask(ABC):
    """
    Abstract base class for a background task.

    This class defines the interface for all tasks that can be run by the TaskManager.
    Each task should inherit from this class and implement the `run` method.

    Attributes:
        task_name: Optional registry name used by autodiscovery. Manually registered
            tasks can still receive their name from TaskManager.register_task().
        task_category: Optional grouping label used for discovered task classes.
        is_exclusive: If True, this task cannot run concurrently with any other tasks.
        is_blocking: If True, the `run` method is a standard synchronous function
            that will be executed in a separate thread to avoid blocking the main
            asyncio event loop. If False (default), `run` must be an async method.
    """

    task_name: ClassVar[str | None] = None
    task_category: ClassVar[str] = "community"
    is_exclusive: ClassVar[bool] = False
    is_blocking: ClassVar[bool] = False

    def __init__(self, task_model: Task):
        """
        Initializes the BaseTask.

        Args:
            task_model: The Pydantic model instance representing this task.
        """
        self._task_model = task_model
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set() # Start in a 'not paused' state

    @property
    def id(self) -> str:
        """The unique ID of the task."""
        return self._task_model.id

    @property
    def name(self) -> str:
        """The name of the task."""
        return self._task_model.name

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Any:
        """
        The main logic of the task.

        This method must be implemented by subclasses. It can be implemented in two ways:

        1.  **As a standard async function**:
            It performs its work and returns a final result. The `TaskManager` will
            set this return value as the task's `result`.

        2.  **As an async generator**:
            It can report progress by `yield`-ing `TaskProgress` objects. The generator
            itself does not need to return a value. If the task needs to produce a
            final result, it should be set directly on `self._task_model.result`
            before the generator finishes.

        Args:
            *args: Positional arguments for the task.
            **kwargs: Keyword arguments for the task.

        Returns:
            The result of the task execution for standard async functions, or an
            AsyncGenerator for progress-reporting tasks.
        """
        raise NotImplementedError

    def cancel(self) -> None:
        """
        Signals the task to cancel its execution.

        The `run` method should periodically check `is_cancelled()` to gracefully
        terminate.
        """
        self._stop_event.set()
        # Ensure paused tasks resume so they can observe the cancellation signal.
        self._pause_event.set()

    def is_cancelled(self) -> bool:
        """
        Checks if a cancellation request has been made.

        Returns:
            True if the task should be cancelled, False otherwise.
        """
        return self._stop_event.is_set()

    def pause(self) -> None:
        """
        Signals the task to pause execution.
        The run loop must use `wait_for_pause()` to honor this.
        """
        self._pause_event.clear()
        logger.debug(f"Pause signal set for task {self.id}")

    def resume(self) -> None:
        """
        Signals a paused task to resume.
        """
        self._pause_event.set()
        logger.debug(f"Resume signal set for task {self.id}")

    async def wait_for_pause(self) -> None:
        """
        Pauses task execution until resume() is called.
        This should be used inside the main loop of a task.
        """
        await self._pause_event.wait()

    def is_paused(self) -> bool:
        """
        Checks if the task is currently signaled to be in a paused state.

        Returns:
            True if the pause signal is active, False otherwise.
        """
        return not self._pause_event.is_set()

    def _update_progress(self, current: float, total: float, message: str = "") -> None:
        """
        Updates the task's progress.

        The elapsed time is calculated and set by the TaskManager.

        Args:
            current: The current progress step.
            total: The total number of steps.
            message: A descriptive message for the current progress.
        """
        self._task_model.progress.current = current
        self._task_model.progress.total = total
        self._task_model.progress.message = message
