# modules/stats.py

import re
from collections import Counter
from datetime import datetime
from typing import Optional

import discord
from discord import Embed, Interaction, User, app_commands
from discord.app_commands import Choice
from discord.ext import commands

# Lokale Module
from modules.dataStorage import load_global_data, load_tournament_data, save_global_data
from modules.embeds import send_status, send_tournament_stats
from modules.logger import logger
from modules.utils import autocomplete_players, autocomplete_teams, has_permission

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
    embed = Embed(title=f"📊 Statistiken für {user.display_name}", color=0x3498DB)

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


def get_mvp() -> str:
    """
    Ermittelt den MVP (Spieler mit den meisten Siegen) aus den globalen Statistiken.
    Gibt den Spielernamen oder eine Usermention zurück.
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    if not player_stats:
        return None

    # Spieler mit meisten Siegen finden
    sorted_players = sorted(player_stats.items(), key=lambda item: item[1].get("wins", 0), reverse=True)

    if not sorted_players or sorted_players[0][1].get("wins", 0) == 0:
        return None  # Keine Siege vorhanden

    mvp_id, mvp_data = sorted_players[0]
    mvp_name = mvp_data.get("name", f"<@{mvp_id}>")

    return mvp_name


def update_player_stats(winner_ids: list, chosen_game: str):
    """
    Aktualisiert die Spielerstatistiken und die Turnier-Historie.

    :param winner_ids: Liste von Gewinner-UserIDs (als Strings).
    :param chosen_game: Das Spiel, das gespielt wurde.
    """
    global_data = load_global_data()

    # Sicherstellen, dass diese Bereiche existieren
    if "player_stats" not in global_data:
        global_data["player_stats"] = {}
    if "tournament_history" not in global_data:
        global_data["tournament_history"] = []

    # Gewinner aktualisieren
    for user_id in winner_ids:
        player = global_data["player_stats"].setdefault(
            str(user_id),
            {
                "wins": 0,
                "participations": 0,
                "mention": f"<@{user_id}>",
                "display_name": f"User {user_id}",
                "game_stats": {},
            },
        )

        player["wins"] += 1
        player["participations"] += 1
        player["game_stats"][chosen_game] = player["game_stats"].get(chosen_game, 0) + 1

    # Turnier-Historie ergänzen
    global_data["tournament_history"].append(
        {
            "game": chosen_game,
            "ended_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )

    save_global_data(global_data)
    logger.info(f"[END] Statistiken aktualisiert für Gewinner {winner_ids} im Spiel '{chosen_game}'.")


def get_winner_ids() -> list:
    """
    Bestimmt die User-IDs der Gewinner basierend auf dem aktuellen Turnierstand.
    Sucht nach dem Team mit den meisten Siegen.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})

    if not teams:
        logger.warning("[GET_WINNER_IDS] Keine Teams im Turnier gefunden.")
        return []

    # Team mit den meisten Siegen finden
    winning_team = max(teams.values(), key=lambda t: t.get("wins", 0))
    winner_members = winning_team.get("members", [])

    winner_ids = []
    for member in winner_members:
        match = re.search(r"\d+", member)
        if match:
            winner_ids.append(match.group(0))

    logger.info(f"[GET_WINNER_IDS] Gewinner-IDs gefunden: {winner_ids}")
    return winner_ids


