# players.py
import discord
import logging
import re
from typing import Optional
from .dataStorage import save_tournament_data, load_tournament_data, load_config, CHANNEL_LIMIT_1
from .logger import setup_logger
from .utils import validate_string, validate_availability

# Konfiguration laden
config = load_config()
tournament = load_tournament_data()

# Logger laden
logger = setup_logger("logs", level=logging.INFO)

async def sign_in_team(
    interaction: discord.Interaction, 
    mitspieler: discord.Member, 
    teamname: str, 
    anmeldungen: dict, 
    verfugbarkeit: str
):
    # Prüfen des Channels
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user.display_name} hat falschen Kanal für Command verwendet")
        return

    # Lade aktuelle Daten
    current_tournament = load_tournament_data()
    if not current_tournament.get("running", False):
        await interaction.response.send_message("Anmeldung nicht aktiv!", ephemeral=True)
        return

    # Teamnamen validieren
    is_valid, error_message = validate_string(teamname)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    # Verfügbarkeitszeit validieren
    is_valid, error_message = validate_availability(verfugbarkeit)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    # Prüfe, ob der User nicht sich selbst als Mitspieler angibt
    if interaction.user.id == mitspieler.id:
        await interaction.response.send_message("Du kannst dich nicht selbst als Mitspieler angeben!", ephemeral=True)
        return

    spieler1_mention = interaction.user.mention
    spieler2_mention = mitspieler.mention

    # Prüfe, ob das Team bereits existiert
    if teamname in current_tournament.get("teams", {}):
        await interaction.response.send_message("Dieses Team existiert bereits!", ephemeral=True)
        return

    # Prüfe, ob einer der Spieler bereits in einem Team ist
    for team, team_entry in current_tournament.get("teams", {}).items():
        members = team_entry.get("members", [])
        if spieler1_mention in members or spieler2_mention in members:
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"User {spieler1_mention} oder {spieler2_mention} ist bereits in einem Team angemeldet")
            return

    # Prüfe, ob einer der Spieler bereits in der Solo-Liste steht
    for entry in current_tournament.get("solo", []):
        if entry.get("player") in (spieler1_mention, spieler2_mention):
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in der Einzelspieler-Liste angemeldet!", ephemeral=True)
            logger.info(f"User {spieler1_mention} oder {spieler2_mention} ist bereits als Solo angemeldet")
            return

    # Erstelle den neuen Team-Eintrag als Dictionary
    team_entry = {"members": [spieler1_mention, spieler2_mention], "verfügbarkeit": verfugbarkeit}
    current_tournament.setdefault("teams", {})[teamname] = team_entry
    save_tournament_data(current_tournament)

    await interaction.response.send_message(
        f"🏆 **Neue Team-Anmeldung!**\n"
        f"📌 **Team:** {teamname}\n"
        f"👤 **Spieler 1:** {spieler1_mention}\n"
        f"👥 **Spieler 2:** {spieler2_mention}\n"
        f"⏰**Verfügbar**: {verfugbarkeit}\n"
        f"✅ Anmeldung gespeichert!",
        ephemeral=False
    )

async def sign_in_solo(interaction: discord.Interaction, anmeldungen: dict, verfugbarkeit: str):
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return
    
    # Prüfen, ob bereits ein Turnier läuft
    current_tournament = load_tournament_data()
    if not current_tournament.get("running", False):
        await interaction.response.send_message("Anmeldung nicht aktiv!", ephemeral=True)
        return

    # Verfügbarkeitszeit validieren
    is_valid, error_message = validate_availability(verfugbarkeit)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    spieler_mention = interaction.user.mention

    # Prüfe, ob der Spieler bereits in einem Team ist
    for team, team_entry in anmeldungen["teams"].items():
        members = team_entry.get("members", [])
        if spieler1_mention in members or spieler2_mention in members:
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"Befehl 'abmelden' von {interaction.user.display_name} aufgerufen")
            return

    # Prüfe, ob der Spieler bereits in der Solo-Liste steht
    for entry in current_tournament.get("solo", []):
        if entry.get("player") == spieler_mention:
            await interaction.response.send_message("❌ Du bist bereits in der Einzelspieler-Liste angemeldet!", ephemeral=True)
            logger.info(f"User {interaction.user.display_name} ist bereits als Solo angemeldet")
            return

    # Füge den Spieler zur Solo-Liste hinzu
    entry = {"player": spieler_mention, "verfügbarkeit": verfugbarkeit}
    current_tournament.setdefault("solo", []).append(entry)
    save_tournament_data(current_tournament)
    await interaction.response.send_message(f"✅ {spieler_mention} wurde erfolgreich zur Einzelspieler-Liste hinzugefügt.", ephemeral=True)
    logger.info(f"User {interaction.user.display_name} wurde angemeldet")
    return

