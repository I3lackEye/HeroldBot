# dataStorage.py
import discord
from discord import app_commands
import os
import json

def load_anmeldungen():
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    print("⚠ Fehler: Datei hat ein falsches Format! Erstelle neue Datei.")
                    return {"teams": {}, "solo": [], "punkte": {}}
                return data
        except json.JSONDecodeError:
            print("⚠ Fehler: Datei ist beschädigt! Erstelle eine leere Datei.")
            return {"teams": {}, "solo": [], "punkte": {}}
    return {"teams": {}, "solo": [], "punkte": {}}

def save_anmeldungen():
    with open(FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(anmeldungen, file, indent=4, ensure_ascii=False)