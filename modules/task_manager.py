# modules/task_manager.py

import asyncio

# Local modules
from modules.logger import logger

all_tasks = {}  # name -> {"task": task, "coro": coro_name}


def add_task(name, task):
    """
    Adds a task to the task manager.
    If a task with the same name exists and is not done, it will be cancelled.
    """
    if name in all_tasks and not all_tasks[name]["task"].done():
        logger.info(f"[TASK-MANAGER] Task '{name}' is being overwritten and old task cancelled.")
        all_tasks[name]["task"].cancel()
    all_tasks[name] = {"task": task, "coro": str(task.get_coro().__name__) if hasattr(task, "get_coro") else "unknown"}
    logger.info(f"[TASK-MANAGER] Task '{name}' started.")


def cancel_all_tasks():
    """Cancels all active tasks."""
    for name, entry in list(all_tasks.items()):
        task = entry["task"]
        if not task.done():
            try:
                logger.info(f"[TASK-MANAGER] Cancelling task: {name}")
            except Exception:
                pass
            task.cancel()
        all_tasks.pop(name, None)


def get_all_tasks():
    """Returns a dict of all tasks."""
    return all_tasks


def log_active_tasks():
    """Logs information about all active tasks."""
    for name, entry in all_tasks.items():
        task = entry["task"]
        coro = entry["coro"]
        logger.info(f"[TASK-MANAGER] Task: {name}, done={task.done()}, cancelled={task.cancelled()}, coroutine={coro}")


def cancel_tournament_tasks():
    """
    Cancels all tournament-related tasks.
    Used when tournament is manually ended or aborted.
    """
    tournament_task_prefixes = [
        "tournament_end",
        "close_registration",
        "auto_end_poll",
        "reschedule_timer"
    ]

    cancelled_tasks = []
    for name, entry in list(all_tasks.items()):
        task = entry["task"]

        # Check if task name starts with any tournament-related prefix
        if any(name.startswith(prefix) for prefix in tournament_task_prefixes):
            if not task.done():
                try:
                    task.cancel()
                    cancelled_tasks.append(name)
                    logger.info(f"[TASK-MANAGER] Cancelled tournament task: {name}")
                except Exception as e:
                    logger.error(f"[TASK-MANAGER] Error cancelling task {name}: {e}")
            all_tasks.pop(name, None)

    if cancelled_tasks:
        logger.info(f"[TASK-MANAGER] Cancelled {len(cancelled_tasks)} tournament tasks: {cancelled_tasks}")
    else:
        logger.info("[TASK-MANAGER] No active tournament tasks to cancel")

    return cancelled_tasks
