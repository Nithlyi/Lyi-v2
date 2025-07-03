# cogs/moderation/lockdown_core.py
import discord
from discord.ext import commands
import logging
from database import execute_query
import asyncio
import time
from typing import Optional 
from discord import app_commands # Adicionado: Importa app_commands

logger = logging.getLogger(__name__)

class LockdownCore(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Cog de Lockdown Core inicializada.")
        self.lockdown_tasks = {} # Para gerenciar lockdowns temporários

    async def _update_channel_permissions(self, channel: discord.TextChannel, locked: bool):
        """
        Atualiza as permissões de envio de mensagens para o @everyone.
        """
        everyone_role = channel.guild.default_role
        
        if locked:
            # Sobrescrever a permissão de @everyone para remover permissão de enviar mensagens
            # Permissões.send_messages deve ser False para lockdown
            await channel.set_permissions(everyone_role, send_messages=False, reason="Lockdown ativado.")
        else:
            # Remover a sobrescrita para @everyone ou definir como None (herdar)
            # Neste caso, queremos definir como None para que o canal volte ao normal
            # ou herde as permissões da categoria.
            await channel.set_permissions(everyone_role, send_messages=None, reason="Lockdown desativado.")
        
    async def _add_locked_channel_to_db(self, channel_id: int, guild_id: int, locked_until: Optional[int], reason: Optional[str], locked_by_id: int):
        """Adiciona um canal bloqueado ao banco de dados."""
        execute_query(
            "INSERT OR REPLACE INTO locked_channels (channel_id, guild_id, locked_until_timestamp, reason, locked_by_id) VALUES (?, ?, ?, ?, ?)",
            (channel_id, guild_id, locked_until, reason, locked_by_id)
        )
        logger.info(f"Canal {channel_id} do guild {guild_id} adicionado ao DB como bloqueado.")

    async def _remove_locked_channel_from_db(self, channel_id: int):
        """Remove um canal bloqueado do banco de dados."""
        execute_query("DELETE FROM locked_channels WHERE channel_id = ?", (channel_id,))
        logger.info(f"Canal {channel_id} removido do DB de canais bloqueados.")

    @commands.hybrid_command(name="lockdown", description="Ativa o modo de lockdown para o canal atual ou especificado.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe( # Removido app_commands.describe por enquanto, caso esteja dando erro
        channel="O canal para ativar o lockdown (padrão: canal atual).",
        duration="Duração do lockdown (ex: 1h, 30m, 5s).",
        reason="A razão para o lockdown."
    )
    async def lockdown(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, duration: Optional[str] = None, *, reason: Optional[str] = "Nenhuma razão fornecida."):
        channel = channel or ctx.channel
        
        # Verificar se o canal já está bloqueado no DB
        if execute_query("SELECT channel_id FROM locked_channels WHERE channel_id = ?", (channel.id,), fetchone=True):
            return await ctx.send(f"⚠️ O canal {channel.mention} já está em lockdown!")

        locked_until_timestamp = None
        if duration:
            seconds = self._parse_duration(duration)
            if seconds is None:
                return await ctx.send("❌ Duração inválida. Use formatos como `1h`, `30m`, `5s`.")
            locked_until_timestamp = int(time.time()) + seconds
            
        await self._update_channel_permissions(channel, True)
        
        # Adicionar ao DB
        await self._add_locked_channel_to_db(channel.id, ctx.guild.id, locked_until_timestamp, reason, ctx.author.id)

        if duration:
            await ctx.send(f"🔒 {channel.mention} colocado em lockdown por {duration} devido a: {reason}. Eu irei desbloqueá-lo automaticamente.")
            # Iniciar tarefa de desbloqueio agendado
            self.lockdown_tasks[channel.id] = self.bot.loop.create_task(
                self._timed_unlock(channel, seconds)
            )
        else:
            await ctx.send(f"🔒 {channel.mention} colocado em lockdown indefinidamente devido a: {reason}.")
        logger.info(f"Canal {channel.id} em {ctx.guild.id} bloqueado por {ctx.author.id}. Duração: {duration}, Razão: {reason}")


    @commands.hybrid_command(name="unlock", description="Desativa o modo de lockdown para o canal atual ou especificado.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe( # Removido app_commands.describe por enquanto, caso esteja dando erro
        channel="O canal para desativar o lockdown (padrão: canal atual)."
    )
    async def unlock(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        channel = channel or ctx.channel

        # Verificar se o canal está bloqueado no DB
        if not execute_query("SELECT channel_id FROM locked_channels WHERE channel_id = ?", (channel.id,), fetchone=True):
            return await ctx.send(f"⚠️ O canal {channel.mention} não está em lockdown!")

        await self._update_channel_permissions(channel, False)
        await self._remove_locked_channel_from_db(channel.id)

        # Cancelar tarefa agendada se existir
        if channel.id in self.lockdown_tasks:
            self.lockdown_tasks[channel.id].cancel()
            del self.lockdown_tasks[channel.id]

        await ctx.send(f"🔓 {channel.mention} foi desbloqueado.")
        logger.info(f"Canal {channel.id} em {ctx.guild.id} desbloqueado por {ctx.author.id}.")

    async def _timed_unlock(self, channel: discord.TextChannel, seconds: int):
        await asyncio.sleep(seconds)
        if execute_query("SELECT channel_id FROM locked_channels WHERE channel_id = ?", (channel.id,), fetchone=True):
            await self._update_channel_permissions(channel, False)
            await self._remove_locked_channel_from_db(channel.id)
            try:
                await channel.send(f"🔓 O lockdown deste canal ({channel.mention}) foi automaticamente desativado após {self._format_seconds(seconds)}.")
            except discord.Forbidden:
                logger.warning(f"Não foi possível enviar mensagem de desbloqueio para {channel.id} após lockdown temporário.")
            except Exception as e:
                logger.error(f"Erro ao enviar mensagem de desbloqueio para {channel.id}: {e}", exc_info=True)
            logger.info(f"Lockdown temporário do canal {channel.id} em {channel.guild.id} finalizado.")
        if channel.id in self.lockdown_tasks:
            del self.lockdown_tasks[channel.id]

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Converte uma string de duração (ex: '1h', '30m', '5s') em segundos."""
        total_seconds = 0
        current_num = ""
        for char in duration_str:
            if char.isdigit():
                current_num += char
            else:
                if not current_num:
                    return None # Formato inválido
                num = int(current_num)
                if char == 's':
                    total_seconds += num
                elif char == 'm':
                    total_seconds += num * 60
                elif char == 'h':
                    total_seconds += num * 3600
                elif char == 'd':
                    total_seconds += num * 86400
                else:
                    return None # Unidade inválida
                current_num = ""
        return total_seconds

    def _format_seconds(self, seconds: int) -> str:
        """Formata segundos em uma string legível (ex: '1h 30m')."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds}s" if remaining_seconds > 0 else f"{minutes}m"
        else:
            hours = seconds // 3600
            remaining_minutes = (seconds % 3600) // 60
            return f"{hours}h {remaining_minutes}m" if remaining_minutes > 0 else f"{hours}h"

    # Listener para carregar estados de lockdown persistentes ao iniciar
    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("Verificando canais em lockdown persistentes...")
        locked_channels_data = execute_query("SELECT channel_id, locked_until_timestamp FROM locked_channels", fetchall=True)
        if locked_channels_data:
            current_time = int(time.time())
            for channel_id, locked_until_timestamp in locked_channels_data:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    logger.warning(f"Canal em lockdown {channel_id} não encontrado, removendo do DB.")
                    await self._remove_locked_channel_from_db(channel_id)
                    continue

                if locked_until_timestamp and locked_until_timestamp <= current_time:
                    # O tempo de lockdown já expirou, desbloquear e remover
                    await self._update_channel_permissions(channel, False)
                    await self._remove_locked_channel_from_db(channel_id)
                    try:
                        await channel.send(f"🔓 O lockdown deste canal ({channel.mention}) foi automaticamente desativado ao reiniciar o bot (tempo expirado).")
                    except discord.Forbidden:
                        logger.warning(f"Não foi possível enviar mensagem de desbloqueio para {channel.id} após reiniciar o bot (tempo expirado).")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem de desbloqueio para {channel.id}: {e}", exc_info=True)
                    logger.info(f"Lockdown temporário do canal {channel.id} em {channel.guild.id} finalizado.")
                else:
                    # Ainda em lockdown, garantir permissões e agendar desbloqueio se temporário
                    await self._update_channel_permissions(channel, True)
                    if locked_until_timestamp:
                        remaining_seconds = locked_until_timestamp - current_time
                        if remaining_seconds > 0:
                            self.lockdown_tasks[channel_id] = self.bot.loop.create_task(
                                self._timed_unlock(channel, remaining_seconds)
                            )
                            logger.info(f"Lockdown temporário para {channel.id} restabelecido por {remaining_seconds} segundos.")
                        else: # Caso por algum motivo o timestamp seja futuro mas menor que 0
                             await self._update_channel_permissions(channel, False)
                             await self._remove_locked_channel_from_db(channel_id)
                             logger.info(f"Lockdown para {channel.id} expirou durante a inicialização e foi desativado.")
                    logger.info(f"Canal {channel.id} em {channel.guild.id} carregado como em lockdown.")
        else:
            logger.info("Nenhum canal em lockdown persistente encontrado.")


# Esta função é CRUCIAL para o bot carregar o cog.
async def setup(bot):
    """Adiciona o cog de Lockdown Core ao bot."""
    await bot.add_cog(LockdownCore(bot))
    logger.info("Cog de Lockdown Core configurada e adicionada ao bot.")