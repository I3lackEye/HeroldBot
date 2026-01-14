# 🛡️ HeroldBot

> Your reliable assistant for organizing and managing Discord tournaments.

A robust Discord bot for automated tournament management with intelligent scheduling, availability management, and comprehensive statistics.

---

## ✨ Key Features

### 🎯 Core Functionality
- 🗳️ **Game Selection via Poll**: Emoji reaction polls to vote for tournament games
- 📥 **Flexible Registration**: Solo players or pre-formed teams with individual availability
- 🎮 **Intelligent Matchmaking**:
  - Automatic pairing of solo players based on common availability
  - Round-robin tournament bracket generation for fair play
  - Availability-based slot assignment with smart pause enforcement
  - Rescue mode for difficult-to-schedule matches
- 🔄 **Flexible Reschedule System**:
  - Reschedule requests with automatic slot search
  - Voting via Discord buttons (✅/❌)
  - Automatic tournament extension when needed
  - 24-hour timeout for voting
- 🔔 **Automatic Reminders**:
  - Match reminders 1 hour before start
  - Direct mention of all affected players
  - Continuous background loop
- 📊 **Comprehensive Statistics**:
  - Players: Wins, participations, favorite game, win rate
  - Tournament: Match history, MVP ranking, overall winner
  - Global leaderboards and tournament archive

### 🏗️ Technical Features
- ⚙️ **Modular Config System**: Separate configuration files for bot, tournament, and features
- 💾 **Atomic File Writes**: Data safety even during crashes
- 🔐 **Role-based Permissions**: Admin, Moderator, Developer roles
- 🌍 **Multi-language**: German/English with localized embeds
- 🕒 **Timezone-Aware**: Correct time processing with ZoneInfo
- 📦 **Automatic Backups**: Tournament archive with JSON and ZIP export
- 🧪 **Extensive Dev Tools**: Dummy generators, diagnostics, test scenarios
- 🛡️ **Robust Error Handling**: Graceful degradation on failures
- 📝 **Typed Configuration**: Type-safe config with Python Dataclasses

---

## 🚀 Installation

### Prerequisites
- Python 3.13+
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- Server with enabled Privileged Gateway Intents (Members, Message Content)

### Setup

```bash
# Clone repository
git clone https://github.com/I3lackEye/HeroldBot.git
cd HeroldBot

# Create virtual environment
python3.13 -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and add your TOKEN

# Start bot
python run.py

# Alternative: Run as module
python -m modules.main
```

---

## ⚙️ Configuration

### Configuration Files

#### **`.env`** – Sensitive Data (never commit!)
```env
TOKEN=your_discord_bot_token_here
DEBUG_MODE=False
REMINDER_ENABLED=True
```

#### **`configs/bot.json`** – Bot Settings
```json
{
  "data_paths": {
    "data": "data/data.json",
    "tournament": "data/tournament.json"
  },
  "channels": {
    "limits": "CHANNEL_ID",
    "reminder": "CHANNEL_ID",
    "reschedule": "CHANNEL_ID"
  },
  "roles": {
    "moderator": ["Moderator", "1234567890"],
    "admin": ["Admin"],
    "dev": ["Developer", "1234567890"],
    "winner": ["Champion"]
  },
  "language": "de",
  "timezone": "Europe/Berlin",
  "max_string_length": 50
}
```

#### **`configs/tournament.json`** – Tournament Parameters
```json
{
  "match_duration_minutes": 90,
  "pause_duration_minutes": 30,
  "max_time_budget_hours": 2,
  "reschedule_timeout_hours": 24,
  "slot_interval_minutes": 60,
  "active_days": {
    "friday": {"start": "16:00", "end": "22:00"},
    "saturday": {"start": "10:00", "end": "22:00"},
    "sunday": {"start": "10:00", "end": "22:00"}
  }
}
```

#### **`configs/features.json`** – Feature Toggles
```json
{
  "enable_auto_match_solo": true,
  "enable_reminder": true,
  "enable_reschedule": true
}
```

### Language Packs
- Embeds and texts in `/locale/{language}/embeds/`
- Team name generator in `/locale/{language}/names_{language}.json`
- Supported: `de`, `en` (easily extensible)

---

## 📚 Slash Commands Overview

### 🧍 Registration & Availability
| Command | Description |
|---------|-------------|
| `/player join` | Register (solo or with partner via modal) |
| `/player leave` | Leave the tournament |
| `/player update_availability` | Update your availability |
| `/player participants` | Show current participant list |

### 📜 Tournament Info
| Command | Description |
|---------|-------------|
| `/info help` | Overview of all bot commands |
| `/info match_schedule` | Current match schedule with times |
| `/info team` | Show your team & availability |
| `/info list_games` | Show available games |

### 🔄 Match Organization
| Command | Description |
|---------|-------------|
| `/player request_reschedule` | Request match reschedule (with voting) |
| `/test_reminder` | Manually test match reminder (Dev only) |

