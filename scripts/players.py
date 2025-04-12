# players.py
import discord
import logging
from typing import Optional
from .dataStorage import save_tournament_data, load_tournament_data, load_config, CHANNEL_LIMIT_1
from .logger import setup_logger
from .utils import validate_string

# Konfiguration laden
config = load_config()
tournament = load_tournament_data()

# Logger laden
logger = setup_logger("logs", level=logging.INFO)

async def sign_in_team(interaction: discord.Interaction, mitspieler: discord.Member, teamname: str, anmeldungen: dict, save_anmeldungen):
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return

    # Eingabe validieren: Teamname darf beispielsweise nur 50 Zeichen lang sein.
    is_valid, error_message = validate_string(teamname)
    if not is_valid:
        await interaction.response.send_message(error_message, ephemeral=True)
        return
    
    # Prüfe, ob der Benutzer nicht sich selbst als Mitspieler angibt:
    if interaction.user.id == mitspieler.id:
        await interaction.response.send_message("Du kannst dich nicht selbst als Mitspieler angeben!", ephemeral=True)
        return
    
    # Hier prüfen, ob die Anmeldung aktiv sein soll (Turnier muss laufen):
    if not tournament.get("running", False):
        await interaction.response.send_message("Anmeldung nicht aktiv!", ephemeral=True)
        return

    spieler1_mention = interaction.user.mention   # Name des ersten Spielers
    spieler2_mention = mitspieler.mention          # Name des zweiten Spielers

    # Überprüfe, ob einer der Spieler bereits in einem Team ist
    for team, members in anmeldungen["teams"].items():
        if spieler1_mention in members or spieler2_mention in members:
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"Befehl 'abmelden' von {interaction.user} aufgerufen")
            return

    # Überprüfe, ob einer der Spieler bereits in der Solo-Liste steht
    if spieler1_mention in anmeldungen["solo"] or spieler2_mention in anmeldungen["solo"]:
        await interaction.response.send_message("❌ Einer der Spieler ist bereits angemeldet!", ephemeral=True)
        logger.info(f"Einer der User ({spieler1_mention, spieler2_mention}) ist bereits angemeldet")
        return

    # Speichere das Team
    anmeldungen["teams"][teamname] = [spieler1_mention, spieler2_mention]
    save_tournament_data(anmeldungen)

    await interaction.response.send_message(
        f"🏆 **Neue Team-Anmeldung!** 🏆\n"
        f"📌 **Team:** {teamname}\n"
        f"👤 **Spieler 1:** {interaction.user.mention}\n"
        f"👥 **Spieler 2:** {mitspieler.mention}\n"
        f"✅ Anmeldung gespeichert!",
        ephemeral=False
    )

async def sign_in_solo(interaction: discord.Interaction, anmeldungen: dict, save_anmeldungen):
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        logger.info(f"User {interaction.user} hat falschen Channel für Command verwendet")
        return
    
    # Prüfen, ob bereits ein Turnier läuft
    if not tournament.get("running", False):
        await interaction.response.send_message("Anmeldung nicht aktiv!", ephemeral=True)
        return

    spieler_mention = interaction.user.mention

    # Prüfe, ob der Spieler bereits in einem Team ist
    for team, members in anmeldungen.get("teams", {}).items():
        if spieler_mention in members:
            await interaction.response.send_message("❌ Du bist bereits in einem Team angemeldet!", ephemeral=True)
            logger.info(f"User {spieler_mention} ist bereits in einem Team angemeldet")
            return

    # Prüfe, ob der Spieler bereits in der Solo-Liste steht
    if spieler_mention in anmeldungen.get("solo", []):
        await interaction.response.send_message("❌ Du bist bereits in der Einzelspieler-Liste angemeldet!", ephemeral=True)
        logger.info(f"User {spieler_mention} ist bereits angemeldet")
        return

    # Füge den Spieler zur Solo-Liste hinzu
    anmeldungen.setdefault("solo", []).append(spieler_mention)
    save_tournament_data(anmeldungen)  # Hier wird das Dictionary übergeben

    await interaction.response.send_message(f"✅ {interaction.user.mention} wurde erfolgreich zur Einzelspieler-Liste hinzugefügt.", ephemeral=True)
    logger.info(f"User {interaction.user.name} ist bereits angemeldet")
    return

