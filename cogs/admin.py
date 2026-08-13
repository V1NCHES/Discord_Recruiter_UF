import discord
from discord.ext import commands
from discord import app_commands
from settings_manager import load_settings, save_settings

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setting_role", description="Устанавливает роль, которая авторизована использовать команды бота.")
    @app_commands.default_permissions(administrator=True)
    async def setting_role(self, interaction: discord.Interaction, role: discord.Role):
        """Sets the role that is authorized to use the bot commands."""
        settings = load_settings()
        settings["authorized_role_id"] = role.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ Роль {role.mention} теперь имеет доступ к командам бота.")

    @app_commands.command(name="setting_channel", description="Устанавливает канал для логов закрытия тикетов.")
    @app_commands.default_permissions(administrator=True)
    async def setting_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Sets the channel where ticket closure logs are sent."""
        settings = load_settings()
        settings["ticket_log_channel_id"] = channel.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ Канал {channel.mention} теперь используется для отчетов о закрытии тикетов.")

    @app_commands.command(name="setting_ban_channel", description="Устанавливает канал для логов банов.")
    @app_commands.default_permissions(administrator=True)
    async def setting_ban_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Sets the channel where ban logs are sent."""
        settings = load_settings()
        settings["ban_log_channel_id"] = channel.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ Канал {channel.mention} теперь используется для отчетов о банах.")

    @app_commands.command(name="setting_rejected_channel", description="Устанавливает канал для логов отклоненных тикетов.")
    @app_commands.default_permissions(administrator=True)
    async def setting_rejected_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Sets the channel where rejected ticket logs are sent."""
        settings = load_settings()
        settings["rejected_log_channel_id"] = channel.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ Канал {channel.mention} теперь используется для отчетов об отклоненных тикетах.")

    @app_commands.command(name="setting_ping_message", description="Устанавливает текст для пинга участников, зашедших на сервер за последние 3 дня.")
    @app_commands.default_permissions(administrator=True)
    async def setting_ping_message(self, interaction: discord.Interaction, message: str):
        """Sets the custom ping message for newcomers."""
        settings = load_settings()
        settings["newcomers_ping_message"] = message
        save_settings(settings)
        await interaction.response.send_message(f"✅ Сообщение для пинга новых участников успешно обновлено на:\n>>> {message}")

async def setup(bot):
    await bot.add_cog(Admin(bot))
