import discord
from discord import app_commands
import json
import os
import random
import logging
import datetime
import calendar

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

def load_anmeldungen():
    """
    loads data from file (player, team etc)
    """
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

def save_anmeldungen():
    """
    saves registered players
    """
    with open(FILE_PATH, "w", encoding="utf-8") as file:
        json.dump(anmeldungen, file, indent=4, ensure_ascii=False)

# Lade bestehende Anmeldungen beim Start
anmeldungen = load_anmeldungen()

# --- Matchplan Helper Functions--- 
def get_mention(guild, username):
    """
    changes playername_string into discords own @mention
    """
    member = discord.utils.get(guild.members, name=username)
    return member.mention if member else username

def has_permission(interaction: discord.Interaction, allowed_roles=["Moderator", "Lappen des Vertrauens"]):
    """
    checks if user has certain permission 
    """
    return any(role.name in allowed_roles for role in interaction.user.roles)

def round_robin_schedule(teams: list) -> list:
    """
    generates a round-robin-plan vor all listed teams
    each teams plays each team once
    
    :param teams: list of teamnames (Strings)
    :return: list of rounds, where each round is a list of matches (tuple)
    """
    # insert placeholder incase of uneven team amount
    if len(teams) % 2 == 1:
        teams.append("BYE")
    
    n = len(teams)
    schedule = []
    fixed = teams[0]  # first team stays fixed
    rest = teams[1:]  # rotate all other teams
    
    for round_index in range(n - 1):
        round_matches = []
        # generate list with current plan
        teams_order = [fixed] + rest
        # generate pairings
        for i in range(n // 2):
            team1 = teams_order[i]
            team2 = teams_order[n - 1 - i]
            # if team is "bye" -> skip
            if team1 != "BYE" and team2 != "BYE":
                round_matches.append((team1, team2))
        schedule.append(round_matches)
        #rotation step: Last team from 'rest' will be moved to beginning
        rest = [rest[-1]] + rest[:-1]
    
    return schedule

def get_weekend_dates(year: int, month: int) -> list:
    """
    gives weekend data (saturday and sunday) from a giving month
    """
    weekend_dates = []
    cal = calendar.monthcalendar(year, month)
    # pythons week starts with monday (index 0) and ends with sunday (index 6)
    for week in cal:
        saturday = week[calendar.SATURDAY]  # saturday (Index 5)
        sunday = week[calendar.SUNDAY]      # sunday (Index 6)
        if saturday != 0:
            weekend_dates.append(datetime.date(year, month, saturday))
        if sunday != 0:
            weekend_dates.append(datetime.date(year, month, sunday))
    weekend_dates.sort()
    return weekend_dates

def reorder_matches(matches: list) -> list:
    """
    Versucht, die Liste von Matches so zu ordnen, dass nie ein Team in zwei
    aufeinanderfolgenden Matches erscheint.
    
    :param matches: Liste von Tupeln (Team1, Team2)
    :return: Neu geordnete Liste von Matches
    """
    if not matches:
        return matches

    # Beginne mit dem ersten Match und entferne es aus der Liste.
    ordered = [matches.pop(0)]
    while matches:
        last_match = ordered[-1]
        found_index = None
        # Suche ein Match, das kein Team aus last_match enthält.
        for i, match in enumerate(matches):
            if last_match[0] not in match and last_match[1] not in match:
                found_index = i
                break
        if found_index is not None:
            ordered.append(matches.pop(found_index))
        else:
            # Wenn kein passendes Match gefunden wurde, füge einfach das erste hinzu.
            ordered.append(matches.pop(0))
    return ordered

def distribute_matches_over_weekends(matches: list, year: int, month: int) -> dict:
    """
    Distributes the given matches (list of tuples) across all weekend days of a specified month. 
    Matches are assigned cyclically, and an attempt is made for each day to arrange the order so that the same team never appears in two consecutive matches.

    :param matches: list of matches (Tupel), for example [("Team A", "Team B"), ...]
    :param year: year as in (e.g. 2025)
    :param month: month as int (1 to 12)
    :return: Dictionary with date as key and list of matches a value
    """
    weekend_dates = get_weekend_dates(year, month)
    schedule = {date: [] for date in weekend_dates}
    num_days = len(weekend_dates)
    
    # spread matches cyclical among weekend days 
    for i, match in enumerate(matches):
        date = weekend_dates[i % num_days]
        schedule[date].append(match)
    
    # order matches so no team plays twice in succession 
    for date in schedule:
        day_matches = schedule[date]
        schedule[date] = reorder_matches(day_matches.copy())
    
    return schedule

# --- Availability Helper Functions ---
def parse_time_interval(interval_str: str) -> tuple:
    """
    Converts a time interval string (e.g., "16:00-18:00") into a tuple (start, end)
    where start and end are datetime.time objects.
    """
    start_str, end_str = interval_str.split("-")
    start = datetime.datetime.strptime(start_str.strip(), "%H:%M").time()
    end = datetime.datetime.strptime(end_str.strip(), "%H:%M").time()
    return start, end

def get_overlap(interval1: tuple, interval2: tuple) -> tuple:
    """
    Calculates the overlapping time interval between two time intervals.
    Returns a tuple (start, end) if an overlap exists, otherwise returns None.
    """
    start = max(interval1[0], interval2[0])
    end = min(interval1[1], interval2[1])
    if start < end:
        return start, end
    return None

def common_availability(team1_intervals: list, team2_intervals: list) -> list:
    """
    Determines the common time slots between two teams.
    
    :param team1_intervals: A list of time interval strings (e.g., ["16:00-18:00", "20:00-22:00"]) for team 1.
    :param team2_intervals: A list of time interval strings for team 2.
    :return: A list of tuples (start, end) representing the common availability.
    """
    parsed_team1 = [parse_time_interval(interval) for interval in team1_intervals]
    parsed_team2 = [parse_time_interval(interval) for interval in team2_intervals]
    
    overlaps = []
    for interval1 in parsed_team1:
        for interval2 in parsed_team2:
            overlap = get_overlap(interval1, interval2)
            if overlap:
                overlaps.append(overlap)
    return overlaps


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

@tree.command(name="set_availability", description="Set your team's availability as comma-separated time intervals (e.g., '16:00-18:00,20:00-22:00').")
async def set_availability(interaction: discord.Interaction, time_slots: str):
    # Check if the command is used in the correct channel (if needed)
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 This command can only be used in a specific channel!", ephemeral=True)
        return

    user_name = interaction.user.name
    team_name = None
    
    # Identify the team that the user is registered in.
    for team, members in anmeldungen["teams"].items():
        if user_name in members:
            team_name = team
            break

    if not team_name:
        await interaction.response.send_message("❌ You are not registered in any team!", ephemeral=True)
        return

    # Split the input string into individual time intervals.
    intervals = [slot.strip() for slot in time_slots.split(",")]
    
    # Validate each time interval using the parse_time_interval function.
    try:
        # If any interval is invalid, an exception will be raised.
        parsed_intervals = [parse_time_interval(slot) for slot in intervals]
    except Exception as e:
        await interaction.response.send_message("❌ Error parsing your time slots. Please use the format HH:MM-HH:MM.", ephemeral=True)
        return

    # Save the availability in the JSON database.
    # Extend the 'anmeldungen' structure if necessary.
    if "availability" not in anmeldungen:
        anmeldungen["availability"] = {}
    anmeldungen["availability"][team_name] = intervals  # storing as a list of strings
    
    save_anmeldungen()

    await interaction.response.send_message(f"✅ Availability for team **{team_name}** has been updated: {', '.join(intervals)}", ephemeral=False)

@tree.command(name="propose_match", description="Propose a match time based on common availability between two teams.")
async def propose_match(interaction: discord.Interaction, team1: str, team2: str):
    # Check if both teams are registered
    if team1 not in anmeldungen["teams"] or team2 not in anmeldungen["teams"]:
        await interaction.response.send_message("One or both teams are not registered.", ephemeral=True)
        return

    # Check if availability is set for both teams
    if "availability" not in anmeldungen or team1 not in anmeldungen["availability"] or team2 not in anmeldungen["availability"]:
        await interaction.response.send_message("Availability is not set for one or both teams.", ephemeral=True)
        return

    # Retrieve availability lists (each as a list of strings, e.g., ["16:00-18:00", "20:00-22:00"])
    avail_team1 = anmeldungen["availability"][team1]
    avail_team2 = anmeldungen["availability"][team2]

    # Compute common time slots using the helper function
    common_slots = common_availability(avail_team1, avail_team2)

    if not common_slots:
        await interaction.response.send_message("No common availability found between the two teams.", ephemeral=True)
        return

    # For simplicity, select the first common slot as the proposed match time
    slot = common_slots[0]
    proposed_time_str = f"{slot[0].strftime('%H:%M')} - {slot[1].strftime('%H:%M')}"

    # Generate mentions for all players from both teams using the get_mention helper function
    team1_players = anmeldungen["teams"][team1]
    team2_players = anmeldungen["teams"][team2]
    # Remove duplicate players if any
    all_players = list(set(team1_players + team2_players))
    mentions = " ".join(get_mention(interaction.guild, player) for player in all_players)

    # Create the proposal message
    message = (
        f"Proposed match time for **{team1}** vs **{team2}**: **{proposed_time_str}**\n"
        f"{mentions}\nPlease react with 👍 to confirm the proposed time."
    )
    
    await interaction.response.send_message(message, ephemeral=False)

# --- Starting the Bot ---
bot.run(os.environ["TOKEN"])