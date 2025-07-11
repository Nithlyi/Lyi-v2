import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import logging

class OwnerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context):
        """Verifica se o usuário que invocou o comando de texto é o proprietário do bot."""
        return await self.bot.is_owner(ctx.author)

    @app_commands.command(name="sync", description="Sincroniza os comandos de barra (apenas para o proprietário do bot).")
    async def sync(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            # Sincroniza comandos globais
            synced_global = await self.bot.tree.sync()
            
            # Se você usa TEST_GUILD_ID, sincronize lá também
            if hasattr(self.bot, 'TEST_GUILD_ID') and self.bot.TEST_GUILD_ID: # Verificação melhorada
                test_guild = discord.Object(id=self.bot.TEST_GUILD_ID)
                self.bot.tree.copy_global_to(guild=test_guild)
                synced_guild = await self.bot.tree.sync(guild=test_guild)
                await interaction.followup.send(f"Comandos globais sincronizados ({len(synced_global)}). Comandos sincronizados para o servidor de testes ({len(synced_guild)}).", ephemeral=True)
            else:
                await interaction.followup.send(f"Comandos globais sincronizados ({len(synced_global)}).", ephemeral=True)
            
            logging.info(f"Comandos de barra sincronizados por {interaction.user.name}")

        except Exception as e:
            logging.error(f"Erro ao sincronizar comandos de barra: {e}")
            # Mensagem de erro consistente com a de reload_cog
            await interaction.followup.send(f"Ocorreu um erro ao sincronizar os comandos de barra: `{e}`", ephemeral=True)

    @app_commands.command(name="reload_cog", description="Recarrega um cog (apenas para o proprietário do bot).")
    @app_commands.describe(cog_name="O nome completo do cog (e.g., cogs.moderation.moderation_commands)")
    async def reload_cog(self, interaction: discord.Interaction, cog_name: str):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.reload_extension(cog_name)
            await interaction.followup.send(f"Cog `{cog_name}` recarregado com sucesso!", ephemeral=True)
            logging.info(f"Cog '{cog_name}' recarregado por {interaction.user.name}")
        except Exception as e:
            await interaction.followup.send(f"Falha ao recarregar cog `{cog_name}`: `{e}`", ephemeral=True)
            logging.error(f"Falha ao recarregar cog '{cog_name}': {e}")

    @app_commands.command(name="shutdown", description="Desliga o bot (apenas para o proprietário do bot).")
    async def shutdown(self, interaction: discord.Interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("Você não tem permissão para usar este comando.", ephemeral=True)
            return

        await interaction.response.send_message("Desligando o bot...", ephemeral=True)
        logging.info(f"Bot desligado por {interaction.user.name}")
        await self.bot.close()

async def setup(bot: commands.Bot):
    await bot.add_cog(OwnerCommands(bot))