async def handle_sign_in(interaction: discord.Interaction, 
                           teamname: Optional[str] = None, 
                           mitspieler: Optional[discord.Member] = None,
                           anmeldungen: dict = None,
                           verfugbarkeit: str = None):
    if verfugbarkeit is None:
        await interaction.response.send_message("Bitte gib deine Verfügbarkeit (z.B. 12:00-18:00) an.", ephemeral=True)
        return

    if teamname is None and mitspieler is None:
        await sign_in_solo(interaction, anmeldungen, verfugbarkeit)
    elif teamname is not None and mitspieler is not None:
        await sign_in_team(interaction, mitspieler, teamname, anmeldungen, verfugbarkeit)
    else:
        await interaction.response.send_message(
            "Bitte gib entweder keine zusätzlichen Parameter für eine Einzelanmeldung oder beide Parameter (Teamname und Mitspieler) für eine Teamanmeldung an.",
            ephemeral=True
        )

async def sign_out(interaction: discord.Interaction):
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

    # Lade die aktuellen Turnierdaten frisch
    current_tournament = load_tournament_data()
    
    # Prüfe, ob derzeit ein Turnier läuft (z.B. ob registration_open einen bestimmten Status hat)
    if not current_tournament.get("running", False):
        await interaction.response.send_message("Moment kein Turnier aktiv.", ephemeral=True)
        return

    # Nutze die Discord-Mention als eindeutigen Identifikator
    user_mention = interaction.user.mention

    # Prüfe, ob der User in einem Team ist.
    found_team = None
    found_team_entry = None
    for team, team_entry in current_tournament.get("teams", {}).items():
        members = team_entry.get("members", [])
        if user_mention in members:
            found_team = team
            found_team_entry = team_entry
            break

    if found_team:
        # Prüfe, ob die Registrierung noch offen ist
        if current_tournament.get("registration_open", False):
            # Falls Registrierung noch offen ist: den abmeldenden User aus dem Team entfernen und den Partner in die Solo-Liste verschieben.
            # Hier: Lösche das ganze Team und füge den anderen Spieler in die Solo-Liste ein.
            other_members = [member for member in found_team_entry.get("members", []) if member != user_mention]
            del current_tournament["teams"][found_team]
            if other_members:
                # Versuche die alte Verfügbarkeit des Teams mitzunehmen
                verfugbarkeit = found_team_entry.get("verfügbarkeit", "")
                entry = {"player": other_members[0], "verfügbarkeit": verfugbarkeit}
                current_tournament.setdefault("solo", []).append(entry)
                logger.info(f"{other_members[0]} wurde aus Team '{found_team}' in die Solo-Liste übernommen mit Verfügbarkeit: {verfugbarkeit}")
                if not verfugbarkeit:
                    logger.warning(f"⚠ Spieler {other_members[0]} wurde ohne gültige Verfügbarkeit in die Solo-Liste aufgenommen. Bitte manuell prüfen oder updaten.")

            save_tournament_data(current_tournament)
            await interaction.response.send_message(
                f"✅ Du wurdest erfolgreich von Team {found_team} abgemeldet. Dein Team wurde aufgelöst und der andere Spieler wurde in die Einzelspieler-Liste verschoben.",
                ephemeral=True
            )
            return
        else:
            # Falls Registrierung geschlossen ist: Lösche das gesamte Team, ohne den Partner in die Solo-Liste aufzunehmen.
            del current_tournament["teams"][found_team]
            save_tournament_data(current_tournament)
            await interaction.response.send_message(
                f"✅ Du wurdest erfolgreich von Team {found_team} abgemeldet. Da die Anmeldung geschlossen ist, wurde das gesamte Team aufgelöst.",
                ephemeral=True
            )
            return

    # Falls der User nicht in einem Team gefunden wurde, prüfe, ob er in der Solo-Liste ist.
    for entry in current_tournament.get("solo", []):
        if entry.get("player") == user_mention:
            current_tournament["solo"].remove(entry)
            save_tournament_data(current_tournament)
            await interaction.response.send_message("✅ Du wurdest erfolgreich aus der Einzelspieler-Liste entfernt.", ephemeral=True)
            return

    await interaction.response.send_message("⚠ Du bist weder in einem Team noch in der Einzelspieler-Liste angemeldet.", ephemeral=True)

