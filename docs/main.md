# main.py

This is the main entry point of the Discord bot.

## Responsibilities:
- Loads environment variables (like the bot token).
- Initializes the bot instance with the necessary intents.
- Dynamically loads all command modules (Cogs) from the `cogs/` directory.
- Manages the connection to the Discord Gateway.
