# cogs/events/raid_protection.py

import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import logging
import time
import re

# Importa a função execute_query do seu módulo database
from database import execute_query

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

join_burst_cache = {}

def parse_duration(duration_str: str) -> datetime.timedelta:
    """Converte uma string de duração (ex: '30m', '1h') em um timedelta."""
    seconds = 0
    if not duration_str:
        raise ValueError("Duração não pode ser vazia.")
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
    if seconds > 2419200: # 28 dias em segundos
        raise ValueError("A duração máxima para silenciamento é de 28 dias.")
    return datetime.timedelta(seconds=seconds)

class RaidProtectionSettingsModal(ui.Modal, title="Configurações Proteção Anti-Raid"):
    """Modal para configurar as definições da proteção anti-raid."""
    def __init__(self, current_settings: dict):
        super().__init__()
        self.current_settings = current_settings

        default_min_age_hours = current_settings.get('min_account_age_hours', 24)
        default_min_age_days = max(1, default_min_age_hours // 24) 

        self.min_account_age = ui.TextInput(
            label="Idade Mínima da Conta (dias)",
            placeholder="Ex: 1 (para contas criadas há menos de 1 dia)",
            default=str(default_min_age_days),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.min_account_age)

        self.join_burst_threshold = ui.TextInput(
            label="Limite de Entradas por Burst",
            placeholder="Ex: 10 (se 10 membros entrarem em X segundos)",
            default=str(current_settings.get('join_burst_threshold', 10)),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.join_burst_threshold)

        self.join_burst_time = ui.TextInput(
            label="Tempo do Burst (segundos)",
            placeholder="Ex: 60 (para 10 membros em 60 segundos)",
            default=str(current_settings.get('join_burst_time_seconds', 60)),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.join_burst_time)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            min_age_days_input = int(self.min_account_age.value)
            burst_threshold = int(self.join_burst_threshold.value)
            burst_time = int(self.join_burst_time.value)

            if min_age_days_input < 0 or burst_threshold < 1 or burst_time < 1:
                await interaction.followup.send("Por favor, insira valores positivos para todas as configurações. O limite de burst deve ser no mínimo 1.", ephemeral=True)
                return
            
            min_age_hours_to_save = min_age_days_input * 24

            current_settings_from_db = execute_query(
                "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
                (interaction.guild.id,),
                fetchone=True
            )

            enabled = current_settings_from_db[0] if current_settings_from_db else False
            channel_id_to_save = current_settings_from_db[4] if current_settings_from_db and current_settings_from_db[4] else None
            message_id_to_save = current_settings_from_db[5] if current_settings_from_db and current_settings_from_db[5] else None


            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (interaction.guild.id, enabled, min_age_hours_to_save, burst_threshold, burst_time, channel_id_to_save, message_id_to_save)
            )

            if success:
                await interaction.followup.send("Configurações Anti-Raid atualizadas com sucesso!", ephemeral=True)
                logging.info(f"Configurações Proteção Anti-Raid atualizadas por {interaction.user.id} na guild {interaction.guild.id}. Novos valores: Idade Minima (horas): {min_age_hours_to_save}, Threshold: {burst_threshold}, Time: {burst_time}. Channel/Message ID (mantidos): {channel_id_to_save}/{message_id_to_save}")
                # Modificação aqui: chamar uma função na View para recriar e atualizar
                if hasattr(self, 'view') and isinstance(self.view, RaidProtectionPanelView):
                    await self.view.refresh_panel(interaction.guild.id, interaction.client) # Passa o client (bot)
            else:
                await interaction.followup.send("Ocorreu um erro ao salvar as configurações Anti-Raid no banco de dados.", ephemeral=True)
                logging.error(f"Erro ao salvar configurações Proteção Anti-Raid para guild {interaction.guild.id}.")

        except ValueError:
            await interaction.followup.send("Por favor, insira apenas números inteiros válidos para as configurações.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro inesperado: {e}", ephemeral=True)
            logging.error(f"Erro inesperado no RaidProtectionSettingsModal: {e}")

