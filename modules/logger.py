# modules/logger.py

import logging
import os
from datetime import datetime
from dotenv import load_dotenv

class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[94m",  # Blau
        "INFO": "\033[92m",  # Grün
        "WARNING": "\033[93m",  # Gelb
        "ERROR": "\033[91m",  # Rot
        "CRITICAL": "\033[95m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

load_dotenv()

def to_bool(value):
    return str(value).lower() in ("1", "true", "yes", "on")

DEBUG_MODE = to_bool(os.getenv("DEBUG", "false"))

def setup_logger(log_folder="logs", level=logging.INFO):
    # Falls DEBUG aktiviert ist, setze level auf DEBUG
    if level == logging.INFO and DEBUG_MODE:
        level = logging.DEBUG

    # Erstelle das Log-Verzeichnis, falls es nicht existiert
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    # Erstelle einen Dateinamen mit Datum und Uhrzeit
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_folder, f"bot_{now}.log")

    # Logger konfigurieren
    logger = logging.getLogger(__name__)
    logger.setLevel(level)

    # Bestehende Handler entfernen, um Duplikate zu vermeiden
    if logger.hasHandlers():
        logger.handlers.clear()

    # FileHandler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",  # ➔ Hier! Datum + Uhrzeit OHNE Millisekunden
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Optionale Ausgabe auf der Konsole
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    color_formatter = ColorFormatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(color_formatter)
    logger.addHandler(console_handler)

    return logger


# Direkt einmal initialisieren
logger = setup_logger()
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
