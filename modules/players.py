import discord
from discord import app_commands, Interaction, Member
from typing import Optional

# Lokale Module
from .dataStorage import load_tournament_data, save_tournament_data, config
from .utils import has_permission, parse_availability, validate_string, intersect_availability
from .logger import logger
from .embeds import send_help
from .stats import autocomplete_teams

# ----------------------------------------
# Slash-Commands
# ----------------------------------------

@app_commands.command(name="anmelden", description="Melde dich für das Turnier an (Solo oder Team).")
@app_commands.describe(
    verfugbarkeit="Deine allgemeine Verfügbarkeit (z.B. 10:00-20:00)",
    team_name="Teamname (optional, wenn du einem Team beitreten oder ein neues Team gründen möchtest)",
    samstag="Verfügbarkeit am Samstag (optional, z.B. 12:00-18:00)",
    sonntag="Verfügbarkeit am Sonntag (optional, z.B. 08:00-22:00)"
)
@app_commands.autocomplete(team_name=autocomplete_teams)
async def anmelden(
    interaction: Interaction,
    verfugbarkeit: str,
    team_name: Optional[str] = None,
    samstag: Optional[str] = None,
    sonntag: Optional[str] = None
 ):
    """
    Meldet einen Spieler für das Turnier an. Entweder Solo oder Team.
    """
    tournament = load_tournament_data()

    if not tournament.get("registration_open", False):
        await interaction.response.send_message("🚫 Die Anmeldung ist aktuell nicht geöffnet.", ephemeral=True)
        return

    # Validierung
    try:
        if verfugbarkeit:
            parse_availability(verfugbarkeit)
        if samstag:
            parse_availability(samstag)
        if sonntag:
            parse_availability(sonntag)
        if team_name:
            validate_string(team_name)
    except ValueError as e:
        await interaction.response.send_message(f"🚫 Ungültiges Format: {str(e)}", ephemeral=True)
        return

    user_mention = interaction.user.mention

    # Doppelte Anmeldung verhindern
    for solo in tournament.get("solo", []):
        if solo["player"] == user_mention:
            await interaction.response.send_message("⚠️ Du bist bereits als Einzelspieler angemeldet.", ephemeral=True)
            return

    for team, data in tournament.get("teams", {}).items():
        if user_mention in data.get("members", []):
            await interaction.response.send_message(f"⚠️ Du bist bereits im Team **{team}** angemeldet.", ephemeral=True)
            return

    if team_name:
        teams = tournament.setdefault("teams", {})

        if team_name in teams:
            # Team existiert ➔ Spieler tritt bei
            team_entry = teams[team_name]

            # Verfügbarkeits-Schnittmenge bilden
            existing_availability = team_entry.get("verfügbarkeit", "00:00-23:59")
            new_availability = intersect_availability(existing_availability, verfugbarkeit)

            if not new_availability:
                await interaction.response.send_message(
                    f"⚠️ Deine Verfügbarkeit überschneidet sich nicht mit dem Team {team_name}. Bitte stimmt euch ab!",
                    ephemeral=True
                )
                return

            team_entry["members"].append(user_mention)
            team_entry["verfügbarkeit"] = new_availability

            # Spezielle Verfügbarkeiten (Samstag/Sonntag) aktualisieren, falls vorhanden
            if samstag:
                team_entry["samstag"] = intersect_availability(team_entry.get("samstag", "00:00-23:59"), samstag)
            if sonntag:
                team_entry["sonntag"] = intersect_availability(team_entry.get("sonntag", "00:00-23:59"), sonntag)

            logger.info(f"[ANMELDUNG] {user_mention} ist Team {team_name} beigetreten.")
            await interaction.response.send_message(f"✅ Du bist dem Team **{team_name}** beigetreten!", ephemeral=True)

        else:
            # Neues Team gründen
            teams[team_name] = {
                "members": [user_mention],
                "verfügbarkeit": verfugbarkeit,
            }
            if samstag:
                teams[team_name]["samstag"] = samstag
            if sonntag:
                teams[team_name]["sonntag"] = sonntag

            logger.info(f"[ANMELDUNG] Neues Team {team_name} erstellt von {user_mention}.")
            await interaction.response.send_message(f"✅ Team **{team_name}** wurde erstellt und du bist beigetreten!", ephemeral=True)

    else:
        # Solo anmelden
        solo_entry = {
            "player": user_mention,
            "verfügbarkeit": verfugbarkeit
        }
        if samstag:
            solo_entry["samstag"] = samstag
        if sonntag:
            solo_entry["sonntag"] = sonntag

        tournament.setdefault("solo", []).append(solo_entry)
        logger.info(f"[ANMELDUNG] {user_mention} hat sich als Einzelspieler angemeldet.")
        await interaction.response.send_message(f"✅ Du wurdest erfolgreich als Solo-Spieler angemeldet!", ephemeral=True)

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
    channel_limit_ids = config.get("CHANNEL_LIMIT", {}).get("ID", [])
    if str(interaction.channel_id) not in channel_limit_ids:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

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

@app_commands.command(name="help", description="Zeigt alle wichtigen Infos und Befehle zum HeroldBot an.")
async def help_command(interaction: Interaction):
    """
    Zeigt das Hilfe-Embed an.
    """
    await send_help(interaction)