class RaidProtectionPanelView(ui.View):
    """View persistente para o painel de control da proteção anti-raid."""
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.message = None 
        # Não é necessário atribuir callbacks aqui, o decorador @ui.button já faz isso.

    # NOVO MÉTODO PARA REFRESH
    async def refresh_panel(self, guild_id: int, bot_client: commands.Bot):
        """Recria e atualiza o painel para garantir que os botões funcionem corretamente."""
        logging.info(f"[refresh_panel] Iniciando refresh do painel para guild_id: {guild_id}")
        
        panel_data = execute_query(
            "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )

        if not panel_data or panel_data[0] is None or panel_data[1] is None:
            logging.warning(f"[refresh_panel] Nenhum dado de canal/mensagem válido encontrado no DB para guild {guild_id}. Não foi possível atualizar o painel.")
            # Se os IDs estão faltando, remove a entrada para forçar reconfiguração
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            return

        channel_id, message_id = panel_data
        
        guild = bot_client.get_guild(guild_id)
        if not guild:
            logging.warning(f"[refresh_panel] Guild {guild_id} não encontrada durante refresh. Removendo painel do DB.")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            return

        channel = None
        try:
            channel = await guild.fetch_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                logging.warning(f"[refresh_panel] Canal {channel_id} (fetched) não é um canal de texto durante refresh. Removendo do DB.")
                execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                return
        except discord.NotFound:
            logging.error(f"[refresh_panel] Canal {channel_id} NÃO ENCONTRADO durante refresh. Removendo do DB.")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            return
        except discord.Forbidden:
            logging.error(f"[refresh_panel] Bot sem permissão para buscar canal {channel_id} durante refresh. Verifique as permissões 'Ver Canais'.")
            return
        except Exception as e:
            logging.error(f"[refresh_panel] Erro inesperado ao buscar canal {channel_id} durante refresh: {e}")
            return

        message = None
        try:
            message = await channel.fetch_message(message_id)
            logging.info(f"[refresh_panel] Mensagem {message_id} encontrada durante refresh.")
        except discord.NotFound:
            logging.error(f"[refresh_panel] Mensagem do painel {message_id} NÃO ENCONTRADA durante refresh. Removendo do DB.")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            return
        except discord.Forbidden:
            logging.error(f"[refresh_panel] Bot sem permissão para ler histórico no canal {channel_id} durante refresh. Não é possível atualizar o painel.")
            return
        except Exception as e:
            logging.error(f"[refresh_panel] Erro inesperado ao buscar mensagem {message_id} durante refresh: {e}")
            return

        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )

        if not settings:
            enabled, min_age_hours, burst_threshold, burst_time = False, 24, 10, 60
            logging.warning(f"[refresh_panel] Configurações não encontradas no DB para guild {guild_id} durante refresh. Usando padrões.")
        else:
            enabled, min_age_hours, burst_threshold, burst_time = settings

        status = "Ativado" if enabled else "Desativado"
        color = discord.Color.green() if enabled else discord.Color.red()

        min_age_days_display = max(1, min_age_hours // 24)
        age_unit = "dias" if min_age_days_display != 1 else "dia"

        embed = discord.Embed(
            title="Painel Proteção Anti-Raid",
            description=f"Status: **{status}**\n\nGerencie as configurações do sistema Anti-Raid.",
            color=color
        )
        embed.add_field(name="Idade Mínima da Conta", value=f"{min_age_days_display} {age_unit}", inline=False)
        embed.add_field(name="Limite de Entradas por Burst", value=f"{burst_threshold} membros em {burst_time} segundos", inline=False)
        embed.set_footer(text="Use os botões abaixo para gerenciar.")

        # AQUI ESTÁ A MUDANÇA CRÍTICA: Recriar a View
        new_view_instance = RaidProtectionPanelView(bot_client, guild_id)
        new_view_instance.message = message # Garante que a nova view tenha referência à mensagem
        
        try:
            logging.info(f"[refresh_panel] Tentando editar mensagem {message.id} com NOVO embed e NOVA view...")
            await message.edit(embed=embed, view=new_view_instance)
            # É importante remover a view antiga e adicionar a nova se ela já foi adicionada globalmente
            # No entanto, discord.py lida com isso se você simplesmente add_view com o mesmo message_id
            # O add_view abaixo não é estritamente necessário aqui se a view já foi adicionada no init do cog
            # mas garante que o bot está ciente da nova instância para persistência
            bot_client.add_view(new_view_instance, message_id=message.id)
            logging.info(f"[refresh_panel] Painel Proteção Anti-Raid atualizado com sucesso com NOVA VIEW para guild {guild_id}.")
        except discord.Forbidden:
            logging.error(f"[refresh_panel] Bot sem permissão para editar a mensagem do painel {message.id} no canal {channel_id} na guild {guild_id}. Verifique as permissões 'Gerenciar Mensagens'.")
        except Exception as e:
            logging.error(f"[refresh_panel] Erro inesperado ao editar a mensagem do painel {message.id} na guild {guild_id} durante refresh: {e}")

    # O método _update_panel_message anterior agora apenas chama refresh_panel
    # E é renomeado para ser mais claro
    async def _internal_update_and_recreate_panel(self, guild_id: int):
        await self.refresh_panel(guild_id, self.bot) # Passa self.bot como bot_client


    @ui.button(label="Ativar Proteção", style=discord.ButtonStyle.success, custom_id="anti_raid_enable")
    async def enable_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        logging.info(f"[enable_button_callback] Iniciando para guild {self.guild_id} por {interaction.user.id}")
        await interaction.response.defer(ephemeral=True) 
        
        try:
            logging.info(f"[enable_button_callback] Buscando dados existentes do painel no DB para guild {self.guild_id}...")
            existing_panel_data = execute_query(
                "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
                (self.guild_id,),
                fetchone=True
            )
            channel_id = existing_panel_data[0] if existing_panel_data else None
            message_id = existing_panel_data[1] if existing_panel_data else None
            logging.info(f"[enable_button_callback] Dados existentes: channel_id={channel_id}, message_id={message_id}")

            logging.info(f"[enable_button_callback] Atualizando status de 'enabled' no DB para True para guild {self.guild_id}...")
            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, COALESCE((SELECT min_account_age_hours FROM anti_raid_settings WHERE guild_id = ?), 24), COALESCE((SELECT join_burst_threshold FROM anti_raid_settings WHERE guild_id = ?), 10), COALESCE((SELECT join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?), 60), ?, ?)",
                (self.guild_id, True, self.guild_id, self.guild_id, self.guild_id, channel_id, message_id)
            )

            if success:
                logging.info(f"[enable_button_callback] Status de 'enabled' atualizado com sucesso no DB para guild {self.guild_id}.")
                await interaction.followup.send("Proteção Anti-Raid foi **ativada**.", ephemeral=True)
                logging.info(f"Proteção Anti-Raid ativado por {interaction.user.id} na guild {self.guild_id}. Channel/Message ID (preservados): {channel_id}/{message_id}")
                
                logging.info(f"[enable_button_callback] Chamando refresh_panel para guild {self.guild_id}...")
                await self.refresh_panel(self.guild_id, interaction.client) # Chamada para o NOVO método
                logging.info(f"[enable_button_callback] refresh_panel concluído para guild {self.guild_id}.")
            else:
                logging.error(f"[enable_button_callback] Falha ao atualizar status de 'enabled' no DB para guild {self.guild_id}.")
                await interaction.followup.send("Ocorreu um erro ao ativar a proteção Anti-Raid no banco de dados.", ephemeral=True)
                
        except discord.Forbidden as e:
            logging.error(f"[enable_button_callback] Erro de permissão ao ativar proteção anti-raid na guild {self.guild_id}: {e}")
            await interaction.followup.send(f"Erro de permissão: {e}. Verifique se o bot tem as permissões necessárias (ex: 'Gerenciar Mensagens', 'Ver Canais').", ephemeral=True)
        except Exception as e:
            logging.error(f"[enable_button_callback] Erro inesperado ao ativar proteção anti-raid na guild {self.guild_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Ocorreu um erro inesperado ao ativar a proteção Anti-Raid: {e}", ephemeral=True)
        logging.info(f"[enable_button_callback] Concluído para guild {self.guild_id}.")


    @ui.button(label="Desativar Proteção", style=discord.ButtonStyle.danger, custom_id="anti_raid_disable")
    async def disable_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        logging.info(f"[disable_button_callback] Iniciando para guild {self.guild_id} por {interaction.user.id}")
        await interaction.response.defer(ephemeral=True)
        
        try:
            logging.info(f"[disable_button_callback] Buscando dados existentes do painel no DB para guild {self.guild_id}...")
            existing_panel_data = execute_query(
                "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
                (self.guild_id,),
                fetchone=True
            )
            channel_id = existing_panel_data[0] if existing_panel_data else None
            message_id = existing_panel_data[1] if existing_panel_data else None
            logging.info(f"[disable_button_callback] Dados existentes: channel_id={channel_id}, message_id={message_id}")

            logging.info(f"[disable_button_callback] Atualizando status de 'enabled' no DB para False para guild {self.guild_id}...")
            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, COALESCE((SELECT min_account_age_hours FROM anti_raid_settings WHERE guild_id = ?), 24), COALESCE((SELECT join_burst_threshold FROM anti_raid_settings WHERE guild_id = ?), 10), COALESCE((SELECT join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?), 60), ?, ?)",
                (self.guild_id, False, self.guild_id, self.guild_id, self.guild_id, channel_id, message_id)
            )

            if success:
                logging.info(f"[disable_button_callback] Status de 'enabled' atualizado com sucesso no DB para guild {self.guild_id}.")
                await interaction.followup.send("Proteção Anti-Raid foi **desativada**.", ephemeral=True)
                logging.info(f"Proteção Anti-Raid desativado por {interaction.user.id} na guild {self.guild_id}. Channel/Message ID (preservados): {channel_id}/{message_id}")
                
                logging.info(f"[disable_button_callback] Chamando refresh_panel para guild {self.guild_id}...")
                await self.refresh_panel(self.guild_id, interaction.client) # Chamada para o NOVO método
                logging.info(f"[disable_button_callback] refresh_panel concluído para guild {self.guild_id}.")
            else:
                logging.error(f"[disable_button_callback] Falha ao atualizar status de 'enabled' no DB para guild {self.guild_id}.")
                await interaction.followup.send("Ocorreu um erro ao desativar a proteção Anti-Raid no banco de dados.", ephemeral=True)

        except discord.Forbidden as e:
            logging.error(f"[disable_button_callback] Erro de permissão ao desativar proteção anti-raid na guild {self.guild_id}: {e}")
            await interaction.followup.send(f"Erro de permissão: {e}. Verifique se o bot tem as permissões necessárias (ex: 'Gerenciar Mensagens', 'Ver Canais').", ephemeral=True)
        except Exception as e:
            logging.error(f"[disable_button_callback] Erro inesperado ao desativar proteção anti-raid na guild {self.guild_id}: {e}", exc_info=True)
            await interaction.followup.send(f"Ocorreu um erro inesperado ao desativar a proteção Anti-Raid: {e}", ephemeral=True)
        logging.info(f"[disable_button_callback] Concluído para guild {self.guild_id}.")


    @ui.button(label="Configurar Valores", style=discord.ButtonStyle.secondary, custom_id="anti_raid_configure")
    async def configure_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (self.guild_id,),
            fetchone=True
        )
        current_settings = {
            'enabled': settings[0] if settings else False,
            'min_account_age_hours': settings[1] if settings else 24,
            'join_burst_threshold': settings[2] if settings else 10,
            'join_burst_time_seconds': settings[3] if settings else 60,
            'channel_id': settings[4] if settings else None,
            'message_id': settings[5] if settings else None
        }
        modal = RaidProtectionSettingsModal(current_settings)
        modal.view = self 
        await interaction.response.send_modal(modal)

class RaidProtectionSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.ensure_persistent_views())

    async def ensure_persistent_views(self):
        await self.bot.wait_until_ready()
        logging.info("Tentando carregar painéis Proteção Anti-Raid persistentes...")
        panel_datas = execute_query("SELECT guild_id, channel_id, message_id FROM anti_raid_settings", fetchall=True)
        logging.info(f"[ensure_persistent_views] Dados lidos do DB: {panel_datas}") 
        
        if panel_datas:
            for guild_id, channel_id, message_id in panel_datas:
                if channel_id is None or message_id is None:
                    logging.warning(f"[ensure_persistent_views] Pulando entrada inválida no DB para guild {guild_id} (channel_id ou message_id é None). Removendo do DB.")
                    execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                    continue 
                
                try:
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        logging.warning(f"Guild {guild_id} não encontrada para painel persistente. Removendo do DB.")
                        execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                        continue
                    
                    channel = await guild.fetch_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        logging.warning(f"Canal {channel_id} não é de texto para painel persistente na guild {guild_id}. Removendo do DB.")
                        execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                        continue

                    message = await channel.fetch_message(message_id)
                    view = RaidProtectionPanelView(self.bot, guild_id)
                    view.message = message 
                    self.bot.add_view(view, message_id=message.id)
                    logging.info(f"Painel Proteção Anti-Raid persistente carregado para guild {guild_id} no canal {channel_id}, mensagem {message_id}.")
                except discord.NotFound:
                    logging.warning(f"Mensagem do painel Proteção Anti-Raid ({message_id}) ou canal ({channel_id}) não encontrada. Removendo do DB para evitar carregamentos futuros.")
                    execute_query("DELETE FROM anti_raid_settings WHERE message_id = ?", (message_id,))
                except discord.Forbidden:
                    logging.error(f"Bot sem permissão para acessar o canal {channel_id} ou mensagem {message_id} na guild {guild_id}. Não foi possível carregar o painel persistente.")
                except Exception as e:
                    logging.error(f"Erro inesperado ao carregar painel persistente para guild {guild_id}, mensagem {message_id}: {e}")
        else:
            logging.info("Nenhum painel Proteção Anti-Raid persistente para carregar.")


    # Evento de entrada de membro
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return 

        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (member.guild.id,),
            fetchone=True
        )

        if not settings or not settings[0]:
            return

        enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds = settings

        account_age_timedelta = datetime.datetime.now(datetime.timezone.utc) - member.created_at
        min_account_age_timedelta = datetime.timedelta(hours=min_account_age_hours)

        if account_age_timedelta < min_account_age_timedelta:
            try:
                await member.kick(reason=f"Proteção Anti-Raid: Conta muito nova ({account_age_timedelta.total_seconds() / 3600:.2f} horas). Idade mínima configurada: {min_account_age_hours} horas.")
                logging.info(f"Membro {member.id} ({member.name}) chutado na guild {member.guild.id} por ter conta muito nova.")
                return 
            except discord.Forbidden:
                logging.error(f"Bot sem permissão para chutar {member.name} na guild {member.guild.id} (conta muito nova).")
            except Exception as e:
                logging.error(f"Erro ao chutar membro {member.name} na guild {member.guild.id} por conta muito nova: {e}")
            return

        guild_id = member.guild.id
        current_time = time.time()

        if guild_id not in join_burst_cache:
            join_burst_cache[guild_id] = []

        join_burst_cache[guild_id] = [
            t for t in join_burst_cache[guild_id] if current_time - t < join_burst_time_seconds
        ]
        
        join_burst_cache[guild_id].append(current_time)

        if len(join_burst_cache[guild_id]) >= join_burst_threshold:
            try:
                logging.warning(f"Possível burst de entradas detectado na guild {member.guild.id}! {len(join_burst_cache[guild_id])} membros em {join_burst_time_seconds} segundos. Disparando ações de proteção...")
                join_burst_cache[guild_id] = []
            except discord.Forbidden:
                logging.error(f"Bot sem permissão para agir no burst de entradas na guild {member.guild.id}.")
            except Exception as e:
                logging.error(f"Erro ao lidar com burst de entradas na guild {member.guild.id}: {e}")

    # Comandos de slash
    @app_commands.command(name="setup_panel", description="Configura ou move o painel de proteção anti-raid para o canal atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_raid_protection_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        old_panel_data = execute_query(
            "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )
        if old_panel_data and (old_panel_data[0] is not None and old_panel_data[1] is not None): 
            old_channel_id, old_message_id = old_panel_data
            try:
                old_channel = await interaction.guild.fetch_channel(old_channel_id)
                if isinstance(old_channel, discord.TextChannel):
                    old_message = await old_channel.fetch_message(old_message_id)
                    await old_message.delete()
                    logging.info(f"[setup_raid_protection_panel] Mensagem do painel anti-raid antigo ({old_message_id}) deletada do canal {old_channel_id}.")
            except discord.NotFound:
                logging.warning(f"[setup_raid_protection_panel] Mensagem do painel Proteção Anti-Raid ({old_message_id}) não encontrada para deletar no canal {old_channel_id}.")
            except discord.Forbidden:
                logging.error(f"[setup_raid_protection_panel] Bot sem permissão para deletar a mensagem do painel antigo ({old_message_id}) no canal {old_channel_id}. Verifique as permissões 'Gerenciar Mensagens'.")
            except Exception as e:
                logging.error(f"[setup_raid_protection_panel] Erro ao deletar painel anti-raid antigo: {e}")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,)) 
        elif old_panel_data: 
            logging.warning(f"[setup_raid_protection_panel] Entrada antiga de painel com IDs None para guild {guild_id}. Deletando do DB.")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))

        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )
        enabled = settings[0] if settings else False
        min_age_hours = settings[1] if settings else 24
        burst_threshold = settings[2] if settings else 10
        burst_time = settings[3] if settings else 60

        min_age_days_display = max(1, min_age_hours // 24)
        age_unit = "dias" if min_age_days_display != 1 else "dia"

        status = "Ativado" if enabled else "Desativado"
        color = discord.Color.green() if enabled else discord.Color.red()

        embed = discord.Embed(
            title="Painel Proteção Anti-Raid",
            description=f"Status: **{status}**\n\nGerencie as configurações do sistema Anti-Raid.",
            color=color
        )
        embed.add_field(name="Idade Mínima da Conta", value=f"{min_age_days_display} {age_unit}", inline=False)
        embed.add_field(name="Limite de Entradas por Burst", value=f"{burst_threshold} membros em {burst_time} segundos", inline=False)
        embed.set_footer(text="Use os botões abaixo para gerenciar.")

        view = RaidProtectionPanelView(self.bot, guild_id) # Cria a View inicial
        
        try:
            panel_message = await interaction.channel.send(embed=embed, view=view)
            view.message = panel_message 

            logging.info(f"[setup_raid_protection_panel] Tentando salvar no DB: guild_id={guild_id}, channel_id={interaction.channel.id}, message_id={panel_message.id}, enabled={enabled}, min_age_hours={min_age_hours}, burst_threshold={burst_threshold}, burst_time={burst_time}")

            success_db_insert = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, channel_id, message_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, interaction.channel.id, panel_message.id, enabled, min_age_hours, burst_threshold, burst_time)
            )
            if success_db_insert:
                logging.info(f"[setup_raid_protection_panel] Dados do painel salvos com sucesso no DB para guild {guild_id}.")
            else:
                logging.error(f"[setup_raid_protection_panel] Falha ao salvar dados do painel no DB para guild {guild_id}.")

            self.bot.add_view(view, message_id=panel_message.id) 
            await interaction.followup.send(f"Painel de proteção anti-raid configurado neste canal: {interaction.channel.mention}", ephemeral=True)
            logging.info(f"Painel Proteção Anti-Raid configurado/movido por {interaction.user.id} para canal {interaction.channel.id} na guild {guild_id}. Mensagem ID: {panel_message.id}.")
        except discord.Forbidden:
            await interaction.followup.send("Não tenho permissão para enviar mensagens neste canal. Por favor, verifique as minhas permissões.", ephemeral=True)
            logging.error(f"Bot sem permissão para enviar painel anti-raid no canal {interaction.channel.id} na guild {guild_id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao configurar o painel: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao configurar painel anti-raid na guild {guild_id}: {e}")

    @app_commands.command(name="delete_panel", description="Deleta o painel de proteção anti-raid existente.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def delete_raid_protection_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        panel_data = execute_query(
            "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )

        if not panel_data:
            await interaction.followup.send("Nenhum painel de proteção anti-raid encontrado para deletar.", ephemeral=True)
            logging.info(f"Tentativa de deletar painel anti-raid, mas nenhum painel encontrado para guild {guild_id}.")
            return

        channel_id, message_id = panel_data
        
        if channel_id is None or message_id is None:
            logging.warning(f"Entrada inválida no DB para guild {guild_id} (channel_id ou message_id é None). Apenas deletando do DB.")
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            await interaction.followup.send("Painel de proteção anti-raid deletado com sucesso (entrada inválida no DB).", ephemeral=True)
            return

        try:
            channel = await interaction.guild.fetch_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                message = await channel.fetch_message(message_id)
                await message.delete()
                logging.info(f"Mensagem do painel Proteção Anti-Raid ({message_id}) deletada com sucesso do canal {channel_id}.")
            else:
                logging.warning(f"Canal {channel_id} não é de texto para painel Proteção Anti-Raid. Removendo do DB sem tentar deletar mensagem.")
        except discord.NotFound:
            logging.warning(f"Mensagem do painel Proteção Anti-Raid ({message_id}) não encontrada para deletar no canal {channel_id}.")
        except discord.Forbidden:
            logging.error(f"Bot sem permissão para deletar a mensagem do painel ({message_id}) no canal {channel_id}. Verifique as permissões 'Gerenciar Mensagens'.")
            await interaction.followup.send("Não tenho permissão para deletar a mensagem do painel. Por favor, verifique as minhas permissões 'Gerenciar Mensagens'.", ephemeral=True)
            return
        except Exception as e:
            logging.error(f"Erro inesperado ao deletar a mensagem do painel anti-raid: {e}")
            await interaction.followup.send(f"Ocorreu um erro inesperado ao deletar o painel: {e}", ephemeral=True)
            return
        finally:
            execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
            await interaction.followup.send("Painel de proteção anti-raid deletado com sucesso.", ephemeral=True)
            logging.info(f"Painel Proteção Anti-Raid deletado por {interaction.user.id} na guild {guild_id}.")

    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.command(name="check_raid_settings", description="Exibe as configurações atuais da proteção anti-raid.")
    async def check_raid_settings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (interaction.guild.id,),
            fetchone=True
        )

        if not settings:
            await interaction.followup.send("As configurações de proteção anti-raid não foram definidas para este servidor. Use `/raid_protection setup_panel` para configurar.", ephemeral=True)
            return

        enabled, min_age_hours, burst_threshold, burst_time = settings
        status = "Ativado" if enabled else "Desativado"
        min_age_days_display = max(1, min_age_hours // 24)
        age_unit = "dias" if min_age_days_display != 1 else "dia"

        embed = discord.Embed(
            title="Configurações Atuais de Proteção Anti-Raid",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Idade Mínima da Conta", value=f"{min_age_days_display} {age_unit}", inline=True)
        embed.add_field(name="Limite de Entradas por Burst", value=f"{burst_threshold} membros", inline=True)
        embed.add_field(name="Tempo do Burst", value=f"{burst_time} segundos", inline=True)
        embed.set_footer(text="Use o painel ou os comandos para ajustar.")

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    """Função de setup para adicionar o cog ao bot."""
    await bot.add_cog(RaidProtectionSystem(bot))