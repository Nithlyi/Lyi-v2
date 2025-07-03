import discord
from discord.ext import commands
from discord import app_commands
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SayCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="say", description="Faz o bot enviar uma mensagem em um canal específico.")
    @app_commands.describe(
        channel="O canal onde a mensagem será enviada.",
        message="O conteúdo da mensagem que o bot irá enviar."
    )
    @app_commands.checks.has_permissions(manage_messages=True) # Requer permissão para gerenciar mensagens
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        await interaction.response.defer(ephemeral=True) # Deferir a interação para evitar timeout

        # Verifica se o bot tem permissão para enviar mensagens no canal alvo
        if not channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {channel.mention}.", ephemeral=True)
            logging.warning(f"Comando /say: Bot sem permissão para enviar mensagem no canal {channel.id} na guild {interaction.guild.id}.")
            return

        try:
            await channel.send(message)
            await interaction.followup.send(f"Mensagem enviada com sucesso em {channel.mention}.", ephemeral=True)
            logging.info(f"Comando /say usado por {interaction.user.id} para enviar mensagem em {channel.id} na guild {interaction.guild.id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao enviar a mensagem: {e}", ephemeral=True)
            logging.error(f"Comando /say: Erro ao enviar mensagem em {channel.id} na guild {interaction.guild.id}: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(SayCommand(bot))

