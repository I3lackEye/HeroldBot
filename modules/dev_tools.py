# modules/dev_tools.py

from modules.embeds import get_message
import asyncio
import random
import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
from modules.task_manager import add_task, get_all_tasks
from modules.tournament import auto_end_poll, close_registration_after_delay, end_tournament_procedure
from modules.utils import (
    generate_random_availability,
    generate_team_name,
    has_permission,
    smart_send,
    now_in_bot_timezone,
    ensure_timezone_aware,
    parse_iso_datetime,
    get_bot_timezone
)


class DevGroup(app_commands.Group):
    def __init__(self, bot):
        super().__init__(
            name="dev",
            description="Developer commands",
            default_permissions=discord.Permissions(administrator=True)
        )
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "🎬 Starting complete test run: Poll ➝ Registration ➝ Match plan.",
            ephemeral=True,
        )

        # Reset registration closed flag for new test tournament
        from modules.tournament import _registration_lock
        import modules.tournament as tournament_module
        async with _registration_lock:
            tournament_module._registration_closed = False

        # Load dummy poll options
        poll_options = load_games()
        if not poll_options:
            await interaction.followup.send(
                "⚠️ No games found! Please fill `games.json` first.",
                ephemeral=True,
            )
            return

        # Prepare tournament data with timezone awareness
        now = now_in_bot_timezone()

        # Registration ends in 20 seconds (for quick testing)
        registration_end = now + timedelta(seconds=20)

        # Tournament duration will be auto-calculated after teams are known
        # For now, set generous default (will be recalculated automatically)
        tournament_end = registration_end + timedelta(weeks=12)

        tournament_data = {
            "registration_open": False,
            "running": True,
            "solo": [],
            "registration_end": registration_end.isoformat(),
            "tournament_end": tournament_end.isoformat(),
            "matches": [],
            "poll_results": {
                "chosen_game": "Test Game (SimulatedFlow)"  # Pre-set game for testing
            },
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
            registration_hours=20,  # Registration duration in seconds (for testing)
            poll_duration_hours=10,  # Poll duration in seconds (for testing)
        )

        # Simulate poll end (which will automatically trigger registration close)
        # Note: auto_end_poll calls close_registration_after_delay automatically
        # based on the registration_end timestamp, so no manual call needed
        asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, delay_seconds=10))

    @app_commands.command(
        name="reset_tournament",
        description="Clears all tournament data (teams, solo, matches).",
    )
    async def reset_tournament(self, interaction: Interaction):
        """Resets tournament to clean state."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            from modules.matchmaker import create_round_robin_schedule, auto_match_solo

            # Pair solo players first
            if solo:
                auto_match_solo()
                # Reload tournament data after auto-matching
                tournament = load_tournament_data()
                teams = tournament.get("teams", {})

            # Get tournament end date
            tournament_end = tournament.get("tournament_end")
            if tournament_end:
                end_date = parse_iso_datetime(tournament_end)
            else:
                # Default: 2 weeks from now
                end_date = now_in_bot_timezone() + timedelta(weeks=2)

            # Try to create schedule
            matchups = create_round_robin_schedule(tournament)

            # Report results
            result = [
                f"**Matchmaker Test Results**",
                f"",
                f"📊 **Input:**",
                f"  • Teams: {len(teams)}",
                f"  • Total matchups needed: {len(matchups)}",
                f"  • Tournament end: {end_date.strftime('%Y-%m-%d')}",
                f"",
                f"🎯 **Round-Robin Pairings:**"
            ]

            for i, match in enumerate(matchups[:10], 1):
                result.append(f"  {i}. {match['team1']} vs {match['team2']}")

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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission"), ephemeral=True)
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
            from modules.matchmaker import (
                auto_match_solo,
                create_round_robin_schedule,
                generate_slot_matrix,
                assign_slots_with_matrix
            )

            # Set tournament as running if not already
            if not tournament.get("running"):
                tournament["running"] = True

            # Set tournament end if not set (default 2 weeks from now)
            if not tournament.get("tournament_end"):
                from datetime import datetime, timedelta
                tournament["tournament_end"] = (datetime.now() + timedelta(weeks=2)).isoformat()

            save_tournament_data(tournament)

            # Step 1: Auto-match solo players
            solo = tournament.get("solo", [])
            if solo:
                auto_match_solo()
                tournament = load_tournament_data()  # Reload after auto-matching

            # Step 2: Create round-robin matchups
            matches = create_round_robin_schedule(tournament)

            # Step 3: Generate time slots
            slot_matrix = generate_slot_matrix(tournament)

            # Step 4: Assign slots to matches
            assigned_matches, unassigned_matches = assign_slots_with_matrix(matches, slot_matrix)

            # Build result message
            if len(matches) == 0:
                msg = "⚠️ No matches could be created (need at least 2 teams)."
            elif len(assigned_matches) == len(matches):
                msg = (
                    f"✅ Successfully generated and scheduled **{len(matches)} matches**!\n"
                    f"All matches have been assigned time slots.\n"
                    f"Use `/dev show_state` to see the schedule."
                )
            elif len(assigned_matches) > 0:
                msg = (
                    f"⚠️ Partially successful:\n"
                    f"  • Created: {len(matches)} matches\n"
                    f"  • Scheduled: {len(assigned_matches)} matches\n"
                    f"  • Unscheduled: {len(unassigned_matches)} matches\n\n"
                    f"Some matches couldn't be scheduled due to availability conflicts.\n"
                    f"Try using `/dev generate_dummy scenario:easy` for better overlap."
                )
            else:
                msg = (
                    f"⚠️ Created {len(matches)} matches but couldn't schedule any!\n"
                    f"This could be due to:\n"
                    f"  • No overlapping availability\n"
                    f"  • All dates blocked\n"
                    f"  • Too many matches for available time slots\n\n"
                    f"Try using `/dev generate_dummy scenario:easy` for a simpler test case."
                )

            await interaction.followup.send(msg, ephemeral=True)
            logger.info(f"[DEV] Force-generated {len(matches)} matches ({len(assigned_matches)} scheduled)")

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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission_short"), ephemeral=True)
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
                dt = parse_iso_datetime(reg_end)
                remaining = dt - now_in_bot_timezone()
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
            await interaction.response.send_message(get_message("PERMISSION", "no_permission_short"), ephemeral=True)
            return
        tasks = get_all_tasks()
        if not tasks:
            await interaction.response.send_message("🚦 Currently **no** background tasks running.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔧 Active Background Tasks",
            description=f"Total: {len(tasks)} task(s)",
            color=0x42F587
        )

        # Categorize tasks
        tournament_tasks = []
        reschedule_tasks = []
        other_tasks = []

        for name, entry in tasks.items():
            task = entry["task"]
            coro = entry["coro"]

            # Determine task category
            if name.startswith("reschedule_timer"):
                reschedule_tasks.append((name, task, coro))
            elif any(name.startswith(prefix) for prefix in ["tournament_", "close_registration", "auto_end_poll"]):
                tournament_tasks.append((name, task, coro))
            else:
                other_tasks.append((name, task, coro))

        # Display tournament tasks first
        if tournament_tasks:
            tournament_field = ""
            for name, task, coro in tournament_tasks[:5]:
                status_icon = "✅" if task.done() else "🟢"
                status_text = "completed" if task.done() else "running"
                tournament_field += f"{status_icon} **{name}**\n└ `{coro}` ({status_text})\n\n"

            embed.add_field(
                name="🏆 Tournament Tasks",
                value=tournament_field or "None",
                inline=False
            )

        # Display reschedule tasks
        if reschedule_tasks:
            reschedule_field = ""
            for name, task, coro in reschedule_tasks[:5]:
                # Extract match ID from task name
                match_id = name.replace("reschedule_timer_match_", "")
                status_icon = "✅" if task.done() else "⏳"
                status_text = "completed" if task.done() else "waiting"
                reschedule_field += f"{status_icon} **Match {match_id}**\n└ `{coro}` ({status_text})\n\n"

            embed.add_field(
                name="🔄 Reschedule Timers",
                value=reschedule_field or "None",
                inline=False
            )

        # Display other tasks
        if other_tasks:
            other_field = ""
            for name, task, coro in other_tasks[:5]:
                status_icon = "✅" if task.done() else "🟢"
                status_text = "completed" if task.done() else "running"
                other_field += f"{status_icon} **{name}**\n└ `{coro}` ({status_text})\n\n"

            embed.add_field(
                name="🔧 Other Tasks",
                value=other_field or "None",
                inline=False
            )

        total_shown = min(len(tournament_tasks) + len(reschedule_tasks) + len(other_tasks), 15)
        if len(tasks) > total_shown:
            embed.set_footer(text=f"... and {len(tasks) - total_shown} more task(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="test_reschedule",
        description="🧪 Test reschedule system with mock data"
    )
    @app_commands.describe(
        action="Action to perform",
        match_id="Match ID (for check_pending action)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Create mock match", value="create"),
        app_commands.Choice(name="Set reschedule pending", value="set_pending"),
        app_commands.Choice(name="Check pending status", value="check_pending"),
        app_commands.Choice(name="Clear reschedule state", value="clear"),
    ])
    async def test_reschedule(
        self,
        interaction: Interaction,
        action: app_commands.Choice[str],
        match_id: int = None
    ):
        """Test the reschedule system with various scenarios."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message(
                get_message("PERMISSION", "not_allowed"),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        tournament = load_tournament_data()

        if action.value == "create":
            # Create a mock match for testing
            teams = tournament.get("teams", {})
            if len(teams) < 2:
                await interaction.followup.send(
                    "❌ Need at least 2 teams in tournament to create a test match.\n"
                    "Use `/dev quick_tournament` first.",
                    ephemeral=True
                )
                return

            team_names = list(teams.keys())[:2]

            # Find next available match ID
            existing_matches = tournament.get("matches", [])
            next_id = max([m.get("match_id", 0) for m in existing_matches], default=0) + 1

            # Create mock match
            mock_match = {
                "match_id": next_id,
                "team1": team_names[0],
                "team2": team_names[1],
                "status": "scheduled",
                "scheduled_time": (now_in_bot_timezone() + timedelta(days=3)).isoformat(),
            }

            tournament["matches"].append(mock_match)
            save_tournament_data(tournament)

            await interaction.followup.send(
                f"✅ **Created test match:**\n"
                f"• Match ID: {next_id}\n"
                f"• Teams: {team_names[0]} vs {team_names[1]}\n"
                f"• Status: scheduled\n\n"
                f"You can now test reschedule with `/player request_reschedule` using match ID `{next_id}`",
                ephemeral=True
            )

        elif action.value == "set_pending":
            if match_id is None:
                await interaction.followup.send(
                    "❌ Please provide a match_id parameter",
                    ephemeral=True
                )
                return

            match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
            if not match:
                await interaction.followup.send(
                    f"❌ Match {match_id} not found",
                    ephemeral=True
                )
                return

            # Set reschedule as pending
            match["reschedule_pending"] = True
            match["reschedule_pending_since"] = now_in_bot_timezone().isoformat()
            match["reschedule_requested_by"] = [match["team1"]]

            save_tournament_data(tournament)

            # Start a test timer (shortened to 1 minute for testing)
            from modules.reschedule import start_reschedule_timer
            timer_task = self.bot.loop.create_task(
                start_reschedule_timer(self.bot, match_id, delay_seconds=60)
            )
            add_task(f"reschedule_timer_match_{match_id}", timer_task)

            await interaction.followup.send(
                f"✅ **Set reschedule pending for match {match_id}:**\n"
                f"• reschedule_pending: True\n"
                f"• reschedule_requested_by: {match['team1']}\n"
                f"• Timer: 1 minute (test duration)\n\n"
                f"Try requesting reschedule now to see the 'already pending' error!",
                ephemeral=True
            )

        elif action.value == "check_pending":
            if match_id is None:
                # Show all pending reschedules
                from modules.reschedule import get_reschedule_pending_matches
                pending = get_reschedule_pending_matches()

                if not pending:
                    await interaction.followup.send(
                        "✅ No pending reschedule requests",
                        ephemeral=True
                    )
                    return

                msg = "**Pending Reschedule Requests:**\n\n"
                for m in pending:
                    mid = m.get("match_id")
                    team = m.get("reschedule_requested_by", ["Unknown"])[0]
                    since_str = m.get("reschedule_pending_since", "Unknown")

                    # Format the timestamp nicely
                    try:
                        since_dt = parse_iso_datetime(since_str)
                        since_formatted = since_dt.strftime("%d.%m.%Y %H:%M")
                    except:
                        since_formatted = since_str

                    msg += f"• Match {mid}: Requested by {team}\n  Since: {since_formatted}\n\n"

                await interaction.followup.send(msg, ephemeral=True)
            else:
                # Check specific match
                match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
                if not match:
                    await interaction.followup.send(
                        f"❌ Match {match_id} not found",
                        ephemeral=True
                    )
                    return

                is_pending = match.get("reschedule_pending", False)
                requested_by = match.get("reschedule_requested_by", [])
                pending_since_str = match.get("reschedule_pending_since", "N/A")

                # Format the timestamp nicely
                if pending_since_str != "N/A":
                    try:
                        pending_since_dt = parse_iso_datetime(pending_since_str)
                        pending_since_formatted = pending_since_dt.strftime("%d.%m.%Y %H:%M")
                    except:
                        pending_since_formatted = pending_since_str
                else:
                    pending_since_formatted = "N/A"

                await interaction.followup.send(
                    f"**Match {match_id} Reschedule Status:**\n\n"
                    f"• Pending: {is_pending}\n"
                    f"• Requested by: {', '.join(requested_by) if requested_by else 'None'}\n"
                    f"• Since: {pending_since_formatted}",
                    ephemeral=True
                )

        elif action.value == "clear":
            if match_id is None:
                await interaction.followup.send(
                    "❌ Please provide a match_id parameter",
                    ephemeral=True
                )
                return

            match = next((m for m in tournament.get("matches", []) if m.get("match_id") == match_id), None)
            if not match:
                await interaction.followup.send(
                    f"❌ Match {match_id} not found",
                    ephemeral=True
                )
                return

            # Clear reschedule state
            fields_cleared = []
            if "reschedule_pending" in match:
                del match["reschedule_pending"]
                fields_cleared.append("reschedule_pending")
            if "reschedule_requested_by" in match:
                del match["reschedule_requested_by"]
                fields_cleared.append("reschedule_requested_by")
            if "reschedule_pending_since" in match:
                del match["reschedule_pending_since"]
                fields_cleared.append("reschedule_pending_since")

            save_tournament_data(tournament)

            # Cancel timer if exists
            task_name = f"reschedule_timer_match_{match_id}"
            all_tasks = get_all_tasks()
            if task_name in all_tasks:
                timer_task = all_tasks[task_name]["task"]
                if not timer_task.done():
                    timer_task.cancel()

            await interaction.followup.send(
                f"✅ Cleared reschedule state for match {match_id}\n"
                f"Removed: {', '.join(fields_cleared) if fields_cleared else 'nothing (was already clear)'}",
                ephemeral=True
            )

    @app_commands.command(
        name="fix_past_matches",
        description="🔧 Reschedules all matches that are in the past"
    )
    async def fix_past_matches(self, interaction: Interaction):
        """Finds all matches scheduled in the past and reschedules them."""
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message(
                get_message("PERMISSION", "not_allowed"),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        now = now_in_bot_timezone()

        # Find matches in the past
        past_matches = []
        for match in matches:
            scheduled_time_str = match.get("scheduled_time")
            if scheduled_time_str and match.get("status") not in ["completed", "forfeit"]:
                try:
                    scheduled_time = parse_iso_datetime(scheduled_time_str)
                    if scheduled_time < now:
                        past_matches.append((match, scheduled_time))
                except Exception as e:
                    logger.error(f"[FIX-PAST] Error parsing time for match {match.get('match_id')}: {e}")

        if not past_matches:
            await interaction.followup.send(
                "✅ No matches scheduled in the past. All good!",
                ephemeral=True
            )
            return

        # Show what will be fixed
        msg = f"**Found {len(past_matches)} match(es) in the past:**\n\n"
        for match, old_time in past_matches[:10]:
            match_id = match.get("match_id")
            team1 = match.get("team1", "Unknown")
            team2 = match.get("team2", "Unknown")
            msg += f"• Match {match_id}: {team1} vs {team2}\n"
            msg += f"  Was: {old_time.strftime('%d.%m.%Y %H:%M')}\n\n"

        if len(past_matches) > 10:
            msg += f"... and {len(past_matches) - 10} more\n\n"

        msg += "**Attempting to reschedule...**\n"

        await interaction.followup.send(msg, ephemeral=True)

        # Reschedule each match
        from modules.matchmaker import generate_slot_matrix, assign_slots_with_matrix

        # Reset scheduled_time for past matches
        for match, _ in past_matches:
            match["scheduled_time"] = None

        # Generate new slot matrix (will use current time as start)
        slot_matrix = generate_slot_matrix(tournament)

        if not slot_matrix:
            await interaction.followup.send(
                "❌ Could not generate slot matrix. Check logs for errors.",
                ephemeral=True
            )
            return

        # Try to assign slots
        matches_to_reschedule = [m for m, _ in past_matches]
        updated_matches, unassigned = assign_slots_with_matrix(matches_to_reschedule, slot_matrix)

        # Save results
        save_tournament_data(tournament)

        # Report results
        result_msg = f"\n**Results:**\n"
        result_msg += f"✅ Successfully rescheduled: {len(updated_matches)}\n"
        result_msg += f"❌ Could not reschedule: {len(unassigned)}\n\n"

        if updated_matches:
            result_msg += "**New times:**\n"
            for match in updated_matches[:10]:
                match_id = match.get("match_id")
                new_time_str = match.get("scheduled_time")
                try:
                    new_time = parse_iso_datetime(new_time_str)
                    result_msg += f"• Match {match_id}: {new_time.strftime('%d.%m.%Y %H:%M')}\n"
                except:
                    result_msg += f"• Match {match_id}: {new_time_str}\n"

        if unassigned:
            result_msg += f"\n⚠️  **{len(unassigned)} match(es) could not be rescheduled**\n"
            result_msg += "Consider extending the tournament or adjusting team availability."

        await interaction.followup.send(result_msg, ephemeral=True)

    @app_commands.command(name="stop", description="🛑 Stops the bot (developers only)")
    async def stop_command(self, interaction: Interaction):
        """Stops the bot gracefully."""
        # Check permissions
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message(get_message("PERMISSION", "not_allowed"), ephemeral=True)
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
