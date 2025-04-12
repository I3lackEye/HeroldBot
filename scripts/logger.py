# logger.py
import logging
import os
from datetime import datetime

def setup_logger(log_folder="logs", level=logging.INFO):
    # Falls DEBUG aktiviert ist, setze level auf DEBUG
    if level == logging.INFO and os.getenv("DEBUG") == "1":
        level = logging.DEBUG

    # Erstelle das Log-Verzeichnis, falls es nicht existiert
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)
    
    # Erstelle einen Dateinamen mit Datum und Uhrzeit
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_folder, f"bot_{now}.log")
    
    # Logger konfigurieren
    logger = logging.getLogger("HeroldBot")
    logger.setLevel(level)
    
    # Bestehende Handler entfernen, um Duplikate zu vermeiden
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # FileHandler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Optionale Ausgabe auf der Konsole
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

if __name__ == "__main__":
    # Beispiel: Lade Konfiguration um DEBUG zu erhalten
    import json
    config_path = "config.json"  # Passe den Pfad bei Bedarf an
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    debug_value = config.get("DEBUG", 0)
    
    # Setze ein Environment-Variable, falls du das im Logger-Setup nutzen möchtest:
    os.environ["DEBUG"] = str(debug_value)
    logger = setup_logger()
    logger.debug("Dies ist eine Debug-Nachricht.")
    logger.info("Dies ist eine Informationsnachricht.")