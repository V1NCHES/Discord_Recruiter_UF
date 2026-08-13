import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

import gc
import datetime

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix='/', intents=intents)
        self.start_time = datetime.datetime.now(datetime.timezone.utc)

    async def setup_hook(self):
        # Load extensions (cogs)
        cogs = ['cogs.admin', 'cogs.recruiter']
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f'Loaded extension: {cog}')
            except Exception as e:
                print(f"Failed to load extension {cog}: {e}")
        
        # Sync the app commands tree
        try:
            synced = await self.tree.sync()
            print(f'Synced {len(synced)} command(s)')
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

bot = MyBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ У вас нет прав для использования этой команды.", ephemeral=True)
        elif isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Эта команда доступна только администраторам.", ephemeral=True)
        else:
            # Default fallback
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Произошла ошибка: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Произошла ошибка: {error}", ephemeral=True)
    finally:
        gc.collect()


if __name__ == '__main__':
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN not found in .env file.")
