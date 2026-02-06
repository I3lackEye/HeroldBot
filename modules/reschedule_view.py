from discord import ui, ButtonStyle, Interaction, Member, SelectOption
from typing import List
from datetime import datetime
import asyncio
import logging
from zoneinfo import ZoneInfo


# Lokale Module
from modules.dataStorage import load_tournament_data, save_tournament_data
from modules.logger import logger
from modules.utils import ensure_timezone_aware, to_utc


# ---------------------------------------
# View für Slot-Auswahl (Requester wählt Zeitpunkt)
# ---------------------------------------
class SlotSelectView(ui.View):
    def __init__(self, match_id: int, requester: Member, available_slots: List[datetime], callback):
        super().__init__(timeout=300)  # 5 Minuten
        self.match_id = match_id
        self.requester = requester
        self.callback = callback

        # Create select menu with up to 25 slots
        options = []
        for slot in available_slots[:25]:  # Discord limit: 25 options
            label = slot.strftime("%a %d.%m.%Y %H:%M")
            value = slot.isoformat()
            options.append(SelectOption(label=label, value=value))

        if not options:
            # No slots available - shouldn't happen but handle gracefully
            options.append(SelectOption(label="No slots available", value="none"))

        select = ui.Select(
            placeholder="Choose a new time slot...",
            options=options,
            min_values=1,
            max_values=1
        )
        select.callback = self.slot_selected
        self.add_item(select)

    async def slot_selected(self, interaction: Interaction):
        """Called when user selects a slot from dropdown."""
        if interaction.user.id != self.requester.id:
            await interaction.response.send_message("🚫 Only the requester can select a slot.", ephemeral=True)
            return

        selected_value = interaction.data["values"][0]

        if selected_value == "none":
            await interaction.response.send_message("❌ No slots available for reschedule.", ephemeral=True)
            return

        selected_slot = datetime.fromisoformat(selected_value)

        await interaction.response.send_message(
            f"✅ You selected: **{selected_slot.strftime('%A %d.%m.%Y %H:%M')}**\n"
            f"Posting reschedule request...",
            ephemeral=True
        )

        # Call callback to post the actual reschedule request
        await self.callback(interaction, selected_slot)
        self.stop()


