# modules/taks_manager.py

import asyncio

# lokale Modules
from modules.logger import logger

all_tasks = {}  # define task list


def add_task(name, task):
    if name in all_tasks and not all_tasks[name].done():
        logger.info(f"[TASK-MANAGER] Task '{name}' wird überschrieben und alter Task gecancelt.")
        all_tasks[name].cancel()
    all_tasks[name] = task
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


def get_task(name):
    return all_tasks.get(name)


def log_active_tasks():
    for name, task in all_tasks.items():
        logger.info(f"[TASK-MANAGER] Aktiver Task: {name}, done={task.done()}")


def get_all_tasks():
    # Gibt ein Dict aller Tasks zurück
    return {name: task for name, task in all_tasks.items()}
