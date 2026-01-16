"""
Game Key Management System
Allows users to donate game/gift keys and winners to claim them.
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional

import discord
from discord import Interaction, app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
from cryptography.fernet import Fernet, InvalidToken

from modules.config import Config
from modules.dataStorage import load_tournament_data
from modules.logger import logger
from modules.utils import has_permission


# ----------------------------------------
# Encryption Utilities
# ----------------------------------------
class KeyEncryption:
    """Handles encryption and decryption of game keys."""

    def __init__(self):
        self.encryption_key = os.getenv("ENCRYPTION_KEY")
        if not self.encryption_key:
            logger.warning("ENCRYPTION_KEY not set in .env file. Key encryption will not work!")
            self.fernet = None
        else:
            try:
                self.fernet = Fernet(self.encryption_key.encode())
            except Exception as e:
                logger.error(f"Failed to initialize Fernet cipher: {e}")
                self.fernet = None

    def encrypt(self, plaintext: str) -> Optional[str]:
        """Encrypts a plaintext string."""
        if not self.fernet:
            logger.error("Encryption not available - ENCRYPTION_KEY not configured")
            return None

        try:
            encrypted = self.fernet.encrypt(plaintext.encode())
            return encrypted.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return None

    def decrypt(self, encrypted_text: str) -> Optional[str]:
        """Decrypts an encrypted string."""
        if not self.fernet:
            logger.error("Decryption not available - ENCRYPTION_KEY not configured")
            return None

        try:
            decrypted = self.fernet.decrypt(encrypted_text.encode())
            return decrypted.decode()
        except InvalidToken:
            logger.error("Decryption failed: Invalid token or corrupted data")
            return None
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None


# ----------------------------------------
# Data Storage Functions
# ----------------------------------------
KEYS_FILE = "data/game_keys.json"


def load_keys_data():
    """Load keys data from JSON file."""
    if not os.path.exists(KEYS_FILE):
        return {"keys": []}

    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load keys data: {e}")
        return {"keys": []}


def save_keys_data(data):
    """Save keys data to JSON file."""
    try:
        os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
        with open(KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save keys data: {e}")


# ----------------------------------------
# Modal for Key Donation
# ----------------------------------------
class DonateKeyModal(Modal, title="Donate a Game Key"):
    """Modal for donating a game/gift key."""

    key_code = TextInput(
        label="Game/Gift Key Code",
        placeholder="Enter the key code here (e.g., XXXXX-XXXXX-XXXXX)",
        required=True,
        max_length=200
    )

    description = TextInput(
        label="Description",
        placeholder="Game name or description (e.g., 'Steam - Cyberpunk 2077')",
        required=True,
        max_length=100
    )

    def __init__(self, encryption: KeyEncryption):
        super().__init__()
        self.encryption = encryption

    async def on_submit(self, interaction: Interaction):
        """Handle the modal submission."""
        key_code = self.key_code.value.strip()
        description = self.description.value.strip()

        # Encrypt the key
        encrypted_key = self.encryption.encrypt(key_code)

        if not encrypted_key:
            await interaction.response.send_message(
                "❌ Failed to encrypt key. Please contact an administrator.",
                ephemeral=True
            )
            return

        # Load current keys
        keys_data = load_keys_data()

        # Create new key entry
        key_entry = {
            "id": str(uuid.uuid4()),
            "encrypted_key": encrypted_key,
            "description": description,
            "donated_by": str(interaction.user.id),
            "donated_by_name": interaction.user.display_name,
            "donated_at": datetime.now().isoformat(),
            "status": "available",
            "claimed_by": None,
            "claimed_at": None
        }

        keys_data["keys"].append(key_entry)
        save_keys_data(keys_data)

        logger.info(f"Key donated by {interaction.user.display_name} ({interaction.user.id}): {description}")

        embed = discord.Embed(
            title="✅ Key Donated Successfully",
            description=f"Thank you for donating a key!\n\n**Description:** {description}",
            color=discord.Color.green()
        )
        embed.set_footer(text="Your key has been encrypted and stored securely.")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------
# View for Key Claiming
# ----------------------------------------
class ClaimKeyView(View):
    """View for claiming available keys."""

    def __init__(self, available_keys: list, user_id: int, team_name: str, team_members: list, encryption: KeyEncryption):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.available_keys = available_keys
        self.user_id = user_id
        self.team_name = team_name
        self.team_members = team_members
        self.encryption = encryption
        self.claimed_keys = []

    async def claim_key(self, interaction: Interaction, key_entry: dict):
        """Claim a specific key."""
        # Verify user is in the winning team
        if str(interaction.user.id) not in [m.strip("<@>") for m in self.team_members]:
            await interaction.response.send_message(
                "❌ You are not part of the winning team!",
                ephemeral=True
            )
            return False

        # Check if user already claimed a key
        keys_data = load_keys_data()
        user_id_str = str(interaction.user.id)

        for key in keys_data["keys"]:
            if key.get("claimed_by") and user_id_str in key["claimed_by"]:
                await interaction.response.send_message(
                    "❌ You have already claimed a key!",
                    ephemeral=True
                )
                return False

        # Decrypt the key
        decrypted_key = self.encryption.decrypt(key_entry["encrypted_key"])

        if not decrypted_key:
            await interaction.response.send_message(
                "❌ Failed to decrypt key. Please contact an administrator.",
                ephemeral=True
            )
            return False

        # Mark key as claimed
        for key in keys_data["keys"]:
            if key["id"] == key_entry["id"]:
                if key["status"] != "available":
                    await interaction.response.send_message(
                        "❌ This key has already been claimed!",
                        ephemeral=True
                    )
                    return False

                key["status"] = "claimed"
                key["claimed_by"] = key.get("claimed_by", [])
                key["claimed_by"].append(user_id_str)
                key["claimed_at"] = datetime.now().isoformat()
                key["claimed_team"] = self.team_name
                break

        save_keys_data(keys_data)

        # Send the key to the user via DM
        try:
            embed = discord.Embed(
                title="🎁 Your Game Key",
                description=f"**Description:** {key_entry['description']}\n**Key:** `{decrypted_key}`",
                color=discord.Color.gold()
            )
            embed.set_footer(text="Congratulations on your win! 🎉")

            await interaction.user.send(embed=embed)

            await interaction.response.send_message(
                f"✅ Key claimed! Check your DMs for the key code.",
                ephemeral=True
            )

            logger.info(f"Key claimed by {interaction.user.display_name} ({interaction.user.id}): {key_entry['description']}")
            return True

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't send you a DM. Please enable DMs from server members and try again.",
                ephemeral=True
            )

            # Rollback the claim
            keys_data = load_keys_data()
            for key in keys_data["keys"]:
                if key["id"] == key_entry["id"]:
                    key["status"] = "available"
                    if user_id_str in key.get("claimed_by", []):
                        key["claimed_by"].remove(user_id_str)
                    break
            save_keys_data(keys_data)

            return False

    async def create_buttons(self):
        """Create buttons for each available key."""
        for i, key in enumerate(self.available_keys[:25]):  # Discord limit: 25 buttons
            button = Button(
                label=key["description"][:80],  # Discord label limit: 80 chars
                style=discord.ButtonStyle.primary,
                custom_id=f"claim_{key['id']}"
            )

            async def button_callback(interaction: Interaction, key_entry=key):
                success = await self.claim_key(interaction, key_entry)
                if success:
                    # Disable the button after claiming
                    for item in self.children:
                        if hasattr(item, 'custom_id') and item.custom_id == f"claim_{key_entry['id']}":
                            item.disabled = True
                            item.style = discord.ButtonStyle.success
                            item.label = f"✓ {item.label}"

                    await interaction.message.edit(view=self)

            button.callback = button_callback
            self.add_item(button)


# ----------------------------------------
# Slash Commands Group
# ----------------------------------------
class KeyGroup(app_commands.Group):
    """Command group for game key management."""

    def __init__(self):
        super().__init__(name="key", description="Manage game/gift keys for tournament winners.")
        self.encryption = KeyEncryption()

    @app_commands.command(
        name="donate",
        description="Donate a game/gift key for tournament winners."
    )
    async def donate(self, interaction: Interaction):
        """Open a modal to donate a game key."""
        config = Config()

        if not config.features.game_key_handler:
            await interaction.response.send_message(
                "❌ Game key feature is currently disabled.",
                ephemeral=True
            )
            return

        modal = DonateKeyModal(self.encryption)
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="list",
        description="List all available game keys."
    )
    async def list_keys(self, interaction: Interaction):
        """List all available keys."""
        config = Config()

        if not config.features.game_key_handler:
            await interaction.response.send_message(
                "❌ Game key feature is currently disabled.",
                ephemeral=True
            )
            return

        keys_data = load_keys_data()
        available_keys = [k for k in keys_data["keys"] if k["status"] == "available"]

        if not available_keys:
            await interaction.response.send_message(
                "📭 No keys available at the moment.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🎁 Available Game Keys",
            description=f"There are currently **{len(available_keys)}** keys available for claiming.",
            color=discord.Color.blue()
        )

        for i, key in enumerate(available_keys[:25], 1):  # Limit to 25 for embed field limit
            donated_at = datetime.fromisoformat(key["donated_at"]).strftime("%Y-%m-%d")
            embed.add_field(
                name=f"{i}. {key['description']}",
                value=f"Donated by {key['donated_by_name']} on {donated_at}",
                inline=False
            )

        if len(available_keys) > 25:
            embed.set_footer(text=f"Showing first 25 of {len(available_keys)} keys")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="claim",
        description="Claim a game key (winners only)."
    )
    async def claim(self, interaction: Interaction):
        """Allow winners to claim keys."""
        config = Config()

        if not config.features.game_key_handler:
            await interaction.response.send_message(
                "❌ Game key feature is currently disabled.",
                ephemeral=True
            )
            return

        # Check if user is part of the winning team
        tournament = load_tournament_data()
        user_mention = interaction.user.mention

        # Find user's team
        user_team = None
        user_team_data = None

        for team_name, team_data in tournament.get("teams", {}).items():
            if user_mention in team_data.get("members", []):
                user_team = team_name
                user_team_data = team_data
                break

        if not user_team:
            await interaction.response.send_message(
                "❌ You are not part of any team!",
                ephemeral=True
            )
            return

        # Check if team has won the tournament
        # Winner is determined by the "winner" role or checking match results
        # For simplicity, we check if the team has the most wins
        team_wins = 0
        for match in tournament.get("matches", []):
            if match.get("winner") == user_team:
                team_wins += 1

        if team_wins == 0:
            await interaction.response.send_message(
                "❌ Your team hasn't won any matches yet. Keys are only available to winners!",
                ephemeral=True
            )
            return

        # Get available keys
        keys_data = load_keys_data()
        available_keys = [k for k in keys_data["keys"] if k["status"] == "available"]

        if not available_keys:
            await interaction.response.send_message(
                "📭 No keys available at the moment.",
                ephemeral=True
            )
            return

        # Check if user already claimed a key
        user_id_str = str(interaction.user.id)
        for key in keys_data["keys"]:
            if key.get("claimed_by") and user_id_str in key["claimed_by"]:
                await interaction.response.send_message(
                    "❌ You have already claimed a key!",
                    ephemeral=True
                )
                return

        # Create view with buttons for each key
        view = ClaimKeyView(
            available_keys=available_keys,
            user_id=interaction.user.id,
            team_name=user_team,
            team_members=user_team_data.get("members", []),
            encryption=self.encryption
        )
        await view.create_buttons()

        embed = discord.Embed(
            title="🎁 Claim a Game Key",
            description="Click a button below to claim a key. The key will be sent to you via DM.",
            color=discord.Color.gold()
        )
        embed.set_footer(text="You can only claim one key per tournament.")

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(
        name="admin_list",
        description="[Admin] List all keys including claimed ones."
    )
    async def admin_list(self, interaction: Interaction):
        """Admin command to list all keys."""
        if not has_permission(interaction.user, ["admin", "dev"]):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        keys_data = load_keys_data()
        all_keys = keys_data["keys"]

        if not all_keys:
            await interaction.response.send_message(
                "📭 No keys in the database.",
                ephemeral=True
            )
            return

        available = len([k for k in all_keys if k["status"] == "available"])
        claimed = len([k for k in all_keys if k["status"] == "claimed"])

        embed = discord.Embed(
            title="🔑 All Game Keys (Admin View)",
            description=f"**Total:** {len(all_keys)} | **Available:** {available} | **Claimed:** {claimed}",
            color=discord.Color.purple()
        )

        for i, key in enumerate(all_keys[:25], 1):
            status_emoji = "✅" if key["status"] == "available" else "❌"
            donated_at = datetime.fromisoformat(key["donated_at"]).strftime("%Y-%m-%d")

            value = f"**Status:** {status_emoji} {key['status']}\n"
            value += f"**Donated by:** {key['donated_by_name']} on {donated_at}\n"
            value += f"**ID:** `{key['id']}`"

            if key["status"] == "claimed":
                claimed_at = datetime.fromisoformat(key["claimed_at"]).strftime("%Y-%m-%d %H:%M")
                value += f"\n**Claimed:** {claimed_at}"
                if key.get("claimed_team"):
                    value += f"\n**Team:** {key['claimed_team']}"

            embed.add_field(
                name=f"{i}. {key['description']}",
                value=value,
                inline=False
            )

        if len(all_keys) > 25:
            embed.set_footer(text=f"Showing first 25 of {len(all_keys)} keys")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_remove",
        description="[Admin] Remove a key by ID."
    )
    @app_commands.describe(key_id="The UUID of the key to remove")
    async def admin_remove(self, interaction: Interaction, key_id: str):
        """Admin command to remove a key."""
        if not has_permission(interaction.user, ["admin", "dev"]):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        keys_data = load_keys_data()
        key_found = None

        for key in keys_data["keys"]:
            if key["id"] == key_id:
                key_found = key
                break

        if not key_found:
            await interaction.response.send_message(
                f"❌ Key with ID `{key_id}` not found.",
                ephemeral=True
            )
            return

        keys_data["keys"].remove(key_found)
        save_keys_data(keys_data)

        logger.info(f"Key removed by {interaction.user.display_name}: {key_found['description']} ({key_id})")

        embed = discord.Embed(
            title="🗑️ Key Removed",
            description=f"Successfully removed key: **{key_found['description']}**",
            color=discord.Color.red()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="admin_decrypt",
        description="[Admin] Decrypt a key by ID (use with caution)."
    )
    @app_commands.describe(key_id="The UUID of the key to decrypt")
    async def admin_decrypt(self, interaction: Interaction, key_id: str):
        """Admin command to decrypt and view a key."""
        if not has_permission(interaction.user, ["admin", "dev"]):
            await interaction.response.send_message(
                "❌ You don't have permission to use this command.",
                ephemeral=True
            )
            return

        keys_data = load_keys_data()
        key_found = None

        for key in keys_data["keys"]:
            if key["id"] == key_id:
                key_found = key
                break

        if not key_found:
            await interaction.response.send_message(
                f"❌ Key with ID `{key_id}` not found.",
                ephemeral=True
            )
            return

        decrypted_key = self.encryption.decrypt(key_found["encrypted_key"])

        if not decrypted_key:
            await interaction.response.send_message(
                "❌ Failed to decrypt key. Check ENCRYPTION_KEY configuration.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🔓 Decrypted Key (Admin)",
            description=f"**Description:** {key_found['description']}\n**Key:** `{decrypted_key}`",
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"ID: {key_id}")

        logger.warning(f"Key decrypted by admin {interaction.user.display_name}: {key_found['description']}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------
# Cog Setup
# ----------------------------------------
class KeyManagerCog(commands.Cog):
    """Cog for managing game/gift keys."""

    def __init__(self, bot):
        self.bot = bot
        self.key_group = KeyGroup()
        bot.tree.add_command(self.key_group)
        logger.info("KeyManagerCog loaded")

    async def cog_unload(self):
        """Cleanup when cog is unloaded."""
        self.bot.tree.remove_command(self.key_group.name)
        logger.info("KeyManagerCog unloaded")


async def setup(bot):
    """Setup function for loading the cog."""
    await bot.add_cog(KeyManagerCog(bot))
