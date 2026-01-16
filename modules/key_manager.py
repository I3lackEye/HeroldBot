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

from modules.config import CONFIG
from modules.dataStorage import load_tournament_data
from modules.embeds import load_embed_template, build_embed_from_template
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
        return {"keys": [], "claims_per_tournament": {}}

    try:
        with open(KEYS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Ensure claims_per_tournament exists for backwards compatibility
            if "claims_per_tournament" not in data:
                data["claims_per_tournament"] = {}
            return data
    except Exception as e:
        logger.error(f"Failed to load keys data: {e}")
        return {"keys": [], "claims_per_tournament": {}}


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

        # Load embed from locale
        template = load_embed_template("keys").get("KEY_DONATION_SUCCESS")
        placeholders = {"description": description}
        embed = build_embed_from_template(template, placeholders)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------
# View for Key Claiming
# ----------------------------------------
class ClaimKeyView(View):
    """View for claiming available keys."""

    def __init__(self, available_keys: list, user_id: int, team_name: str, winner_ids: list, tournament_id: str, encryption: KeyEncryption):
        super().__init__(timeout=300)  # 5 minutes timeout
        self.available_keys = available_keys
        self.user_id = user_id
        self.team_name = team_name
        self.winner_ids = winner_ids
        self.tournament_id = tournament_id
        self.encryption = encryption
        self.claimed_keys = []

    async def claim_key(self, interaction: Interaction, key_entry: dict):
        """Claim a specific key."""
        user_id_str = str(interaction.user.id)

        # Verify user is in the winning team
        is_winner = False
        for winner_id in self.winner_ids:
            clean_id = winner_id.strip("<@>")
            if clean_id == user_id_str:
                is_winner = True
                break

        if not is_winner:
            await interaction.response.send_message(
                "❌ You are not part of the winning team!",
                ephemeral=True
            )
            return False

        # Check if user already claimed a key for THIS tournament
        keys_data = load_keys_data()
        claims_per_tournament = keys_data.get("claims_per_tournament", {})
        tournament_claims = claims_per_tournament.get(self.tournament_id, {})

        if user_id_str in tournament_claims:
            await interaction.response.send_message(
                "❌ You have already claimed a key for this tournament!",
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
                key["claimed_by"] = user_id_str
                key["claimed_at"] = datetime.now().isoformat()
                key["claimed_team"] = self.team_name
                key["tournament_id"] = self.tournament_id
                break

        # Track claim in claims_per_tournament for robust duplicate prevention
        if self.tournament_id not in claims_per_tournament:
            claims_per_tournament[self.tournament_id] = {}
        claims_per_tournament[self.tournament_id][user_id_str] = {
            "claimed_at": datetime.now().isoformat(),
            "key_id": key_entry["id"]
        }
        keys_data["claims_per_tournament"] = claims_per_tournament

        save_keys_data(keys_data)

        # Send the key to the user via DM
        try:
            # Load embed from locale
            template = load_embed_template("keys").get("KEY_CLAIMED_SUCCESS")
            placeholders = {
                "description": key_entry['description'],
                "key": decrypted_key
            }
            embed = build_embed_from_template(template, placeholders)

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
                    key["claimed_by"] = None
                    key["claimed_at"] = None
                    key["claimed_team"] = None
                    key["tournament_id"] = None
                    break

            # Remove from claims_per_tournament
            claims_per_tournament = keys_data.get("claims_per_tournament", {})
            if self.tournament_id in claims_per_tournament:
                claims_per_tournament[self.tournament_id].pop(user_id_str, None)
            keys_data["claims_per_tournament"] = claims_per_tournament

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
        config = CONFIG

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
        config = CONFIG

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

        # Prepare placeholders
        footer_text = ""
        if len(available_keys) > 25:
            footer_text = f"Showing first 25 of {len(available_keys)} keys"
        else:
            footer_text = f"Total: {len(available_keys)} keys"

        placeholders = {
            "key_count": str(len(available_keys)),
            "footer": footer_text
        }

        # Load and build embed from template
        template = load_embed_template("keys").get("KEY_LIST")
        embed = build_embed_from_template(template, placeholders)

        # Add fields for each key
        for i, key in enumerate(available_keys[:25], 1):  # Limit to 25 for embed field limit
            donated_at = datetime.fromisoformat(key["donated_at"]).strftime("%Y-%m-%d")
            embed.add_field(
                name=f"{i}. {key['description']}",
                value=f"Donated by {key['donated_by_name']} on {donated_at}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="claim",
        description="Claim a game key (winners only)."
    )
    async def claim(self, interaction: Interaction):
        """Allow winners to claim keys."""
        config = CONFIG

        if not config.features.game_key_handler:
            await interaction.response.send_message(
                "❌ Game key feature is currently disabled.",
                ephemeral=True
            )
            return

        # Load last tournament winner from global data
        from modules.dataStorage import load_global_data
        global_data = load_global_data()
        last_winner = global_data.get("last_tournament_winner", {})

        if not last_winner or not last_winner.get("ended_at"):
            await interaction.response.send_message(
                "❌ No completed tournament found! Keys are only available to tournament winners.",
                ephemeral=True
            )
            return

        # Use ended_at as unique tournament ID
        tournament_id = last_winner.get("ended_at")
        winning_team_name = last_winner.get("winning_team")

        if not winning_team_name:
            await interaction.response.send_message(
                "❌ No tournament winner found!",
                ephemeral=True
            )
            return

        # Get winner IDs from last tournament
        from modules.info import get_winner_ids
        winner_ids = last_winner.get("winner_ids", [])

        # If not stored in last_winner, try to get from current calculation
        if not winner_ids:
            logger.warning("[KEY_CLAIM] winner_ids not found in last_tournament_winner, unable to verify eligibility")
            await interaction.response.send_message(
                "❌ Unable to verify tournament winners. Please contact an administrator.",
                ephemeral=True
            )
            return

        # Check if user is in the winning team
        user_id_str = str(interaction.user.id)
        user_mention = interaction.user.mention

        # Check if user is in winner_ids
        is_winner = False
        for winner_id in winner_ids:
            # winner_id might be a string like "123456" or "<@123456>"
            clean_id = winner_id.strip("<@>")
            if clean_id == user_id_str:
                is_winner = True
                break

        if not is_winner:
            await interaction.response.send_message(
                f"❌ Keys are only available to the tournament winner team!\n"
                f"**Last winner:** {winning_team_name}",
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

        # Check if user already claimed a key for THIS tournament
        claims_per_tournament = keys_data.get("claims_per_tournament", {})
        tournament_claims = claims_per_tournament.get(tournament_id, {})

        if user_id_str in tournament_claims:
            await interaction.response.send_message(
                "❌ You have already claimed a key for this tournament!",
                ephemeral=True
            )
            return

        # Create view with buttons for each key
        view = ClaimKeyView(
            available_keys=available_keys,
            user_id=interaction.user.id,
            team_name=winning_team_name,
            winner_ids=winner_ids,
            tournament_id=tournament_id,
            encryption=self.encryption
        )
        await view.create_buttons()

        # Load embed from locale
        template = load_embed_template("keys").get("KEY_CLAIM_SELECT")
        embed = build_embed_from_template(template)

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

        # Prepare placeholders
        footer_text = ""
        if len(all_keys) > 25:
            footer_text = f"Showing first 25 of {len(all_keys)} keys"
        else:
            footer_text = f"All {len(all_keys)} keys displayed"

        placeholders = {
            "total": str(len(all_keys)),
            "available": str(available),
            "claimed": str(claimed),
            "footer": footer_text
        }

        # Load and build embed from template
        template = load_embed_template("keys").get("KEY_ADMIN_LIST")
        embed = build_embed_from_template(template, placeholders)

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

        # Load and build embed from template
        placeholders = {
            "description": key_found['description']
        }
        template = load_embed_template("keys").get("KEY_REMOVED")
        embed = build_embed_from_template(template, placeholders)

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

        # Load and build embed from template
        placeholders = {
            "description": key_found['description'],
            "key": decrypted_key,
            "id": key_id
        }
        template = load_embed_template("keys").get("KEY_DECRYPTED")
        embed = build_embed_from_template(template, placeholders)

        logger.warning(f"Key decrypted by admin {interaction.user.display_name}: {key_found['description']}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


# ----------------------------------------
# Helper Function for Tournament End
# ----------------------------------------
async def notify_winners_about_keys(bot, winner_ids: list, winning_team_name: str):
    """
    Notifies tournament winners about available game keys.
    Called from end_tournament_procedure.

    Args:
        bot: Discord bot instance
        winner_ids: List of winner user IDs (as strings)
        winning_team_name: Name of the winning team
    """
    # Check if feature is enabled
    if not config.features.game_key_handler:
        logger.info("[KEY_NOTIFICATION] Game key feature is disabled, skipping notification")
        return

    # Check if there are any available keys
    keys_data = load_keys_data()
    available_keys = [k for k in keys_data["keys"] if k["status"] == "available"]

    if not available_keys:
        logger.info("[KEY_NOTIFICATION] No keys available, skipping notification")
        return

    logger.info(f"[KEY_NOTIFICATION] Notifying {len(winner_ids)} winners about {len(available_keys)} available keys")

    # Create key list preview
    key_list = "\n".join([f"• {key['description']}" for key in available_keys[:5]])
    if len(available_keys) > 5:
        key_list += f"\n• ... and {len(available_keys) - 5} more"

    # Load embed from locale
    template = load_embed_template("keys").get("KEY_WINNER_NOTIFICATION")
    placeholders = {
        "team_name": winning_team_name,
        "key_count": str(len(available_keys)),
        "key_list": key_list
    }
    embed = build_embed_from_template(template, placeholders)

    # Send DM to each winner
    success_count = 0
    for user_id in winner_ids:
        try:
            user_id_int = int(user_id.strip("<@>"))
            user = await bot.fetch_user(user_id_int)

            await user.send(embed=embed)
            success_count += 1
            logger.info(f"[KEY_NOTIFICATION] Sent notification to {user.display_name} ({user_id_int})")

        except discord.Forbidden:
            logger.warning(f"[KEY_NOTIFICATION] Could not send DM to user {user_id} (DMs disabled)")
        except discord.NotFound:
            logger.warning(f"[KEY_NOTIFICATION] User {user_id} not found")
        except Exception as e:
            logger.error(f"[KEY_NOTIFICATION] Error sending notification to {user_id}: {e}")

    logger.info(f"[KEY_NOTIFICATION] Successfully notified {success_count}/{len(winner_ids)} winners")


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
