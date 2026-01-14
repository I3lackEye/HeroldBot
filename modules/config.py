"""
Centralized configuration management for HeroldBot.

This module loads and validates all configuration from separate JSON files:
- configs/bot.json: Bot-level settings (channels, roles, language)
- configs/tournament.json: Tournament settings (match duration, active days)
- configs/features.json: Feature flags
"""

import json
import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Any

from modules.logger import logger


# =======================================
# CONFIGURATION DATA CLASSES
# =======================================

@dataclass
class DataPaths:
    """Paths to data storage files."""
    data: str
    tournament: str


@dataclass
class Channels:
    """Discord channel IDs."""
    limits: str
    reminder: str
    reschedule: str


@dataclass
class Roles:
    """Discord role names and IDs."""
    moderator: List[str]
    admin: List[str]
    dev: List[str]
    winner: List[str]


@dataclass
class BotConfig:
    """Bot-level configuration."""
    data_paths: DataPaths
    channels: Channels
    roles: Roles
    language: str
    timezone: str
    max_string_length: int


@dataclass
class ActiveDay:
    """Active day time range."""
    start: str
    end: str


@dataclass
class TournamentConfig:
    """Tournament-specific configuration."""
    match_duration_minutes: int
    pause_duration_minutes: int
    max_time_budget_hours: int
    reschedule_timeout_hours: int
    slot_interval_minutes: int
    active_days: Dict[str, ActiveDay]

    @property
    def match_duration(self) -> timedelta:
        """Get match duration as timedelta."""
        return timedelta(minutes=self.match_duration_minutes)

    @property
    def pause_duration(self) -> timedelta:
        """Get pause duration as timedelta."""
        return timedelta(minutes=self.pause_duration_minutes)

    @property
    def max_time_budget(self) -> timedelta:
        """Get max time budget as timedelta."""
        return timedelta(hours=self.max_time_budget_hours)

    @property
    def reschedule_timeout(self) -> timedelta:
        """Get reschedule timeout as timedelta."""
        return timedelta(hours=self.reschedule_timeout_hours)

    @property
    def slot_interval(self) -> timedelta:
        """Get slot interval as timedelta."""
        return timedelta(minutes=self.slot_interval_minutes)


@dataclass
class Features:
    """Feature flags."""
    reminder_enabled: bool
    game_key_handler: bool
    debug_save_slot_matrix: bool


# =======================================
# CONFIGURATION MANAGER
# =======================================

class ConfigManager:
    """
    Centralized configuration manager.
    Loads and validates all configuration files.
    """

    def __init__(self):
        self.bot: Optional[BotConfig] = None
        self.tournament: Optional[TournamentConfig] = None
        self.features: Optional[Features] = None
        self._base_dir: Optional[str] = None

    def load(self, base_dir: Optional[str] = None) -> None:
        """
        Load all configuration files.

        :param base_dir: Base directory (defaults to parent of modules/)
        """
        if base_dir is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        self._base_dir = base_dir

        # Load each config file
        self.bot = self._load_bot_config()
        self.tournament = self._load_tournament_config()
        self.features = self._load_features_config()

        logger.info("[CONFIG] All configurations loaded successfully")

    def _load_json(self, relative_path: str) -> Dict[str, Any]:
        """Load JSON file from configs directory."""
        full_path = os.path.join(self._base_dir, relative_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"[CONFIG] File not found: {relative_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"[CONFIG] Error parsing {relative_path}: {e}")
            raise

    def _load_bot_config(self) -> BotConfig:
        """Load bot configuration from configs/bot.json."""
        data = self._load_json("configs/bot.json")

        return BotConfig(
            data_paths=DataPaths(**data["data_paths"]),
            channels=Channels(**data["channels"]),
            roles=Roles(**data["roles"]),
            language=data["language"],
            timezone=data["timezone"],
            max_string_length=data["max_string_length"],
        )

    def _load_tournament_config(self) -> TournamentConfig:
        """Load tournament configuration from configs/tournament.json."""
        data = self._load_json("configs/tournament.json")

        # Convert active_days dict to ActiveDay objects
        active_days = {
            day: ActiveDay(**day_data)
            for day, day_data in data["active_days"].items()
        }

        return TournamentConfig(
            match_duration_minutes=data["match_duration_minutes"],
            pause_duration_minutes=data["pause_duration_minutes"],
            max_time_budget_hours=data["max_time_budget_hours"],
            reschedule_timeout_hours=data["reschedule_timeout_hours"],
            slot_interval_minutes=data["slot_interval_minutes"],
            active_days=active_days,
        )

    def _load_features_config(self) -> Features:
        """Load features configuration from configs/features.json."""
        data = self._load_json("configs/features.json")
        return Features(**data)

    def get_data_path(self, key: str) -> str:
        """Get absolute path to data file."""
        if key == "data":
            relative_path = self.bot.data_paths.data
        elif key == "tournament":
            relative_path = self.bot.data_paths.tournament
        else:
            raise ValueError(f"Unknown data path key: {key}")

        return os.path.join(self._base_dir, relative_path)

    def get_channel_id(self, channel_name: str) -> int:
        """Get channel ID as integer."""
        channel_id_str = getattr(self.bot.channels, channel_name, None)
        if channel_id_str is None:
            raise ValueError(f"Unknown channel: {channel_name}")

        try:
            return int(channel_id_str)
        except ValueError:
            logger.error(f"[CONFIG] Invalid channel ID for {channel_name}: {channel_id_str}")
            return 0

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled."""
        return getattr(self.features, feature_name, False)


# =======================================
# GLOBAL CONFIG INSTANCE
# =======================================

# Create single global instance
CONFIG = ConfigManager()

# Auto-load on import
try:
    CONFIG.load()
except Exception as e:
    logger.error(f"[CONFIG] Failed to load configuration: {e}")
    # Don't raise - let the bot handle startup errors
