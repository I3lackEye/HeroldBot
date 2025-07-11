# modules/tournament.py

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import Embed, Interaction, app_commands
from discord.ext import commands

# Lokale Module
from modules import poll
from modules.archive import archive_current_tournament, update_tournament_history
from modules.dataStorage import (
    backup_current_state,
    delete_tournament_file,
    load_games,
    load_global_data,
    load_tournament_data,
    reset_tournament,
    save_tournament_data,
)
from modules.embeds import (
    build_embed_from_template,
    load_embed_template,
    send_list_matches,
    send_match_schedule_for_channel,
    send_registration_closed,
    send_tournament_announcement,
    send_tournament_end_announcement,
)
from modules.logger import logger
from modules.matchmaker import (
    auto_match_solo,
    cleanup_orphan_teams,
    create_round_robin_schedule,
    generate_and_assign_slots,
    generate_schedule_overview,
)
from modules.stats import (
    autocomplete_players,
    autocomplete_teams,
    get_mvp,
    get_winner_ids,
    get_winner_team,
    update_player_stats,
)
from modules.task_manager import add_task
from modules.utils import (
    all_matches_completed,
    autocomplete_teams,
    get_current_chosen_game,
    get_player_team,
    has_permission,
    smart_send,
    update_all_participants,
    update_player_stats,
)

# Global Var
_registration_closed = False


# ---------------------------------------
# Start Turnier Command
# ---------------------------------------
class TournamentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot



# ---------------------------------------
# Hilfsfunktion
# ---------------------------------------


async def end_tournament_procedure(
    channel: discord.TextChannel,
    manual_trigger: bool = False,
    interaction: Optional[Interaction] = None,
):
    tournament = load_tournament_data()

    if not manual_trigger and not all_matches_completed():
        logger.info("[TOURNAMENT] Nicht alle Matches abgeschlossen. Abbruch des automatischen Endes.")
        await channel.send("⚠️ Es sind noch nicht alle Matches abgeschlossen. Turnier bleibt offen.")
        return

    # Archivieren und aufräumen
    try:
        archive_path = archive_current_tournament()
        logger.info(f"[TOURNAMENT] Turnier archiviert unter: {archive_path}")
    except Exception as e:
        logger.error(f"[TOURNAMENT] Fehler beim Archivieren: {e}")

    backup_current_state()
    logger.info(f"[TOURNAMENT] Backup erfolgreich")

    # Gewinner, MVP usw.
    winner_ids = get_winner_ids()
    chosen_game = get_current_chosen_game()
    mvp = get_mvp()  # mvp als str z.b. <@1234567890>

    # Standardwert
    new_champion_id = None

    # MVP ID extrahieren, falls vorhanden
    if mvp:
        match = re.search(r"\d+", mvp)  # MVP könnte ein Mention wie <@1234567890> sein
        if match:
            new_champion_id = int(match.group(0))

    updated_count = await update_all_participants()
    logger.info(f"[TOURNAMENT] {updated_count} Teilnehmerstatistiken aktualisiert.")

    if winner_ids and chosen_game != "Unbekannt":
        update_player_stats(winner_ids, chosen_game)
        logger.info(f"[TOURNAMENT] Gewinner gespeichert: {winner_ids} für Spiel: {chosen_game}")
    else:
        logger.warning("[TOURNAMENT] Keine Gewinner oder kein Spielname gefunden.")

    update_tournament_history(
        winner_ids=winner_ids,
        chosen_game=chosen_game or "Unbekannt",
        mvp_name=mvp or "Kein MVP",
    )

    reset_tournament()

    try:
        delete_tournament_file()
        logger.info("[TOURNAMENT] Turnierdatei gelöscht.")
    except Exception as e:
        logger.error(f"[TOURNAMENT] Fehler beim Löschen der Turnierdatei: {e}")

    # Abschluss-Embed schicken
    mvp_message = f"🏆 MVP des Turniers: **{mvp}**!" if mvp else "🏆 Kein MVP ermittelt."
    await send_tournament_end_announcement(channel, mvp_message, winner_ids, new_champion_id)

    if mvp:  # Wenn MVP existiert
        try:
            guild = channel.guild  # Hole die Guild aus dem Channel
            mvp_id = int(mvp.strip("<@!>"))  # MVP aus Mention extrahieren
            await update_champion_role(guild, mvp_id)
        except Exception as e:
            logger.error(f"[CHAMPION] Fehler beim Aktualisieren der Champion-Rolle: {e}")

    logger.info("[TOURNAMENT] Turnier abgeschlossen und System bereit für Neues.")