# ---------------------------------------
# View für Reschedule Buttons (Accept/Decline mit Forfeit)
# ---------------------------------------
class RescheduleView(ui.View):
    def __init__(self, match_id: int, team1: str, team2: str, new_datetime: datetime,
                 players: List[Member], requester: Member):
        super().__init__(timeout=86400)  # 24 Stunden
        self.match_id = match_id
        self.team1 = team1
        self.team2 = team2
        self.new_datetime = new_datetime
        self.players = players
        self.requester = requester
        self.approved = set()
        self.message = None

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Nur erlaubte Spieler dürfen klicken."""
        if interaction.user not in self.players:
            logger.warning(f"[RESCHEDULE] {interaction.user.display_name} (ID {interaction.user.id}) tried to vote on match {self.match_id} but was not authorized.")
            await interaction.response.send_message("🚫 You are not authorized to vote on this reschedule.", ephemeral=True)
            return False
        return True

    @ui.button(label="✅ Accept", style=ButtonStyle.success)
    async def accept(self, interaction: Interaction, button: ui.Button):
        if interaction.user in self.approved:
            await interaction.response.send_message("✅ You already accepted.", ephemeral=True)
            return

        self.approved.add(interaction.user)
        logger.info(f"[RESCHEDULE] {interaction.user.display_name} accepted reschedule for match {self.match_id}.")

        await interaction.response.send_message("✅ Accepted!", ephemeral=True)

        # Check if all players approved
        if self.approved == set(self.players):
            await self.success()

    @ui.button(label="❌ Decline (Forfeit)", style=ButtonStyle.danger)
    async def decline(self, interaction: Interaction, button: ui.Button):
        """
        When a player declines the reschedule, the match is forfeited.
        The declining player's team loses automatically.
        """
        await interaction.response.defer()

        logger.warning(f"[RESCHEDULE] {interaction.user.display_name} DECLINED reschedule for match {self.match_id}!")
        logger.warning(f"[RESCHEDULE] Match {self.match_id} will be forfeited - decliner's team loses.")

        # Determine which team the declining player belongs to
        tournament = load_tournament_data()
        teams = tournament.get("teams", {})

        decliner_team = None
        for team_name, team_data in teams.items():
            if interaction.user.mention in team_data.get("members", []):
                decliner_team = team_name
                break

        if not decliner_team:
            logger.error(f"[RESCHEDULE] Could not find team for declining player {interaction.user.mention}")
            await interaction.followup.send("❌ Error: Could not determine your team.", ephemeral=True)
            return

        # Set match to forfeit
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)
        if match:
            match["status"] = "forfeit"
            match["forfeit_by"] = decliner_team

            # Opponent wins
            opponent = self.team2 if self.team1 == decliner_team else self.team1
            match["winner"] = opponent

            # Clear reschedule state fields
            if "reschedule_requested_by" in match:
                del match["reschedule_requested_by"]
            if "reschedule_pending" in match:
                del match["reschedule_pending"]
            if "reschedule_pending_since" in match:
                del match["reschedule_pending_since"]

            save_tournament_data(tournament)
            logger.info(f"[RESCHEDULE] Match {self.match_id} forfeited by {decliner_team}. Winner: {opponent}")

        # Import at runtime to avoid circular dependency
        from modules.reschedule import _reschedule_lock
        from modules.task_manager import get_all_tasks

        async with _reschedule_lock:
            # Cancel the timer task if it exists in task manager
            task_name = f"reschedule_timer_match_{self.match_id}"
            all_tasks = get_all_tasks()
            if task_name in all_tasks:
                timer_task = all_tasks[task_name]["task"]
                if not timer_task.done():
                    timer_task.cancel()
                    logger.debug(f"[RESCHEDULE] Cancelled timer task for match {self.match_id} after decline")

        if self.message:
            await self.message.edit(
                content=(
                    f"❌ **{interaction.user.mention}** declined the reschedule request.\n"
                    f"⚠️ Match {self.match_id} has been **forfeited**.\n"
                    f"🏆 **{opponent}** wins by forfeit."
                ),
                embed=None,
                view=None
            )

        self.stop()

    async def success(self):
        """Wenn alle zugestimmt haben: Match verschieben."""
        # Import at runtime to avoid circular dependency
        from modules.reschedule import _reschedule_lock
        from modules.task_manager import get_all_tasks

        # Acquire lock for ENTIRE critical section to prevent race conditions
        async with _reschedule_lock:
            # Reload tournament data to avoid race conditions
            tournament = load_tournament_data()

            match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)
            if not match:
                logger.error(f"[RESCHEDULE] ❌ Match {self.match_id} not found during success()")
                await self.message.edit(
                    content=f"❌ Error: Match {self.match_id} no longer exists.",
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Validate match status
            if match.get("status") in ["completed", "forfeit"]:
                logger.warning(f"[RESCHEDULE] ❌ Match {self.match_id} already {match.get('status')} - cannot reschedule")
                await self.message.edit(
                    content=f"❌ Match {self.match_id} is already {match.get('status')} and cannot be rescheduled.",
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Validate teams still exist
            teams = tournament.get("teams", {})
            if self.team1 not in teams or self.team2 not in teams:
                logger.error(f"[RESCHEDULE] ❌ One or both teams no longer exist: {self.team1}, {self.team2}")
                await self.message.edit(
                    content=f"❌ Error: One or both teams no longer exist in the tournament.",
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Validate all voting players are still in their teams
            team1_members = set(teams[self.team1].get("members", []))
            team2_members = set(teams[self.team2].get("members", []))
            current_players = {member.mention for member in self.players}

            expected_players = team1_members | team2_members

            if current_players != expected_players:
                logger.error(f"[RESCHEDULE] ❌ Player membership changed for match {self.match_id}")
                logger.error(f"[RESCHEDULE]    Expected: {expected_players}")
                logger.error(f"[RESCHEDULE]    Got: {current_players}")

                missing_players = expected_players - current_players
                extra_players = current_players - expected_players

                error_msg = "❌ **Team membership has changed since the reschedule request:**\n"
                if missing_players:
                    error_msg += f"Missing players: {', '.join(missing_players)}\n"
                if extra_players:
                    error_msg += f"Unexpected players: {', '.join(extra_players)}\n"
                error_msg += "\nThe reschedule request is now invalid. Please submit a new request."

                await self.message.edit(
                    content=error_msg,
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Re-check slot is still in future (in case voting took hours)
            from modules.utils import now_in_bot_timezone
            if self.new_datetime <= now_in_bot_timezone():
                logger.error(f"[RESCHEDULE] ❌ Selected slot {self.new_datetime} is now in the past")
                await self.message.edit(
                    content=(
                        f"❌ **Selected time slot is now in the past!**\n"
                        f"The voting took too long and the selected time **{self.new_datetime.strftime('%d.%m.%Y %H:%M')}** has passed.\n"
                        f"Please request a new reschedule with a future time."
                    ),
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Critical: Check if slot is still free (prevent double booking)
            new_slot_iso = to_utc(ensure_timezone_aware(self.new_datetime)).isoformat()
            booked_slots = {
                m["scheduled_time"]
                for m in tournament.get("matches", [])
                if m.get("scheduled_time") and m["match_id"] != self.match_id  # Exclude current match
            }

            if new_slot_iso in booked_slots:
                logger.error(f"[RESCHEDULE] ❌ RACE CONDITION PREVENTED: Slot {new_slot_iso} already booked by another match!")
                await self.message.edit(
                    content=(
                        f"❌ **Slot conflict detected!**\n"
                        f"The selected time slot **{self.new_datetime.strftime('%d.%m.%Y %H:%M')}** was booked by another match "
                        f"while you were voting.\n"
                        f"Please request a new reschedule with a different time."
                    ),
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # All validations passed - assign slot
            match["scheduled_time"] = new_slot_iso
            match["rescheduled_once"] = True

            # Clear reschedule state fields after successful reschedule
            if "reschedule_requested_by" in match:
                del match["reschedule_requested_by"]
            if "reschedule_pending" in match:
                del match["reschedule_pending"]
            if "reschedule_pending_since" in match:
                del match["reschedule_pending_since"]

            logger.debug(f"[RESCHEDULE] UTC saved: {match['scheduled_time']}")

            # Save tournament data with error handling
            try:
                save_tournament_data(tournament)
                logger.info(f"[RESCHEDULE] ✅ Match {self.match_id} successfully rescheduled to {self.new_datetime}.")
            except Exception as e:
                logger.error(f"[RESCHEDULE] ❌ Failed to save reschedule: {e}")
                await self.message.edit(
                    content=f"❌ **Failed to save reschedule!**\nError: {str(e)}\nPlease try again or contact an admin.",
                    embed=None,
                    view=None
                )
                self.stop()
                return

            # Cancel the timer task if it exists in task manager
            task_name = f"reschedule_timer_match_{self.match_id}"
            all_tasks = get_all_tasks()
            if task_name in all_tasks:
                timer_task = all_tasks[task_name]["task"]
                if not timer_task.done():
                    timer_task.cancel()
                    logger.debug(f"[RESCHEDULE] Cancelled timer task for match {self.match_id} after success")

        # Success message (outside lock)
        await self.message.edit(
            content=f"✅ All players accepted! Match {self.match_id} rescheduled to **{self.new_datetime.strftime('%d.%m.%Y %H:%M')}**!",
            embed=None,
            view=None
        )
        self.stop()

    async def on_timeout(self):
        """Timeout nach 24h - kein Forfeit, nur Abbruch."""
        logger.warning(f"[RESCHEDULE] Timeout for match {self.match_id}. Request automatically cancelled.")

        # Clear reschedule state fields to allow team to request again
        tournament = load_tournament_data()
        match = next((m for m in tournament.get("matches", []) if m.get("match_id") == self.match_id), None)
        if match:
            fields_cleared = []
            if "reschedule_requested_by" in match:
                del match["reschedule_requested_by"]
                fields_cleared.append("reschedule_requested_by")
            if "reschedule_pending" in match:
                del match["reschedule_pending"]
                fields_cleared.append("reschedule_pending")
            if "reschedule_pending_since" in match:
                del match["reschedule_pending_since"]
                fields_cleared.append("reschedule_pending_since")

            if fields_cleared:
                save_tournament_data(tournament)
                logger.info(f"[RESCHEDULE] Cleared {', '.join(fields_cleared)} for match {self.match_id} after timeout")

        if self.message:
            try:
                await self.message.edit(
                    content=f"⌛ Reschedule request for match {self.match_id} has expired. Match remains at original time.",
                    embed=None,
                    view=None
                )
            except Exception as e:
                logger.error(f"[RESCHEDULE] Error editing message on timeout: {e}")