async def list_participants(interaction: discord.Interaction):
    """
    Erstellt einen formatierten Text, der alle Teams und Solo-Spieler auflistet.
    Bei Solo-Spielern wird erwartet, dass jeder Eintrag ein Dictionary mit mindestens
    dem Schlüssel "player" (Discord-Mention) und optional "verfügbarkeit" (Verfügbarkeitszeitraum) ist.
    """
    teams = anmeldungen.get("teams", {})
    solo = anmeldungen.get("solo", [])
    
    total_teams = len(teams)
    total_solo = len(solo)
    
    lines = []
    lines.append("**Teilnehmerliste:**")
    lines.append(f"**Teams ({total_teams}):**")
    
    if total_teams:
        for teamname, team_entry in teams.items():
            members = team_entry.get("members", [])
            # Hier wird jetzt der korrekte Schlüssel "verfügbarkeit" abgefragt
            avail = team_entry.get("verfügbarkeit", "")
            member_str = ", ".join(members)
            if avail:
                lines.append(f"- **{teamname}**: {member_str} (Verfügbar: {avail})")
            else:
                lines.append(f"- **{teamname}**: {member_str}")
    else:
        lines.append("Keine Teams angemeldet.")
    
    lines.append(f"\n**Solo-Spieler ({total_solo}):**")
    if total_solo:
        solo_strings = []
        for entry in solo:
            player = entry.get("player", "Unbekannt")
            avail = entry.get("verfügbarkeit", "")
            if avail:
                solo_strings.append(f"{player} (Verfügbar: {avail})")
            else:
                solo_strings.append(f"{player}")
        lines.append(", ".join(solo_strings))
    else:
        lines.append("Keine Einzelspieler angemeldet.")
    
    return "\n".join(lines)

async def update_availability_function(interaction: discord.Interaction, verfugbarkeit: str):
    """
    Aktualisiert den Verfügbarkeitszeitraum der Anmeldung.
    Der Zeitbereich muss im Format HH:MM-HH:MM vorliegen.
    """
    # Validierung des Eingabeformats (verwende deine validate_availability-Funktion)
    is_valid, error_message = validate_availability(verfugbarkeit)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    user_mention = interaction.user.mention
    tournament = load_tournament_data()
    updated = False
    team_name = None  # Wenn der User in einem Team ist

    # Zuerst: Überprüfe die Solo-Liste.
    for entry in tournament.get("solo", []):
        if entry.get("player") == user_mention:
            entry["verfügbarkeit"] = verfugbarkeit
            updated = True
            break

    # Falls nicht in der Solo-Liste, prüfe, ob der User in einem Team ist.
    if not updated:
        for tname, team_entry in tournament.get("teams", {}).items():
            if user_mention in team_entry.get("members", []):
                team_entry["verfügbarkeit"] = verfugbarkeit
                updated = True
                team_name = tname
                break

    if not updated:
        await interaction.response.send_message("Du bist in keiner Anmeldung gefunden.", ephemeral=True)
        return

    save_tournament_data(tournament)
    await interaction.response.send_message(
        f"Deine Verfügbarkeitszeit wurde auf {verfugbarkeit} aktualisiert.",
        ephemeral=True
    )

    # Falls der User in einem Team ist, aktualisiere auch den Spielplan für die betroffenen Matches
    if team_name:
        from .matchmaker import run_matchmaker  # Stelle sicher, dass run_matchmaker() deinen aktuellen Spielplan generiert
        schedule = run_matchmaker()  # Diese Funktion generiert den Spielplan basierend auf den Teams und deren 'verfügbarkeit'
        if schedule:
            lines = ["**Aktueller Spielplan:**"]
            for match in schedule:
                # Beispielausgabe: Datum, Startzeit und die beteiligten Teams
                lines.append(f"{match['date']} um {match['start_time']}: {match['team1']} vs. {match['team2']}")
            schedule_msg = "\n".join(lines)
            await interaction.channel.send(schedule_msg)
        else:
            await interaction.channel.send("Der Spielplan konnte nicht neu generiert werden (evtl. nicht genügend Teams mit Verfügbarkeitsangaben).")

