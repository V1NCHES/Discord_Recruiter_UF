# Cogs (Command Modules)

The `cogs/` directory contains modular command groups.

## `admin.py`
Contains administrative commands.
- **`!setting @Role`**: Allows a server administrator to define which role can use the recruiter tools.

## `recruiter.py`
Contains the core functionality for recruitment.
- **`!info_rec`**: Shows the help menu with all available recruitment commands.
- **`!stat <nickname>`**: Fetches, parses, and displays a comprehensive player profile card from AlbionDB (including PvP, PvE, Gathering, Crafting, and full Guild History with stay durations).

## `general.py`
Contains utility commands.
- **`!ping`**: A simple command to check if the bot is online and responding.
