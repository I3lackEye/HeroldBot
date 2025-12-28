# modules/info.py

import re
from collections import Counter
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, User, app_commands
from discord.app_commands import Choice
from discord.ext import commands

# Local modules
from modules.config import CONFIG
from modules.dataStorage import load_global_data, load_tournament_data, save_global_data
from modules.embeds import send_status, send_tournament_stats
from modules.logger import logger
from modules.utils import autocomplete_players, autocomplete_teams, has_permission

# ----------------------------------------
# Helper Functions
# ----------------------------------------


def get_leaderboard() -> str:
    """
    Returns a formatted leaderboard based on player wins.
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    if not player_stats:
        return "No statistics available."

    sorted_players = sorted(player_stats.items(), key=lambda item: item[1].get("wins", 0), reverse=True)

    lines = []
    for idx, (user_id, data) in enumerate(sorted_players, start=1):
        name = data.get("name", f"<@{user_id}>")
        wins = data.get("wins", 0)
        lines.append(f"{idx}. {name} – 🏅 {wins} Win{'s' if wins != 1 else ''}")

    leaderboard = "\n".join(lines)
    return leaderboard


def build_stats_embed(user, stats: dict) -> Embed:
    """Builds an embed with player statistics."""
    embed = Embed(title=f"📊 Statistics for {user.display_name}", color=0x3498DB)

    wins = stats.get("wins", 0)
    participations = stats.get("participations", 0)
    winrate = f"{(wins / participations * 100):.1f}%" if participations > 0 else "–"

    # Determine favorite game
    favorite_game = "No favorite game yet"
    game_stats = stats.get("game_stats")
    if game_stats:
        favorite_game = max(game_stats.items(), key=lambda x: x[1])[0]

    embed.add_field(name="🏆 Wins", value=wins, inline=True)
    embed.add_field(name="🧩 Participations", value=participations, inline=True)
    embed.add_field(name="📈 Win Rate", value=winrate, inline=True)
    embed.add_field(name="🎮 Favorite Game", value=favorite_game, inline=False)
    embed.set_footer(text="Tournament Evaluation")

    return embed


def get_tournament_summary() -> str:
    """
    Returns a small summary of all statistics (players, wins, win rate).
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
        best_name = "Nobody"
        best_wins = 0

    output = (
        f"📊 **Tournament Overview**\n\n"
        f"👥 Total players: **{total_players}**\n"
        f"🏆 Total wins awarded: **{total_wins}**\n"
        f"🥇 Best player: {best_name} ({best_wins} wins)\n"
    )

    return output


def update_global_game_stats(game_name: str):
    """
    Updates the global statistics for the most played game.
    :param game_name: The name of the played game (e.g. "Beyond all Reason").
    """
    global_data = load_global_data()

    # Initialize if not yet present
    if "game_stats" not in global_data:
        global_data["game_stats"] = {}

    if game_name not in global_data["game_stats"]:
        global_data["game_stats"][game_name] = 0

    global_data["game_stats"][game_name] += 1

    save_global_data(global_data)
    logger.info(f"Game statistics updated: {game_name} has now been played {global_data['game_stats'][game_name]}x.")


def get_favorite_game() -> str:
    """Returns the most played game."""
    global_data = load_global_data()
    game_stats = global_data.get("game_stats", {})

    if not game_stats:
        return "No games played."

    most_played_game, count = max(game_stats.items(), key=lambda item: item[1])
    return f"{most_played_game} (played {count}x)"


def get_mvp() -> str:
    """
    Determines the MVP (player with most wins) from global statistics.
    Returns the player name or a user mention.
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})

    if not player_stats:
        return None

    # Find player with most wins
    sorted_players = sorted(player_stats.items(), key=lambda item: item[1].get("wins", 0), reverse=True)

    if not sorted_players or sorted_players[0][1].get("wins", 0) == 0:
        return None  # No wins available

    mvp_id, mvp_data = sorted_players[0]
    mvp_name = mvp_data.get("name", f"<@{mvp_id}>")

    return mvp_name


def update_player_stats(winner_ids: list, chosen_game: str):
    """
    Updates player statistics and tournament history.

    :param winner_ids: List of winner user IDs (as strings).
    :param chosen_game: The game that was played.
    """
    global_data = load_global_data()

    # Ensure these sections exist
    if "player_stats" not in global_data:
        global_data["player_stats"] = {}
    if "tournament_history" not in global_data:
        global_data["tournament_history"] = []

    # Update winners
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

    # Add to tournament history
    global_data["tournament_history"].append(
        {
            "game": chosen_game,
            "ended_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )

    save_global_data(global_data)
    logger.info(f"[END] Statistics updated for winners {winner_ids} in game '{chosen_game}'.")


def get_winner_ids() -> list:
    """
    Determines the user IDs of the winners based on current tournament standings.
    Searches for the team with the most wins.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})

    if not teams:
        logger.warning("[GET_WINNER_IDS] No teams found in tournament.")
        return []

    # Find team with most wins
    winning_team = max(teams.values(), key=lambda t: t.get("wins", 0))
    winner_members = winning_team.get("members", [])

    winner_ids = []
    for member in winner_members:
        match = re.search(r"\d+", member)
        if match:
            winner_ids.append(match.group(0))

    logger.info(f"[GET_WINNER_IDS] Winner IDs found: {winner_ids}")
    return winner_ids


