# scripts/embeds.py

import discord
from discord import Embed, Interaction, TextChannel


from .utils import load_config, smart_send

def create_embed_from_config(key: str, placeholders: dict = None) -> Embed:
    """
    Erzeugt ein Discord-Embed basierend auf einem Template in config.json.
    
    :param key: Der Schlüssel unter dem das Embed gespeichert ist (z.B. "TOURNAMENT_ANNOUNCEMENT")
    :param placeholders: Platzhalter im Text, die ersetzt werden sollen {PLACEHOLDER_NAME: "Wert"}
    :return: Discord Embed Objekt
    """
    config = load_config()
    embed_data = config.get("EMBEDS", {}).get(key, {})

    description = embed_data.get("description", "")

    # Platzhalter in der Beschreibung ersetzen
    if placeholders:
        for placeholder, replacement in placeholders.items():
            description = description.replace(placeholder, replacement)

    embed = Embed(
        title=embed_data.get("title", "Kein Titel angegeben"),
        description=description,
        color=0x3498DB
    )

    for field in embed_data.get("fields", []):
        name = field.get("name", "")
        value = field.get("value", "")

        if placeholders:
            for placeholder, replacement in placeholders.items():
                value = value.replace(placeholder, replacement)

        embed.add_field(name=name, value=value, inline=False)

    if footer := embed_data.get("footer"):
        embed.set_footer(text=footer)

    return embed

# ------------------------------
# 🔥 Utility Funktionen
# ------------------------------

async def send_tournament_announcement(channel: TextChannel, placeholders: dict):
    embed = create_embed_from_config("TOURNAMENT_ANNOUNCEMENT", placeholders)
    await channel.send(embed=embed)

async def send_tournament_ended(channel: TextChannel, placeholders: dict):
    embed = create_embed_from_config("TOURNAMENT_ENDED_ANNOUNCEMENT", placeholders)
    await channel.send(embed=embed)

async def send_poll_results(channel: TextChannel, placeholders: dict):
    embed = create_embed_from_config("POLL_RESULT_EMBED", placeholders)
    await channel.send(embed=embed)

async def send_registration_open(channel: TextChannel, placeholders: dict):
    embed = create_embed_from_config("REGISTRATION_OPEN_ANNOUNCEMENT", placeholders)
    await channel.send(embed=embed)

async def send_global_stats_embed(interaction: Interaction, description_text: str):
    embed = create_embed_from_config("GLOBAL_STATS_EMBED")
    embed.description = description_text
    await interaction.response.send_message(embed=embed)

async def send_registration_closed(channel: discord.TextChannel):
    embed = create_embed_from_config("REGISTRATION_CLOSED_ANNOUNCEMENT")
    await channel.send(embed=embed)

async def send_tournament_stats_embed(interaction: Interaction, total_players: int, total_wins: int, best_player: str, favorite_game: str):
    placeholders = {
        "PLACEHOLDER_TOTAL_PLAYERS": str(total_players),
        "PLACEHOLDER_TOTAL_WINS": str(total_wins),
        "PLACEHOLDER_BEST_PLAYER": best_player,
        "PLACEHOLDER_FAVORITE_GAME": favorite_game
    }
    embed = create_embed_from_config("TOURNAMENT_STATS_EMBED", placeholders)
    await interaction.response.send_message(embed=embed)

async def send_help_embed(interaction: Interaction):
    """
    Sendet das Hilfe-Embed an den User.
    """
    embed = create_embed_from_config("HELP_EMBED")
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def send_status_embed(interaction: Interaction, placeholders: dict):
    embed = create_embed_from_config("STATUS_EMBED", placeholders)
    await interaction.response.send_message(embed=embed)

async def send_list_matches_embed(interaction: Interaction, matches: list):
    """
    Schickt eine Übersicht der geplanten Matches als Embed.
    """
    embed = create_embed_from_config("LIST_MATCHES_EMBED")
    
    if not matches:
        embed.description = "⚠️ Es wurden noch keine Matches geplant."
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    for match in matches:
        team1 = match.get("team1", "Unbekannt")
        team2 = match.get("team2", "Unbekannt")
        scheduled_time = match.get("scheduled_time", "Noch nicht geplant")
        status = match.get("status", "offen")

        if scheduled_time and scheduled_time != "Noch nicht geplant":
            try:
                scheduled_time = datetime.fromisoformat(scheduled_time).strftime("%d.%m.%Y %H:%M")
            except Exception:
                scheduled_time = "Ungültige Zeit"

        embed.add_field(
            name=f"{team1} vs {team2}",
            value=f"🕒 Geplant: {scheduled_time}\n📋 Status: {status.capitalize()}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

async def send_match_schedule_embed(interaction: Interaction, description_text: str):
    embed_template = create_embed_from_config("MATCH_SCHEDULE_EMBED")

    if len(description_text) <= 4096:
        embed_template.description = description_text
        await smart_send(interaction, embed=embed_template)
    else:
        # Text aufteilen in 4096-Blöcke
        chunks = [description_text[i:i+4096] for i in range(0, len(description_text), 4096)]

        for idx, chunk in enumerate(chunks):
            embed = create_embed_from_config("MATCH_SCHEDULE_EMBED")
            embed.description = chunk
            if idx == 0:
                await smart_send(interaction, embed=embed)  # erstes Mal
            else:
                await interaction.channel.send(embed=embed)  # danach normal in den Channel posten

async def send_cleanup_summary(channel: discord.TextChannel, teams_deleted: list, players_rescued: list):
    embed = create_embed_from_config("CLEANUP_SUMMARY_EMBED")

    desc = ""
    if teams_deleted:
        desc += "**🗑️ Gelöschte Teams:**\n" + "\n".join(f"• {team}" for team in teams_deleted) + "\n\n"
    if players_rescued:
        desc += "**👤 Gerettete Spieler:**\n" + "\n".join(f"• {player}" for player in players_rescued)

    if not desc:
        desc = "Keine unvollständigen Teams gefunden."

    embed.description = desc
    await channel.send(embed=embed)
