# bot.py
import discord
from discord import app_commands
import os
import json
from HeroldBot import sign_in_team, load_config, load_anmeldungen  # Import aus dem Package


# Konfiguration laden
config = load_config()

TOKEN = config.get("TOKEN")
DATABASE_PATH = config.get("DATABASE_PATH")
STATS_DATABASE_PATH = config.get("STATS_DATABASE_PATH")
ROLE_PERMISSIONS = config.get("ROLE_PERMISSIONS", {})

# Jetzt kannst du die Variablen in deinem Bot verwenden
print("TOKEN:", TOKEN)
print("DATABASE_PATH:", DATABASE_PATH)
print("ROLE_PERMISSIONS:", ROLE_PERMISSIONS)


# Lade die Daten beim Start
anmeldungen = load_anmeldungen()

# Erstelle den Bot und registriere Slash-Commands
intents = discord.Intents.default()
intents.members = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"{bot.user} ist online!")

@tree.command(name="anmelden", description="Melde dich mit einem festen Team für das Turnier an.")
async def anmelden(interaction: discord.Interaction, mitspieler: discord.Member, teamname: str):
    # Verwende die ausgelagerte Funktion sign_in_team
    await sign_in_team(interaction, mitspieler, teamname, anmeldungen, save_anmeldungen)

bot.run(os.environ.get("TOKEN"))