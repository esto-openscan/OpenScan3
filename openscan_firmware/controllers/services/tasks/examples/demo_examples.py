"""
Autodiscovered example tasks for OpenScan3.

These classes are safe to import (no hardware initialization at import time)
and carry explicit task_name values with the required `_task` suffix.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

from openscan_firmware.controllers.services.tasks.base_task import BaseTask
from openscan_firmware.models.task import TaskProgress

logger = logging.getLogger(__name__)


class HelloWorldBlockingTask(BaseTask):
    """Demonstrates a blocking (synchronous) task.

    The TaskManager will run this in a thread pool since `is_blocking=True`.
    """

    task_name = "hello_world_blocking_task"
    task_category = "example"
    is_exclusive = False
    is_blocking = True

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the blocking example task.

        Args:
            *args: Unused.
            **kwargs: May contain `duration`.

        Returns:
            A simple completion string.
        """
        duration = kwargs.get("duration", 3)
        logger.info(f"[{self.id}] Starting blocking task for {duration} seconds. This will run in a thread.")
        time.sleep(duration)
        logger.info(f"[{self.id}] Blocking task finished.")
        return "Blocking task complete."


class ExclusiveDemoTask(BaseTask):
    """Demonstrates an exclusive async task."""

    task_name = "exclusive_demo_task"
    task_category = "example"
    is_exclusive = True
    is_blocking = False

    async def run(self, duration: float = 1.0):
        """Sleep for a given duration to simulate exclusive work.

        Args:
            duration: Duration in seconds to sleep.
        """
        logger.info(f"Starting exclusive task '{self.id}' for {duration}s.")
        self._task_model.progress = TaskProgress(current=0, total=1, message="Starting exclusive lock")
        await asyncio.sleep(duration)
        self._task_model.progress = TaskProgress(current=1, total=1, message="Finished exclusive lock")
        logger.info(f"Finished exclusive task '{self.id}'.")
        return {"status": "completed", "duration": duration}


class HelloWorldProgressTask(BaseTask):
    """Demonstrates the canonical async progress-reporting task pattern."""

    task_name = "hello_world_progress_task"
    task_category = "example"
    is_exclusive = False
    is_blocking = False

    async def run(self, total_steps: int = 10, interval: float = 0.5) -> AsyncGenerator[TaskProgress, None]:
        """Run the async progress example task.

        Args:
            total_steps: The number of steps to complete.
            interval: Sleep interval per step.

        Yields:
            TaskProgress updates.
        """
        if total_steps <= 0:
            yield TaskProgress(current=0, total=0, message="No steps to run.")
            return

        yield TaskProgress(current=0, total=total_steps, message="Starting Hello World progress task.")

        for i in range(1, total_steps + 1):
            await self.wait_for_pause()
            if self.is_cancelled():
                logger.info(f"Task {self.name} ({self.id}) stopping due to cancellation.")
                yield TaskProgress(
                    current=i - 1,
                    total=total_steps,
                    message="Hello World progress task cancelled.",
                )
                return

            await asyncio.sleep(interval)
            yield TaskProgress(
                current=i,
                total=total_steps,
                message=f"Hello World! Step {i} of {total_steps} complete.",
            )

        logger.info(f"[{self.id}] HelloWorldProgressTask finished.")
        self._task_model.result = f"Hello World progress task completed after {total_steps} steps."


class FailingTask(BaseTask):
    """A task that raises an exception to test error handling."""

    task_name = "failing_task"
    task_category = "example"
    is_exclusive = False
    is_blocking = False

    async def run(self, error_message: str = "This task was designed to fail."):
        """Raise an exception after a tiny delay.

        Args:
            error_message: The message to raise.
        """
        await asyncio.sleep(0.01)
        raise ValueError(error_message)
