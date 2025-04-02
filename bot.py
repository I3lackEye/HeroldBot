import discord
from discord import app_commands
import json
import os
import random
import logging

LIMITED_CHANNEL_ID_1 = 1351213319104761937 #Limited to channel "wettkampf"
LIMITED_CHANNEL_ID_2 = 1351583903348953109 #Limited to channel "leaderboard"

# **Logging für Discord-Events aktivieren**
logger = logging.getLogger("discord")  # Nutzt das interne Discord-Logging
logger.setLevel(logging.INFO)  # Setzt das Log-Level (ändern auf DEBUG für mehr Details)

# **FileHandler für Logging in `discord.log`**
handler = logging.FileHandler(filename="debug.log", encoding="utf-8", mode="w")
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
handler.setFormatter(formatter)

logger.addHandler(handler)  # Logger mit dem FileHandler verknüpfen

# **Zusätzliches Logging für eigene Events**
bot_logger = logging.getLogger("HeroldBot")
bot_logger.setLevel(logging.INFO)
bot_logger.addHandler(handler)

# Datei für die Speicherung der Anmeldungen
FILE_PATH = os.environ["DATABASE_PATH"]

# Funktion zum Laden der Anmeldungen aus der Datei
def load_anmeldungen():
    if os.path.exists(FILE_PATH):
        try:
            with open(FILE_PATH, "r", encoding="utf-8") as file:
                data = json.load(file)
                if not isinstance(data, dict):
                    print("⚠ Fehler: Datei hat ein falsches Format! Erstelle neue Datei.")
                    return {"teams": {}, "solo": [], "punkte": {}}
                return data
        except json.JSONDecodeError:
            print("⚠ Fehler: Datei ist beschädigt! Erstelle eine leere Datei.")
            return {"teams": {}, "solo": [], "punkte": {}}
    return {"teams": {}, "solo": [], "punkte": {}}  # Falls Datei nicht existiert

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

# **Hilfsfunktion: Prüft, ob der Nutzer eine bestimmte Rolle hat**
def has_permission(interaction: discord.Interaction, allowed_roles=["Moderator", "Lappen des Vertrauens"]):
    return any(role.name in allowed_roles for role in interaction.user.roles)

# Globaler Speicher für den aktuellen Matchplan (Liste von Dicts)
# Jeder Eintrag: { "date": "YYYY-MM-DD", "match": (TeamA, TeamB), "time": "HH:MM" oder None }
match_plan = []

# --- Funktionen zum Erzeugen des Matchplans ---

# Erzeugt aus den registrierten Teams zufällige Paarungen.
# Hinweis: Bei ungerader Anzahl wird das letzte Team in diesem Beispiel nicht berücksichtigt.
def generate_matches(teams: dict):
    team_names = list(teams.keys())
    random.shuffle(team_names)
    matches = []
    for i in range(0, len(team_names) - 1, 2):
        matches.append((team_names[i], team_names[i+1]))
    return matches

