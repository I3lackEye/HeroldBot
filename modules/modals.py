# modules/modals.py

import discord

from discord.ui import Modal, TextInput, View, Select
from discord import Interaction


from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.utils import validate_string, generate_team_name, validate_time_range, validate_date

### Helper function

def find_member(guild, search_str):
    # Versuche erstmal als Mention/ID
    search_str = search_str.strip()
    # Erwähnung: <@12345>
    if search_str.startswith("<@") and search_str.endswith(">"):
        user_id = int(''.join(filter(str.isdigit, search_str)))
        return guild.get_member(user_id)
    # Reine User-ID
    if search_str.isdigit():
        return guild.get_member(int(search_str))
    # Name#Discriminator
    if "#" in search_str:
        name, discrim = search_str.split("#", 1)
        for m in guild.members:
            if m.name.lower() == name.lower() and m.discriminator == discrim:
                return m
    # Displayname Case-Insensitive (Fuzzy)
    for m in guild.members:
        if m.display_name.lower() == search_str.lower() or m.name.lower() == search_str.lower():
            return m
    # Optional: Fuzzy-Match (z.B. Levenshtein)
    return None


class TestModal(Modal, title="Testmodal"):
    test = TextInput(label="Testfeld")

class TeamFullJoinModal(Modal):
    def __init__(self):
        super().__init__(title="Team-Anmeldung")

        self.team_name = TextInput(
            label="Teamname",
            required=False,
            placeholder="Freilassen für Zufällig",
            max_length=32
        )
        self.mitspieler_field = TextInput(
            label="Mitspieler (nur Name, keine ID/Tag/@)",
            required=False,
            placeholder="z.B. Aldemar",
            max_length=32
        )
        self.samstag_zeit = TextInput(
            label="Verfügbarkeit Samstag (z.B. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20
        )
        self.sonntag_zeit = TextInput(
            label="Verfügbarkeit Sonntag (z.B. 12:00-18:00)",
            required=True,
            placeholder="12:00-18:00",
            max_length=20
        )
        self.unavailable_dates = TextInput(
            label="Blockierte Tage (YYYY-MM-DD)",
            required=False,
            placeholder="2025-06-01, 2025-06-08",
            max_length=200
        )

        self.add_item(self.team_name)
        self.add_item(self.mitspieler_field)
        self.add_item(self.samstag_zeit)
        self.add_item(self.sonntag_zeit)
        self.add_item(self.unavailable_dates)

    async def on_submit(self, interaction: Interaction):
        team_name = self.team_name.value.strip() or generate_team_name()
        mitspieler_name = self.mitspieler_field.value.strip()
        samstag = self.samstag_zeit.value.strip()
        sonntag = self.sonntag_zeit.value.strip()
        unavailable_raw = self.unavailable_dates.value.strip().replace('\n', ',').replace(' ', '')
        unavailable_list = [d for d in unavailable_raw.split(',') if d] if unavailable_raw else []

        # Teamname validieren
        is_valid, err = validate_string(team_name, max_length=32)
        if not is_valid:
            await interaction.response.send_message(f"❌ Teamname ungültig: {err}", ephemeral=True)
            return

        # Mitspieler validieren
        is_valid, err = validate_string(mitspieler_name, max_length=32)
        if not is_valid:
            await interaction.response.send_message(f"❌ Mitspieler ungültig: {err}", ephemeral=True)
            return

        # Mitspieler finden
        mitspieler = None
        for m in interaction.guild.members:
            if m.display_name.lower() == mitspieler_name.lower() or m.name.lower() == mitspieler_name.lower():
                mitspieler = m
                break
        if not mitspieler:
            await interaction.response.send_message(
                "❌ Mitspieler nicht gefunden! Bitte exakt den Namen angeben.", ephemeral=True
            )
            return

        # Verfügbarkeit validieren (simple Regex oder strikte Zeitprüfung)
        # Verfügbarkeit Samstag validieren
        samstag = self.samstag_zeit.value.strip()
        valid, err = validate_time_range(samstag)
        if not valid:
            await interaction.response.send_message(f"❌ Fehler bei Samstag: {err}", ephemeral=True)
            return

        # Verfügbarkeit Sonntag validieren
        sonntag = self.sonntag_zeit.value.strip()
        valid, err = validate_time_range(sonntag)
        if not valid:
            await interaction.response.send_message(f"❌ Fehler bei Sonntag: {err}", ephemeral=True)
            return

        # Blockierte Tage validieren (jedes einzelne Datum)
        for d in unavailable_list:
            valid, err = validate_date(d)
            if not valid:
                await interaction.response.send_message(f"❌ {err}", ephemeral=True)
                return

        # Daten speichern
        tournament = load_tournament_data()
        teams = tournament.setdefault("teams", {})
        teams[team_name] = {
            "members": [interaction.user.mention, mitspieler.mention],
            "verfügbarkeit": {"samstag": samstag, "sonntag": sonntag},
            "unavailable_dates": unavailable_list
        }
        save_tournament_data(tournament)

        await interaction.response.send_message(
            f"✅ Anmeldung gespeichert für **{team_name}**!\n"
            f"Mitspieler: {mitspieler.mention}\n"
            f"Samstag: {samstag}\nSonntag: {sonntag}\n"
            f"Blockierte Tage: {', '.join(unavailable_list) if unavailable_list else 'Keine'}",
            ephemeral=True
        )

class SoloJoinModal(Modal, title="Solo-Anmeldung"):
    nickname = TextInput(label="Dein Name (optional)", required=False, max_length=32)
    samstag_zeit = TextInput(label="Verfügbarkeit Samstag (HH:MM-HH:MM)", required=True, placeholder="12:00-20:00", max_length=11)
    sonntag_zeit = TextInput(label="Verfügbarkeit Sonntag (HH:MM-HH:MM)", required=True, placeholder="14:00-22:00", max_length=11)
    unavailable_dates = TextInput(
        label="Nicht verfügbare Daten (YYYY-MM-DD, Komma oder neue Zeile)", 
        required=False, 
        style=2,
        placeholder="2025-05-25, 2025-06-02",
        max_length=200
    )

    async def on_submit(self, interaction: Interaction):
        nickname = self.nickname.value.strip() or interaction.user.display_name
        samstag = self.samstag_zeit.value.strip()
        sonntag = self.sonntag_zeit.value.strip()
        unavailable = self.unavailable_dates.value.strip().replace('\n', ',').replace(' ', '')

        unavailable_list = [d for d in unavailable.split(',') if d] if unavailable else []

        tournament = load_tournament_data()
        solo_list = tournament.setdefault("solo", [])
        if any(entry.get("player") == interaction.user.mention for entry in solo_list):
            await interaction.response.send_message("❗ Du bist bereits angemeldet.", ephemeral=True)
            return
        solo_entry = {
            "player": interaction.user.mention,
            "nickname": nickname,
            "verfügbarkeit": {
                "samstag": samstag,
                "sonntag": sonntag
            },
            "unavailable_dates": unavailable_list
        }
        solo_list.append(solo_entry)
        save_tournament_data(tournament)

        await interaction.response.send_message(
            f"✅ Solo-Anmeldung gespeichert!\n"
            f"Samstag: {samstag}\nSonntag: {sonntag}\n"
            f"Nicht verfügbare Daten: {', '.join(unavailable_list) if unavailable_list else 'Keine'}",
            ephemeral=True
        )
