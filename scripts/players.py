# players.py
import discord

async def sign_in_team(interaction: discord.Interaction, mitspieler: discord.Member, teamname: str, anmeldungen: dict, save_anmeldungen):
    LIMITED_CHANNEL_ID_1 = 1351213319104761937  # Beispiel-Kanal-ID
    if interaction.channel_id != LIMITED_CHANNEL_ID_1:
        await interaction.response.send_message("🚫 Dieser Befehl kann nur in einem bestimmten Kanal verwendet werden!", ephemeral=True)
        return
    
    spieler1_name = interaction.user.name  # Name des ersten Spielers
    spieler2_name = mitspieler.name          # Name des zweiten Spielers

    # Überprüfe, ob einer der Spieler bereits in einem Team ist
    for team, members in anmeldungen["teams"].items():
        if spieler1_name in members or spieler2_name in members:
            await interaction.response.send_message("❌ Einer der Spieler ist bereits in einem Team angemeldet!", ephemeral=True)
            return

    # Überprüfe, ob einer der Spieler bereits in der Solo-Liste steht
    if spieler1_name in anmeldungen["solo"] or spieler2_name in anmeldungen["solo"]:
        await interaction.response.send_message("❌ Einer der Spieler ist bereits angemeldet!", ephemeral=True)
        return

    # Speichere das Team
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