async def handle_sign_in(interaction: discord.Interaction, 
                   teamname: Optional[str] = None, 
                   mitspieler: Optional[discord.Member] = None,
                   anmeldungen: dict = None,
                   save_anmeldungen = None):
    """
    Meldet den Nutzer entweder als Solo oder als Team an, abhängig davon, ob
    zusätzliche Parameter angegeben wurden.
    
    - Keine Parameter → Einzelanmeldung
    - teamname und mitspieler angegeben → Teamanmeldung
    - Eine ungültige Kombination (nur ein Parameter) → Fehlermeldung
    """
    # Überprüfe, welche Parameter übergeben wurden:
    if teamname is None and mitspieler is None:
        # Einzelanmeldung
        await sign_in_solo(interaction, anmeldungen, save_anmeldungen)
    elif teamname is not None and mitspieler is not None:
        # Teamanmeldung
        await sign_in_team(interaction, mitspieler, teamname, anmeldungen, save_anmeldungen)
    else:
        # Ungültige Parameter-Kombination
        await interaction.response.send_message(
            "Bitte gib entweder keine zusätzlichen Parameter für eine Einzelanmeldung "
            "oder beide Parameter (Teamname und Mitspieler) für eine Teamanmeldung an.",
            ephemeral=True
        )

async def sign_out(interaction: discord.Interaction, anmeldungen: dict, save_anmeldungen):
    if interaction.channel_id != CHANNEL_LIMIT_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

    # Hole den Spielernamen aus der Interaction:
    spieler_name = interaction.user.name

    # Prüfe, ob der Spieler in einem Team ist.
    found_team = None
    for team, members in anmeldungen["teams"].items():
        if spieler_name in members:
            found_team = team
            break

    if found_team:
        # Entferne das Team und/oder melde den Nutzer ab
        del anmeldungen["teams"][found_team]
        save_tournament_data(anmeldungen)
        await interaction.response.send_message(f"✅ Du wurdest erfolgreich von Team ({found_team}) abgemeldet.", ephemeral=True)
        return

    # Prüfe, ob der Spieler in der Solo-Liste steht und entferne ihn
    if spieler_name in anmeldungen["solo"]:
        anmeldungen["solo"].remove(spieler_name)
        save_tournament_data(anmeldungen)
        await interaction.response.send_message("✅ Du wurdest erfolgreich aus der Einzelspieler-Liste entfernt.", ephemeral=True)
        return

    await interaction.response.send_message("⚠ Du bist weder in einem Team noch in der Einzelspieler-Liste angemeldet.", ephemeral=True)

async def list_participants(interaction: discord.Interaction, anmeldungen: dict) -> str:
    """
    Erstellt einen formatierten Text, der alle Teams und Einzelspieler auflistet.
    """
    teams = anmeldungen.get("teams", {})
    solo = anmeldungen.get("solo", [])
    
    total_teams = len(teams)
    total_solo = len(solo)
    
    lines = []
    lines.append("**Teilnehmerliste:**")
    lines.append(f"**Teams ({total_teams}):**")
    
    if total_teams:
        for teamname, members in teams.items():
            member_str = ", ".join(members)
            lines.append(f"- **{teamname}**: {member_str}")
    else:
        lines.append("Keine Teams angemeldet.")
    
    lines.append(f"\n**Solo-Spieler ({total_solo}):**")
    if total_solo:
        lines.append(", ".join(solo))
    else:
        lines.append("Keine Einzelspieler angemeldet.")
    
    return "\n".join(lines) 