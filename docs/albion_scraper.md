# AlbionDB Scraper & Stats Command

This module provides real-time player statistics extraction from `albiondb.net` (Europe server) and integrates it into the Discord bot.

## Features

- **Automated Scraping**: Uses `undetected-chromedriver` to bypass Cloudflare protection.
- **Detailed Player Data**: Extracts Kill Fame, Death Fame, PvE stats, Gathering, Crafting, and Guild History.
- **Stay Duration Calculation**: Automatically calculates how many days a player spent in each guild.
- **Visual Highlights**: Flags short guild stays (less than 7 days) with a red circle emoji `🔴`.
- **Smart Formatting**: Abbreviates large numbers (e.g., 1.5 billion, 847.5 million) for better readability in Discord embeds.
- **Interactive Links**: Provides direct links to MurderLedger and AlbionDB profiles.

## Commands

### `!stat <nickname>`
Fetches and displays a comprehensive recruitment report for the specified player.

**Output includes:**
- **PvP Stats**: Kill Fame and Death Fame (with shorthand notation).
- **PvE Fame**: Detailed breakdown (Total, Royal, Outlands, Avalon) in a 2x2 grid.
- **Gathering & Crafting**: Total lifetime statistics for resources and crafting.
- **Guild History**: Full list of previous guilds with entry/exit dates and stay duration in days.

## Technical Details

- **Module**: `AL_DB/scraper.py`
- **Driver**: `undetected-chromedriver` (runs in visible mode to ensure bypass).
- **Processing**: Runs in a separate thread using `asyncio.to_thread` to prevent blocking the bot's event loop.
- **Memory Management**: HTML content is processed in-memory; no temporary files are stored after parsing.