def get_winner_team(winner_ids: list) -> Optional[str]:
    """
    Findet das Team basierend auf der Gewinner-Spieler-IDs.
    Gibt den Teamnamen zurück oder None, wenn nicht gefunden.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})

    for team_name, team_info in teams.items():
        team_members = [str(member_id) for member_id in team_info.get("members", [])]
        if all(winner_id in team_members for winner_id in winner_ids):
            return team_name

    return None


# ----------------------------------------
# Slash-Commands
# ----------------------------------------
class StatsGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="stats", description="Statistiken und Auswertungen")


    @app_commands.command(
    name="overview",
    description="Zeigt eine Turnierübersicht, Bestenliste oder Matchhistorie.",
    )
    @app_commands.describe(view="Was möchtest du anzeigen?")
    @app_commands.choices(view=[
        Choice(name="🏆 Bestenliste", value="leaderboard"),
        Choice(name="📊 Turnierstatistik", value="summary"),
        Choice(name="📜 Match-Historie", value="history"),
    ])
    async def stats_overview(self, interaction: Interaction, view: Choice[str]):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        if view.value == "leaderboard":
            # Zeige Bestenliste
            board = get_leaderboard()
            embed = Embed(title="🏆 Bestenliste", description=board, color=0xF1C40F)
            await interaction.response.send_message(embed=embed)

        elif view.value == "summary":
            # Zeige Turnierstatistik
            global_data = load_global_data()
            player_stats = global_data.get("player_stats", {})
            tournament_history = global_data.get("tournament_history", [])

            total_players = len(player_stats)
            total_wins = sum(player.get("wins", 0) for player in player_stats.values())

            best_player_entry = max(player_stats.items(), key=lambda kv: kv[1].get("wins", 0), default=None)
            best_player = f"{best_player_entry[1]['display_name']} ({best_player_entry[1]['wins']} Siege)" if best_player_entry else "Niemand"

            game_counter = Counter(entry["game"] for entry in tournament_history if "game" in entry)
            favorite_game = f"{game_counter.most_common(1)[0][0]} ({game_counter.most_common(1)[0][1]}x)" if game_counter else "Keine Spiele gespielt"

            await send_tournament_stats(interaction, total_players, total_wins, best_player, favorite_game)

        elif view.value == "history":
            # Zeige Match-Historie
            tournament = load_tournament_data()
            matches = tournament.get("matches", [])

            if not matches:
                await interaction.response.send_message("⚠️ Keine Matches gefunden.", ephemeral=True)
                return

            embed = Embed(
                title="🏛️ Turnier-Match-Historie",
                description="Hier sind die bisherigen Matches:",
                color=0x7289DA,
            )

            for match in matches[:25]:  # Discord Limit
                result = match.get("result", "Unbekannt").upper()
                team_name = match.get("team", "Unbekannt")
                opponent = match.get("opponent", "Unbekannt")
                timestamp = match.get("timestamp", "Keine Zeitangabe")
                outcome_symbol = "✅" if result == "WIN" else "❌"

                embed.add_field(
                    name=f"{team_name} vs {opponent}",
                    value=f"{outcome_symbol} Ergebnis: **{result}**\n🕑 {timestamp}",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

    """@app_commands.command(name="team_stats", description="Zeigt Statistiken eines bestimmten Teams.")
    @app_commands.describe(team="Wähle ein Team aus")
    @app_commands.autocomplete(team=autocomplete_teams)
    async def team_stats(self, interaction: Interaction, team: str):
        tournament = load_tournament_data()

        team_data = tournament.get("teams", {}).get(team)
        if not team_data:
            await interaction.response.send_message(f"⚠ Das Team **{team}** existiert nicht.", ephemeral=True)
            return

        wins = team_data.get("wins", 0)
        matches_played = team_data.get("matches_played", 0)

        embed = discord.Embed(title=f"📊 Teamstatistik: {team}", color=0x1ABC9C)
        embed.add_field(name="🏆 Siege", value=wins, inline=True)
        embed.add_field(name="🎯 Gespielte Matches", value=matches_played, inline=True)
        embed.set_footer(text="Turnierauswertung")

        await interaction.response.send_message(embed=embed)"""
    @app_commands.command(name="stats", description="Zeigt deine oder die Stats eines Spielers oder Teams.")
    @app_commands.describe(target="Spieler (Mention oder Name) oder Teamname")
    async def stats_smart(self, interaction: Interaction, target: Optional[str] = None):
        global_data = load_global_data()
        tournament = load_tournament_data()

        # 1. Keine Eingabe → eigene Stats
        if not target:
            user_id = str(interaction.user.id)
            stats = global_data.get("player_stats", {}).get(user_id)

            if not stats:
                await interaction.response.send_message("⚠️ Du hast noch keine Statistiken.", ephemeral=True)
                return

            embed = build_stats_embed(interaction.user, stats)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 2. Ist es ein Spieler? (ID, Mention oder Displayname)
        for user_id, stats in global_data.get("player_stats", {}).items():
            name_match = stats.get("display_name", "").lower()
            mention_match = stats.get("mention", "").replace("<@", "").replace(">", "")

            if (
                target.lower() in name_match
                or target in stats.get("mention", "")
                or target == mention_match
            ):
                # Versuche echten Member zu finden
                member = interaction.guild.get_member(int(user_id))
                fake_user = discord.Object(id=int(user_id)) if not member else member
                embed = build_stats_embed(fake_user, stats)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # 3. Ist es ein Teamname?
        team_data = tournament.get("teams", {}).get(target)
        if team_data:
            wins = team_data.get("wins", 0)
            matches_played = team_data.get("matches_played", 0)

            embed = discord.Embed(title=f"📊 Teamstatistik: {target}", color=0x1ABC9C)
            embed.add_field(name="🏆 Siege", value=wins, inline=True)
            embed.add_field(name="🎯 Gespielte Matches", value=matches_played, inline=True)
            embed.set_footer(text="Turnierauswertung")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 4. Nichts gefunden
        await interaction.response.send_message("❌ Kein Spieler oder Team gefunden.", ephemeral=True)


    @app_commands.command(name="tournament", description="Zeigt den aktuellen Turnierstatus an.")
    async def status(self, interaction: Interaction):
        tournament = load_tournament_data()
        now = datetime.now()

        registration_open = tournament.get("registration_open", False)
        registration_end = tournament.get("registration_end")
        tournament_running = tournament.get("running", False)
        tournament_end = tournament.get("tournament_end")
        poll_results = tournament.get("poll_results") or {}
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
            "registration": registration_text,
            "tournament": tournament_text,
            "game": chosen_game,
            "matches": str(len(matches)),
        }

        await send_status(interaction, placeholders)


class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(StatsGroup())


async def setup(bot):
    await bot.add_cog(StatsCog(bot))
