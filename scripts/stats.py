#stats.py

import discord
from discord import app_commands, Interaction, Embed, User
from discord.app_commands import Choice
from collections import Counter
from datetime import datetime

# Lokale Module
from .dataStorage import load_global_data, save_global_data, load_tournament_data
from .utils import has_permission
from .logger import setup_logger
from .embeds import send_tournament_stats_embed, send_status_embed
logger = setup_logger("logs")

# ----------------------------------------
# Hilfsfunktionen
# ----------------------------------------

def get_leaderboard() -> str:
    """
    Gibt eine formatierte Bestenliste zurück, basierend auf den Siegen der Spieler.
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    if not player_stats:
        return "Keine Statistiken verfügbar."

    sorted_players = sorted(player_stats.items(), key=lambda item: item[1].get("wins", 0), reverse=True)

    lines = []
    for idx, (user_id, data) in enumerate(sorted_players, start=1):
        name = data.get("name", f"<@{user_id}>")
        wins = data.get("wins", 0)
        lines.append(f"{idx}. {name} – 🏅 {wins} Sieg{'e' if wins != 1 else ''}")

    leaderboard = "\n".join(lines)
    return leaderboard

def build_stats_embed(user, stats: dict) -> Embed:
    embed = Embed(
        title=f"📊 Statistiken für {user.display_name}",
        color=0x3498DB
    )

    wins = stats.get("wins", 0)
    participations = stats.get("participations", 0)
    winrate = f"{(wins / participations * 100):.1f} %" if participations > 0 else "–"

    # Lieblingsspiel bestimmen
    favorite_game = "Noch kein Lieblingsspiel"
    game_stats = stats.get("game_stats")
    if game_stats:
        favorite_game = max(game_stats.items(), key=lambda x: x[1])[0]

    embed.add_field(name="🏆 Siege", value=wins, inline=True)
    embed.add_field(name="🧩 Teilnahmen", value=participations, inline=True)
    embed.add_field(name="📈 Winrate", value=winrate, inline=True)
    embed.add_field(name="🎮 Lieblingsspiel", value=favorite_game, inline=False)
    embed.set_footer(text="Turnierauswertung")

    return embed

def get_tournament_summary() -> str:
    """
    Gibt eine kleine Zusammenfassung aller Statistiken aus (Spieler, Siege, Winrate).
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    total_players = len(player_stats)
    total_wins = sum(player.get("wins", 0) for player in player_stats.values())

    if player_stats:
        best_player_id, best_player_data = max(player_stats.items(), key=lambda item: item[1].get("wins", 0))
        best_name = best_player_data.get("name", f"<@{best_player_id}>")
        best_wins = best_player_data.get("wins", 0)
    else:
        best_name = "Niemand"
        best_wins = 0

    output = (
        f"📊 **Turnier-Übersicht**\n\n"
        f"👥 Spieler insgesamt: **{total_players}**\n"
        f"🏆 Vergebene Siege: **{total_wins}**\n"
        f"🥇 Bester Spieler: {best_name} ({best_wins} Siege)\n"
    )

    return output

def update_global_game_stats(game_name: str):
    """
    Aktualisiert die globale Statistik für das meistgespielte Spiel.
    :param game_name: Der Name des gespielten Spiels (z.B. "Beyond all Reason").
    """
    global_data = load_global_data()

    # Initialisiere, falls noch nicht vorhanden
    if "game_stats" not in global_data:
        global_data["game_stats"] = {}

    if game_name not in global_data["game_stats"]:
        global_data["game_stats"][game_name] = 0

    global_data["game_stats"][game_name] += 1

    save_global_data(global_data)
    logger.info(f"Spielstatistik aktualisiert: {game_name} wurde nun {global_data['game_stats'][game_name]}x gespielt.")

def get_favorite_game() -> str:
    global_data = load_global_data()
    game_stats = global_data.get("game_stats", {})

    if not game_stats:
        return "Keine Spiele gespielt."

    most_played_game, count = max(game_stats.items(), key=lambda item: item[1])
    return f"{most_played_game} ({count}x gespielt)"



