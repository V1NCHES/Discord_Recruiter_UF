import json
import os
import datetime
import discord
from discord import app_commands

SETTINGS_FILE = 'settings.json'

def load_settings():
    """Loads settings from the JSON file safely, handles empty or corrupted files."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {"authorized_role_id": None}
                return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            # Если файл пуст или поврежден, возвращаем структуру по умолчанию
            return {"authorized_role_id": None}
    return {"authorized_role_id": None}

def save_settings(settings):
    """Saves settings to the JSON file."""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4)

def has_bot_permission():
    """Custom app_commands check to verify if the user is an admin or has the authorized role (hierarchical check)."""
    def predicate(interaction: discord.Interaction) -> bool:
        # Check for administrator permissions
        if interaction.user.guild_permissions.administrator:
            return True
        
        settings = load_settings()
        role_id = settings.get("authorized_role_id")
        
        # Check if the user has a role NOT LOWER than the authorized role
        if role_id:
            role = interaction.guild.get_role(int(role_id))
            if role:
                user_top_role = interaction.user.top_role
                if user_top_role.position >= role.position:
                    return True
        
        return False
    
    return app_commands.check(predicate)

def increment_stat(stat_name, recruiter_id=None):
    """Increments a counter in settings.json safely, including recruiter-specific counters and history logs."""
    settings = load_settings()
    if "stats" not in settings:
        settings["stats"] = {}
    
    # Инкрементируем общую статистику
    settings["stats"][stat_name] = settings["stats"].get(stat_name, 0) + 1
    
    # Инкрементируем статистику конкретного рекрутера
    if recruiter_id:
        recruiter_id_str = str(recruiter_id)
        if "recruiters" not in settings["stats"]:
            settings["stats"]["recruiters"] = {}
        if recruiter_id_str not in settings["stats"]["recruiters"]:
            settings["stats"]["recruiters"][recruiter_id_str] = {}
            
        recruiter_stats = settings["stats"]["recruiters"][recruiter_id_str]
        recruiter_stats[stat_name] = recruiter_stats.get(stat_name, 0) + 1
        
    # Записываем историю действий с таймстампом
    if "history" not in settings["stats"]:
        settings["stats"]["history"] = []
        
    now_str = datetime.datetime.utcnow().isoformat()
    settings["stats"]["history"].append({
        "timestamp": now_str,
        "recruiter_id": str(recruiter_id) if recruiter_id else None,
        "action": stat_name
    })
    
    save_settings(settings)