### 📊 Statistics
| Command | Description |
|---------|-------------|
| `/stats stats` | Show your or others' statistics |
| `/stats overview` | Leaderboard, tournament overview, match history |
| `/stats status` | Current tournament status (teams, matches, schedule) |

### 🛡️ Admin Commands
| Command | Description |
|---------|-------------|
| `/admin start_tournament` | Start new tournament (modal with times) |
| `/admin end_tournament` | End tournament & archive |
| `/admin close_registration` | Manually close registration |
| `/admin archive_tournament` | Move tournament to archive |
| `/admin sign_out` | Force sign-out player/team |
| `/admin add_win` | Manually award win |
| `/admin award_overall_winner` | Set overall winner |
| `/admin manage_game` | Add/remove games |
| `/admin end_poll` | Manually end game selection poll |
| `/admin reload` | Re-sync slash commands |
| `/admin reset_reschedule` | Reset reschedule request |
| `/admin export_data` | Export tournament data as ZIP (via DM) |

### 🧪 Developer Tools
| Command | Description |
|---------|-------------|
| `/dev simulate_full_flow` | Simulate complete tournament flow |
| `/dev generate_dummy` | Generate test data (6 scenarios: easy, hard, blocked, mixed, realistic, custom) |
| `/dev reset_tournament` | Reset tournament data to default |
| `/dev show_state` | Show detailed tournament status |
| `/dev test_matchmaker` | Test matchmaker algorithm (dry-run) |
| `/dev generate_matches` | Generate and assign matches |
| `/dev diagnose` | System diagnostics (channels, roles, tasks, config) |
| `/dev stop` | Safely shutdown bot |

---

## 🔐 Security

- ✅ Never commit or share `.env` publicly!
- ✅ `.gitignore` protects `.env`, `/data/`, `/backups/`, `/logs/`, and `__pycache__/`
- ✅ All admin functions are role-protected
- ✅ Atomic file writes prevent data loss on crashes
- ✅ Input validation for all user inputs
- ✅ Automatic backups before critical operations

---

## 🧠 Intelligent Features in Detail

### Availability-Based Matchmaking
1. **Slot Matrix Generation**: Creates global time windows based on team availability
2. **Overlap Detection**: Finds optimal play times for both teams
3. **Pause Enforcement**: Guarantees minimum breaks between matches
4. **Time Budget Tracking**: Prevents overloading individual game days
5. **Rescue Mode**: Assigns difficult matches with relaxed rules

### Solo-Player Auto-Matching
- Merges availability of solo players
- Only creates teams with actual time overlap
- Automatic team name generation from dictionary
- Orphan team cleanup for odd player numbers

### Reschedule System
- Automatically finds free slots after tournament end
- Extends tournament when needed
- DM notifications to all affected players
- Button-based voting (consensus required)
- 24h timeout with automatic rejection

---

## 🛣️ Roadmap V3 (Planned)

- 🌀 **Flexible Tournament Modes**: Double Elimination, Swiss System, Group Stage
- 🎨 **Custom Themes**: Customizable embed colors and designs
- 🌐 **Extended Multi-language**: More languages, runtime language switching
- 📆 **Custom Game Days**: More flexible tournament periods
- 🎁 **Reward System**: Automatic key distribution for winners
- 📅 **Calendar Integration**: iCal export for matches
- 📈 **Analytics Dashboard**: Web interface for tournament insights

---

## 📊 Technical Details

### Dependencies
- **discord.py**: Discord bot framework
- **python-dotenv**: Environment variable management
- **typing**: Type hints and annotations
- **zoneinfo**: Timezone-aware datetime handling
- **json**: Configuration and data storage
- **asyncio**: Asynchronous background tasks

### Performance
- Atomic file operations for data safety
- Lazy loading of configurations
- Caching of frequently used data
- Efficient slot matrix generation
- Background tasks for non-blocking operations

### Error Handling
- Global event error handlers
- Slash command error handlers with user feedback
- Graceful degradation on partial failures
- Comprehensive logging for debugging
- Validation at all input levels

---

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## ✨ Credits

- **I3lackEye** – Development, Architecture, Coffee Consumption
- **discord.py Community** – Excellent documentation and support

---

## 📄 License

This project is licensed under the MIT License.

---

## 🔗 Resources

- [discord.py on GitHub](https://github.com/Rapptz/discord.py)
- [discord.py Documentation](https://discordpy.readthedocs.io/en/stable/)
- [Python ZoneInfo](https://docs.python.org/3/library/zoneinfo.html)
- [Discord Developer Portal](https://discord.com/developers/applications)
- [Discord Privileged Intents](https://discord.com/developers/docs/topics/gateway#privileged-intents)

---

## 📞 Support

For questions or issues:
- Open a [GitHub Issue](https://github.com/I3lackEye/HeroldBot/issues)
- Contact I3lackEye

---

**Made with ❤️ and ☕ by I3lackEye**
