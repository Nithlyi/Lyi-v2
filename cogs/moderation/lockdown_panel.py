import discord
from discord.ext import commands
import logging
from discord.ui import Button, View
from discord import ButtonStyle, app_commands
from database import execute_query # Certifique-se de que database.py está no caminho correto
import json # Para lidar com embeds em formato JSON

logger = logging.getLogger(__name__)

# Certifique-se de que o LockdownCore está carregado ANTES deste cog
# A lógica de lockdown real (aplicar/remover permissões) deve estar no LockdownCore

class LockdownPanelButtons(View):
    def __init__(self, bot):
        super().__init__(timeout=None) # Timeout=None para view persistente
        self.bot = bot

    @discord.ui.button(label="Ativar Lockdown", style=ButtonStyle.red, custom_id="lockdown_panel:activate")
    async def activate_lockdown(self, interaction: discord.Interaction, button: Button):
        # A lógica de lockdown está no LockdownCore
        lockdown_cog = self.bot.get_cog("LockdownCore")
        if not lockdown_cog:
            await interaction.response.send_message("❌ Erro interno: O módulo de lockdown não está carregado corretamente.", ephemeral=True)
            logger.error("LockdownCore cog não encontrado ao tentar ativar lockdown do painel.")
            return

        # Verifica permissões do usuário que clicou
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("🚫 Você não tem permissão para ativar o lockdown (requer 'Gerenciar Canais').", ephemeral=True)
            return

        # Busca o canal atual do painel de lockdown para ver se ele já está bloqueado
        panel_settings = execute_query("SELECT channel_id FROM lockdown_panel_settings WHERE guild_id = ?", 
                                        (interaction.guild_id,), fetchone=True)
        
        if panel_settings and panel_settings[0] == interaction.channel_id:
            # Se o botão está no canal do painel, verificar se o *canal do painel* já está em lockdown
            is_locked = execute_query("SELECT channel_id FROM locked_channels WHERE channel_id = ?", 
                                      (interaction.channel_id,), fetchone=True)
            if is_locked:
                await interaction.response.send_message("⚠️ Este canal já está em lockdown.", ephemeral=True)
                return

            try:
                # Usar a função de lockdown do LockdownCore para o canal atual
                await interaction.response.defer(ephemeral=True) # Defer para evitar "Interaction failed"
                await lockdown_cog._update_channel_permissions(interaction.channel, True)
                await lockdown_cog._add_locked_channel_to_db(interaction.channel.id, interaction.guild_id, None, "Ativado via painel de lockdown", interaction.user.id)
                await interaction.followup.send(f"🔒 Este canal ({interaction.channel.mention}) foi colocado em lockdown!", ephemeral=False)
                logger.info(f"Canal {interaction.channel.id} bloqueado via painel por {interaction.user.id}.")
            except Exception as e:
                await interaction.followup.send(f"❌ Ocorreu um erro ao tentar ativar o lockdown: {e}", ephemeral=True)
                logger.error(f"Erro ao ativar lockdown via painel para canal {interaction.channel.id}: {e}", exc_info=True)
        else:
            await interaction.response.send_message("❌ Este painel de lockdown não está configurado para este canal.", ephemeral=True)


    @discord.ui.button(label="Desativar Lockdown", style=ButtonStyle.green, custom_id="lockdown_panel:deactivate")
    async def deactivate_lockdown(self, interaction: discord.Interaction, button: Button):
        lockdown_cog = self.bot.get_cog("LockdownCore")
        if not lockdown_cog:
            await interaction.response.send_message("❌ Erro interno: O módulo de lockdown não está carregado corretamente.", ephemeral=True)
            logger.error("LockdownCore cog não encontrado ao tentar desativar lockdown do painel.")
            return
        
        # Verifica permissões do usuário que clicou
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("🚫 Você não tem permissão para desativar o lockdown (requer 'Gerenciar Canais').", ephemeral=True)
            return

        # Busca o canal atual do painel de lockdown para ver se ele está bloqueado
        panel_settings = execute_query("SELECT channel_id FROM lockdown_panel_settings WHERE guild_id = ?", 
                                        (interaction.guild_id,), fetchone=True)
        
        if panel_settings and panel_settings[0] == interaction.channel_id:
            # Se o botão está no canal do painel, verificar se o *canal do painel* está em lockdown
            is_locked = execute_query("SELECT channel_id FROM locked_channels WHERE channel_id = ?", 
                                      (interaction.channel_id,), fetchone=True)
            if not is_locked:
                await interaction.response.send_message("⚠️ Este canal não está em lockdown.", ephemeral=True)
                return

            try:
                # Usar a função de unlock do LockdownCore para o canal atual
                await interaction.response.defer(ephemeral=True)
                await lockdown_cog._update_channel_permissions(interaction.channel, False)
                await lockdown_cog._remove_locked_channel_from_db(interaction.channel.id)
                # Cancelar tarefa agendada se existir
                if interaction.channel.id in lockdown_cog.lockdown_tasks:
                    lockdown_cog.lockdown_tasks[interaction.channel.id].cancel()
                    del lockdown_cog.lockdown_tasks[interaction.channel.id]

                await interaction.followup.send(f"🔓 Este canal ({interaction.channel.mention}) foi desbloqueado!", ephemeral=False)
                logger.info(f"Canal {interaction.channel.id} desbloqueado via painel por {interaction.user.id}.")
            except Exception as e:
                await interaction.followup.send(f"❌ Ocorreu um erro ao tentar desativar o lockdown: {e}", ephemeral=True)
                logger.error(f"Erro ao desativar lockdown via painel para canal {interaction.channel.id}: {e}", exc_info=True)
        else:
            await interaction.response.send_message("❌ Este painel de lockdown não está configurado para este canal.", ephemeral=True)


class LockdownPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Cog de Painel de Lockdown inicializada.")
        # O bot.add_view(LockdownPanelButtons(self.bot)) é normalmente feito no on_ready
        # ou em um setup_hook para views persistentes carregadas do DB.
        # Mas para garantir que a view é "conhecida" pelo bot desde o início, mantemos aqui.
        # A forma mais robusta é no listener on_ready ou setup_hook após o carregamento do DB.

    @commands.hybrid_group(name="lockdown_panel", description="Comandos para gerenciar o painel de lockdown.")
    @commands.has_permissions(manage_guild=True)
    async def lockdown_panel_group(self, ctx: commands.Context):
        """Comandos para gerenciar o painel de lockdown."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Comando inválido para o painel de lockdown. Use `setup` ou `remove`.", ephemeral=True) # Adicionado ephemeral=True

    @lockdown_panel_group.command(name="setup", description="Configura o painel de lockdown em um canal.")
    @app_commands.describe(
        channel="O canal onde o painel de lockdown será enviado."
    )
    async def setup_panel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not ctx.guild:
            return await ctx.send("Este comando só pode ser usado em um servidor.", ephemeral=True)

        embed = discord.Embed(
            title="Painel de Lockdown",
            description="Clique nos botões abaixo para ativar ou desativar o lockdown neste canal.",
            color=discord.Color.red()
        )
        embed.set_footer(text="Apenas membros com permissão de 'Gerenciar Canais' podem usar.")

        # Tenta enviar a mensagem e guardar o ID
        try:
            message = await channel.send(embed=embed, view=LockdownPanelButtons(self.bot))
            
            # Salva no banco de dados
            execute_query(
                "INSERT OR REPLACE INTO lockdown_panel_settings (guild_id, channel_id, message_id) VALUES (?, ?, ?)",
                (ctx.guild.id, channel.id, message.id)
            )
            await ctx.send(f"✅ Painel de lockdown configurado em {channel.mention}.", ephemeral=True)
            logger.info(f"Painel de lockdown configurado no guild {ctx.guild.id} no canal {channel.id} (message_id: {message.id}).")
        except discord.Forbidden:
            await ctx.send(f"🚫 Não tenho permissão para enviar mensagens no canal {channel.mention}. Verifique minhas permissões.", ephemeral=True)
            logger.error(f"Erro de permissão ao configurar painel de lockdown no guild {ctx.guild.id} canal {channel.id}.")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao configurar o painel de lockdown: {e}", ephemeral=True)
            logger.error(f"Erro ao configurar painel de lockdown no guild {ctx.guild.id}: {e}", exc_info=True)


    @lockdown_panel_group.command(name="remove", description="Remove o painel de lockdown configurado.")
    async def remove_panel(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send("Este comando só pode ser usado em um servidor.", ephemeral=True)

        settings = execute_query("SELECT channel_id, message_id FROM lockdown_panel_settings WHERE guild_id = ?", 
                                 (ctx.guild.id,), fetchone=True)

        if not settings:
            return await ctx.send("⚠️ Nenhum painel de lockdown configurado para este servidor.", ephemeral=True)

        channel_id, message_id = settings
        channel = self.bot.get_channel(channel_id)

        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                await ctx.send(f"✅ Painel de lockdown removido de {channel.mention}.", ephemeral=True)
            except discord.NotFound:
                await ctx.send("⚠️ Mensagem do painel de lockdown não encontrada. Removendo apenas do banco de dados.", ephemeral=True)
            except discord.Forbidden:
                await ctx.send(f"🚫 Não tenho permissão para apagar mensagens no canal {channel.mention}. Removendo apenas do banco de dados.", ephemeral=True)
                logger.warning(f"Não foi possível apagar mensagem do painel de lockdown em {channel.id} para guild {ctx.guild.id}. Permissões insuficientes.")
            except Exception as e:
                await ctx.send(f"❌ Ocorreu um erro ao tentar apagar a mensagem: {e}", ephemeral=True)
                logger.error(f"Erro ao apagar mensagem do painel de lockdown: {e}", exc_info=True)
        
        execute_query("DELETE FROM lockdown_panel_settings WHERE guild_id = ?", (ctx.guild.id,))
        logger.info(f"Painel de lockdown removido do DB para guild {ctx.guild.id}.")
        
        if not channel: # Se o canal não foi encontrado, mas a entrada existia no DB
            await ctx.send("✅ Configuração do painel de lockdown removida do banco de dados (o canal original pode não existir mais).", ephemeral=True)


    @commands.Cog.listener()
    async def on_ready(self):
        # Garante que as views persistentes são adicionadas ao bot
        # Isso é importante para que os botões do painel funcionem após um reinício
        self.bot.add_view(LockdownPanelButtons(self.bot))
        logger.info("Views persistentes de Painel de Lockdown garantidas.")


# Esta função é CRUCIAL para o bot carregar o cog.
async def setup(bot):
    """Adiciona o cog de Painel de Lockdown ao bot."""
    await bot.add_cog(LockdownPanel(bot))
    logger.info("Cog de Painel de Lockdown configurada e adicionada ao bot.")