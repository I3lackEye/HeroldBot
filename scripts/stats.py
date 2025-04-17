#stats.py

import discord
from discord import app_commands, Interaction, Embed
from .dataStorage import load_global_data
from .utils import has_permission
from .logger import setup_logger

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

def build_stats_embed(user: discord.Member, stats: dict) -> Embed:
    """
    Baut ein schönes Embed für die persönlichen Stats eines Spielers.
    """
    wins = stats.get("wins", 0)
    participations = stats.get("participations", 0)
    favorite_game = stats.get("favorite_game", "Unbekannt")

    winrate = f"{(wins / participations * 100):.1f} %" if participations > 0 else "–"

    embed = Embed(
        title=f"📊 Statistiken für {user.display_name}",
        color=0x3498DB
    )
    embed.add_field(name="🏆 Siege", value=wins, inline=True)
    embed.add_field(name="🧩 Teilnahmen", value=participations, inline=True)
    embed.add_field(name="📈 Winrate", value=winrate, inline=True)
    embed.add_field(name="🎮 Lieblingsspiel", value=favorite_game, inline=True)
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

@app_commands.command(name="stats", description="Zeigt deine persönlichen Turnierstatistiken an.")
async def stats(interaction: Interaction):
    global_data = load_global_data()
    user_id = str(interaction.user.id)
    player_stats = global_data.get("player_stats", {}).get(user_id)

    if not player_stats:
        await interaction.response.send_message("⚠ Du hast noch keine Statistiken.", ephemeral=True)
        return

    embed = build_stats_embed(interaction.user, player_stats)
    await interaction.response.send_message(embed=embed)

@app_commands.command(name="tournament_stats", description="Zeigt allgemeine Turnierstatistiken an.")
async def tournament_stats(interaction: Interaction):
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
        return

    summary = get_tournament_summary()
    embed = Embed(
        title="📋 Turnierstatistiken",
        description=summary,
        color=0x2ECC71
    )
    await interaction.response.send_message(embed=embed)