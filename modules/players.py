import discord
from discord import app_commands, Interaction, Member, Embed
from typing import Optional

# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data, config
from modules.utils import has_permission, parse_availability, validate_string, intersect_availability, generate_team_name
from modules.logger import logger
from modules.embeds import send_registration_confirmation, send_participants_overview, send_wrong_channel


# ----------------------------------------
# Hilfsfunktion 
# ----------------------------------------
def generate_participants_list() -> str:
    """
    Erstellt die Beschreibung für den Teilnehmer-Embed.
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
        return "Es sind noch keine Teilnehmer angemeldet."

    return "\n".join(lines)

# ----------------------------------------
# Slash-Commands
# ----------------------------------------

@app_commands.command(name="anmelden", description="Melde dich für das Turnier an (Solo oder Team).")
@app_commands.describe(
    verfugbarkeit="Deine allgemeine Verfügbarkeit (z.B. 10:00-20:00)",
    team_name="Teamname (optional, wenn du selbst einen vergeben möchtest)",
    team_random_name="Teamnamen automatisch generieren lassen?",
    mitspieler="Discord-Mitspieler, wenn du ein Team zusammen anmelden möchtest",
    samstag="Verfügbarkeit am Samstag (optional, z.B. 12:00-18:00)",
    sonntag="Verfügbarkeit am Sonntag (optional, z.B. 08:00-22:00)"
)
async def anmelden(
    interaction: Interaction,
    verfugbarkeit: str,
    team_name: Optional[str] = None,
    team_random_name: Optional[bool] = False,
    mitspieler: Optional[discord.Member] = None,
    samstag: Optional[str] = None,
    sonntag: Optional[str] = None
):
    """
    Meldet einen Spieler für das Turnier an (Solo, Teamgründung oder Teambeitritt).
    """
    tournament = load_tournament_data()

    if not tournament.get("registration_open", False):
        await interaction.response.send_message("🚫 Die Anmeldung ist aktuell nicht geöffnet.", ephemeral=True)
        return

    # Validierung
    try:
        parse_availability(verfugbarkeit)
        if samstag:
            parse_availability(samstag)
        if sonntag:
            parse_availability(sonntag)
    except ValueError as e:
        await interaction.response.send_message(f"🚫 Ungültiges Format: {str(e)}", ephemeral=True)
        return

    user_mention = interaction.user.mention

    # Check: Spieler schon angemeldet?
    for solo in tournament.get("solo", []):
        if solo["player"] == user_mention:
            await interaction.response.send_message("⚠️ Du bist bereits als Einzelspieler angemeldet.", ephemeral=True)
            return
    for team_data in tournament.get("teams", {}).values():
        if user_mention in team_data.get("members", []):
            await interaction.response.send_message("⚠️ Du bist bereits in einem Team angemeldet.", ephemeral=True)
            return

    # === TEAM-ANMELDUNG ===
    if team_name or team_random_name:
        teams = tournament.setdefault("teams", {})

        # Falls zufälliger Name gewünscht
        if team_random_name:
            team_name = generate_team_name()
            tries = 0
            while team_name in teams and tries < 5:
                team_name = generate_team_name()
                tries += 1
            if tries >= 5:
                await interaction.response.send_message("🚫 Konnte keinen freien Teamnamen finden. Bitte versuche es erneut.", ephemeral=True)
                return
            logger.info(f"[ANMELDUNG] Zufälliger Teamname generiert: {team_name}")

        # Name prüfen
        if team_name in teams:
            await interaction.response.send_message(f"⚠️ Das Team **{team_name}** existiert bereits. Bitte wähle einen anderen Namen.", ephemeral=True)
            return

        # Zusatzcheck: Mitspieler
        mitspieler_mention = None
        if mitspieler:
            if mitspieler.id == interaction.user.id:
                await interaction.response.send_message("⚠️ Du kannst dich nicht selbst als Mitspieler angeben.", ephemeral=True)
                return
            for team_data in teams.values():
                if mitspieler.mention in team_data.get("members", []):
                    await interaction.response.send_message(f"⚠️ {mitspieler.display_name} ist bereits in einem anderen Team angemeldet.", ephemeral=True)
                    return
            mitspieler_mention = mitspieler.mention

        # Team anlegen
        team_entry = {
            "members": [user_mention],
            "verfügbarkeit": verfugbarkeit,
        }
        if mitspieler_mention:
            team_entry["members"].append(mitspieler_mention)

        if samstag:
            team_entry["samstag"] = samstag
        if sonntag:
            team_entry["sonntag"] = sonntag

        teams[team_name] = team_entry

        logger.info(f"[ANMELDUNG] {user_mention} hat Team {team_name} gegründet. Mitspieler: {mitspieler.display_name if mitspieler else 'keiner'}")

        detail_text = f"Mitspieler: {mitspieler.display_name}" if mitspieler else "Du startest alleine."
        await send_registration_confirmation(interaction, {
            "TYPE": f"im neuen Team **{team_name}**",
            "DETAILS": detail_text
        })

    # === SOLO-ANMELDUNG ===
    else:
        solo_entry = {
            "player": user_mention,
            "verfügbarkeit": verfugbarkeit
        }
        if samstag:
            solo_entry["samstag"] = samstag
        if sonntag:
            solo_entry["sonntag"] = sonntag

        tournament.setdefault("solo", []).append(solo_entry)

        logger.info(f"[ANMELDUNG] {user_mention} hat sich als Solo-Spieler angemeldet.")

        await send_registration_confirmation(interaction, {
            "TYPE": "als Solo-Spieler",
            "DETAILS": "Du nimmst alleine am Turnier teil."
        })

    save_tournament_data(tournament)

@app_commands.command(name="update_availability", description="Aktualisiere deine Verfügbarkeiten für das Turnier.")
@app_commands.describe(
    verfugbarkeit="Allgemeine Verfügbarkeit (z.B. 10:00-20:00)",
    samstag="Verfügbarkeit am Samstag (z.B. 12:00-18:00)",
    sonntag="Verfügbarkeit am Sonntag (z.B. 08:00-22:00)"
)
async def update_availability(
    interaction: Interaction,
    verfugbarkeit: Optional[str] = None,
    samstag: Optional[str] = None,
    sonntag: Optional[str] = None
    ):
    """
    Aktualisiert die Verfügbarkeit eines Spielers im Turnier.
    Mindestens einer der Parameter (verfugbarkeit, samstag oder sonntag) muss angegeben werden.
    """
    if not any([verfugbarkeit, samstag, sonntag]):
        await interaction.response.send_message("⚠️ Bitte gib mindestens eine Verfügbarkeit an (verfugbarkeit, samstag oder sonntag).", ephemeral=True)
        return

    # Verfügbarkeiten prüfen
    try:
        if verfugbarkeit:
            parse_availability(verfugbarkeit)
        if samstag:
            parse_availability(samstag)
        if sonntag:
            parse_availability(sonntag)
    except ValueError as e:
        await interaction.response.send_message(f"🚫 Ungültiges Format: {str(e)}", ephemeral=True)
        return

    # Turnierdaten laden
    tournament = load_tournament_data()
    updated = False

    # Solo-Teilnehmer aktualisieren
    for entry in tournament.get("solo", []):
        if entry["player"] == interaction.user.mention:
            if verfugbarkeit:
                entry["verfügbarkeit"] = verfugbarkeit
            if samstag:
                entry["samstag"] = samstag
            if sonntag:
                entry["sonntag"] = sonntag
            updated = True
            break

    # Team-Mitglieder aktualisieren
    for team_data in tournament.get("teams", {}).values():
        if interaction.user.mention in team_data.get("members", []):
            if verfugbarkeit:
                team_data["verfügbarkeit"] = verfugbarkeit
            if samstag:
                team_data["samstag"] = samstag
            if sonntag:
                team_data["sonntag"] = sonntag
            updated = True
            break

    if not updated:
        await interaction.response.send_message("⚠️ Du bist aktuell in keinem Team oder auf der Solo-Liste eingetragen.", ephemeral=True)
        return

    save_tournament_data(tournament)
    await interaction.response.send_message("✅ Deine Verfügbarkeit wurde erfolgreich aktualisiert!", ephemeral=True)

@app_commands.command(name="sign_out", description="Melde dich vom Turnier ab.")
async def sign_out(interaction: Interaction):
    """
    Meldet den User vom Turnier ab.
    """

    tournament = load_tournament_data()

    if not tournament.get("running", False):
        await interaction.response.send_message("Momentan läuft kein Turnier.", ephemeral=True)
        return

    user_mention = interaction.user.mention
    user_name = interaction.user.display_name
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

                 # Namen auflösen
                other_id = int(other_members[0].strip("<@>"))
                other_member = interaction.guild.get_member(other_id)
                other_name = other_member.display_name if other_member else other_members[0]
                
                logger.info(f"[SIGN OUT] {other_name[0]} wurde aus Team {found_team} in die Solo-Liste übernommen.")
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] {user_name} hat Team {found_team} verlassen. Team wurde aufgelöst.")
            await interaction.response.send_message(f"✅ Du wurdest erfolgreich von Team {found_team} abgemeldet.", ephemeral=True)
            return
        else:
            del tournament["teams"][found_team]
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] {user_name} hat Team {found_team} verlassen. Turnier war bereits geschlossen.")
            await interaction.response.send_message(f"✅ Dein Team {found_team} wurde entfernt.", ephemeral=True)
            return

    for entry in tournament.get("solo", []):
        if entry.get("player") == user_mention:
            tournament["solo"].remove(entry)
            save_tournament_data(tournament)
            logger.info(f"[SIGN OUT] Solo-Spieler {user_name} wurde erfolgreich abgemeldet.")
            await interaction.response.send_message("✅ Du wurdest erfolgreich aus der Solo-Liste entfernt.", ephemeral=True)
            return

    logger.warning(f"[SIGN OUT] {user_name} wollte sich abmelden, wurde aber nicht gefunden.")
    await interaction.response.send_message("⚠ Du bist weder in einem Team noch in der Solo-Liste angemeldet.", ephemeral=True)

@app_commands.command(name="participants", description="Liste aller Teilnehmer anzeigen.")
async def participants(interaction: Interaction):
    """
    Listet alle aktuellen Teilnehmer (Teams und Einzelspieler), alphabetisch sortiert.
    """
    tournament = load_tournament_data()

    teams = tournament.get("teams", {})
    solo = tournament.get("solo", [])

    # Teams alphabetisch sortieren
    sorted_teams = sorted(teams.items(), key=lambda x: x[0].lower())

    # Solo-Spieler alphabetisch sortieren (nach Mention)
    sorted_solo = sorted(solo, key=lambda x: x.get("player", "").lower())

    team_lines = []
    for name, team_entry in sorted_teams:
        members = ", ".join(team_entry.get("members", []))
        team_lines.append(f"- {name}: {members}")

    solo_lines = []
    for solo_entry in sorted_solo:
        solo_lines.append(f"- {solo_entry.get('player')}")

    # Text zusammensetzen
    full_text = ""

    if team_lines:
        full_text += "**Teams:**\n" + "\n".join(team_lines) + "\n\n"

    if solo_lines:
        full_text += "**Einzelspieler:**\n" + "\n".join(solo_lines)

    if not full_text:
        await interaction.response.send_message("❌ Es sind noch keine Teilnehmer angemeldet.", ephemeral=True)
    else:
        await send_participants_overview(interaction, full_text)
