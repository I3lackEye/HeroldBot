# utils.py
import discord
from discord import app_commands
from typing import List
from .dataStorage import load_config, load_global_data

# Konfiguration laden (falls nicht schon global geladen)
config = load_config()

def has_permission(member: discord.Member, *required_permissions: str) -> bool:
    """
    Überprüft, ob der Member mindestens eine der in der Konfiguration
    unter den übergebenen Berechtigungen angegebenen Rollen besitzt.
    
    Beispiel: has_permission(member, "Moderator", "Admin")
    
    :param member: Der Discord Member, der den Befehl ausführt.
    :param required_permissions: Ein oder mehrere Schlüssel aus ROLE_PERMISSIONS.
    :return: True, wenn der Member mindestens eine entsprechende Rolle besitzt, sonst False.
    """
    allowed_roles = []
    role_permissions = config.get("ROLE_PERMISSIONS", {})
    for permission in required_permissions:
        allowed_roles.extend(role_permissions.get(permission, []))
    
    # Alle Rollennamen des Members abrufen:
    member_role_names = [role.name for role in member.roles]
    
    # Prüfe, ob eine der erlaubten Rollen in den Member-Rollen enthalten ist:
    return any(role in member_role_names for role in allowed_roles)

def validate_string(input_str: str, max_length: int = None) -> (bool, str):
    """
    Überprüft, ob der Eingabestring ausschließlich aus alphanumerischen Zeichen,
    dem Unterstrich '_', dem Bindestrich '-' und Leerzeichen besteht und optional,
    ob er höchstens max_length Zeichen lang ist.
    
    :param input_str: Der zu überprüfende String.
    :param max_length: Die maximale erlaubte Länge. Falls None, wird der Wert aus der Konfiguration (STR_MAX_LENGTH) oder 50 verwendet.
    :return: Ein Tupel (is_valid, error_message). is_valid ist True, wenn alle Prüfungen bestanden wurden,
             ansonsten False, und error_message enthält den Fehlerhinweis.
    """
    # Falls kein max_length übergeben wurde, nutze den Wert aus der Konfiguration oder 50 als Fallback.
    if max_length is None:
        max_length = config.get("STR_MAX_LENGTH", 50)
    
    # Prüfe die Länge
    if len(input_str) > max_length:
        return False, f"Die Eingabe darf höchstens {max_length} Zeichen lang sein."
    
    # Erlaubte Zeichen: alphanumerisch, '_' , '-' und Leerzeichen
    allowed_special = ['_', '-', ' ']
    invalid_chars = [char for char in input_str if not (char.isalnum() or char in allowed_special)]
    if invalid_chars:
        invalid_unique = ", ".join(sorted(set(invalid_chars)))
        return False, f"Die Eingabe enthält ungültige Zeichen: {invalid_unique}. Erlaubt sind nur Buchstaben, Zahlen, Leerzeichen, '_' und '-'."
    
    return True, ""

async def remove_game_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """
    Liefert eine Liste von app_commands.Choice, die Spiele enthalten, 
    deren Name den aktuellen Suchtext (current) beinhaltet.
    """
    data = load_global_data()
    games = data.get("games", [])
    # Filtere alle Spiele, die "current" (case-insensitive) enthalten.
    return [
        app_commands.Choice(name=game, value=game)
        for game in games if current.lower() in game.lower()
    ]