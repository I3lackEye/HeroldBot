#tournament.py
import discord
import asyncio
import logging
import random
import os
import re
from discord.ui import View, Button
from discord.utils import get
from discord import Embed
from datetime import datetime, timedelta
from .logger import setup_logger
from .matchmaker import auto_match_solo
from .dataStorage import (
    reset_tournament_data,
    load_global_data, 
    save_global_data,
    load_tournament_data, 
    save_tournament_data, 
    load_config, 
    CHANNEL_LIMIT_1,
    TOURNAMENT_FILE_PATH
)
from .utils import(
    has_permission,
    update_player_stats,
    register_participation,
    get_all_registered_user_ids,
    update_favorite_game
)


# Setup Logger
logger = setup_logger("logs", level=logging.INFO)
config = load_config()

async def finalize_registration(interaction: discord.Interaction, registration_period: int):
    # Warte, bis die Registrierungszeit abgelaufen ist
    await asyncio.sleep(registration_period)
    
    # Setze das Flag "registration_open" auf False
    tournament = load_tournament_data()
    tournament["registration_open"] = False
    save_tournament_data(tournament)
    await interaction.channel.send("Die Anmeldephase ist nun geschlossen.")
    
    # Rufe die Funktion zum automatischen Zusammenführen der Solo-Spieler auf
    new_teams = auto_match_solo()
    
    # Sende eine Nachricht mit den neu gebildeten Teams
    if new_teams:
        msg_lines = ["Neue Teams aus der Solo-Anmeldung:"]
        for team, members in new_teams.items():
            msg_lines.append(f"**{team}**: {', '.join(members)}")
        msg = "\n".join(msg_lines)
    else:
        msg = "Es wurden keine neuen Teams gebildet (nicht genügend Spieler)."
    
    await interaction.channel.send(msg)
    logger.info("Automatisches Matchmaking durchgeführt.")

