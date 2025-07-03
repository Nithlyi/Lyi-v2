import discord
from discord.ext import commands
from discord import app_commands

class DiversionCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hello", description="Diz olá!")
    async def hello(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Olá, {interaction.user.display_name}!", ephemeral=False)

    # Adicione mais comandos de diversão aqui, como !roll, !8ball, etc.

async def setup(bot: commands.Bot):
    await bot.add_cog(DiversionCommands(bot))
