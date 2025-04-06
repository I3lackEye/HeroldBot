# utils.py
import json

def load_config(config_path="config.json"):
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        return config
    except FileNotFoundError:
        print(f"Config file '{config_path}' not found.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing config file: {e}")
        return {}

if __name__ == "__main__":
    # Teste die Funktion, wenn du die Datei direkt ausführst
    config = load_config()
    TOKEN = config.get("TOKEN")
    DATABASE_PATH = config.get("DATABASE_PATH")
    STATS_DATABASE_PATH = config.get("STATS_DATABASE_PATH")
    ROLE_PERMISSIONS = config.get("ROLE_PERMISSIONS", {})

    print("TOKEN:", TOKEN)
    print("DATABASE_PATH:", DATABASE_PATH)
    print("ROLE_PERMISSIONS:", ROLE_PERMISSIONS)