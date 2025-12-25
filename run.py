#!/usr/bin/env python3
"""
HeroldBot Launcher Script
Ensures correct Python path setup before starting the bot.
"""
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now import and run the bot
if __name__ == "__main__":
    from modules.main import main
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] Bot shutdown requested by user (Ctrl+C)")
    except Exception as e:
        print(f"[SYSTEM] ❌ CRITICAL: Unexpected error: {e}")
        raise
