import os
import shutil
import pytest

from openscan_firmware.controllers.services.tasks.core.registry import BUILTIN_TASKS
from openscan_firmware.controllers.services.tasks import (
    task_manager as task_manager_module,
)
from openscan_firmware.controllers.services.tasks.task_manager import TaskManager


BUILTIN_TASK_NAMES = {task_class.task_name for task_class in BUILTIN_TASKS}


@pytest.mark.asyncio
async def test_autodiscover_registers_core_tasks():
    """Autodiscovery should register every built-in task.

    We only assert the presence of core tasks here to avoid coupling to demo examples.
    """
    # Clean persistence dir and reset singleton
    TaskManager._instance = None
    tm = TaskManager()

    # Ensure a clean registry
    tm._task_registry.clear()

    registered = tm.autodiscover_tasks(
        namespaces=[
            "openscan_firmware.controllers.services.tasks",
            "openscan_firmware.tasks.community",
        ],
        extra_ignore_modules={"base_task", "task_manager", "example_tasks"},
        override_on_conflict=False,
    )

    builtin_names = BUILTIN_TASK_NAMES

    # Core tasks must be present
    for task_name in builtin_names:
        assert task_name in tm._task_registry

    # The method should return the list of newly registered tasks
    for task_name in builtin_names:
        assert task_name in registered


@pytest.mark.asyncio
async def test_autodiscover_safe_mode_handles_import_errors():
    """Autodiscovery should not crash on import errors when safe_mode=True.

    We intentionally do NOT ignore the legacy module `example_tasks` which raises
    ImportError on import. In safe_mode, this should be logged and skipped.
    """
    TaskManager._instance = None
    tm = TaskManager()

    # Add a bogus namespace to trigger an import error while staying in safe mode
    tm.autodiscover_tasks(
        namespaces=[
            "openscan_firmware.controllers.services.tasks",
            "openscan_firmware.controllers.services.tasks.non_existent_namespace",
        ],
        extra_ignore_modules={"base_task", "task_manager"},
        override_on_conflict=False,
    )

    builtin_names = BUILTIN_TASK_NAMES

    # Core tasks should still be discovered
    for task_name in builtin_names:
        assert task_name in tm._task_registry


@pytest.mark.asyncio
async def test_autodiscover_ignore_examples_package():
    """Ignoring the examples package should prevent demo tasks from registering."""
    TaskManager._instance = None
    tm = TaskManager()

    tm.autodiscover_tasks(
        namespaces=["openscan_firmware.controllers.services.tasks"],
        extra_ignore_modules={"base_task", "task_manager", "examples"},
        override_on_conflict=False,
    )

    # Demo/example tasks should not be present (including crop_task, now an example)
    assert "hello_world_progress_task" not in tm._task_registry
    assert "hello_world_blocking_task" not in tm._task_registry
    assert "exclusive_demo_task" not in tm._task_registry
    assert "crop_task" not in tm._task_registry


@pytest.mark.asyncio
async def test_autodiscover_defaults_register_core_tasks():
    """Calling autodiscover_tasks() without args should use built-in defaults."""
    TaskManager._instance = None
    tm = TaskManager()

    tm._task_registry.clear()

    registered = tm.autodiscover_tasks()

    builtin_names = BUILTIN_TASK_NAMES

    for task_name in builtin_names:
        assert task_name in tm._task_registry
        assert task_name in registered


@pytest.mark.asyncio
async def test_autodiscover_conflict_override_false():
    """When a task_name already exists and override_on_conflict=False, keep original."""
    from openscan_firmware.controllers.services.tasks.base_task import BaseTask

    class DummyTask(BaseTask):
        task_name = "scan_task"
        task_category = "test"
        is_exclusive = False
        async def run(self):
            return None

    TaskManager._instance = None
    tm = TaskManager()

    # Pre-register dummy under the same name as a core task
    tm.register_task("scan_task", DummyTask)
    original_cls = tm._task_registry["scan_task"]

    tm.autodiscover_tasks(
        namespaces=["openscan_firmware.controllers.services.tasks"],
        extra_ignore_modules={"base_task", "task_manager"},
        override_on_conflict=False,
    )

    # Registry should still point to the original dummy task
    assert tm._task_registry["scan_task"] is original_cls


def test_external_task_overrides_builtin_when_enabled(tmp_path, monkeypatch):
    override_file = tmp_path / "scan_override.py"
    override_file.write_text(
        "\n".join(
            [
                "from openscan_firmware.controllers.services.tasks.base_task import BaseTask",
                "",
                "class ScanOverrideTask(BaseTask):",
                '    task_name = "scan_task"',
                '    task_category = "community"',
                "",
                "    async def run(self):",
                '        return "external override"',
            ]
        )
    )
    monkeypatch.setattr(
        task_manager_module,
        "resolve_community_tasks_dir",
        lambda: tmp_path,
    )

    TaskManager._instance = None
    tm = TaskManager()
    tm.initialize_core_tasks(
        autodiscovery_enabled=True,
        override_on_conflict=True,
    )

    registered_class = tm._task_registry["scan_task"]
    assert registered_class.__name__ == "ScanOverrideTask"
    assert registered_class.__module__ == "openscan_external_tasks.scan_override"


def test_builtin_registry_has_unique_explicit_names():
    names = [task_class.task_name for task_class in BUILTIN_TASKS]

    assert all(names)
    assert len(names) == len(set(names))


def test_initialize_core_tasks_uses_builtin_registry_without_autodiscovery():
    TaskManager._instance = None
    tm = TaskManager()

    tm.initialize_core_tasks(autodiscovery_enabled=False)

    assert tm._task_registry == {
        task_class.task_name: task_class for task_class in BUILTIN_TASKS
    }
