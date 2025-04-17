import discord
from discord import app_commands, Interaction, Member
from typing import Optional
from .dataStorage import load_tournament_data, save_tournament_data
from .utils import has_permission, validate_availability
from .logger import setup_logger
from .matchmaker import run_matchmaker

logger = setup_logger("logs")

# ----------------------------------------
# Lokale Hilfsfunktionen
# ----------------------------------------

async def handle_sign_in(interaction: Interaction, verfugbarkeit: str, mitspieler: Optional[Member] = None, teamname: Optional[str] = None):
    anmeldungen = load_tournament_data()

    if not verfugbarkeit:
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

async def sign_in_solo(interaction: Interaction, anmeldungen: dict, verfugbarkeit: str):
    user = interaction.user
    spieler_mention = user.mention

    # Doppelte Anmeldung verhindern
    for team_entry in anmeldungen.get("teams", {}).values():
        members = team_entry.get("members", [])
        if spieler_mention in members:
            await interaction.response.send_message("❌ Du bist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"User {user.display_name} ist bereits in einem Team angemeldet.")
            return

    for solo_entry in anmeldungen.get("solo", []):
        if solo_entry.get("player") == spieler_mention:
            await interaction.response.send_message("❌ Du bist bereits als Einzelspieler angemeldet!", ephemeral=True)
            logger.info(f"User {user.display_name} ist bereits als Einzelspieler angemeldet.")
            return

    # Anmeldung speichern
    anmeldungen.setdefault("solo", []).append({
        "player": spieler_mention,
        "verfügbarkeit": verfugbarkeit
    })
    save_tournament_data(anmeldungen)
    logger.info(f"User {user.display_name} hat sich erfolgreich als Solo-Spieler angemeldet.")

    await interaction.response.send_message(f"✅ {spieler_mention}, du bist erfolgreich als Einzelspieler angemeldet.", ephemeral=True)

async def sign_in_team(interaction: Interaction, mitspieler: Member, teamname: str, anmeldungen: dict, verfugbarkeit: str):
    user = interaction.user
    user_mention = user.mention
    mitspieler_mention = mitspieler.mention

    # Doppelte Anmeldungen verhindern
    for team_entry in anmeldungen.get("teams", {}).values():
        members = team_entry.get("members", [])
        if user_mention in members or mitspieler_mention in members:
            await interaction.response.send_message("❌ Einer von euch ist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"Anmeldung fehlgeschlagen: {user.display_name} oder {mitspieler.display_name} ist bereits in einem Team.")
            return

    for solo_entry in anmeldungen.get("solo", []):
        if solo_entry.get("player") in (user_mention, mitspieler_mention):
            await interaction.response.send_message("❌ Einer von euch ist bereits als Einzelspieler angemeldet!", ephemeral=True)
            logger.info(f"Anmeldung fehlgeschlagen: {user.display_name} oder {mitspieler.display_name} ist bereits als Einzelspieler angemeldet.")
            return

    # Anmeldung speichern
    anmeldungen.setdefault("teams", {})[teamname] = {
        "members": [user_mention, mitspieler_mention],
        "verfügbarkeit": verfugbarkeit
    }
    save_tournament_data(anmeldungen)
    logger.info(f"Team {teamname} ({user.display_name} und {mitspieler.display_name}) wurde erfolgreich angemeldet.")

    await interaction.response.send_message(f"✅ Team **{teamname}** ({user_mention} und {mitspieler_mention}) wurde erfolgreich angemeldet!", ephemeral=True)

# ----------------------------------------
# Slash-Commands
# ----------------------------------------

@app_commands.command(name="anmelden", description="Melde dich für das Turnier an.")
@app_commands.describe(
    verfugbarkeit="Deine Verfügbarkeit (z.B. 12:00-18:00)",
    mitspieler="Optional: Wähle einen Mitspieler aus.",
    teamname="Optional: Teamname angeben"
)
async def anmelden(interaction: Interaction, verfugbarkeit: str, mitspieler: Optional[Member] = None, teamname: Optional[str] = None):
    await handle_sign_in(interaction, verfugbarkeit, mitspieler, teamname)

@app_commands.command(name="update_availability", description="Aktualisiere deinen Verfügbarkeitszeitraum.")
@app_commands.describe(verfugbarkeit="Neuer Verfügbarkeitszeitraum im Format HH:MM-HH:MM (z.B. 12:00-18:00)")
async def update_availability(interaction: Interaction, verfugbarkeit: str):
    """
    Aktualisiert den Verfügbarkeitszeitraum der Anmeldung.
    """
    is_valid, error_message = validate_availability(verfugbarkeit)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return

    user_mention = interaction.user.mention
    tournament = load_tournament_data()
    updated = False
    team_name = None

    for entry in tournament.get("solo", []):
        if entry.get("player") == user_mention:
            entry["verfügbarkeit"] = verfugbarkeit
            updated = True
            break

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
        f"✅ Deine Verfügbarkeit wurde auf {verfugbarkeit} aktualisiert.",
        ephemeral=True
    )

    if team_name:
        schedule = run_matchmaker()
        if schedule:
            lines = ["**Aktueller Spielplan:**"]
            for match in schedule:
                lines.append(f"{match['date']} um {match['start_time']}: {match['team1']} vs. {match['team2']}")
            schedule_msg = "\n".join(lines)
            await interaction.channel.send(schedule_msg)
        else:
            await interaction.channel.send("⚠ Kein neuer Spielplan verfügbar.")

@app_commands.command(name="sign_out", description="Melde dich vom Turnier ab.")
async def sign_out_command(interaction: Interaction):
    """
    Meldet den User vom Turnier ab.
    """
    from ..config import CHANNEL_LIMIT_1

    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

    tournament = load_tournament_data()

    if not tournament.get("running", False):
        await interaction.response.send_message("Momentan läuft kein Turnier.", ephemeral=True)
        return

    user_mention = interaction.user.mention
    found_team = None
    found_team_entry = None

    for team, team_entry in tournament.get("teams", {}).items():
        if user_mention in team_entry.get("members", []):
            found_team = team
            found_team_entry = team_entry
            break

    if found_team:
        if tournament.get("registration_open", False):
            other_members = [m for m in found_team_entry.get("members", []) if m != user_mention]
            del tournament["teams"][found_team]
            if other_members:
                verfugbarkeit = found_team_entry.get("verfügbarkeit", "")
                tournament.setdefault("solo", []).append({"player": other_members[0], "verfügbarkeit": verfugbarkeit})
                logger.info(f"[SIGN OUT] {other_members[0]} wurde aus Team {found_team} in die Solo-Liste übernommen.")
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] {user_mention} hat Team {found_team} verlassen. Team wurde aufgelöst.")
            await interaction.response.send_message(f"✅ Du wurdest erfolgreich von Team {found_team} abgemeldet.", ephemeral=True)
            return
        else:
            del tournament["teams"][found_team]
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] {user_mention} hat Team {found_team} verlassen. Turnier war bereits geschlossen.")
            await interaction.response.send_message(f"✅ Dein Team {found_team} wurde entfernt.", ephemeral=True)
            return

    for entry in tournament.get("solo", []):
        if entry.get("player") == user_mention:
            tournament["solo"].remove(entry)
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] Solo-Spieler {user_mention} wurde erfolgreich abgemeldet.")
            await interaction.response.send_message("✅ Du wurdest erfolgreich aus der Solo-Liste entfernt.", ephemeral=True)
            return

    logger.warning(f"[SIGN OUT] {user_mention} wollte sich abmelden, wurde aber nicht gefunden.")
    await interaction.response.send_message("⚠ Du bist weder in einem Team noch in der Solo-Liste angemeldet.", ephemeral=True)

@app_commands.command(name="participants", description="Liste aller Teilnehmer anzeigen.")
async def participants(interaction: Interaction):
    """
    Listet alle aktuellen Teilnehmer.
    """
    tournament = load_tournament_data()

    teams = tournament.get("teams", {})
    solo = tournament.get("solo", [])

    lines = []

    if teams:
        lines.append("**Teams:**")
        for name, team_entry in teams.items():
            members = ", ".join(team_entry.get("members", []))
            lines.append(f"- {name}: {members}")
    if solo:
        lines.append("\n**Einzelspieler:**")
        for solo_entry in solo:
            lines.append(f"- {solo_entry.get('player')}")

    if not lines:
        await interaction.response.send_message("Es sind noch keine Teilnehmer angemeldet.", ephemeral=True)
    else:
        await interaction.response.send_message("\n".join(lines), ephemeral=False)
