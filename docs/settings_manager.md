# settings_manager.py

This module manages the bot's configuration and persistence.

## Responsibilities:
- **`load_settings()`**: Reads the `settings.json` file to retrieve the authorized role ID.
- **`save_settings()`**: Writes updates to the `settings.json` file.
- **`has_bot_permission()`**: A custom decorator used in command modules to verify if a user has permission to execute a command (Administrator or Authorized Role).
