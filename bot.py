import discord
from discord import app_commands
import json
import os
import random

# Datei für die Speicherung der Anmeldungen
FILE_PATH = os.environ.get["DATABASE_PATH","anmeldung.json"]

# Erstelle eine Instanz des Bots mit allen Intents
intents = discord.Intents.default()
intents.members = True  # Notwendig, um Mitglieder zu erkennen
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Funktion zum Laden der Anmeldungen aus der Datei
def load_anmeldungen():
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    print("⚠ Fehler: {FILE_PATH} hatte ein falsches Format! Erstelle neue Datei.")
                    return {"teams": [], "solo": []}
                return data
        except json.JSONDecodeError:
            print("⚠ Fehler: {FILE_PATH} ist beschädigt! Leere Datei wird erstellt.")
            return {"teams": [], "solo": []}
    return {"teams": [], "solo": []}  # Falls Datei nicht existiert

# Funktion zum Speichern der Anmeldungen
def save_anmeldungen():
    with open(FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(anmeldungen, file, indent=4, ensure_ascii=False)

# Lade bestehende Anmeldungen beim Start
anmeldungen = load_anmeldungen()

# **Hilfsfunktion, um einen Spieler in @mention umzuwandeln**
def get_mention(guild, username):
    member = discord.utils.get(guild.members, name=username)
    return member.mention if member else username

@bot.event
async def on_ready():
    await tree.sync()  # Slash-Commands synchronisieren
    print(f'✅ {bot.user} ist online und bereit!')
    print(f'📌 Registrierte Slash-Commands: {[cmd.name for cmd in tree.get_commands()]}')

# **Anmelden als Team**
@tree.command(name="anmelden", description="Melde dich mit einem festen Team für das Turnier an.")
async def anmelden(interaction: discord.Interaction, spieler: discord.Member, teamname: str):
    team = {
        "teamname": teamname,
        "spieler1": interaction.user.name,
        "spieler2": spieler.name
    }

    anmeldungen["teams"].append(team)
    save_anmeldungen()
    
    await interaction.response.send_message(
        f"🏆 **Neue Turnier-Anmeldung!** 🏆\n"
        f"📌 **Team:** {teamname}\n"
        f"👤 **Spieler 1:** {interaction.user.mention}\n"
        f"👥 **Spieler 2:** {spieler.mention}\n"
        f"✅ Anmeldung gespeichert!",
        ephemeral=False
    )

# **Anmelden als Einzelspieler**
@tree.command(name="anmelden_solo", description="Melde dich alleine an, um später in ein Team zugeteilt zu werden.")
async def anmelden_solo(interaction: discord.Interaction):
    spieler_name = interaction.user.name

    # Prüfen, ob der Spieler bereits in einem Team ist
    for team in anmeldungen["teams"]:
        if spieler_name in (team["spieler1"], team["spieler2"]):
            await interaction.response.send_message("❌ Du bist bereits in einem Team angemeldet!", ephemeral=True)
            return

    if spieler_name in anmeldungen["solo"]:
        await interaction.response.send_message("❌ Du bist bereits in der Einzelspieler-Liste!", ephemeral=True)
        return

    anmeldungen["solo"].append(spieler_name)
    save_anmeldungen()

    await interaction.response.send_message(
        f"👤 **{interaction.user.mention}** wurde zur Einzelspieler-Liste hinzugefügt! 🎲",
        ephemeral=False
    )

# **Abmelden aus der Team-Liste**
@tree.command(name="abmelden", description="Entfernt dein Team aus der Turnierliste.")
async def abmelden(interaction: discord.Interaction):
    spieler_name = interaction.user.name
    found_team = None

    for team in anmeldungen["teams"]:
        if spieler_name in (team["spieler1"], team["spieler2"]):
            found_team = team
            break

    if found_team:
        spieler1_mention = get_mention(interaction.guild, found_team['spieler1'])
        spieler2_mention = get_mention(interaction.guild, found_team['spieler2'])
        teamname = found_team["teamname"]
        
        anmeldungen["teams"].remove(found_team)
        save_anmeldungen()
        
        await interaction.response.send_message(
            f"❌ **Team entfernt:** `{teamname}`\n"
            f"👤 **{spieler1_mention} & {spieler2_mention}** sind nun nicht mehr angemeldet.",
            ephemeral=False
        )
    else:
        await interaction.response.send_message("⚠ Du bist in keinem Team angemeldet!", ephemeral=True)

# **Abmelden aus der Einzelspieler-Liste**
@tree.command(name="abmelden_solo", description="Entfernt dich aus der Einzelspieler-Liste.")
async def abmelden_solo(interaction: discord.Interaction):
    spieler_name = interaction.user.name

    if spieler_name in anmeldungen["solo"]:
        anmeldungen["solo"].remove(spieler_name)
        save_anmeldungen()
        
        spieler_mention = get_mention(interaction.guild, spieler_name)
        
        await interaction.response.send_message(
            f"✅ **{spieler_mention}** wurde aus der Einzelspieler-Liste entfernt.",
            ephemeral=False
        )
    else:
        await interaction.response.send_message("⚠ Du bist nicht in der Einzelspieler-Liste!", ephemeral=True)


# **Teilnehmerliste anzeigen**
@tree.command(name="teilnehmer", description="Zeigt die aktuelle Teilnehmerliste.")
async def teilnehmer(interaction: discord.Interaction):
    total_teams = len(anmeldungen["teams"])
    total_solo_players = len(anmeldungen["solo"])
    total_players = total_teams * 2 + total_solo_players

    msg = f"🏆 **Aktuelle Turnierteilnehmer:**\n"
    msg += f"📊 **Teams insgesamt:** {total_teams}\n"
    msg += f"👥 **Spieler insgesamt:** {total_players}\n\n"

    if total_teams > 0:
        msg += "🔹 **Team-Anmeldungen:**\n"
        for team in anmeldungen["teams"]:
            spieler1_mention = get_mention(interaction.guild, team['spieler1'])
            spieler2_mention = get_mention(interaction.guild, team['spieler2'])
            msg += f"📌 **{team['teamname']}** – {spieler1_mention} & {spieler2_mention}\n"
        msg += "\n"

    if total_solo_players > 0:
        msg += "🎲 **Einzelspieler, die noch auf Teameinteilung warten:**\n"
        solo_mentions = [get_mention(interaction.guild, spieler) for spieler in anmeldungen["solo"]]
        msg += ", ".join(solo_mentions) + "\n"

    await interaction.response.send_message(msg, ephemeral=False)

# **Team zufällig generieren**
@tree.command(name="team_shuffle", description="Teilt alle Einzelspieler zufällig in 2er-Teams ein.")
async def team_shuffle(interaction: discord.Interaction):
    if len(anmeldungen["solo"]) < 2:
        await interaction.response.send_message("❌ Nicht genug Einzelspieler für eine zufällige Teameinteilung!", ephemeral=True)
        return

    random.shuffle(anmeldungen["solo"])
    neue_teams = []

    while len(anmeldungen["solo"]) >= 2:
        spieler1 = anmeldungen["solo"].pop(0)
        spieler2 = anmeldungen["solo"].pop(0)
        teamname = f"Team-{spieler1}-{spieler2}"

        team = {
            "teamname": teamname,
            "spieler1": spieler1,
            "spieler2": spieler2
        }

        anmeldungen["teams"].append(team)
        neue_teams.append(team)

    save_anmeldungen()

    msg = "🎲 **Neue zufällig generierte Teams:**\n"
    for team in neue_teams:
        spieler1_mention = get_mention(interaction.guild, team['spieler1'])
        spieler2_mention = get_mention(interaction.guild, team['spieler2'])
        msg += f"📌 **{team['teamname']}** – {spieler1_mention} & {spieler2_mention}\n"

    await interaction.response.send_message(msg, ephemeral=False)

# **Team umbenennen**
@tree.command(name="team_umbenennen", description="Ändert den Namen deines Teams.")
async def team_umbenennen(interaction: discord.Interaction, neuer_name: str):
    spieler_name = interaction.user.name
    found_team = None

    for team in anmeldungen["teams"]:
        if spieler_name in (team["spieler1"], team["spieler2"]):
            found_team = team
            break

    if found_team:
        alter_name = found_team["teamname"]
        found_team["teamname"] = neuer_name
        save_anmeldungen()
        await interaction.response.send_message(
            f"🔄 **Teamname geändert:** `{alter_name}` ➝ `{neuer_name}`",
            ephemeral=False
        )
    else:
        await interaction.response.send_message("⚠ Du bist in keinem Team angemeldet!", ephemeral=True)

# Startet den Bot
bot.run(os.environ["TOKEN"])