# modules/dev_tools.py

import asyncio
import random
import discord
from datetime import datetime, timedelta
from discord import Interaction, app_commands
from discord.ext import commands


# Import helper modules
from modules import poll
from modules.config import CONFIG
from modules.dataStorage import (
    load_games,
    load_tournament_data,
    save_tournament_data,
    DEBUG_MODE
)
from modules.embeds import build_embed_from_template, load_embed_template
from modules.logger import logger
from modules.task_manager import get_all_tasks
from modules.tournament import auto_end_poll, close_registration_after_delay
from modules.utils import (
    generate_random_availability,
    generate_team_name,
    has_permission,
    smart_send,
)


class DevGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(name="dev", description="Developer commands")
        self.bot = bot

    @app_commands.command(
        name="generate_dummy",
        description="Generates dummy data for testing with preset scenarios.",
    )
    @app_commands.describe(
        scenario="Testing scenario: easy, hard, blocked, mixed, realistic, or custom",
        num_teams="Number of teams (for custom scenario)",
        num_solo="Number of solo players (for custom scenario)"
    )
    @app_commands.choices(scenario=[
        app_commands.Choice(name="Easy - All overlapping availability", value="easy"),
        app_commands.Choice(name="Hard - Minimal overlap", value="hard"),
        app_commands.Choice(name="Blocked - Many unavailable dates", value="blocked"),
        app_commands.Choice(name="Mixed - Variable team sizes", value="mixed"),
        app_commands.Choice(name="Realistic - Random realistic data", value="realistic"),
        app_commands.Choice(name="Custom - Specify numbers", value="custom"),
    ])
    async def generate_dummy_teams(
        self,
        interaction: Interaction,
        scenario: str = "realistic",
        num_teams: int = 6,
        num_solo: int = 2
    ):
        """Generates dummy data for testing purposes with various scenarios."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        tournament = load_tournament_data()

        # Scenario configurations
        if scenario == "easy":
            # All teams have full overlapping availability - should find slots easily
            num_teams, num_solo = 8, 4
            fixed_availability = {
                "saturday": "10:00-22:00",
                "sunday": "10:00-22:00"
            }
            blocked_dates = []
            msg = "✅ Generated **easy scenario**: 8 teams + 4 solo, all with full availability overlap"

        elif scenario == "hard":
            # Minimal overlap - tests edge cases
            num_teams, num_solo = 6, 2
            fixed_availability = None  # Will use narrow random ranges
            blocked_dates = []
            msg = "✅ Generated **hard scenario**: 6 teams + 2 solo with minimal time overlap"

        elif scenario == "blocked":
            # Many unavailable dates - tests conflict resolution
            num_teams, num_solo = 6, 3
            fixed_availability = {
                "saturday": "12:00-20:00",
                "sunday": "12:00-20:00"
            }
            # Will add many blocked dates
            blocked_dates = self._generate_blocked_dates(num_dates=5)
            msg = f"✅ Generated **blocked scenario**: 6 teams + 3 solo with {len(blocked_dates)} blocked dates each"

        elif scenario == "mixed":
            # Variable team sizes (1v1, 2v2, 3v3)
            num_teams, num_solo = 9, 0  # 3 of each size
            fixed_availability = {
                "saturday": "14:00-22:00",
                "sunday": "10:00-20:00"
            }
            blocked_dates = []
            msg = "✅ Generated **mixed scenario**: Teams with sizes 1, 2, and 3 players"

        elif scenario == "realistic":
            # Random but realistic patterns
            num_teams, num_solo = 6, 3
            fixed_availability = None
            blocked_dates = []
            msg = "✅ Generated **realistic scenario**: 6 teams + 3 solo with random realistic availability"

        else:  # custom
            fixed_availability = None
            blocked_dates = []
            msg = f"✅ Generated **custom scenario**: {num_teams} teams + {num_solo} solo players"

        # Generate solo players
        solo_players = []
        for i in range(num_solo):
            player_name = f"<@{222220000000000 + i*2}>"

            if fixed_availability:
                availability = fixed_availability.copy()
            elif scenario == "hard":
                # Narrow time windows
                start_hour = random.randint(10, 16)
                availability = {
                    "saturday": f"{start_hour:02d}:00-{start_hour+3:02d}:00",
                    "sunday": f"{start_hour:02d}:00-{start_hour+3:02d}:00"
                }
            else:
                availability = generate_random_availability()

            player_entry = {
                "player": player_name,
                "availability": availability,
                "unavailable_dates": blocked_dates.copy() if blocked_dates else []
            }
            solo_players.append(player_entry)

        tournament.setdefault("solo", []).extend(solo_players)

        # Generate teams
        teams = tournament.setdefault("teams", {})

        if scenario == "mixed":
            # Create teams of different sizes
            team_sizes = [1, 1, 1, 2, 2, 2, 3, 3, 3]
            for i, size in enumerate(team_sizes):
                team_name = generate_team_name()
                members = [f"<@{1111110000000000 + i*10 + j}>" for j in range(size)]

                team_entry = {
                    "members": members,
                    "availability": fixed_availability.copy(),
                    "unavailable_dates": []
                }
                teams[team_name] = team_entry
        else:
            # Regular 2-player teams
            for i in range(num_teams):
                team_name = generate_team_name()
                member1 = f"<@{1111110000000000 + i*2}>"
                member2 = f"<@{1111110000000001 + i*2}>"

                if fixed_availability:
                    availability = fixed_availability.copy()
                elif scenario == "hard":
                    # Each team gets slightly different narrow windows
                    start_hour = random.randint(12, 17)
                    availability = {
                        "saturday": f"{start_hour:02d}:00-{start_hour+4:02d}:00",
                        "sunday": f"{start_hour:02d}:00-{start_hour+4:02d}:00"
                    }
                else:
                    availability = generate_random_availability()

                team_entry = {
                    "members": [member1, member2],
                    "availability": availability,
                    "unavailable_dates": blocked_dates.copy() if blocked_dates else []
                }
                teams[team_name] = team_entry

        save_tournament_data(tournament)

        logger.info(f"[DUMMY] Scenario '{scenario}': {num_solo} solo + {num_teams} teams created")
        await interaction.response.send_message(msg, ephemeral=True)

    def _generate_blocked_dates(self, num_dates: int = 5) -> list:
        """Generate realistic blocked dates for testing."""
        from datetime import datetime, timedelta
        blocked = []
        base_date = datetime.now()

        for i in range(num_dates):
            # Random date in next 4 weeks
            days_ahead = random.randint(0, 28)
            date = base_date + timedelta(days=days_ahead)
            blocked.append(date.strftime("%Y-%m-%d"))

        return blocked

    @app_commands.command(
        name="test_reminder",
        description="Tests a reminder embed with a random match.",
    )
    async def test_reminder(self, interaction: Interaction):
        """Sends a test reminder embed."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this command.", ephemeral=True)
            return

        reminder_channel_id = CONFIG.get_channel_id("reminder")

        guild = interaction.guild
        if not guild:
            await smart_send(
                interaction,
                content="🚫 This command can only be used on a server.",
                ephemeral=True,
            )
            return

        channel = guild.get_channel(reminder_channel_id)
        if not channel:
            await smart_send(
                interaction,
                content="🚫 Reminder channel not found! Please check the config.",
                ephemeral=True,
            )
            return

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        teams = tournament.get("teams", {})

        if not matches:
            await smart_send(
                interaction,
                content="🚫 No matches available. Reminder test not possible.",
                ephemeral=True,
            )
            return

        # Choose random match
        match = random.choice(matches)

        # Collect team members (already stored in mention format)
        team1_members = teams.get(match.get("team1", ""), {}).get("members", [])
        team2_members = teams.get(match.get("team2", ""), {}).get("members", [])
        all_mentions = " ".join(team1_members + team2_members)

        # Set placeholders
        placeholders = {
            "match_id": match.get("match_id", "???"),
            "team1": match.get("team1", "Team 1"),
            "team2": match.get("team2", "Team 2"),
            "time": match.get("scheduled_time", "No appointment").replace("T", " ")[:16],
            "mentions": all_mentions,
        }

        # Load template
        template = load_embed_template("reminder").get("REMINDER")
        if not template:
            logger.error("[EMBED] REMINDER template missing.")
            await smart_send(interaction, content="🚫 Reminder template missing.", ephemeral=True)
            return

        # Build and send embed
        embed = build_embed_from_template(template, placeholders)
        await channel.send(embed=embed)
        await smart_send(
            interaction,
            content=f"✅ Reminder test with match ID {placeholders['match_id']} successfully sent.",
            ephemeral=True,
        )

        logger.info(
            f"[TEST] Reminder embed for match {placeholders['match_id']} ({placeholders['team1']} vs {placeholders['team2']}) sent to channel #{channel.name}."
        )

    @app_commands.command(
        name="simulate_poll_end",
        description="Simulates automatic poll end after a short time (testing purposes).",
    )
    async def simulate_poll_end(self, interaction: Interaction):
        """Simulates poll ending for testing."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Simulating poll end in 10 seconds...", ephemeral=True)

        from modules.tournament import auto_end_poll

        # Pass current channel + client
        asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, delay_seconds=10))

    @app_commands.command(
        name="simulate_registration_close",
        description="Simulates automatic registration closure in 10 seconds.",
    )
    async def simulate_registration_close(self, interaction: Interaction):
        """Simulates registration closing for testing."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⏳ Registration will automatically close in 10 seconds (test run)...",
            ephemeral=True,
        )

        from modules.tournament import close_registration_after_delay

        asyncio.create_task(close_registration_after_delay(delay_seconds=10, channel=interaction.channel))

    @app_commands.command(
        name="simulate_full_flow",
        description="Starts a test tournament with dummies, poll, and automatic flow.",
    )
    async def simulate_full_flow(self, interaction: Interaction):
        """Runs a complete tournament simulation."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "🎬 Starting complete test run: Poll ➝ Registration ➝ Match plan.",
            ephemeral=True,
        )

        # Load dummy poll options
        poll_options = load_games()
        if not poll_options:
            await interaction.followup.send(
                "⚠️ No games found! Please fill `games.json` first.",
                ephemeral=True,
            )
            return

        # Prepare tournament data
        now = datetime.utcnow()

        # Tournament period: Start now, end after two full weekends starting next Saturday
        next_saturday = now + timedelta((5 - now.weekday()) % 7)
        tournament_end = next_saturday + timedelta(days=8)  # Sat + Sun + Sat + Sun

        tournament_data = {
            "registration_open": False,
            "running": True,
            "solo": [],
            "registration_end": (now + timedelta(seconds=20)).isoformat(),
            "tournament_end": tournament_end.isoformat(),
            "matches": [],
            "poll_results": {},
        }

        # Optional: Add solo players
        solo_players = []
        for i in range(4):
            player_name = f"<@{222220000000000 + i}>"
            availability = generate_random_availability()
            solo_players.append({"player": player_name, "availability": availability})

        tournament_data["solo"] = solo_players

        # Add dummy players and teams
        teams = {}
        for i in range(6):  # Six dummy teams
            team_name = generate_team_name()
            member1 = f"<@{1111110000000000 + i*2}>"  # Dummy mentions
            member2 = f"<@{1111110000000001 + i*2}>"
            availability = generate_random_availability()

            team_entry = {"members": [member1, member2], "availability": availability}
            teams[team_name] = team_entry

        tournament_data["teams"] = teams
        save_tournament_data(tournament_data)

        # Start poll
        await interaction.channel.send("🗳️ **Test poll is starting...**")
        await poll.start_poll(
            interaction.channel,
            poll_options,
            registration_hours=20,
            poll_duration_hours=10,
        )

        # Simulate poll end
        asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, delay_seconds=10))

        # Simulate registration close
        asyncio.create_task(close_registration_after_delay(delay_seconds=20, channel=interaction.channel))

    @app_commands.command(
        name="reset_tournament",
        description="Clears all tournament data (teams, solo, matches).",
    )
    async def reset_tournament(self, interaction: Interaction):
        """Resets tournament to clean state."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        from modules.dataStorage import DEFAULT_TOURNAMENT_DATA

        # Reset to default state
        save_tournament_data(DEFAULT_TOURNAMENT_DATA.copy())

        logger.info("[DEV] Tournament data reset by developer")
        await interaction.response.send_message(
            "✅ Tournament data has been reset!\n"
            "All teams, solo players, and matches have been cleared.",
            ephemeral=True
        )

    @app_commands.command(
        name="show_state",
        description="Shows current tournament state (teams, availability, matches).",
    )
    async def show_state(self, interaction: Interaction):
        """Displays current tournament state for debugging."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})
        solo = tournament.get("solo", [])
        matches = tournament.get("matches", [])

        embed = discord.Embed(
            title="🔍 Tournament State",
            color=0x3498db,
            description=f"**Status:** {'🟢 Running' if tournament.get('running') else '🔴 Inactive'}"
        )

        # Teams info
        if teams:
            team_info = []
            for team_name, team_data in list(teams.items())[:5]:
                members = team_data.get("members", [])
                avail = team_data.get("availability", {})
                sat = avail.get("saturday", "N/A")
                sun = avail.get("sunday", "N/A")
                blocked = len(team_data.get("unavailable_dates", []))
                team_info.append(
                    f"**{team_name}** ({len(members)} players)\n"
                    f"  Sat: {sat} | Sun: {sun} | Blocked: {blocked}"
                )

            if len(teams) > 5:
                team_info.append(f"\n... and {len(teams)-5} more teams")

            embed.add_field(
                name=f"👥 Teams ({len(teams)})",
                value="\n".join(team_info) if team_info else "None",
                inline=False
            )
        else:
            embed.add_field(name="👥 Teams", value="No teams registered", inline=False)

        # Solo info
        if solo:
            solo_info = []
            for entry in solo[:3]:
                player = entry.get("player", "Unknown")
                avail = entry.get("availability", {})
                sat = avail.get("saturday", "N/A")
                sun = avail.get("sunday", "N/A")
                solo_info.append(f"{player}: Sat {sat}, Sun {sun}")

            if len(solo) > 3:
                solo_info.append(f"... and {len(solo)-3} more")

            embed.add_field(
                name=f"🙋 Solo Players ({len(solo)})",
                value="\n".join(solo_info),
                inline=False
            )
        else:
            embed.add_field(name="🙋 Solo Players", value="No solo players", inline=False)

        # Matches info
        if matches:
            match_info = []
            for match in matches[:5]:
                team1 = match.get("team1", "?")
                team2 = match.get("team2", "?")
                time = match.get("scheduled_time", "Not scheduled")
                match_info.append(f"**{team1}** vs **{team2}**\n  {time}")

            if len(matches) > 5:
                match_info.append(f"\n... and {len(matches)-5} more matches")

            embed.add_field(
                name=f"📅 Matches ({len(matches)})",
                value="\n".join(match_info),
                inline=False
            )
        else:
            embed.add_field(name="📅 Matches", value="No matches scheduled", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="test_matchmaker",
        description="Tests the matchmaker algorithm without actually scheduling matches.",
    )
    async def test_matchmaker(self, interaction: Interaction):
        """Runs matchmaker in test mode to see what it would generate."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})
        solo = tournament.get("solo", [])

        if not teams and not solo:
            await interaction.followup.send(
                "❌ No teams or solo players found. Use `/dev generate_dummy` first!",
                ephemeral=True
            )
            return

        try:
            from modules.matchmaker import create_round_robin_schedule, pair_solo_players

            # Pair solo players first
            if solo:
                pair_solo_players(tournament)
                teams = tournament.get("teams", {})

            # Get tournament end date
            from datetime import datetime, timedelta
            tournament_end = tournament.get("tournament_end")
            if tournament_end:
                end_date = datetime.fromisoformat(tournament_end)
            else:
                # Default: 2 weeks from now
                end_date = datetime.now() + timedelta(weeks=2)

            # Try to create schedule
            all_teams = list(teams.keys())
            matchups = create_round_robin_schedule(all_teams)

            # Report results
            result = [
                f"**Matchmaker Test Results**",
                f"",
                f"📊 **Input:**",
                f"  • Teams: {len(all_teams)}",
                f"  • Total matchups needed: {len(matchups)}",
                f"  • Tournament end: {end_date.strftime('%Y-%m-%d')}",
                f"",
                f"🎯 **Round-Robin Pairings:**"
            ]

            for i, (team1, team2) in enumerate(matchups[:10], 1):
                result.append(f"  {i}. {team1} vs {team2}")

            if len(matchups) > 10:
                result.append(f"  ... and {len(matchups)-10} more matchups")

            result.append(f"\n✅ Matchmaker test completed successfully!")
            result.append(f"\n**Note:** No actual matches were scheduled. Use `/dev generate_matches` to schedule for real.")

            await interaction.followup.send("\n".join(result), ephemeral=True)

        except Exception as e:
            logger.error(f"[DEV] Matchmaker test failed: {e}")
            await interaction.followup.send(
                f"❌ Matchmaker test failed:\n```{str(e)}```",
                ephemeral=True
            )

    @app_commands.command(
        name="generate_matches",
        description="Forces match generation with current tournament data.",
    )
    async def generate_matches(self, interaction: Interaction):
        """Generates and schedules matches for the current tournament."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You don't have permission for this.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        if not teams:
            await interaction.followup.send(
                "❌ No teams found. Generate dummy data first with `/dev generate_dummy`!",
                ephemeral=True
            )
            return

        try:
            from modules.matchmaker import generate_matches as run_matchmaker

            # Set tournament as running if not already
            if not tournament.get("running"):
                tournament["running"] = True
                save_tournament_data(tournament)

            # Run matchmaker
            matches = run_matchmaker(tournament)

            if matches:
                await interaction.followup.send(
                    f"✅ Successfully generated **{len(matches)} matches**!\n"
                    f"Use `/dev show_state` to see the schedule.",
                    ephemeral=True
                )
                logger.info(f"[DEV] Force-generated {len(matches)} matches")
            else:
                await interaction.followup.send(
                    "⚠️ Matchmaker ran but generated 0 matches.\n"
                    "This could be due to:\n"
                    "  • No overlapping availability\n"
                    "  • All dates blocked\n"
                    "  • Not enough teams\n\n"
                    "Try using `/dev generate_dummy scenario:easy` for a simpler test case.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"[DEV] Match generation failed: {e}")
            await interaction.followup.send(
                f"❌ Match generation failed:\n```{str(e)}```",
                ephemeral=True
            )

    @app_commands.command(
    name="diagnose",
    description="Admin diagnosis: Shows all relevant system information and error sources."
    )
    async def diagnose(self, interaction: Interaction):
        """Performs a system diagnosis check."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from modules.poll import poll_channel_id, poll_message_id
        from modules.task_manager import get_all_tasks
        from modules.dataStorage import load_games
        from modules.embeds import load_embed_template

        tournament = load_tournament_data()
        report = []
        language = CONFIG.bot.language

        # Tournament status
        running = tournament.get("running", False)
        report.append(f"🏁 Tournament status: {'✅ Running' if running else '❌ Inactive'}")

        # Registration
        reg_open = tournament.get("registration_open", False)
        reg_end = tournament.get("registration_end")
        if reg_open and reg_end:
            try:
                dt = datetime.fromisoformat(reg_end)
                remaining = dt - datetime.utcnow()
                report.append(f"📝 Registration: ✅ Open ({remaining.days}d {remaining.seconds//3600}h remaining)")
            except Exception:
                report.append("📝 Registration: ⚠️ Invalid date format")
        else:
            report.append("📝 Registration: ❌ Not open")

        # Poll
        poll_status = f"✅ Yes (ID: {poll_message_id})" if poll_message_id else "❌ No"
        report.append(f"📊 Active poll: {poll_status}")

        # Matches & participants
        report.append(f"📅 Scheduled matches: {len(tournament.get('matches', []))}")
        report.append(f"👥 Teams: {len(tournament.get('teams', {}))}")
        report.append(f"🙋 Solo players: {len(tournament.get('solo', []))}")

        # Game list
        games = load_games()
        report.append(f"🎮 Games loaded: {len(games)} {'✅' if games else '❌ NO GAMES'}")

        # Check channels
        report.append("📺 Channel access:")
        channel_names = ["limits", "reminder", "reschedule"]
        for key in channel_names:
            try:
                cid = CONFIG.get_channel_id(key)
                channel = interaction.client.get_channel(cid)
                if not channel:
                    report.append(f"  ❌ {key}: Channel not found (ID {cid})")
                    continue
                perms = channel.permissions_for(channel.guild.me)
                if not perms.send_messages:
                    report.append(f"  ⚠️  {key}: No write permissions for #{channel.name}")
                else:
                    report.append(f"  ✅ {key}: #{channel.name}")
            except Exception as e:
                report.append(f"  ❌ {key}: Error – {e}")

        # Check templates
        report.append("📦 Templates:")
        templates = ["tournament_start", "poll", "registration", "close", "tournament_end"]
        for tpl in templates:
            content = load_embed_template(tpl, language=language)
            status = "✅" if content else "❌"
            report.append(f"  {status} `{tpl}`")

        # Tasks
        report.append("🧵 Background tasks:")
        tasks = get_all_tasks()
        if not tasks:
            report.append("  ❌ No active tasks found")
        else:
            for name, entry in tasks.items():
                task = entry["task"]
                status = "✅ completed" if task.done() else "🟢 running"
                report.append(f"  {name}: {status}")

        # Send summary
        report_text = "\n".join(report)
        await interaction.followup.send(f"🩺 **System diagnosis:**\n```{report_text}```", ephemeral=True)


    @app_commands.command(name="tasks", description="Shows all currently running bot tasks.")
    async def tasks(self, interaction: Interaction):
        """Lists all active background tasks."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 No permission.", ephemeral=True)
            return
        tasks = get_all_tasks()
        if not tasks:
            await interaction.response.send_message("🚦 Currently **no** background tasks running.", ephemeral=True)
            return

        embed = discord.Embed(title="Active Background Tasks", color=0x42F587)
        for name, entry in list(tasks.items())[:5]:
            task = entry["task"]
            coro = entry["coro"]
            status = "✅ completed" if task.done() else "🟢 running"
            embed.add_field(name=name, value=f"Status: {status}\nCoroutine: `{coro}`", inline=False)

        if len(tasks) > 5:
            embed.set_footer(text=f"... and {len(tasks)-5} more task(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="stop", description="🛑 Stops the bot (developers only)")
    async def stop_command(self, interaction: Interaction):
        """Stops the bot gracefully."""
        # Check permissions
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 You are not allowed to use this command.", ephemeral=True)
            logger.warning(f"[SECURITY] {interaction.user.display_name} ({interaction.user.id}) tried to stop the bot.")
            return

        await interaction.response.send_message("🛑 The bot is now stopping...", ephemeral=True)
        logger.warning(f"[SYSTEM] 🛑 Bot stop requested by {interaction.user.display_name} ({interaction.user.id}).")

        # Terminate running tasks (e.g. reminder, background loops, etc.)
        for name, entry in get_all_tasks().items():
            task = entry.get("task")
            if task:
                task.cancel()
                logger.debug(f"[SYSTEM] Task '{name}' was stopped.")

        # Optional: Wait to allow tasks time to cleanly terminate
        await asyncio.sleep(1)

        # Close bot
        await self.bot.close()


class DevCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(DevGroup(bot))


async def setup(bot):
    if DEBUG_MODE:
        await bot.add_cog(DevCog(bot))
    else:
        from modules.logger import logger
        logger.info("[DEV] Dev commands disabled (DEBUG_MODE is 0)")
