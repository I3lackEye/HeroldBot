# modules/taks_manager.py

import asyncio

# lokale Modules
from modules.logger import logger

all_tasks = {}  # name -> {"task": task, "coro": coro_name}


def add_task(name, task):
    if name in all_tasks and not all_tasks[name]["task"].done():
        logger.info(f"[TASK-MANAGER] Task '{name}' wird überschrieben und alter Task gecancelt.")
        all_tasks[name]["task"].cancel()
    all_tasks[name] = {
        "task": task,
        "coro": str(task.get_coro().__name__) if hasattr(task, "get_coro") else "unknown"
    }
    logger.info(f"[TASK-MANAGER] Task '{name}' gestartet.")


def cancel_all_tasks():
    for name, task in list(all_tasks.items()):
        if not task.done():
            try:
                logger.info(f"[TASK-MANAGER] Cancelling Task: {name}")
            except Exception:
                pass
            task.cancel()
        all_tasks.pop(name, None)


def get_all_tasks():
    return all_tasks


def log_active_tasks():
    for name, entry in all_tasks.items():
        task = entry["task"]
        coro = entry["coro"]
        logger.info(f"[TASK-MANAGER] Task: {name}, done={task.done()}, cancelled={task.cancelled()}, coroutine={coro}")




def get_all_tasks():
    # Gibt ein Dict aller Tasks zurück
    return {name: task for name, task in all_tasks.items()}