# ----------------------------------------
# Autocomplete
# ----------------------------------------

async def autocomplete_players(interaction: Interaction, current: str):
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    choices = []
    for user_id, stats in player_stats.items():
        member = interaction.guild.get_member(int(user_id))
        if member:
            display_name = member.display_name
        else:
            display_name = stats.get("display_name") or stats.get("name") or f"Unbekannt ({user_id})"
        
        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name, value=user_id))

    return choices[:25]

async def autocomplete_teams(interaction: Interaction, current: str):
    logger.info(f"[AUTOCOMPLETE] Aufgerufen – Eingabe: {current}")

    tournament = load_tournament_data()
    if not tournament:
        logger.error("[AUTOCOMPLETE] Keine Turnierdaten geladen!")
        return []

    teams = tournament.get("teams", {})
    if not teams:
        logger.warning("[AUTOCOMPLETE] Keine Teams vorhanden im Turnier.")
        return []

    logger.info(f"[AUTOCOMPLETE] Gefundene Teams: {list(teams.keys())}")

    # Filtere die Teams, die zum aktuellen Eingabetext passen
    suggestions = [
        app_commands.Choice(name=team, value=team)
        for team in teams.keys()
        if current.lower() in team.lower()
    ][:25]

    logger.info(f"[AUTOCOMPLETE] {len(suggestions)} Vorschläge erstellt.")

    return suggestions





# ----------------------------------------
# Slash-Commands
# ----------------------------------------

@app_commands.command(name="leaderboard", description="Zeigt die Bestenliste aller Spieler an.")
async def leaderboard(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
        return

    board = get_leaderboard()
    embed = Embed(
        title="🏆 Bestenliste",
        description=board,
        color=0xF1C40F
    )
    await interaction.response.send_message(embed=embed)

@app_commands.command(name="stats", description="Zeigt deine oder die Statistiken eines anderen Spielers an.")
@app_commands.describe(user="Optional: Spieler auswählen")
@app_commands.autocomplete(user=autocomplete_players)
async def stats(interaction: Interaction, user: str = None):
    """
    Zeigt die Statistiken eines Spielers (oder eigene, falls kein Spieler ausgewählt wurde).
    """
    global_data = load_global_data()

    if user:
        user_id = user
        member = interaction.guild.get_member(int(user_id))
        if member:
            target_user = member
        else:
            # Fallback, falls User nicht mehr auf dem Server ist
            target_user = discord.Object(id=int(user_id))
    else:
        target_user = interaction.user
        user_id = str(interaction.user.id)

    player_stats = global_data.get("player_stats", {}).get(user_id)

    if not player_stats:
        await interaction.response.send_message("⚠ Es gibt noch keine Statistiken für diesen Spieler.", ephemeral=True)
        return

    embed = build_stats_embed(target_user, player_stats)
    await interaction.response.send_message(embed=embed)

@app_commands.command(name="tournament_stats", description="Zeigt allgemeine Turnierstatistiken an.")
async def tournament_stats(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
        return

    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})
    tournament_history = global_data.get("tournament_history", [])

    # Berechnungen
    total_players = len(player_stats)
    total_wins = sum(player.get("wins", 0) for player in player_stats.values())

    best_player_entry = max(player_stats.items(), key=lambda kv: kv[1].get("wins", 0), default=None)
    if best_player_entry:
        best_player = f"{best_player_entry[1]['display_name']} ({best_player_entry[1]['wins']} Siege)"
    else:
        best_player = "Niemand"

    game_counter = Counter(entry["game"] for entry in tournament_history if "game" in entry)
    if game_counter:
        most_played_game, count = game_counter.most_common(1)[0]
        favorite_game = f"{most_played_game} ({count}x)"
    else:
        favorite_game = "Keine Spiele gespielt."

    # Embed verschicken
    await send_tournament_stats_embed(interaction, total_players, total_wins, best_player, favorite_game)