# Gibt für einen gegebenen Index (0,1,2,...) ein Datum zurück:
# Index 0 -> nächster Samstag, 1 -> nächster Sonntag, 2 -> übernächster Samstag, 3 -> übernächster Sonntag, usw.
def get_dates(i: int) -> datetime.date:
    today = datetime.date.today()
    # Berechne den nächsten Samstag:
    days_ahead = (5 - today.weekday()) % 7  # Samstag hat weekday 5
    next_saturday = today + datetime.timedelta(days=days_ahead)
    if i % 2 == 0:
        # Samstag eines bestimmten Wochenendes
        return next_saturday + datetime.timedelta(days=(i // 2) * 7)
    else:
        # Sonntag desselben Wochenendes
        return next_saturday + datetime.timedelta(days=1 + (i // 2) * 7)

# Erzeugt einen Matchplan (nur Datum und Platzhalter für die Uhrzeit)
# Es werden pro Tag maximal zwei Matches eingeplant.
def generate_plan(matches):
    scheduled_days = {}  # Mapping: Datum (als String) -> Liste von Matches (Tupel)
    day_index = 0
    plan = []

    for match in matches:
        assigned = False
        # Suche das früheste Datum, an dem weder eines der Teams bereits spielt noch bereits 2 Matches geplant sind.
        while not assigned:
            current_date = get_dates(day_index)
            date_str = current_date.isoformat()
            matches_today = scheduled_days.get(date_str, [])
            # Prüfe, ob eines der Teams in diesem Tag schon eingeplant ist
            conflict = False
            for m in matches_today:
                if match[0] in m or match[1] in m:
                    conflict = True
                    break
            if not conflict and len(matches_today) < 2:
                # Match an diesem Datum einplanen
                matches_today.append(match)
                scheduled_days[date_str] = matches_today
                plan.append({
                    "date": date_str,
                    "match": match,
                    "time": None  # Zeit wird später von den Spielern gesetzt
                })
                assigned = True
            else:
                # Entweder Konflikt oder bereits zwei Matches an diesem Tag – probiere den nächsten Tag
                day_index += 1
    # Sortiere den Plan nach Datum
    plan.sort(key=lambda x: x["date"])
    return plan

# --- Slash-Commands ---

# Erstelle eine Instanz des Bots mit allen Intents
intents = discord.Intents.default()
intents.members = True  # Notwendig, um Mitglieder zu erkennen
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    await tree.sync()  # Slash-Commands synchronisieren
    bot_logger.info(f'✅ {bot.user} ist online und bereit!')
    bot_logger.info(f'Registrierte Slash-Commands: {[cmd.name for cmd in tree.get_commands()]}')

# **Logger für Fehlermeldungen**
@bot.event
async def on_error(event, *args, **kwargs):
    bot_logger.error(f"⚠ Fehler im Event `{event}`: {args}, {kwargs}")

# **Logger für Befehle**
@tree.command(name="test_log", description="Testet den Logger.")
async def test_log(interaction: discord.Interaction):
    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return
    bot_logger.info(f"{interaction.user} hat /test_log benutzt.")
    await interaction.response.send_message("✅ Logger funktioniert!", ephemeral=True)

# **Anmelden als Team**
@tree.command(name="anmelden", description="Melde dich mit einem festen Team für das Turnier an.")
async def anmelden(interaction: discord.Interaction, mitspieler: discord.Member, teamname: str):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    
    spieler1_name = interaction.user.name  # Name des ersten Spielers
    spieler2_name = mitspieler.name  # Name des zweiten Spielers

    # Prüfen, ob einer der Spieler bereits in einem Team ist
    for team, members in anmeldungen["teams"].items():
        if spieler1_name in members or spieler2_name in members:
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in einem Team angemeldet!", ephemeral=True)
            return

    # Prüfen, ob der Spieler bereits in Solo eingetragen ist
    if spieler1_name in anmeldungen["solo"] or spieler2_name in anmeldungen["solo"]:
        await interaction.response.send_message("❌ Einer der Spieler ist bereits Angemeldet!", ephemeral=True)
        return

    # Team speichern
    anmeldungen["teams"][teamname] = [spieler1_name, spieler2_name]
    save_anmeldungen()
    
    await interaction.response.send_message(
        f"🏆 **Neue Team-Anmeldung!** 🏆\n"
        f"📌 **Team:** {teamname}\n"
        f"👤 **Spieler 1:** {interaction.user.mention}\n"
        f"👥 **Spieler 2:** {mitspieler.mention}\n"
        f"✅ Anmeldung gespeichert!",
        ephemeral=False
    )

# **Anmelden als Einzelspieler**
@tree.command(name="anmelden_solo", description="Melde dich alleine an, um später in ein Team zugeteilt zu werden.")
async def anmelden_solo(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    spieler_name = interaction.user.name

    # Prüfen, ob der Spieler bereits in einem Team ist
    for team_name, members in anmeldungen["teams"].items():
        if spieler_name in members:
            await interaction.response.send_message("❌ Du bist bereits in einem Team angemeldet!", ephemeral=True)
            return
    
    # Prüfen, ob der Spieler bereits in Solo eingetragen ist
    if spieler_name in anmeldungen["solo"]:
        await interaction.response.send_message("❌ Du bist bereits in der Einzelspieler-Liste!", ephemeral=True)
        return

    anmeldungen["solo"].append(spieler_name)
    save_anmeldungen()

    await interaction.response.send_message(
        f"👤 **{interaction.user.mention}** wurde zur Einzelspieler-Liste hinzugefügt! 🎲",
        ephemeral=False
    )

# **Abmelden aus Teilnehmerliste**
@tree.command(name="abmelden", description="Entfernt dich aus dem Turnier (egal ob Team oder Einzelanmeldung).")
async def abmelden(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

    spieler_name = interaction.user.name
    found_team = None
    other_player = None

    # Überprüfung, ob der Spieler in einem Team ist
    for team_name, team_members in anmeldungen["teams"].items():
        if spieler_name in team_members:
            found_team = team_name
            other_player = team_members[0] if team_members[1] == spieler_name else team_members[1]  # Finde den anderen Spieler
            break

    if found_team:
        # Team auflösen
        anmeldungen["teams"].pop(found_team)

        # Falls der andere Spieler noch nicht in der Solo-Liste ist, hinzufügen
        if other_player not in anmeldungen["solo"]:
            anmeldungen["solo"].append(other_player)

        save_anmeldungen()

        spieler1_mention = get_mention(interaction.guild, spieler_name)
        spieler2_mention = get_mention(interaction.guild, other_player)

        await interaction.response.send_message(
            f"❌ **Team `{found_team}` wurde aufgelöst!**\n"
            f"👤 {spieler1_mention} hat sich abgemeldet.\n"
            f"👥 {spieler2_mention} wurde in die Einzelspieler-Liste verschoben.",
            ephemeral=False
        )
        return

    # Falls kein Team gefunden wurde, prüfen, ob der Spieler in der Solo-Liste ist
    if spieler_name in anmeldungen["solo"]:
        anmeldungen["solo"].remove(spieler_name)
        save_anmeldungen()

        spieler_mention = get_mention(interaction.guild, spieler_name)

        await interaction.response.send_message(
            f"✅ **{spieler_mention}** wurde aus der Einzelspieler-Liste entfernt.",
            ephemeral=False
        )
        return

    # Falls der Spieler weder in einem Team noch als Einzelspieler angemeldet ist
    await interaction.response.send_message("⚠ Du bist weder in einem Team noch als Einzelspieler angemeldet!", ephemeral=True)

# **Teilnehmerliste anzeigen**
@tree.command(name="teilnehmer", description="Zeigt die aktuelle Teilnehmerliste.")
async def teilnehmer(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    total_teams = len(anmeldungen["teams"])
    total_solo_players = len(anmeldungen["solo"])
    total_players = total_teams * 2 + total_solo_players

    msg = f"🏆 **Aktuelle Turnierteilnehmer:**\n"
    msg += f"📊 **Teams insgesamt:** {total_teams}\n"
    msg += f"👥 **Spieler insgesamt:** {total_players}\n\n"

    if total_teams > 0:
        msg += "🔹 **Team-Anmeldungen:**\n"
        for team_name, members in anmeldungen["teams"].items():  # Korrekte Iteration
            spieler1_mention = get_mention(interaction.guild, members[0])  # Erster Spieler
            spieler2_mention = get_mention(interaction.guild, members[1])  # Zweiter Spieler

            msg += f"📌 **{team_name}** - {spieler1_mention} & {spieler2_mention}\n"

    if total_solo_players > 0:
        msg += "🎲 **Einzelspieler, die noch auf Teameinteilung warten:**\n"
        solo_mentions = [get_mention(interaction.guild, spieler) for spieler in anmeldungen["solo"]]
        msg += ", ".join(solo_mentions) + "\n"

    await interaction.response.send_message(msg, ephemeral=False)

# **Team zufällig generieren**
@tree.command(name="team_shuffle", description="Teilt alle Einzelspieler zufällig in 2er-Teams ein.")
async def team_shuffle(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return

    if len(anmeldungen["solo"]) < 2:
        await interaction.response.send_message("❌ Nicht genug Einzelspieler für eine zufällige Teameinteilung!", ephemeral=True)
        return

    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return

    random.shuffle(anmeldungen["solo"])
    neue_teams = []

    while len(anmeldungen["solo"]) >= 2:
        spieler1 = anmeldungen["solo"].pop(0)
        spieler2 = anmeldungen["solo"].pop(0)
        teamname = f"Team-{spieler1}-{spieler2}"  # Erzeugt eindeutigen Teamnamen

        # Team korrekt als Key-Value-Paar zum Dictionary hinzufügen
        anmeldungen["teams"][teamname] = [spieler1, spieler2]
        neue_teams.append((teamname, spieler1, spieler2))

    save_anmeldungen()

    # Nachricht mit den neu erstellten Teams senden
    msg = "🎲 **Neue zufällig generierte Teams:**\n"
    for teamname, spieler1, spieler2 in neue_teams:
        spieler1_mention = get_mention(interaction.guild, spieler1)
        spieler2_mention = get_mention(interaction.guild, spieler2)
        msg += f"📌 **{teamname}** – {spieler1_mention} & {spieler2_mention}\n"

    await interaction.response.send_message(msg, ephemeral=False)

# **Team umbennen**
@tree.command(name="team_umbenennen", description="Ändert den Namen deines Teams.")
async def team_umbenennen(interaction: discord.Interaction, neuer_name: str):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    spieler_name = interaction.user.name
    found_team = None

    # Durch alle Teams iterieren
    for team_name, team_data in anmeldungen["teams"].items():
        if spieler_name in team_data:  # Korrektur: Überprüfung in der Liste
            found_team = team_name
            break

    if found_team:
        alter_name = found_team
        anmeldungen["teams"][neuer_name] = anmeldungen["teams"].pop(found_team)  # Team umbenennen
        save_anmeldungen()
        await interaction.response.send_message(
            f"🔄 **Teamname geändert:** `{alter_name}` → `{neuer_name}`",
            ephemeral=False
        )
    else:
        await interaction.response.send_message("⚠ Du bist in keinem Team angemeldet!", ephemeral=True)

# **Punkte vergeben (nur für Admins)**
@tree.command(name="punkte", description="Vergibt Punkte an das Team eines Spielers.")
async def punkte(interaction: discord.Interaction, name: discord.Member, punkte: int):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return

    # Team des Spielers finden
    team_name = None
    user_name = name.name  # Wandle discord.Member in String um
    for team, members in anmeldungen["teams"].items():
        if user_name in members:
            team_name = team
            break

    if team_name is None:
        await interaction.response.send_message(f"❌ Spieler **{name}** ist in keinem Team!", ephemeral=True)
        return

    # Punkte dem Team hinzufügen
    if team_name not in anmeldungen["punkte"]:
        anmeldungen["punkte"][team_name] = 0

    anmeldungen["punkte"][team_name] += punkte
    save_anmeldungen()

    bot_logger.info(f"{interaction.user} hat {punkte} Punkte zu {team_name} hinzugefügt.")
    await interaction.response.send_message(f"✅ `{punkte}` Punkte wurden dem Team **{team_name}** gutgeschrieben! (Gesamt: `{anmeldungen['punkte'][team_name]}`)", ephemeral=False)

# **Punkte entfernen (nur für Admins)**
@tree.command(name="punkte_entfernen", description="Entfernt Punkte von einem Team oder Spieler.")
async def punkte_entfernen(interaction: discord.Interaction, name: str, punkte: int):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return

    if name not in anmeldungen["punkte"]:
        await interaction.response.send_message(f"⚠ **{name}** hat noch keine Punkte.", ephemeral=True)
        return

    anmeldungen["punkte"][name] = max(0, anmeldungen["punkte"][name] - punkte)
    save_anmeldungen()

    bot_logger.info(f"{interaction.user} hat die Punkte von {name} entfernt.")
    await interaction.response.send_message(f"❌ `{punkte}` Punkte wurden von **{name}** entfernt! (Gesamt: `{anmeldungen['punkte'][name]}`)", ephemeral=False)

# **Punkte zurücksetzen (nur für Admins)**
@tree.command(name="punkte_reset", description="Setzt alle Punkte auf 0 zurück.")
async def punkte_reset(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return

    anmeldungen["punkte"] = {}
    save_anmeldungen()

    bot_logger.info(f"{interaction.user} hat die Punkte zurückgesetzt.")
    await interaction.response.send_message("🔄 Alle Punkte wurden zurückgesetzt!", ephemeral=False)

# **Leaderboard anzeigen**
@tree.command(name="leaderboard", description="Zeigt die Punkteliste aller Teams.")
async def leaderboard(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_2:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    if not anmeldungen["punkte"]:
        await interaction.response.send_message("❌ Es gibt noch keine vergebenen Punkte!", ephemeral=True)
        return

    sorted_teams = sorted(anmeldungen["punkte"].items(), key=lambda x: x[1], reverse=True)
    leaderboard_text = "**🏆 Team Leaderboard 🏆**\n"
    for i, (team, punkte) in enumerate(sorted_teams, start=1):
        leaderboard_text += f"**{i}. {team}** - {punkte} Punkte\n"

    bot_logger.info(f"{interaction.user} hat das Leaderboard abgerufen.")
    await interaction.response.send_message(leaderboard_text, ephemeral=False)

# **Teilnehmerliste zurücksetzen (nur für Admins)**
@tree.command(name="teilnehmer_reset", description="Löscht alle angemeldeten Teams und Einzelspieler.")
async def teilnehmer_reset(interaction: discord.Interaction):
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    if not has_permission(interaction):
        await interaction.response.send_message("⛔ Du hast keine Berechtigung, diesen Befehl auszuführen!", ephemeral=True)
        return

    anmeldungen["teams"] = {}  # Alle Teams löschen
    anmeldungen["solo"] = []  # Alle Einzelanmeldungen löschen
    anmeldungen["punkte"] = {}
    save_anmeldungen()

    bot_logger.info(f"{interaction.user} Hat die Teilnehmer zurückgesetzt.")
    await interaction.response.send_message("🔄 **Alle Teams und Einzelspieler wurden entfernt!**", ephemeral=False)


# Startet den Bot
bot.run(os.environ["TOKEN"])