async def auto_end_poll(bot: discord.Client, channel: discord.TextChannel, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    await poll.end_poll(bot, channel)


async def update_champion_role(guild: discord.Guild, new_champion_id: int, role_name: str = "Champion"):
    """
    Aktualisiert die Champion-Rolle im Server:
    - Entzieht die Rolle allen bisherigen Trägern
    - Verleiht die Rolle dem neuen Champion
    """
    # Rolle suchen
    champion_role = discord.utils.get(guild.roles, name=role_name)
    if not champion_role:
        logger.error(f"[CHAMPION] Rolle '{role_name}' nicht gefunden!")
        return

    # Neuen Champion zuweisen
    new_champion = guild.get_member(new_champion_id)
    if not new_champion:
        logger.error(f"[CHAMPION] Neuer Champion (User ID {new_champion_id}) nicht gefunden!")
        return

    # Check: Hat der neue Champion die Rolle schon?
    if champion_role in new_champion.roles:
        logger.info(
            f"[CHAMPION] Neuer Champion {new_champion.display_name} hat die Rolle bereits – keine Änderungen notwendig."
        )
        return

    # Alten Champion finden und Rolle entfernen
    for member in guild.members:
        if champion_role in member.roles:
            try:
                await member.remove_roles(champion_role, reason="Neuer Champion wurde vergeben.")
                logger.info(f"[CHAMPION] Champion-Rolle entfernt von {member.display_name}")
            except Exception as e:
                logger.error(f"[CHAMPION] Fehler beim Entfernen der Champion-Rolle von {member.display_name}: {e}")

    # Rolle dem neuen Champion geben
    try:
        await new_champion.add_roles(champion_role, reason="Turniersieg MVP.")
        logger.info(f"[CHAMPION] Champion-Rolle vergeben an {new_champion.display_name}")
    except Exception as e:
        logger.error(f"[CHAMPION] Fehler beim Vergeben der Champion-Rolle an {new_champion.display_name}: {e}")


# ---------------------------------------
# ⏳ Hintergrundaufgaben
# ---------------------------------------


async def close_registration_after_delay(delay_seconds: int, channel: discord.TextChannel):
    """
    Schließt die Anmeldung nach einer Verzögerung automatisch
    und startet das automatische Matchmaking & Cleanup.
    """
    tournament = load_tournament_data()  # always load data first

    global _registration_closed
    await asyncio.sleep(delay_seconds)

    if _registration_closed:
        logger.warning("[REGISTRATION] Ablauf bereits abgeschlossen – Doppelvermeidung aktiv.")
        return
    _registration_closed = True

    if not tournament.get("running", False):
        await channel.send(f"⚠️ Es läuft kein Turnier – Registrierung wird nicht geschlossen.")
        return

    if not tournament.get("registration_open", False):
        logger.warning("[CLOSE] Anmeldung war bereits geschlossen, fahre aber mit Matchplanung fort.")
    else:
        # Jetzt erst schließen
        tournament["registration_open"] = False
        save_tournament_data(tournament)
        await send_registration_closed(channel)
        logger.info("[TOURNAMENT] Anmeldung automatisch geschlossen.")

    # Verwaiste Teams aufräumen
    await cleanup_orphan_teams(channel)

    # Solo-Spieler automatisch matchen
    auto_match_solo()

    # Matchplan erstellen
    create_round_robin_schedule()

    # Alle übrig gebliebenen Solo-Spieler entfernen
    tournament = load_tournament_data()
    tournament["solo"] = []
    save_tournament_data(tournament)

    # Matches laden
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    # Slots generieren und Matches verteilen
    await generate_and_assign_slots()

    # Nach dem Verteilen neu laden
    tournament = load_tournament_data()
    matches = tournament.get("matches", [])

    # Überblick posten
    description_text = generate_schedule_overview(matches)
    await send_match_schedule_for_channel(channel, description_text)


async def close_tournament_after_delay(delay_seconds: int, channel: discord.TextChannel):
    await asyncio.sleep(delay_seconds)

    await end_tournament_procedure(channel)


async def setup(bot):
    await bot.add_cog(TournamentCog(bot))