@app_commands.command(name="team_stats", description="Zeigt Statistiken eines bestimmten Teams.")
@app_commands.describe(team="Wähle ein Team aus")
@app_commands.autocomplete(team=autocomplete_teams)
async def team_stats(interaction: Interaction, team: str):
    tournament = load_tournament_data()

    team_data = tournament.get("teams", {}).get(team)
    if not team_data:
        await interaction.response.send_message(f"⚠ Das Team **{team}** existiert nicht.", ephemeral=True)
        return

    wins = team_data.get("wins", 0)
    matches_played = team_data.get("matches_played", 0)

    embed = discord.Embed(
        title=f"📊 Teamstatistik: {team}",
        color=0x1ABC9C
    )
    embed.add_field(name="🏆 Siege", value=wins, inline=True)
    embed.add_field(name="🎯 Gespielte Matches", value=matches_played, inline=True)
    embed.set_footer(text="Turnierauswertung")
    
    await interaction.response.send_message(embed=embed)

@app_commands.command(name="match_history", description="Zeigt die Turnier-Matchhistorie an. Optional für ein bestimmtes Team.")
@app_commands.describe(team="Optional: Filtere nach einem bestimmten Team")
@app_commands.autocomplete(team=autocomplete_teams)
async def match_history(interaction: Interaction, team: str = None):
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    # Filter anwenden, falls Team angegeben
    if team:
        matches = [match for match in matches if match.get("team") == team or match.get("opponent") == team]

    if not matches:
        if team:
            await interaction.response.send_message(f"⚠️ Keine Matches für Team **{team}** gefunden.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ Keine Matches gefunden.", ephemeral=True)
        return

    embed = Embed(
        title="🏛️ Turnier-Match-Historie" if not team else f"🏛️ Matches von {team}",
        description="Hier sind die bisherigen Matches:",
        color=0x7289DA
    )

    for match in matches:
        result = match.get("result", "Unbekannt").upper()
        team_name = match.get("team", "Unbekannt")
        opponent = match.get("opponent", "Unbekannt")
        timestamp = match.get("timestamp", "Keine Zeitangabe")
        outcome_symbol = "✅" if result == "WIN" else "❌"

        embed.add_field(
            name=f"{team_name} vs {opponent}",
            value=f"{outcome_symbol} Ergebnis: **{result}**\n🕑 {timestamp}",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

@app_commands.command(name="status", description="Zeigt den aktuellen Turnierstatus an.")
async def status(interaction: Interaction):
    tournament = load_tournament_data()
    now = datetime.now()

    registration_open = tournament.get("registration_open", False)
    registration_end = tournament.get("registration_end")
    tournament_running = tournament.get("running", False)
    tournament_end = tournament.get("tournament_end")
    poll_results = tournament.get("poll_results", {})
    chosen_game = poll_results.get("chosen_game", "Noch kein Spiel gewählt")
    matches = tournament.get("matches", [])

    # Platzhalter vorbereiten
    registration_text = "Momentan geschlossen."
    if registration_open and registration_end:
        reg_end = datetime.fromisoformat(registration_end)
        registration_text = f"Offen bis {reg_end.strftime('%d.%m.%Y %H:%M')}"

    tournament_text = "Kein aktives Turnier."
    if tournament_running and tournament_end:
        tourn_end = datetime.fromisoformat(tournament_end)
        delta = tourn_end - now
        days = delta.days
        hours = delta.seconds // 3600
        tournament_text = f"Läuft – endet in {days} Tagen, {hours} Stunden"

    placeholders = {
        "PLACEHOLDER_REGISTRATION": registration_text,
        "PLACEHOLDER_TOURNAMENT": tournament_text,
        "PLACEHOLDER_GAME": chosen_game,
        "PLACEHOLDER_MATCHES": str(len(matches))
    }

    await send_status_embed(interaction, placeholders)