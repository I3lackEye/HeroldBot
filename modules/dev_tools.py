# modules/dev_tools.py

import asyncio
import random
from datetime import datetime, timedelta

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from modules import poll

# Hilfsmodule importieren
from modules.dataStorage import (
    load_config,
    load_games,
    load_tournament_data,
    save_tournament_data,
)
from modules.embeds import build_embed_from_template, load_embed_template
from modules.logger import logger
from modules.task_manager import get_all_tasks
from modules.utils import (
    generate_random_availability,
    generate_team_name,
    has_permission,
    smart_send,
)


class DevGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="dev", description="Dev-Befehle")

    @app_commands.command(
        name="generate_dummy",
        description="(Admin) Erzeugt Dummy-Solos und Dummy-Teams zum Testen.",
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
            player_name = f"DummySolo_{i+1}"
            availability, special = generate_random_availability()

            player_entry = {"player": player_name, "verfügbarkeit": availability}
            if special:
                player_entry.update(special)

            solo_players.append(player_entry)

        tournament.setdefault("solo", []).extend(solo_players)

        # Teams erzeugen
        teams = tournament.setdefault("teams", {})
        for i in range(num_teams):
            team_name = generate_team_name()
            member1 = f"TeamMember_{i+1}_1"
            member2 = f"TeamMember_{i+1}_2"
            availability, special = generate_random_availability()

            team_entry = {"members": [member1, member2], "verfügbarkeit": availability}
            if special:
                team_entry.update(special)

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
        template = load_embed_template("reminder", category="default").get("REMINDER")
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
        tournament_data = {
            "registration_open": False,
            "running": True,
            "solo": [],
            "registration_end": (now + timedelta(seconds=20)).isoformat(),
            "tournament_end": (now + timedelta(days=7)).isoformat(),
            "matches": [],
            "poll_results": {},
        }

        # Dummy-Spieler und Teams hinzufügen
        teams = {}
        for i in range(2):  # Zwei Dummy-Teams
            team_name = f"TestTeam_{i+1}"
            member1 = f"<@{1111110000000000 + i*2}>"  # Dummy Mentions
            member2 = f"<@{1111110000000001 + i*2}>"
            availability, special = generate_random_availability()

            team_entry = {"members": [member1, member2], "verfügbarkeit": availability}
            team_entry.update(special)
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
        name="health_check",
        description="Admin-Check: Prüft wichtige Zustände des Systems.",
    )
    async def health_check_command(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung für diesen Befehl.", ephemeral=True)
            return

        tournament = load_tournament_data()
        embed = discord.Embed(title="🩺 System Health Check", color=discord.Color.green())

        # 1. Turnierstatus
        running = tournament.get("running", False)
        embed.add_field(name="Turnier läuft", value="✅ Ja" if running else "❌ Nein", inline=True)

        # 2. Poll aktiv?
        from modules.poll import poll_channel_id, poll_message_id

        embed.add_field(
            name="Aktive Umfrage",
            value=f"✅ Ja (ID: {poll_message_id})" if poll_message_id else "❌ Nein",
            inline=True,
        )

        # 3. Anmeldung offen
        reg_open = tournament.get("registration_open", False)
        reg_end = tournament.get("registration_end")
        if reg_end:
            try:
                dt = datetime.fromisoformat(reg_end)
                remaining = dt - datetime.utcnow()
                reg_info = f"✅ Offen (noch {remaining.days}d {remaining.seconds//3600}h)"
            except Exception:
                reg_info = "⚠️ Ungültiges Datumsformat"
        else:
            reg_info = "❌ Nicht gesetzt"

        embed.add_field(name="Anmeldung", value=reg_info, inline=False)

        # 4. Matches
        matches = tournament.get("matches", [])
        embed.add_field(name="Geplante Matches", value=str(len(matches)), inline=True)

        # 5. Teilnehmer
        embed.add_field(name="Teams", value=str(len(tournament.get("teams", {}))), inline=True)
        embed.add_field(name="Solo-Spieler", value=str(len(tournament.get("solo", []))), inline=True)

        # Antwort
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="diagnose_all",
        description="Führt eine vollständige Diagnose aller Konfigurationen, Channels & Templates durch.",
    )
    async def diagnose_all(self, interaction: Interaction):
        if not has_permission(interaction.user, "Dev"):
            await interaction.response.send_message("🚫 Keine Berechtigung.", ephemeral=True)
            return

        from modules.dataStorage import load_config, load_games
        from modules.embeds import load_embed_template

        config = load_config()

        report = []

        # Games
        games = load_games()
        report.append(f"🎮 Spiele geladen: {len(games)} {'✅' if games else '❌ KEINE SPIELE'}")

        # Channels
        channels = config.get("CHANNELS", {})
        for key, id_str in channels.items():
            try:
                cid = int(id_str)
                channel = interaction.client.get_channel(cid)
                if not channel:
                    report.append(f"❌ Channel {key}: Nicht gefunden (ID: {id_str})")
                    continue
                perms = channel.permissions_for(channel.guild.me)
                if not perms.send_messages:
                    report.append(f"⚠️ Channel {key} (#{channel.name}): Keine Schreibrechte")
                else:
                    report.append(f"✅ Channel {key} (#{channel.name}): OK")
            except Exception as e:
                report.append(f"❌ Channel {key}: Fehler – {e}")

        # Templates
        templates = [
            "tournament_start",
            "poll",
            "registration",
            "close",
            "tournament_end",
        ]
        for tpl in templates:
            content = load_embed_template(tpl, category="default")
            status = "✅" if content else "❌"
            report.append(f"{status} Template: `{tpl}`")

        # Rückgabe
        text = "\n".join(report)
        await interaction.response.send_message(f"🩺 **Diagnosebericht:**\n```{text}```", ephemeral=True)

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
        for name, task in tasks.items():
            status = "✅ abgeschlossen" if task.done() else "🟢 läuft"
            embed.add_field(name=name, value=f"Status: {status}\nTask: {task}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class DevCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tree.add_command(DevGroup())


async def setup(bot):
    await bot.add_cog(DevCog(bot))