def get_winner_team(winner_ids: list) -> Optional[str]:
    """
    Finds the team based on winner player IDs.
    Returns the team name or None if not found.
    """
    tournament = load_tournament_data()
    teams = tournament.get("teams", {})

    for team_name, team_info in teams.items():
        team_members = [str(member_id) for member_id in team_info.get("members", [])]
        if all(winner_id in team_members for winner_id in winner_ids):
            return team_name

    return None


# ----------------------------------------
# Slash Commands
# ----------------------------------------
class InfoGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="info", description="Tournament information and statistics")


    @app_commands.command(
    name="overview",
    description="Shows tournament overview, leaderboard, or match history.",
    )
    @app_commands.describe(view="What do you want to display?")
    @app_commands.choices(view=[
        Choice(name="🏆 Leaderboard", value="leaderboard"),
        Choice(name="📊 Tournament Statistics", value="summary"),
        Choice(name="📜 Match History", value="history"),
    ])
    async def stats_overview(self, interaction: Interaction, view: Choice[str]):
        """Displays tournament overview, leaderboard, or match history."""
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return

        if view.value == "leaderboard":
            # Show leaderboard
            board = get_leaderboard()
            embed = Embed(title="🏆 Leaderboard", description=board, color=0xF1C40F)
            await interaction.response.send_message(embed=embed)

        elif view.value == "summary":
            # Show tournament statistics
            global_data = load_global_data()
            player_stats = global_data.get("player_stats", {})
            tournament_history = global_data.get("tournament_history", [])

            total_players = len(player_stats)
            total_wins = sum(player.get("wins", 0) for player in player_stats.values())

            best_player_entry = max(player_stats.items(), key=lambda kv: kv[1].get("wins", 0), default=None)
            best_player = f"{best_player_entry[1]['display_name']} ({best_player_entry[1]['wins']} wins)" if best_player_entry else "Nobody"

            game_counter = Counter(entry["game"] for entry in tournament_history if "game" in entry)
            favorite_game = f"{game_counter.most_common(1)[0][0]} ({game_counter.most_common(1)[0][1]}x)" if game_counter else "No games played"

            await send_tournament_stats(interaction, total_players, total_wins, best_player, favorite_game)

        elif view.value == "history":
            # Show match history
            tournament = load_tournament_data()
            matches = tournament.get("matches", [])

            if not matches:
                await interaction.response.send_message("⚠️ No matches found.", ephemeral=True)
                return

            embed = Embed(
                title="🏛️ Tournament Match History",
                description="Here are the past matches:",
                color=0x7289DA,
            )

            for match in matches[:25]:  # Discord limit
                result = match.get("result", "Unknown").upper()
                team_name = match.get("team", "Unknown")
                opponent = match.get("opponent", "Unknown")
                timestamp = match.get("timestamp", "No timestamp")
                outcome_symbol = "✅" if result == "WIN" else "❌"

                embed.add_field(
                    name=f"{team_name} vs {opponent}",
                    value=f"{outcome_symbol} Result: **{result}**\n🕑 {timestamp}",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stats", description="Shows your stats or those of a player or team.")
    @app_commands.describe(target="Player (mention or name) or team name")
    async def stats_smart(self, interaction: Interaction, target: Optional[str] = None):
        """Displays statistics for yourself, a player, or a team."""
        global_data = load_global_data()
        tournament = load_tournament_data()

        # 1. No input → own stats
        if not target:
            user_id = str(interaction.user.id)
            stats = global_data.get("player_stats", {}).get(user_id)

            if not stats:
                await interaction.response.send_message("⚠️ You don't have any statistics yet.", ephemeral=True)
                return

            embed = build_stats_embed(interaction.user, stats)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 2. Is it a player? (ID, mention, or display name)
        for user_id, stats in global_data.get("player_stats", {}).items():
            name_match = stats.get("display_name", "").lower()
            mention_match = stats.get("mention", "").replace("<@", "").replace(">", "")

            if (
                target.lower() in name_match
                or target in stats.get("mention", "")
                or target == mention_match
            ):
                # Try to find real member
                member = interaction.guild.get_member(int(user_id))
                fake_user = discord.Object(id=int(user_id)) if not member else member
                embed = build_stats_embed(fake_user, stats)
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # 3. Is it a team name?
        team_data = tournament.get("teams", {}).get(target)
        if team_data:
            wins = team_data.get("wins", 0)
            matches_played = team_data.get("matches_played", 0)

            embed = discord.Embed(title=f"📊 Team Statistics: {target}", color=0x1ABC9C)
            embed.add_field(name="🏆 Wins", value=wins, inline=True)
            embed.add_field(name="🎯 Matches Played", value=matches_played, inline=True)
            embed.set_footer(text="Tournament Evaluation")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 4. Nothing found
        await interaction.response.send_message("❌ No player or team found.", ephemeral=True)


    @app_commands.command(name="tournament", description="Shows the current tournament status.")
    async def status(self, interaction: Interaction):
        """Displays current tournament status."""
        tournament = load_tournament_data()

        # Get timezone from config and use timezone-aware datetime
        tz = ZoneInfo(CONFIG.bot.timezone)
        now = datetime.now(tz=tz)

        registration_open = tournament.get("registration_open", False)
        registration_end = tournament.get("registration_end")
        tournament_running = tournament.get("running", False)
        tournament_end = tournament.get("tournament_end")
        poll_results = tournament.get("poll_results") or {}
        chosen_game = poll_results.get("chosen_game", "No game chosen yet")
        matches = tournament.get("matches", [])

        # Prepare placeholders
        registration_text = "Currently closed."
        if registration_open and registration_end:
            reg_end = datetime.fromisoformat(registration_end)
            # Ensure timezone awareness
            if reg_end.tzinfo is None:
                reg_end = reg_end.replace(tzinfo=tz)
            registration_text = f"Open until {reg_end.strftime('%d.%m.%Y %H:%M')}"

        tournament_text = "No active tournament."
        if tournament_running and tournament_end:
            tourn_end = datetime.fromisoformat(tournament_end)
            # Ensure timezone awareness
            if tourn_end.tzinfo is None:
                tourn_end = tourn_end.replace(tzinfo=tz)
            delta = tourn_end - now
            days = delta.days
            hours = delta.seconds // 3600
            tournament_text = f"Running – ends in {days} days, {hours} hours"

        placeholders = {
            "registration": registration_text,
            "tournament": tournament_text,
            "game": chosen_game,
            "matches": str(len(matches)),
        }

        await send_status(interaction, placeholders)

    @app_commands.command(name="participants", description="Show list of all participants.")
    async def participants(self, interaction: Interaction):
        """
        Lists all current participants (teams and solo players), sorted alphabetically.
        """
        tournament = load_tournament_data()

        teams = tournament.get("teams", {})
        solo = tournament.get("solo", [])

        # Sort teams alphabetically
        sorted_teams = sorted(teams.items(), key=lambda x: x[0].lower())

        # Sort solo players alphabetically (by mention)
        sorted_solo = sorted(solo, key=lambda x: x.get("player", "").lower())

        team_lines = []
        for name, team_entry in sorted_teams:
            members = ", ".join(team_entry.get("members", []))
            avail = team_entry.get("availability", {})
            saturday = avail.get("saturday", "-")
            sunday = avail.get("sunday", "-")
            team_lines.append(f"**{name}**\n  Players: {members}\n  Sat: {saturday} | Sun: {sunday}\n")

        solo_lines = []
        for solo_entry in sorted_solo:
            solo_lines.append(f"• {solo_entry.get('player')}")

        # Compose embed
        embed = discord.Embed(
            title="👥 Tournament Participants",
            color=0x3498DB
        )

        if team_lines:
            teams_text = "\n".join(team_lines)
            # Discord embed field limit is 1024 characters
            if len(teams_text) > 1024:
                teams_text = teams_text[:1020] + "..."
            embed.add_field(name=f"🏆 Teams ({len(teams)})", value=teams_text, inline=False)

        if solo_lines:
            solo_text = "\n".join(solo_lines)
            if len(solo_text) > 1024:
                solo_text = solo_text[:1020] + "..."
            embed.add_field(name=f"🙋 Solo Players ({len(solo)})", value=solo_text, inline=False)

        if not team_lines and not solo_lines:
            embed.description = "❌ No participants registered yet."

        await interaction.response.send_message(embed=embed, ephemeral=False)


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(InfoGroup())


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
