# modules/logger.py

import logging
import os
from datetime import datetime
from dotenv import load_dotenv

class ColorFormatter(logging.Formatter):
    """Custom formatter that adds color to console log output."""
    COLORS = {
        "DEBUG": "\033[94m",  # Blue
        "INFO": "\033[92m",  # Green
        "WARNING": "\033[93m",  # Yellow
        "ERROR": "\033[91m",  # Red
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

load_dotenv()

def to_bool(value):
    """Convert string to boolean."""
    return str(value).lower() in ("1", "true", "yes", "on")

DEBUG_MODE = to_bool(os.getenv("DEBUG", "false"))

def setup_logger(log_folder="logs", level=logging.INFO):
    """
    Sets up the logger with file and console handlers.
    If DEBUG mode is active, level is set to DEBUG.
    """
    # If DEBUG is active, set level to DEBUG
    if level == logging.INFO and DEBUG_MODE:
        level = logging.DEBUG

    # Create log directory if it doesn't exist
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    # Create filename with date and time
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_folder, f"bot_{now}.log")

    # Configure logger
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # FileHandler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Optional console output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    color_formatter = ColorFormatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(color_formatter)
    logger.addHandler(console_handler)

    return logger


# Initialize once
logger = setup_logger()
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