async def force_sign_out(interaction, user: str):
    user_mention = user
    tournament = load_tournament_data()
    updated = False

    if not re.match(r"^<@!?(\d+)>$", user):
        await interaction.response.send_message("⚠ Bitte gib eine gültige Spieler-Mention ein (z. B. @Spieler).", ephemeral=True)
        return

    for team, team_entry in tournament.get("teams", {}).items():
        members = team_entry.get("members", [])
        if user_mention in members:
            # Team auflösen
            del tournament["teams"][team]
            logger.info(f"[ADMIN] Spieler {user_mention} wurde aus Team '{team}' entfernt. Team wurde aufgelöst.")

            # Übrig gebliebenes Teammitglied in Solo-Liste eintragen
            other_members = [m for m in members if m != user_mention]
            if other_members:
                verfugbarkeit = team_entry.get("verfügbarkeit", "")
                entry = {"player": other_members[0], "verfügbarkeit": verfugbarkeit}
                tournament.setdefault("solo", []).append(entry)
                logger.info(f"[ADMIN] Spieler {other_members[0]} wurde aus Team '{team}' in die Solo-Liste übernommen mit Verfügbarkeit: {verfugbarkeit}")
                if not verfugbarkeit:
                    logger.warning(f"[ADMIN] ⚠ Achtung: Spieler {other_members[0]} hat keine gültige Verfügbarkeit erhalten.")

            updated = True
            break


    # Falls der Spieler in der Solo-Liste ist:
    if not updated:
        for entry in tournament.get("solo", []):
            if entry.get("player") == user_mention:
                tournament["solo"].remove(entry)
                logger.info(f"[ADMIN] Spieler {user_mention} wurde aus der Solo-Liste entfernt.")
                updated = True
                break

    if updated:
        save_tournament_data(tournament)
        await interaction.response.send_message(f"✅ {user_mention} wurde erfolgreich aus dem Turnier entfernt.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠ {user_mention} ist weder in einem Team noch in der Solo-Liste registriert.", ephemeral=True)

def get_leaderboard() -> str:
    """
    Erzeugt einen formatierten Text, der das Leaderboard aller Teams anzeigt.
    Es werden die Teams nach der Anzahl ihrer Punkte (aus tournament["punkte"]) absteigend sortiert.
    
    :return: String mit Leaderboard-Informationen.
    """
    tournament = load_tournament_data()
    punkte = tournament.get("punkte", {})
    
    if not punkte:
        return "Noch keine Punkte vergeben."
    
    # Sortiere die Teams absteigend nach ihrer Punktzahl
    sorted_teams = sorted(punkte.items(), key=lambda kv: kv[1], reverse=True)
    
    lines = ["**Leaderboard**"]
    rank = 1
    for team, score in sorted_teams:
        lines.append(f"{rank}. **{team}** - {score} Punkt{'e' if score != 1 else ''}")
        rank += 1
    
    leaderboard_text = "\n".join(lines)
    logger.info("Leaderboard generiert.")
    return leaderboard_text