# PollView: Verwende Message Components (Buttons)
class PollView(View):
    def __init__(self, options: list, registration_period: int = 604800):  # ca. 7 Tage Anmeldungsfrist
        """
        :param options: Liste der Poll-Optionen (z.B. Spiele).
        :param registration_period: Dauer der Freigabe in Sekunden.
        """
        super().__init__(timeout=None)  # Kein Timeout
        self.message = None  # Attribut initialisieren
        self.options = options
        self.results = {i: 0 for i in range(len(options))}
        self.registration_period = registration_period
        for i, option in enumerate(options):
            button = Button(label=option, custom_id=f"poll_{i}", style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(i, option)
            self.add_item(button)
        # Button, um den Poll zu beenden
        end_button = Button(label="Poll beenden", style=discord.ButtonStyle.danger, custom_id="end_poll")
        end_button.callback = self.end_poll
        self.add_item(end_button)

    def make_callback(self, index: int, option: str):
        async def callback(interaction: discord.Interaction):
            self.results[index] += 1
            await interaction.response.send_message(f"Du hast für **{option}** gestimmt!", ephemeral=True)
        return callback

    async def end_poll(self, interaction: discord.Interaction):
        if not has_permission(interaction.user, "Moderator", "Admin"):
            await interaction.response.send_message("🚫 Du hast keine Berechtigung, die Umfrage zu beenden.", ephemeral=True)
            return

        poll_result_mapping = {self.options[i]: count for i, count in self.results.items()}
        sorted_games = sorted(poll_result_mapping.items(), key=lambda kv: kv[1], reverse=True)

        if not sorted_games or sorted_games[0][1] == 0:
            chosen_game = "Keine Stimmen abgegeben"
        else:
            max_votes = sorted_games[0][1]
            top_games = [game for game, votes in sorted_games if votes == max_votes]
            chosen_game = random.choice(top_games)

            logger.info(f"Poll abgeschlossen – gewähltes Spiel: {chosen_game}")
            if len(top_games) > 1:
                logger.info(f"Gleichstand bei der Abstimmung ({max_votes} Stimmen). Mögliche Spiele: {top_games}. Zufällig gewählt: {chosen_game}")
            else:
                logger.info(f"Spiel mit den meisten Stimmen: {chosen_game} ({max_votes} Stimmen)")

        # Save poll results & gewähltes Spiel
        poll_result_mapping["chosen_game"] = chosen_game
        tournament = load_tournament_data()
        tournament["poll_results"] = poll_result_mapping
        tournament["game"] = chosen_game
        save_tournament_data(tournament)

        # Zeige Ergebnisse im Embed
        await send_poll_results_embed(interaction, poll_result_mapping, chosen_game)

        # Registrierung freigeben
        tournament["registration_open"] = True
        save_tournament_data(tournament)
        end_time = datetime.now() + timedelta(seconds=self.registration_period)
        formatted_end = end_time.strftime("%d.%m.%Y %H:%M")
        await interaction.channel.send(f"📣 Die Anmeldung ist bis **{formatted_end}** freigegeben!")

        # Hintergrundtask nach Ablauf der Registrierungszeit
        async def close_registration_and_finalize():
            await asyncio.sleep(self.registration_period)

            tournament = load_tournament_data()
            tournament["registration_open"] = False
            save_tournament_data(tournament)
            await interaction.channel.send("🔒 Die Anmeldephase ist nun geschlossen.")

            # Teilnahme & Lieblingsspiel tracken
            user_ids = get_all_registered_user_ids(tournament)
            register_participation([
                interaction.guild.get_member(uid) for uid in user_ids if interaction.guild.get_member(uid)
            ])

            game = tournament.get("game")
            if game:
                update_favorite_game(user_ids, game)

            # Matchmaking
            new_teams = auto_match_solo()
            if new_teams:
                msg_lines = ["🛠️ Neue Teams aus der Solo-Anmeldung:"]
                for team, members in new_teams.items():
                    msg_lines.append(f"**{team}**: {', '.join(members)}")
                await interaction.channel.send("\n".join(msg_lines))
            else:
                await interaction.channel.send("❗ Es konnten keine neuen Teams gebildet werden (nicht genügend Solo-Spieler).")

            logger.info("Matchmaking abgeschlossen und Teams wurden gebildet.")

        asyncio.create_task(close_registration_and_finalize())
        self.stop()

        # Nachricht löschen (optional)
        if self.message:
            try:
                await self.message.delete()
                logger.info("Poll-Nachricht wurde gelöscht.")
            except Exception as e:
                logger.error(f"Fehler beim Löschen der Poll-Nachricht: {e}")

# Funktion zum Starten eines Turniers inkl. Poll
async def start_tournament(interaction: discord.Interaction, registration_period: int = 604800):
    # Überprüfe auf Korrekten Channel
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return
    
    # Überprüfe, ob der Nutzer Administratorrechte hat.
    if not has_permission(interaction.user, "Moderator", "Admin"):
        logger.info(f"{interaction.user} hatte keine Berechtigung")
        await interaction.response.send_message("Du hast keine ausreichenden Rechte, um diesen Befehl auszuführen.", ephemeral=True)
        return

    tournament = load_tournament_data()
    if tournament.get("running", False):
        await interaction.response.send_message("Ein Turnier läuft bereits!", ephemeral=True)
        return

    # Setze das Turnier zurück und markiere es als laufend
    tournament = reset_tournament_data()
    tournament["running"] = True
    save_tournament_data(tournament)

    # Lade die globalen Spieldaten
    global_data = load_global_data()
    games = global_data.get("games", [])
    if not games:
        await interaction.response.send_message("Es sind keine Spiele in den globalen Daten hinterlegt.", ephemeral=True)
        return

    # Erstelle die PollView mit der angegebenen Registrierungsdauer (in Sekunden)
    view = PollView(games, registration_period=registration_period)
    poll_msg = await interaction.channel.send("Bitte stimme ab, welches Spiel im Turnier gespielt werden soll:", view=view)
    view.message = poll_msg

    # Sende eine Bestätigung (optional auch mit Anzeige des Endzeitpunkts)
    end_time = datetime.now() + timedelta(seconds=registration_period)
    formatted_end = end_time.strftime("%d.%m.%Y %H:%M")
    await interaction.response.send_message(f"Neues Turnier gestartet. Die Anmeldung ist bis {formatted_end} freigegeben.", ephemeral=True)

async def finalize_and_schedule_matches(interaction: discord.Interaction, registration_period: int):
    # Warte, bis die Anmeldefrist abgelaufen ist
    await asyncio.sleep(registration_period)
    
    # Setze die Registrierung als geschlossen
    tournament = load_tournament_data()
    tournament["registration_open"] = False
    save_tournament_data(tournament)
    await interaction.channel.send("Die Anmeldephase ist nun geschlossen.")
    
    # Führe den Matchmaker aus
    schedule = run_matchmaker()
    if schedule:
        msg_lines = ["**Spielplan für Round-Robin-Matches:**"]
        for match in schedule:
            msg_lines.append(f"{match['date']} um {match['start_time']}: {match['team1']} vs. {match['team2']}")
        message = "\n".join(msg_lines)
    else:
        message = "Es konnten keine Matches generiert werden."
    
    await interaction.channel.send(message)

async def set_winner(interaction: discord.Interaction, team: str):
    # Funktionalität, z. B.:
    if not has_permission(interaction.user, "Moderator", "Admin"):
        await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl auszuführen.", ephemeral=True)
        return

    # Daten Laden
    tournament = load_tournament_data()

    if team not in tournament.get("teams", {}):
        await interaction.response.send_message(f"Das Team '{team}' existiert nicht.", ephemeral=True)
        return

    # Suche das Match und trage den Gewinner ein
    schedule = tournament.get("schedule", [])
    for match in schedule:
        if team in (match.get("team1"), match.get("team2")) and not match.get("winner"):
            match["winner"] = team
            break  # Nur ein Match aktualisieren

    punkte = tournament.get("punkte", {})
    current_points = punkte.get(team, 0)
    punkte[team] = current_points + 1
    tournament["punkte"] = punkte
    schedule = tournament.get("schedule", [])
    for match in schedule:
        if team in (match.get("team1"), match.get("team2")) and not match.get("winner"):
            match["winner"] = team
            logger.info(f"Match {match['team1']} vs. {match['team2']} – Gewinner gesetzt: {team}")
            break  # Nur ein Match aktualisieren

    # Spielplan wieder speichern
    tournament["schedule"] = schedule
    save_tournament_data(tournament)
    logger.info(f"Team '{team}' hat jetzt {punkte[team]} Punkte.")
    await interaction.response.send_message(f"Gewinner gesetzt: Team '{team}' erhält einen Punkt. Aktuelle Punkte: {punkte[team]}", ephemeral=True)

async def end_tournament(interaction: discord.Interaction):
    """
    Beendet das aktuelle Turnier:
      - Ermittelt das Gewinnerteam anhand der Punkte im aktuellen Turnier und speichert Details.
      - Aktualisiert globale Daten (data.json) mit den Gewinnerdetails.
      - Setzt das Turnier als beendet.
      - Ermittelt den overall turnierübergreifenden Gewinner (über get_overall_winner()) 
        und weist ihm die in der Konfiguration definierte Siegerrolle zu.
      - Sendet eine Zusammenfassung als Nachricht an den Channel.
    """
    # Lade die aktuellen Turnierdaten
    tournament = load_tournament_data()
    
    # Prüfe, ob tatsächlich ein Turnier läuft
    if not tournament.get("running", False):
        await interaction.response.send_message("Es läuft derzeit kein Turnier.", ephemeral=True)
        return
    
    punkte = tournament.get("punkte", {})
    if not punkte:
        await interaction.response.send_message("Es wurden noch keine Punkte vergeben.", ephemeral=True)
        return

    # Ermittele das Gewinnerteam des aktuellen Turniers
    sorted_teams = sorted(punkte.items(), key=lambda kv: kv[1], reverse=True)
    winning_team, winning_points = sorted_teams[0]

    # Ermittle optional das im Poll gewählte Spiel
    poll_results = tournament.get("poll_results", {})
    if poll_results:
        sorted_games = sorted(poll_results.items(), key=lambda kv: kv[1], reverse=True)
        chosen_game = sorted_games[0][0] if sorted_games and sorted_games[0][1] > 0 else "Keine Stimmen abgegeben"
    else:
        chosen_game = "Nicht ausgewählt"

    # Gewinnerdetails für das aktuelle Turnier
    winner_details = {
        "winning_team": winning_team,
        "points": winning_points,
        "game": chosen_game,
        "ended_at": datetime.now().isoformat()
    }

    # Speichere Gewinnerdetails in den globalen Daten
    global_data = load_global_data()
    global_data["last_tournament_winner"] = winner_details
    save_global_data(global_data)

    # Aktualisiere die individuellen Spielerstatistiken (z.B. über update_player_stats() in players.py)
    winning_team_entry = tournament.get("teams", {}).get(winning_team)
    if winning_team_entry and winning_team_entry.get("members"):
        update_player_stats(winning_team_entry["members"])
    else:
        logger.warning("Kein gültiges Gewinnerteam gefunden, oder Mitglieder fehlen.")

    # Setze das Turnier als beendet
    tournament["running"] = False
    save_tournament_data(tournament)

    response_text = (
        f"Das Turnier ist beendet!\n"
        f"Gewinnerteam: **{winning_team}** mit {winning_points} Punkten\n"
        f"Gewähltes Spiel: **{chosen_game}**\n"
        f"Gewinnerdetails wurden gespeichert und Spielerstatistiken aktualisiert."
    )
    #await interaction.channel.send(response_text)
    await send_tournament_end_announcement(interaction, winning_team, winning_points, chosen_game)
    
    # Jetzt: Ermittele den overall turnierübergreifenden Gewinner und weise ihm die Siegerrolle zu.
    overall_winner, wins = get_overall_winner()  # Gibt die User-ID als String und die Anzahl der Siege zurück
    if overall_winner is None:
        await interaction.response.send_message("Es wurden noch keine turnierübergreifenden Sieger ermittelt.", ephemeral=True)
        return

    # Löschen der alten tournament.json
    if os.path.exists(TOURNAMENT_FILE_PATH):
        try:
            os.remove(TOURNAMENT_FILE_PATH)
            logger.info("tournament.json wurde gelöscht.")
        except Exception as e:
            logger.error(f"Fehler beim Löschen von tournament.json: {e}")

    # Erstelle einen Discord-Mention-String aus der User-ID
    overall_winner_mention = f"<@{overall_winner}>"
    
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Kein Guild-Objekt gefunden.", ephemeral=True)
        return

    role_id_list = config.get("WINNER_ROLE_ID")
    logger.info(f"WINNER_ROLE_ID:{role_id_list}")
    if not role_id_list or not isinstance(role_id_list, list) or not role_id_list[0]:
        await interaction.response.send_message("WINNER_ROLE_ID nicht korrekt definiert.", ephemeral=False)
        return

    role_id = role_id_list[0]
    role = guild.get_role(int(role_id))
    if not role:
        await interaction.response.send_message("Gewinnerrolle nicht gefunden.", ephemeral=False)
        return

    member = guild.get_member(int(overall_winner))
    if not member:
        await interaction.response.send_message("Gewinner-Mitglied nicht gefunden.", ephemeral=True)
        return

    try:
        await member.add_roles(role, reason="Overall Turnier Gewinner")
        logger.info(f"Rolle '{role.name}' wurde an {member.display_name} vergeben.")
        await interaction.response.send_message(f"{overall_winner_mention} wurde die Siegerrolle zugewiesen!", ephemeral=False)
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen der Rolle: {e}")
        await interaction.response.send_message("Fehler beim Hinzufügen der Gewinnerrolle.", ephemeral=True)

def get_overall_winner() -> (str, int):
    """
    Ermittelt den Spieler (User-ID als String) mit den meisten turnierübergreifenden Siegen aus den player_stats.
    :return: Tuple (user_id, wins) des Spielers mit den meisten Siegen. Falls keine Daten vorhanden sind, wird (None, 0) zurückgegeben.
    """
    global_data = load_global_data()
    player_stats = global_data.get("player_stats", {})
    if not player_stats:
        return None, 0
    overall_winner, stats = max(player_stats.items(), key=lambda kv: kv[1].get("wins", 0))
    return overall_winner, stats.get("wins", 0)

async def send_tournament_announcement(interaction: discord.Interaction, registration_period: int):
    announcement_config = config.get("TOURNAMENT_ANNOUNCEMENT", {})
    end_time = datetime.now() + timedelta(seconds=registration_period)
    formatted_end = end_time.strftime("%d.%m.%Y um %H:%M")

    embed = Embed(
        title=announcement_config.get("title", "Turnier gestartet"),
        description=announcement_config.get("description", ""),
        color=0x5865F2
    )

    # Füge die Embed-Felder hinzu
    for field in announcement_config.get("fields", []):
        name = field.get("name", "")
        value = field.get("value", "").replace("PLACEHOLDER_ENDTIME", f"**{formatted_end} Uhr**")
        embed.add_field(name=name, value=value, inline=False)

    # Setze Footer
    footer_text = announcement_config.get("footer")
    if footer_text:
        embed.set_footer(
            text=footer_text,
            icon_url=interaction.client.user.avatar.url if interaction.client.user.avatar else None
        )

    await interaction.channel.send(embed=embed)

async def send_tournament_end_announcement(interaction: discord.Interaction, winning_team: str, points: int, game: str):
    embed_config = config.get("TOURNAMENT_ENDED_ANNOUNCEMENT", {})
    
    embed = Embed(
        title=embed_config.get("title", "Turnier beendet"),
        description=embed_config.get("description", ""),
        color=0x2ECC71  # ein schönes Grün zum Abschluss
    )

    for field in embed_config.get("fields", []):
        name = field.get("name", "")
        value = field.get("value", "")
        value = value.replace("PLACEHOLDER_WINNERTEAM", f"**{winning_team}**")
        value = value.replace("PLACEHOLDER_POINTS", f"**{points} Punkte**")
        value = value.replace("PLACEHOLDER_GAME", f"**{game}**")
        embed.add_field(name=name, value=value, inline=False)

    footer = embed_config.get("footer")
    if footer:
        embed.set_footer(text=footer)

    await interaction.channel.send(embed=embed)

async def send_poll_results_embed(interaction: discord.Interaction, poll_results: dict, chosen_game: str):
    embed_config = config.get("POLL_RESULT_EMBED", {})

    embed = Embed(
        title=embed_config.get("title", "Poll abgeschlossen"),
        description=embed_config.get("description", ""),
        color=0x5865F2  # Standardfarbe (Blau)
    )

    sorted_results = sorted(poll_results.items(), key=lambda kv: kv[1], reverse=True)

    for option, count in sorted_results:
        value = f"{count} Stimme" if count == 1 else f"{count} Stimmen"
        embed.add_field(name=option, value=value, inline=False)

    if sorted_results and sorted_results[0][1] > 0 and embed_config.get("highlight_winner", True):
        embed.add_field(
            name="🏆 Gewähltes Spiel",
            value=f"**{chosen_game}** 🎉",
            inline=False
        )
    else:
        embed.add_field(name="⚠ Kein Ergebnis", value="Kein Spiel hat Stimmen erhalten.", inline=False)

    footer = embed_config.get("footer")
    if footer:
        embed.set_footer(text=footer)

    embed.timestamp = datetime.utcnow()

    await interaction.channel.send(embed=embed)

async def send_registration_open_embed(interaction, end_time: datetime):
    embed_config = config.get("REGISTRATION_OPEN_ANNOUNCEMENT", {})

    formatted_end = end_time.strftime("%d.%m.%Y um %H:%M")

    # Platzhalter ersetzen
    raw_description = embed_config.get("description", "Die Anmeldung ist bis **PLACEHOLDER_ENDTIME Uhr** geöffnet.")
    description = raw_description.replace("PLACEHOLDER_ENDTIME", formatted_end)

    # Embed erstellen
    embed = Embed(
        title=embed_config.get("title", "📥 Anmeldung freigegeben!"),
        description=description,
        color=0x1ABC9C  # Türkis (standardmäßig)
    )

    # Footer setzen
    footer = embed_config.get("footer", "Reagiere schnell – begrenzte Zeit!")
    embed.set_footer(text=footer)

    # Optionaler Zeitstempel
    embed.timestamp = datetime.utcnow()

    await interaction.channel.send(embed=embed)