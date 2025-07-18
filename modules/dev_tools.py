# modules/dev_tools.py

import asyncio
import random
import discord
from datetime import datetime, timedelta
from discord import Interaction, app_commands
from discord.ext import commands


# Hilfsmodule importieren
from modules import poll
from modules.dataStorage import (
    load_config,
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
        super().__init__(name="dev", description="Dev-Befehle")
        self.bot = bot

    @app_commands.command(
        name="generate_dummy",
        description="Erzeugt Dummy-Solos und Dummy-Teams zum Testen.",
    )
    @app_commands.describe(num_solo="Anzahl Solo-Spieler", num_teams="Anzahl Teams")
    async def generate_dummy_teams(self, interaction: Interaction, num_solo: int = 4, num_teams: int = 2):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
            return

        tournament = load_tournament_data()

        # Solo-Spieler erzeugen
        solo_players = []
        for i in range(num_solo):
            player_name = f"<@{222220000000000 + i*2}>"
            availability = generate_random_availability()

            player_entry = {"player": player_name, "verfügbarkeit": availability}
            solo_players.append(player_entry)

        tournament.setdefault("solo", []).extend(solo_players)

        # Teams erzeugen
        teams = tournament.setdefault("teams", {})
        for i in range(num_teams):
            team_name = generate_team_name()
            member1 = f"<@{1111110000000000 + i*2}>"  # Dummy Mentions
            member2 = f"<@{1111110000000001 + i*2}>"
            availability = generate_random_availability()

            team_entry = {"members": [member1, member2], "verfügbarkeit": availability}
            teams[team_name] = team_entry

        save_tournament_data(tournament)

        logger.info(f"[DUMMY] {num_solo} Solo-Spieler und {num_teams} Teams erstellt.")
        await interaction.response.send_message(
            f"✅ {num_solo} Solo-Spieler und {num_teams} Teams wurden erfolgreich erzeugt!",
            ephemeral=True,
        )

    @app_commands.command(
        name="test_reminder",
        description="Testet ein Reminder-Embed mit einem zufälligen Match.",
    )
    async def test_reminder(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        config = load_config()
        reminder_channel_id = int(config.get("CHANNELS", {}).get("REMINDER", 0))

        guild = interaction.guild
        if not guild:
            await smart_send(
                interaction,
                content="🚫 Dieser Befehl kann nur auf einem Server genutzt werden.",
                ephemeral=True,
            )
            return

        channel = guild.get_channel(reminder_channel_id)
        if not channel:
            await smart_send(
                interaction,
                content="🚫 Reminder-Channel nicht gefunden! Bitte überprüfe die Config.",
                ephemeral=True,
            )
            return

        tournament = load_tournament_data()
        matches = tournament.get("matches", [])
        teams = tournament.get("teams", {})

        if not matches:
            await smart_send(
                interaction,
                content="🚫 Keine Matches vorhanden. Reminder-Test nicht möglich.",
                ephemeral=True,
            )
            return

        # Zufälliges Match wählen
        match = random.choice(matches)

        # Team-Mitglieder sammeln (bereits im Mention-Format gespeichert)
        team1_members = teams.get(match.get("team1", ""), {}).get("members", [])
        team2_members = teams.get(match.get("team2", ""), {}).get("members", [])
        all_mentions = " ".join(team1_members + team2_members)

        # Platzhalter setzen
        placeholders = {
            "match_id": match.get("match_id", "???"),
            "team1": match.get("team1", "Team 1"),
            "team2": match.get("team2", "Team 2"),
            "time": match.get("scheduled_time", "Kein Termin").replace("T", " ")[:16],
            "mentions": all_mentions,
        }

        # Template laden
        template = load_embed_template("reminder").get("REMINDER")
        if not template:
            logger.error("[EMBED] REMINDER Template fehlt.")
            await smart_send(interaction, content="🚫 Reminder-Template fehlt.", ephemeral=True)
            return

        # Embed bauen und senden
        embed = build_embed_from_template(template, placeholders)
        await channel.send(embed=embed)
        await smart_send(
            interaction,
            content=f"✅ Reminder-Test mit Match-ID {placeholders['match_id']} erfolgreich gesendet.",
            ephemeral=True,
        )

        logger.info(
            f"[TEST] Reminder-Embed für Match {placeholders['match_id']} ({placeholders['team1']} vs {placeholders['team2']}) im Channel #{channel.name} gesendet."
        )

    @app_commands.command(
        name="simulate_poll_end",
        description="Simuliert das automatische Ende der Umfrage nach kurzer Zeit (Testzwecke).",
    )
    async def simulate_poll_end(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Simuliere Poll-Ende in 10 Sekunden...", ephemeral=True)

        from modules.tournament import auto_end_poll

        # Aktuellen Channel + Client übergeben
        asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, delay_seconds=10))

    @app_commands.command(
        name="simulate_registration_close",
        description="Simuliert automatisches Schließen der Anmeldung in 10 Sekunden.",
    )
    async def simulate_registration_close(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⏳ Anmeldung wird in 10 Sekunden automatisch geschlossen (Testlauf)...",
            ephemeral=True,
        )

        from modules.tournament import close_registration_after_delay

        asyncio.create_task(close_registration_after_delay(delay_seconds=10, channel=interaction.channel))

    @app_commands.command(
        name="simulate_full_flow",
        description="Startet ein Testturnier inkl. Dummies, Poll und automatischem Ablauf.",
    )
    async def simulate_full_flow(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung dafür.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            "🎬 Starte vollständigen Testlauf: Poll ➝ Anmeldung ➝ Matchplan.",
            ephemeral=True,
        )

        # Dummy Poll-Optionen laden
        poll_options = load_games()
        if not poll_options:
            await interaction.followup.send(
                "⚠️ Keine Spiele gefunden! Bitte fülle `games.json` zuerst.",
                ephemeral=True,
            )
            return

        # Turnierdaten vorbereiten
        now = datetime.utcnow()

        # Turnierzeitraum: Start jetzt, Ende nach zwei vollen Wochenenden ab nächstem Samstag
        next_saturday = now + timedelta((5 - now.weekday()) % 7)
        tournament_end = next_saturday + timedelta(days=8)  # Samstag + Sonntag + Samstag + Sonntag

        tournament_data = {
            "registration_open": False,
            "running": True,
            "solo": [],
            "registration_end": (now + timedelta(seconds=20)).isoformat(),
            "tournament_end": tournament_end.isoformat(),
            "matches": [],
            "poll_results": {},
        }

        # Optional: Solo-Spieler hinzufügen
        solo_players = []
        for i in range(4):
            player_name = f"<@{222220000000000 + i}>"
            availability = generate_random_availability()
            solo_players.append({"player": player_name, "verfügbarkeit": availability})

        tournament_data["solo"] = solo_players

        # Dummy-Spieler und Teams hinzufügen
        teams = {}
        for i in range(6):  # Zwei Dummy-Teams
            team_name = generate_team_name()
            member1 = f"<@{1111110000000000 + i*2}>"  # Dummy Mentions
            member2 = f"<@{1111110000000001 + i*2}>"
            availability = generate_random_availability()

            team_entry = {"members": [member1, member2], "verfügbarkeit": availability}
            teams[team_name] = team_entry

        tournament_data["teams"] = teams
        save_tournament_data(tournament_data)

        # Poll starten
        await interaction.channel.send("🗳️ **Testumfrage wird gestartet...**")
        await poll.start_poll(
            interaction.channel,
            poll_options,
            registration_hours=20,
            poll_duration_hours=10,
        )

        # Poll-Ende simulieren
        asyncio.create_task(auto_end_poll(interaction.client, interaction.channel, delay_seconds=10))

        # Anmeldungsschluss simulieren
        asyncio.create_task(close_registration_after_delay(delay_seconds=20, channel=interaction.channel))

    @app_commands.command(
    name="diagnose",
    description="Admin-Diagnose: Zeigt alle relevanten Systeminformationen und Fehlerquellen."
    )
    async def diagnose(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from modules.poll import poll_channel_id, poll_message_id
        from modules.task_manager import get_all_tasks
        from modules.dataStorage import load_games
        from modules.embeds import load_embed_template

        config = load_config()
        tournament = load_tournament_data()
        report = []
        language = config.get("language", "de")

        # Turnierstatus
        running = tournament.get("running", False)
        report.append(f"🏁 Turnierstatus: {'✅ Läuft' if running else '❌ Inaktiv'}")

        # Anmeldung
        reg_open = tournament.get("registration_open", False)
        reg_end = tournament.get("registration_end")
        if reg_open and reg_end:
            try:
                dt = datetime.fromisoformat(reg_end)
                remaining = dt - datetime.utcnow()
                report.append(f"📝 Anmeldung: ✅ Offen ({remaining.days}d {remaining.seconds//3600}h verbleibend)")
            except Exception:
                report.append("📝 Anmeldung: ⚠️ Ungültiges Datumsformat")
        else:
            report.append("📝 Anmeldung: ❌ Nicht offen")

        # Poll
        poll_status = f"✅ Ja (ID: {poll_message_id})" if poll_message_id else "❌ Nein"
        report.append(f"📊 Aktive Umfrage: {poll_status}")

        # Matches & Teilnehmer
        report.append(f"📅 Geplante Matches: {len(tournament.get('matches', []))}")
        report.append(f"👥 Teams: {len(tournament.get('teams', {}))}")
        report.append(f"🙋 Solo-Spieler: {len(tournament.get('solo', []))}")

        # Spieleliste
        games = load_games()
        report.append(f"🎮 Spiele geladen: {len(games)} {'✅' if games else '❌ KEINE SPIELE'}")

        # Channels prüfen
        report.append("📺 Channel-Zugriffe:")
        channels = config.get("CHANNELS", {})
        for key, id_str in channels.items():
            try:
                cid = int(id_str)
                channel = interaction.client.get_channel(cid)
                if not channel:
                    report.append(f"  ❌ {key}: Channel nicht gefunden (ID {id_str})")
                    continue
                perms = channel.permissions_for(channel.guild.me)
                if not perms.send_messages:
                    report.append(f"  ⚠️  {key}: Keine Schreibrechte für #{channel.name}")
                else:
                    report.append(f"  ✅ {key}: #{channel.name}")
            except Exception as e:
                report.append(f"  ❌ {key}: Fehler – {e}")

        # Templates prüfen
        report.append("📦 Templates:")
        templates = ["tournament_start", "poll", "registration", "close", "tournament_end"]
        for tpl in templates:
            content = load_embed_template(tpl, language=language)
            status = "✅" if content else "❌"
            report.append(f"  {status} `{tpl}`")

        # Tasks
        report.append("🧵 Hintergrund-Tasks:")
        tasks = get_all_tasks()
        if not tasks:
            report.append("  ❌ Keine aktiven Tasks gefunden")
        else:
            for name, entry in tasks.items():
                task = entry["task"]
                status = "✅ abgeschlossen" if task.done() else "🟢 läuft"
                report.append(f"  {name}: {status}")

        # Zusammenfassung schicken
        report_text = "\n".join(report)
        await interaction.followup.send(f"🩺 **Systemdiagnose:**\n```{report_text}```", ephemeral=True)


    @app_commands.command(name="tasks", description="Zeigt alle aktuell laufenden Bot-Tasks an.")
    async def tasks(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return
        tasks = get_all_tasks()
        if not tasks:
            await interaction.response.send_message("🚦 Es laufen aktuell **keine** Hintergrund-Tasks.", ephemeral=True)
            return

        embed = discord.Embed(title="Aktive Hintergrund-Tasks", color=0x42F587)
        for name, entry in list(tasks.items())[:5]:
            task = entry["task"]
            coro = entry["coro"]
            status = "✅ abgeschlossen" if task.done() else "🟢 läuft"
            embed.add_field(name=name, value=f"Status: {status}\nCoroutine: `{coro}`", inline=False)

        if len(tasks) > 5:
            embed.set_footer(text=f"... und {len(tasks)-5} weitere Task(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="stop", description="🛑 Stoppt den Bot (nur für Entwickler)")
    async def stop_command(self, interaction: Interaction):
        # Berechtigungen prüfen
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du darfst diesen Befehl nicht verwenden.", ephemeral=True)
            logger.warning(f"[SECURITY] {interaction.user.display_name} ({interaction.user.id}) hat versucht, den Bot zu stoppen.")
            return

        await interaction.response.send_message("🛑 Der Bot wird jetzt gestoppt...", ephemeral=True)
        logger.warning(f"[SYSTEM] 🛑 Bot-Stop durch {interaction.user.display_name} ({interaction.user.id}) angefordert.")

        # Laufende Tasks beenden (z. B. Reminder, Background Loops etc.)
        for name, entry in get_all_tasks().items():
            task = entry.get("task")
            if task:
                task.cancel()
                logger.debug(f"[SYSTEM] Task '{name}' wurde gestoppt.")

        # Optional: Warten, damit Tasks Zeit zum sauberen Beenden haben
        await asyncio.sleep(1)

        # Bot schließen
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
        logger.info("[DEV] Dev-Befehle deaktiviert (DEBUG_MODE ist 0)")