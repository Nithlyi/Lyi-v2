import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import logging
import re # Para parsing do tempo

from database import execute_query

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Funções Auxiliares para Parsing de Tempo ---
def parse_duration(duration_str: str) -> datetime.timedelta:
    """
    Parses a duration string (e.g., "1h", "30m", "2d") into a datetime.timedelta object.
    Supports: s (seconds), m (minutes), h (hours), d (days).
    """
    seconds = 0
    if not duration_str:
        raise ValueError("Duração não pode ser vazia.")

    # Regex para encontrar números e unidades (s, m, h, d)
    parts = re.findall(r'(\d+)([smhd])', duration_str.lower())
    if not parts:
        raise ValueError("Formato de duração inválido. Use, por exemplo: '30m', '1h', '2d'.")

    for value, unit in parts:
        value = int(value)
        if unit == 's':
            seconds += value
        elif unit == 'm':
            seconds += value * 60
        elif unit == 'h':
            seconds += value * 3600
        elif unit == 'd':
            seconds += value * 86400
    
    # Discord API timeout limit is 28 days (2419200 seconds)
    if seconds > 2419200:
        raise ValueError("A duração máxima para silenciamento é de 28 dias.")

    return datetime.timedelta(seconds=seconds)


# --- Modals para Ações de Moderação ---
class WarnModal(ui.Modal, title="Advertir Usuário"):
    def __init__(self, target_member: discord.Member, target_channel: discord.TextChannel):
        super().__init__()
        self.target_member = target_member
        self.target_channel = target_channel

        self.reason = ui.TextInput(
            label="Razão da Advertência",
            placeholder="Descreva o motivo da advertência...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        
        reason_text = self.reason.value

        success = execute_query(
            "INSERT INTO moderation_logs (guild_id, action, target_id, moderator_id, reason) VALUES (?, ?, ?, ?, ?)",
            (interaction.guild_id, "warn", self.target_member.id, interaction.user.id, reason_text)
        )

        if success:
            embed = discord.Embed(
                title="Advertência Registrada",
                description=f"O usuário {self.target_member.mention} foi advertido.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Razão", value=reason_text, inline=False)
            embed.add_field(name="Canal da Advertência", value=self.target_channel.mention, inline=True)
            embed.set_footer(text=f"ID do Usuário: {self.target_member.id}")

            try:
                await self.target_channel.send(embed=embed)
                await interaction.followup.send(f"Advertência enviada para {self.target_channel.mention}!", ephemeral=True)
                logging.info(f"Advertência registrada para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id} e enviada para {self.target_channel.name}. Razão: {reason_text}")
            except discord.Forbidden:
                await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {self.target_channel.mention}.", ephemeral=True)
                logging.error(f"Permissão negada ao enviar advertência para {self.target_channel.name} na guild {interaction.guild.id}.")
            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro ao enviar a advertência: {e}", ephemeral=True)
                logging.error(f"Erro ao enviar advertência para {self.target_channel.name}: {e}")

            try:
                dm_embed = discord.Embed(
                    title="Você foi Advertido(a)!",
                    description=f"Você recebeu uma advertência no servidor **{interaction.guild.name}**.",
                    color=discord.Color.orange()
                )
                dm_embed.add_field(name="Razão", value=reason_text, inline=False)
                dm_embed.add_field(name="Canal", value=self.target_channel.mention, inline=True)
                dm_embed.set_footer(text="Por favor, revise as regras do servidor para evitar futuras advertências.")
                await self.target_member.send(embed=dm_embed)
                logging.info(f"DM de advertência enviada para {self.target_member.id}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar DM de advertência para {self.target_member.id}.")
            except Exception as e:
                logging.error(f"Erro ao enviar DM de advertência para {self.target_member.id}: {e}")

        else:
            await interaction.followup.send("Ocorreu um erro ao registrar a advertência no banco de dados.", ephemeral=True)
            logging.error(f"Erro ao registrar advertência no DB para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild_id}.")


class KickModal(ui.Modal, title="Expulsar Usuário"):
    def __init__(self, target_member: discord.Member, target_channel: discord.TextChannel):
        super().__init__()
        self.target_member = target_member
        self.target_channel = target_channel
        self.reason = ui.TextInput(
            label="Razão da Expulsão",
            placeholder="Descreva o motivo da expulsão...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason_text = self.reason.value

        if not self.target_member:
            await interaction.followup.send("Membro alvo não encontrado para expulsão.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.kick_members:
            await interaction.followup.send("Não tenho permissão para expulsar membros.", ephemeral=True)
            return
        if interaction.user.top_role <= self.target_member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Você não pode expulsar um membro com cargo igual ou superior ao seu.", ephemeral=True)
            return
        if self.target_member.id == interaction.user.id:
            await interaction.followup.send("Você não pode expulsar a si mesmo.", ephemeral=True)
            return
        if self.target_member.id == interaction.guild.owner_id:
            await interaction.followup.send("Você não pode expulsar o proprietário do servidor.", ephemeral=True)
            return
        if self.target_member.bot and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send("Você não pode expulsar um bot a menos que seja um administrador.", ephemeral=True)
            return

        try:
            try:
                dm_embed = discord.Embed(
                    title="Você foi Expulso(a)!",
                    description=f"Você foi expulso(a) do servidor **{interaction.guild.name}**.",
                    color=discord.Color.red()
                )
                dm_embed.add_field(name="Razão", value=reason_text, inline=False)
                dm_embed.set_footer(text="Esta ação é permanente. Você pode tentar entrar novamente se for um erro.")
                await self.target_member.send(embed=dm_embed)
                logging.info(f"DM de expulsão enviada para {self.target_member.id}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar DM de expulsão para {self.target_member.id}.")
            except Exception as e:
                logging.error(f"Erro ao enviar DM de expulsão para {self.target_member.id}: {e}")

            await self.target_member.kick(reason=reason_text)
            
            execute_query(
                "INSERT INTO moderation_logs (guild_id, action, target_id, moderator_id, reason) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, "kick", self.target_member.id, interaction.user.id, reason_text)
            )

            embed = discord.Embed(
                title="Usuário Expulso",
                description=f"O usuário {self.target_member.mention} foi expulso.",
                color=discord.Color.red()
            )
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Razão", value=reason_text, inline=False)
            embed.add_field(name="Canal da Expulsão", value=self.target_channel.mention, inline=True)
            embed.set_footer(text=f"ID do Usuário: {self.target_member.id}")

            try:
                await self.target_channel.send(embed=embed)
                await interaction.followup.send(f"Expulsão enviada para {self.target_channel.mention}!", ephemeral=True)
                logging.info(f"Expulsão registrada para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id} e enviada para {self.target_channel.name}. Razão: {reason_text}")
            except discord.Forbidden:
                await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {self.target_channel.mention}.", ephemeral=True)
                logging.error(f"Permissão negada ao enviar expulsão para {self.target_channel.name} na guild {interaction.guild.id}.")
            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro ao enviar a expulsão: {e}", ephemeral=True)
                logging.error(f"Erro ao enviar expulsão para {self.target_channel.name}: {e}")

        except discord.Forbidden:
            await interaction.followup.send("N��o tenho permissão para expulsar este membro.", ephemeral=True)
            logging.error(f"Permissão negada ao expulsar {self.target_member.id} na guild {interaction.guild.id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao expulsar o membro: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao expulsar {self.target_member.id}: {e}")


class BanModal(ui.Modal, title="Banir Usuário"):
    def __init__(self, target_member: discord.Member, target_channel: discord.TextChannel):
        super().__init__()
        self.target_member = target_member
        self.target_channel = target_channel
        self.reason = ui.TextInput(
            label="Razão do Banimento",
            placeholder="Descreva o motivo do banimento...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)
        self.delete_message_days = ui.TextInput(
            label="Deletar Histórico de Mensagens (dias)",
            placeholder="Número de dias (0 a 7) para deletar mensagens. Padrão: 0",
            style=discord.TextStyle.short,
            required=False,
            default="0"
        )
        self.add_item(self.delete_message_days)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason_text = self.reason.value
        delete_days = 0
        try:
            delete_days = int(self.delete_message_days.value)
            if not 0 <= delete_days <= 7:
                await interaction.followup.send("O número de dias para deletar histórico deve ser entre 0 e 7.", ephemeral=True)
                return
        except ValueError:
            await interaction.followup.send("Por favor, insira um número válido para deletar histórico de mensagens.", ephemeral=True)
            return

        if not self.target_member:
            await interaction.followup.send("Membro alvo não encontrado para banimento.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.followup.send("Não tenho permissão para banir membros.", ephemeral=True)
            return
        if interaction.user.top_role <= self.target_member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Você não pode banir um membro com cargo igual ou superior ao seu.", ephemeral=True)
            return
        if self.target_member.id == interaction.user.id:
            await interaction.followup.send("Você não pode banir a si mesmo.", ephemeral=True)
            return
        if self.target_member.id == interaction.guild.owner_id:
            await interaction.followup.send("Você não pode banir o proprietário do servidor.", ephemeral=True)
            return
        if self.target_member.bot and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send("Você não pode banir um bot a menos que seja um administrador.", ephemeral=True)
            return

        try:
            try:
                dm_embed = discord.Embed(
                    title="Você foi Banido(a)!",
                    description=f"Você foi banido(a) do servidor **{interaction.guild.name}**.",
                    color=discord.Color.dark_red()
                )
                dm_embed.add_field(name="Razão", value=reason_text, inline=False)
                dm_embed.set_footer(text="Esta ação é permanente e impede que você entre novamente.")
                await self.target_member.send(embed=dm_embed)
                logging.info(f"DM de banimento enviada para {self.target_member.id}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar DM de banimento para {self.target_member.id}.")
            except Exception as e:
                logging.error(f"Erro ao enviar DM de banimento para {self.target_member.id}: {e}")

            await self.target_member.ban(reason=reason_text, delete_message_days=delete_days)
            
            execute_query(
                "INSERT INTO moderation_logs (guild_id, action, target_id, moderator_id, reason) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, "ban", self.target_member.id, interaction.user.id, reason_text)
            )

            embed = discord.Embed(
                title="Usuário Banido",
                description=f"O usuário {self.target_member.mention} foi banido.",
                color=discord.Color.dark_red()
            )
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Razão", value=reason_text, inline=False)
            embed.add_field(name="Mensagens Deletadas (dias)", value=delete_days, inline=True)
            embed.add_field(name="Canal do Banimento", value=self.target_channel.mention, inline=True)
            embed.set_footer(text=f"ID do Usuário: {self.target_member.id}")

            try:
                await self.target_channel.send(embed=embed)
                await interaction.followup.send(f"Banimento enviado para {self.target_channel.mention}!", ephemeral=True)
                logging.info(f"Banimento registrado para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id} e enviada para {self.target_channel.name}. Razão: {reason_text}. Mensagens deletadas: {delete_days} dias.")
            except discord.Forbidden:
                await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {self.target_channel.mention}.", ephemeral=True)
                logging.error(f"Permissão negada ao enviar banimento para {self.target_channel.name} na guild {interaction.guild.id}.")
            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro ao enviar o banimento: {e}", ephemeral=True)
                logging.error(f"Erro ao enviar banimento para {self.target_channel.name}: {e}")

        except discord.Forbidden:
            await interaction.followup.send("Não tenho permissão para banir este membro.", ephemeral=True)
            logging.error(f"Permissão negada ao banir {self.target_member.id} na guild {interaction.guild.id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao banir o membro: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao banir {self.target_member.id}: {e}")


class MuteModal(ui.Modal, title="Silenciar Usuário"):
    def __init__(self, target_member: discord.Member, target_channel: discord.TextChannel):
        super().__init__()
        self.target_member = target_member
        self.target_channel = target_channel
        self.duration_input = ui.TextInput(
            label="Duração do Silenciamento (ex: 30m, 1h, 2d)",
            placeholder="Ex: 30m para 30 minutos, 1h para 1 hora, 2d para 2 dias (máx: 28d)",
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.duration_input)
        self.reason = ui.TextInput(
            label="Razão do Silenciamento",
            placeholder="Descreva o motivo do silenciamento...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason_text = self.reason.value
        duration_str = self.duration_input.value

        if not self.target_member:
            await interaction.followup.send("Membro alvo não encontrado para silenciamento.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.followup.send("Não tenho permissão para silenciar membros (moderate_members).", ephemeral=True)
            return
        if interaction.user.top_role <= self.target_member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Você não pode silenciar um membro com cargo igual ou superior ao seu.", ephemeral=True)
            return
        if self.target_member.id == interaction.user.id:
            await interaction.followup.send("Você não pode silenciar a si mesmo.", ephemeral=True)
            return
        if self.target_member.id == interaction.guild.owner_id:
            await interaction.followup.send("Você não pode silenciar o proprietário do servidor.", ephemeral=True)
            return
        if self.target_member.bot and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send("Você não pode silenciar um bot a menos que seja um administrador.", ephemeral=True)
            return

        try:
            duration = parse_duration(duration_str)
            timeout_until = datetime.datetime.now(datetime.timezone.utc) + duration

            try:
                dm_embed = discord.Embed(
                    title="Você foi Silenciado(a)!",
                    description=f"Você foi silenciado(a) no servidor **{interaction.guild.name}** por {duration_str}.",
                    color=discord.Color.yellow()
                )
                dm_embed.add_field(name="Razão", value=reason_text, inline=False)
                dm_embed.set_footer(text="Você poderá falar novamente após o término do silenciamento.")
                await self.target_member.send(embed=dm_embed)
                logging.info(f"DM de silenciamento enviada para {self.target_member.id}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar DM de silenciamento para {self.target_member.id}.")
            except Exception as e:
                logging.error(f"Erro ao enviar DM de silenciamento para {self.target_member.id}: {e}")

            await self.target_member.timeout(timeout_until, reason=reason_text)
            
            execute_query(
                "INSERT INTO moderation_logs (guild_id, action, target_id, moderator_id, reason, duration) VALUES (?, ?, ?, ?, ?, ?)",
                (interaction.guild.id, "mute", self.target_member.id, interaction.user.id, reason_text, duration_str)
            )

            embed = discord.Embed(
                title="Usuário Silenciado",
                description=f"O usuário {self.target_member.mention} foi silenciado por {duration_str}.",
                color=discord.Color.yellow()
            )
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Razão", value=reason_text, inline=False)
            embed.add_field(name="Canal do Silenciamento", value=self.target_channel.mention, inline=True)
            embed.set_footer(text=f"ID do Usuário: {self.target_member.id}")

            try:
                await self.target_channel.send(embed=embed)
                await interaction.followup.send(f"Silenciamento enviado para {self.target_channel.mention}!", ephemeral=True)
                logging.info(f"Silenciamento registrado para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id} e enviada para {self.target_channel.name}. Razão: {reason_text}. Duração: {duration_str}.")
            except discord.Forbidden:
                await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {self.target_channel.mention}.", ephemeral=True)
                logging.error(f"Permissão negada ao enviar silenciamento para {self.target_channel.name} na guild {interaction.guild.id}.")
            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro ao enviar o silenciamento: {e}", ephemeral=True)
                logging.error(f"Erro ao enviar silenciamento para {self.target_channel.name}: {e}")

        except ValueError as ve:
            await interaction.followup.send(f"Erro na duração: {ve}", ephemeral=True)
            logging.error(f"Erro de valor na duração do silenciamento para {self.target_member.id}: {ve}")
        except discord.Forbidden:
            await interaction.followup.send("Não tenho permiss��o para silenciar este membro.", ephemeral=True)
            logging.error(f"Permissão negada ao silenciar {self.target_member.id} na guild {interaction.guild.id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao silenciar o membro: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao silenciar {self.target_member.id}: {e}")


class UnmuteModal(ui.Modal, title="Remover Silenciamento"):
    def __init__(self, target_member: discord.Member, target_channel: discord.TextChannel):
        super().__init__()
        self.target_member = target_member
        self.target_channel = target_channel
        self.reason = ui.TextInput(
            label="Razão para Remover Silenciamento",
            placeholder="Descreva o motivo da remoção...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        reason_text = self.reason.value

        if not self.target_member:
            await interaction.followup.send("Membro alvo não encontrado para remover silenciamento.", ephemeral=True)
            return

        if not interaction.guild.me.guild_permissions.moderate_members:
            await interaction.followup.send("Não tenho permissão para remover silenciamento de membros (moderate_members).", ephemeral=True)
            return
        if interaction.user.top_role <= self.target_member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Você não pode remover silenciamento de um membro com cargo igual ou superior ao seu.", ephemeral=True)
            return
        if self.target_member.id == interaction.user.id:
            await interaction.followup.send("Você não pode remover silenciamento de si mesmo.", ephemeral=True)
            return
        if self.target_member.id == interaction.guild.owner_id:
            await interaction.followup.send("Você não pode remover silenciamento do proprietário do servidor.", ephemeral=True)
            return
        if self.target_member.bot and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send("Você não pode remover silenciamento de um bot a menos que seja um administrador.", ephemeral=True)
            return

        if not self.target_member.is_timed_out():
            await interaction.followup.send(f"{self.target_member.mention} não está silenciado(a).", ephemeral=True)
            return

        try:
            try:
                dm_embed = discord.Embed(
                    title="Silenciamento Removido!",
                    description=f"Seu silenciamento no servidor **{interaction.guild.name}** foi removido.",
                    color=discord.Color.green()
                )
                dm_embed.add_field(name="Razão", value=reason_text, inline=False)
                await self.target_member.send(embed=dm_embed)
                logging.info(f"DM de remoção de silenciamento enviada para {self.target_member.id}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar DM de remoção de silenciamento para {self.target_member.id}.")
            except Exception as e:
                logging.error(f"Erro ao enviar DM de remoção de silenciamento para {self.target_member.id}: {e}")

            await self.target_member.timeout(None, reason=reason_text) # Remove o timeout
            
            execute_query(
                "INSERT INTO moderation_logs (guild_id, action, target_id, moderator_id, reason) VALUES (?, ?, ?, ?, ?)",
                (interaction.guild.id, "unmute", self.target_member.id, interaction.user.id, reason_text)
            )

            embed = discord.Embed(
                title="Silenciamento Removido",
                description=f"O silenciamento de {self.target_member.mention} foi removido.",
                color=discord.Color.green()
            )
            embed.add_field(name="Moderador", value=interaction.user.mention, inline=True)
            embed.add_field(name="Razão", value=reason_text, inline=False)
            embed.add_field(name="Canal da Remoção", value=self.target_channel.mention, inline=True)
            embed.set_footer(text=f"ID do Usuário: {self.target_member.id}")

            try:
                await self.target_channel.send(embed=embed)
                await interaction.followup.send(f"Remoção de silenciamento enviada para {self.target_channel.mention}!", ephemeral=True)
                logging.info(f"Remoção de silenciamento registrada para {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id} e enviada para {self.target_channel.name}. Razão: {reason_text}.")
            except discord.Forbidden:
                await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {self.target_channel.mention}.", ephemeral=True)
                logging.error(f"Permissão negada ao enviar remoção de silenciamento para {self.target_channel.name} na guild {interaction.guild.id}.")
            except Exception as e:
                await interaction.followup.send(f"Ocorreu um erro ao enviar a remoção de silenciamento: {e}", ephemeral=True)
                logging.error(f"Erro ao enviar remoção de silenciamento para {self.target_channel.name}: {e}")

        except discord.Forbidden:
            await interaction.followup.send("Não tenho permissão para remover silenciamento deste membro.", ephemeral=True)
            logging.error(f"Permissão negada ao remover silenciamento de {self.target_member.id} na guild {interaction.guild.id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao remover o silenciamento do membro: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao remover silenciamento de {self.target_member.id}: {e}")


# --- View para Seleção de Canal ---
class BaseChannelSelectView(ui.View):
    def __init__(self, target_member: discord.Member, modal_class: type[ui.Modal]):
        super().__init__(timeout=60)
        self.target_member = target_member
        self.modal_class = modal_class
        self.message = None

        self.add_item(self.ChannelSelect(target_member.guild.text_channels, self.modal_class))

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Tempo esgotado para seleção de canal.", view=self)

    class ChannelSelect(ui.Select):
        def __init__(self, text_channels: list[discord.TextChannel], modal_class: type[ui.Modal]):
            options = [
                discord.SelectOption(label=channel.name, value=str(channel.id))
                for channel in text_channels if channel.permissions_for(channel.guild.me).send_messages
            ]
            if not options:
                options.append(discord.SelectOption(label="Nenhum canal de texto disponível", value="none", default=True))

            super().__init__(
                placeholder="Selecione o canal...",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="channel_select"
            )
            self.modal_class = modal_class

        async def callback(self, interaction: discord.Interaction):
            if self.values[0] == "none":
                await interaction.response.send_message("Não há canais válidos para enviar a mensagem.", ephemeral=True)
                return

            selected_channel_id = int(self.values[0])
            selected_channel = interaction.guild.get_channel(selected_channel_id)

            if not selected_channel or not isinstance(selected_channel, discord.TextChannel):
                await interaction.response.send_message("Canal inválido ou não é um canal de texto.", ephemeral=True)
                return
            
            await interaction.response.send_modal(self.modal_class(target_member=self.view.target_member, target_channel=selected_channel))
            self.view.stop()


class WarnChannelSelectView(BaseChannelSelectView):
    def __init__(self, target_member: discord.Member):
        super().__init__(target_member, WarnModal)

class KickChannelSelectView(BaseChannelSelectView):
    def __init__(self, target_member: discord.Member):
        super().__init__(target_member, KickModal)

class BanChannelSelectView(BaseChannelSelectView):
    def __init__(self, target_member: discord.Member):
        super().__init__(target_member, BanModal)

class MuteChannelSelectView(BaseChannelSelectView):
    def __init__(self, target_member: discord.Member):
        super().__init__(target_member, MuteModal)

class UnmuteChannelSelectView(BaseChannelSelectView):
    def __init__(self, target_member: discord.Member):
        super().__init__(target_member, UnmuteModal)


# --- View de Confirmação para Deletar Advertência ---
class DeleteWarnConfirmView(ui.View):
    def __init__(self, log_id: int, target_member: discord.Member, interaction_user_id: int):
        super().__init__(timeout=60) # 60 segundos para confirmar
        self.log_id = log_id
        self.target_member = target_member
        self.interaction_user_id = interaction_user_id # ID do usuário que iniciou a interação
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Apenas o usuário que iniciou a interação pode confirmar/cancelar
        if interaction.user.id != self.interaction_user_id:
            await interaction.response.send_message("Você não tem permissão para interagir com esta confirmação.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if not self.confirmed:
            for item in self.children:
                item.disabled = True
            if self.message:
                await self.message.edit(content="Tempo esgotado para confirmar a remoção da advertência.", view=self)

    @ui.button(label="Confirmar Exclusão", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_delete(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Processando exclusão...", view=self)

        success = execute_query(
            "DELETE FROM moderation_logs WHERE log_id = ? AND guild_id = ? AND action = 'warn'",
            (self.log_id, interaction.guild_id)
        )

        if success:
            await interaction.followup.send(f"Advertência (ID: `{self.log_id}`) de {self.target_member.mention} removida com sucesso.", ephemeral=False)
            logging.info(f"Advertência (ID: {self.log_id}) de {self.target_member.id} removida por {interaction.user.id} na guild {interaction.guild.id}.")
        else:
            await interaction.followup.send(f"Não foi possível remover a advertência (ID: `{self.log_id}`). Pode já ter sido removida ou o ID está incorreto.", ephemeral=True)
            logging.error(f"Erro ao remover advertência (ID: {self.log_id}) de {self.target_member.id} por {interaction.user.id} na guild {interaction.guild.id}.")
        self.stop() # Para a view

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_delete(self, interaction: discord.Interaction, button: ui.Button):
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Remoção de advertência cancelada.", view=self)
        self.stop() # Para a view


# --- View para Ações de Moderação (Botões) ---
class ModActionsView(ui.View):
    def __init__(self, target_member: discord.Member):
        super().__init__(timeout=180) # Timeout de 3 minutos para a view
        self.target_member = target_member # Armazena o membro alvo
        self.message = None # Para armazenar a mensagem do painel

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message: # Se a mensagem foi armazenada
            await self.message.edit(content="Sessão de moderação expirada.", view=self)

    @ui.button(label="Advertir", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def warn_button(self, interaction: discord.Interaction, button: ui.Button):
        select_view = WarnChannelSelectView(target_member=self.target_member)
        await interaction.response.send_message("Por favor, selecione o canal onde a advertência será enviada:", view=select_view, ephemeral=True)
        select_view.message = await interaction.original_response()

    @ui.button(label="Silenciar", style=discord.ButtonStyle.secondary, emoji=None) # Removido emoji, usando None
    async def mute_button(self, interaction: discord.Interaction, button: ui.Button):
        select_view = MuteChannelSelectView(target_member=self.target_member)
        await interaction.response.send_message("Por favor, selecione o canal onde o silenciamento será enviado:", view=select_view, ephemeral=True)
        select_view.message = await interaction.original_response()

    @ui.button(label="Remover Silenciamento", style=discord.ButtonStyle.secondary, emoji=None) # Removido emoji, usando None
    async def unmute_button(self, interaction: discord.Interaction, button: ui.Button):
        select_view = UnmuteChannelSelectView(target_member=self.target_member)
        await interaction.response.send_message("Por favor, selecione o canal onde a remoção do silenciamento será enviada:", view=select_view, ephemeral=True)
        select_view.message = await interaction.original_response()

    @ui.button(label="Expulsar", style=discord.ButtonStyle.secondary, emoji="❌") # Alterado para '❌'
    async def kick_button(self, interaction: discord.Interaction, button: ui.Button):
        select_view = KickChannelSelectView(target_member=self.target_member)
        await interaction.response.send_message("Por favor, selecione o canal onde a expulsão será enviada:", view=select_view, ephemeral=True)
        select_view.message = await interaction.original_response()

    @ui.button(label="Banir", style=discord.ButtonStyle.danger, emoji="⛔") # Alterado para '⛔'
    async def ban_button(self, interaction: discord.Interaction, button: ui.Button):
        select_view = BanChannelSelectView(target_member=self.target_member)
        await interaction.response.send_message("Por favor, selecione o canal onde o banimento será enviado:", view=select_view, ephemeral=True)
        select_view.message = await interaction.original_response()


class ModerationCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="mod_actions", description="Abre um painel de ações de moderação para um usuário.")
    @app_commands.checks.has_permissions(kick_members=True) # Requer permissão para usar o comando
    @app_commands.describe(member="O membro para o qual você deseja realizar ações de moderação.")
    async def mod_actions(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        if member.id == interaction.user.id:
            await interaction.followup.send("Você não pode realizar ações de moderação em si mesmo.", ephemeral=True)
            return
        if member.bot:
            await interaction.followup.send("Você não pode realizar ações de moderação em bots (use o comando de ban/kick direto se necessário).", ephemeral=True)
            return
        if member.id == interaction.guild.owner_id:
            await interaction.followup.send("Você não pode realizar ações de moderação no proprietário do servidor.", ephemeral=True)
            return
        # A permissão `moderate_members` é necessária para silenciar/desmutar
        # e é um bom check geral para mod_actions
        if not interaction.user.guild_permissions.moderate_members and \
           interaction.user.top_role <= member.top_role and \
           interaction.user.id != interaction.guild.owner_id:
            await interaction.followup.send("Você não pode realizar ações de moderação em um membro com cargo igual ou superior ao seu, ou você não tem a permissão necessária (`Moderar Membros`).", ephemeral=True)
            return
        
        # Criar um embed para o painel de moderação
        embed = discord.Embed(
            title=f"Ações de Moderação para {member.display_name}",
            description=f"Selecione uma ação para {member.mention}.",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID do Usuário: {member.id}")

        view = ModActionsView(target_member=member)
        view.message = await interaction.followup.send(
            embed=embed,
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="warns", description="Exibe as advertências de um usuário.")
    @app_commands.checks.has_permissions(kick_members=True) # Permissão para ver logs de moderação
    @app_commands.describe(member="O membro cujo histórico de advertências você deseja ver.")
    async def warns(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        target_id = member.id

        # Busca todas as advertências para o usuário no servidor
        warn_logs = execute_query(
            "SELECT log_id, moderator_id, reason, timestamp FROM moderation_logs WHERE guild_id = ? AND action = 'warn' AND target_id = ? ORDER BY timestamp DESC",
            (guild_id, target_id),
            fetchall=True
        )

        if not warn_logs:
            await interaction.followup.send(f"Nenhuma advertência encontrada para {member.mention}.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Advertências de {member.display_name}",
            description=f"Aqui estão as advertências registradas para {member.mention}:",
            color=discord.Color.orange()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"ID do Usuário: {member.id}")

        for log in warn_logs:
            log_id, moderator_id, reason, timestamp_str = log
            
            moderator_user = self.bot.get_user(moderator_id)
            moderator_name = moderator_user.mention if moderator_user else f"ID: {moderator_id}"

            timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            timestamp_unix = int(timestamp.timestamp())

            embed.add_field(
                name=f"Advertência ID: `{log_id}`",
                value=(
                    f"**Moderador:** {moderator_name}\n"
                    f"**Razão:** {reason if reason else 'N/A'}\n"
                    f"**Quando:** <t:{timestamp_unix}:F>"
                ),
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        logging.info(f"Comando /warns usado por {interaction.user.id} para {member.id} na guild {interaction.guild.id}.")


    @app_commands.command(name="delwarn", description="Remove uma advertência específica de um usuário.")
    @app_commands.checks.has_permissions(kick_members=True) # Permissão para gerenciar advertências
    @app_commands.describe(log_id="O ID da advertência a ser removida (obtido de /warns).")
    async def delwarn(self, interaction: discord.Interaction, log_id: int):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id

        # Verifica se a advertência existe e pertence a este servidor e é uma 'warn'
        warn_info = execute_query(
            "SELECT target_id, reason FROM moderation_logs WHERE log_id = ? AND guild_id = ? AND action = 'warn'",
            (log_id, guild_id),
            fetchone=True
        )

        if not warn_info:
            await interaction.followup.send(f"Advertência com ID `{log_id}` não encontrada ou não pertence a este servidor.", ephemeral=True)
            return

        target_id, reason = warn_info
        target_member = interaction.guild.get_member(target_id)
        target_name = target_member.mention if target_member else f"Usuário Desconhecido (ID: {target_id})"

        # Envia a confirmação
        confirm_view = DeleteWarnConfirmView(log_id, target_member, interaction.user.id)
        confirm_message = await interaction.followup.send(
            f"Tem certeza que deseja remover a advertência (ID: `{log_id}`) de {target_name}?\n"
            f"Razão original: `{reason}`",
            view=confirm_view,
            ephemeral=True
        )
        confirm_view.message = confirm_message # Armazena a mensagem para timeout

        logging.info(f"Comando /delwarn iniciado por {interaction.user.id} para advertência ID: {log_id} na guild {interaction.guild.id}.")


    @app_commands.command(name="view_mod_logs", description="Visualiza os últimos logs de moderação do servidor.")
    @app_commands.checks.has_permissions(view_audit_log=True)
    async def view_mod_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        logs = execute_query(
            "SELECT action, target_id, moderator_id, reason, timestamp, duration FROM moderation_logs WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 10",
            (guild_id,),
            fetchall=True
        )

        if not logs:
            await interaction.followup.send("Nenhum log de moderação encontrado para este servidor.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Logs de Moderação em {interaction.guild.name}",
            description="Aqui estão os últimos 10 registros de moderação:",
            color=discord.Color.blue()
        )

        for log in logs:
            action, target_id, moderator_id, reason, timestamp_str, duration = log
            
            target_user = self.bot.get_user(target_id)
            moderator_user = self.bot.get_user(moderator_id)

            target_name = target_user.mention if target_user else f"ID: {target_id}"
            moderator_name = moderator_user.mention if moderator_user else f"ID: {moderator_id}"

            timestamp = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            timestamp_unix = int(timestamp.timestamp())

            log_value = (
                f"**Alvo:** {target_name}\n"
                f"**Moderador:** {moderator_name}\n"
                f"**Razão:** {reason if reason else 'N/A'}\n"
            )
            if action in ["mute"] and duration: # Apenas para mute, mostrar duração
                log_value += f"**Duração:** {duration}\n"
            log_value += f"**Quando:** <t:{timestamp_unix}:F>"

            embed.add_field(
                name=f"Ação: {action.upper()}",
                value=log_value,
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCommands(bot))