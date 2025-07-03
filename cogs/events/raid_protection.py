import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import datetime
import logging
import time
import re

# Importa a função execute_query do seu módulo database
# Certifique-se de que 'database' está configurado corretamente e acessível.
from database import execute_query

# Configuração de logging (garante que o logging seja configurado, se não estiver globalmente)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cache para o controle de burst de entradas por guild_id
join_burst_cache = {}

# --- Funções Auxiliares (mantidas, mas podem ser movidas para um util.py se usadas em outros lugares) ---
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
    if seconds > 2419200: # 28 dias em segundos é o limite do Discord para timeout
        raise ValueError("A duração máxima para silenciamento é de 28 dias.")
    return datetime.timedelta(seconds=seconds)

# --- Modals ---
class RaidProtectionSettingsModal(ui.Modal, title="Configurações Proteção Anti-Raid"):
    """Modal para configurar as definições da proteção anti-raid."""
    def __init__(self, current_settings: dict, parent_view: 'RaidProtectionPanelView'):
        super().__init__()
        self.current_settings = current_settings
        self.parent_view = parent_view # Referência à view pai para chamar o refresh_panel

        # Calcula a idade mínima em dias para exibição no modal
        default_min_age_days = max(0, current_settings.get('min_account_age_hours', 24) // 24)

        self.min_account_age = ui.TextInput(
            label="Idade Mínima da Conta (dias)",
            placeholder="Ex: 1 (para contas criadas há menos de 1 dia). Use 0 para desativar.",
            default=str(default_min_age_days),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.min_account_age)

        self.join_burst_threshold = ui.TextInput(
            label="Limite de Entradas por Burst",
            placeholder="Ex: 10 (se 10 membros entrarem em X segundos). Use 0 para desativar.",
            default=str(current_settings.get('join_burst_threshold', 10)),
            style=discord.TextStyle.short,
            required=True
        )
        self.add_item(self.join_burst_threshold)

        self.join_burst_time = ui.TextInput(
            label="Tempo do Burst (segundos)",
            placeholder="Ex: 60 (para 10 membros em 60 segundos). Mínimo 1 segundo.",
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

            if min_age_days_input < 0:
                await interaction.followup.send("A idade mínima da conta não pode ser negativa.", ephemeral=True)
                return
            if burst_threshold < 0: # Agora permite 0 para desativar
                await interaction.followup.send("O limite de entradas por burst não pode ser negativo.", ephemeral=True)
                return
            if burst_time < 1:
                await interaction.followup.send("O tempo do burst deve ser de pelo menos 1 segundo.", ephemeral=True)
                return
            
            min_age_hours_to_save = min_age_days_input * 24

            # Buscar as configurações existentes para preservar 'enabled', 'channel_id', 'message_id'
            current_settings_from_db = execute_query(
                "SELECT enabled, channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
                (interaction.guild.id,),
                fetchone=True
            )

            enabled = current_settings_from_db[0] if current_settings_from_db else False
            channel_id_to_save = current_settings_from_db[1] if current_settings_from_db else None
            message_id_to_save = current_settings_from_db[2] if current_settings_from_db else None

            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (interaction.guild.id, enabled, min_age_hours_to_save, burst_threshold, burst_time, channel_id_to_save, message_id_to_save)
            )

            if success:
                await interaction.followup.send("Configurações Anti-Raid atualizadas com sucesso!", ephemeral=True)
                logging.info(f"Configurações Proteção Anti-Raid atualizadas por {interaction.user.id} na guild {interaction.guild.id}. Novos valores: Idade Minima (horas): {min_age_hours_to_save}, Threshold: {burst_threshold}, Time: {burst_time}. Channel/Message ID (mantidos): {channel_id_to_save}/{message_id_to_save}")
                # Chamar o refresh_panel da view pai
                await self.parent_view.refresh_panel(interaction.guild.id, interaction.client)
            else:
                await interaction.followup.send("Ocorreu um erro ao salvar as configurações Anti-Raid no banco de dados.", ephemeral=True)
                logging.error(f"Erro ao salvar configurações Proteção Anti-Raid para guild {interaction.guild.id}.")

        except ValueError:
            await interaction.followup.send("Por favor, insira apenas números inteiros válidos para as configurações.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro inesperado: {e}", ephemeral=True)
            logging.error(f"Erro inesperado no RaidProtectionSettingsModal: {e}", exc_info=True)

# --- Views ---
class RaidProtectionPanelView(ui.View):
    """View persistente para o painel de controle da proteção anti-raid."""
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None) # Timeout=None para View persistente
        self.bot = bot
        self.guild_id = guild_id
        self.message: discord.Message = None # Tipo hint para melhor clareza

    # Método para carregar as configurações do DB
    def _load_settings(self) -> dict:
        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (self.guild_id,),
            fetchone=True
        )
        if not settings:
            # Retorna configurações padrão se não houver nada no DB
            return {'enabled': False, 'min_account_age_hours': 24, 'join_burst_threshold': 10, 'join_burst_time_seconds': 60}
        
        return {
            'enabled': bool(settings[0]), # Garante que é um booleano
            'min_account_age_hours': settings[1],
            'join_burst_threshold': settings[2],
            'join_burst_time_seconds': settings[3]
        }

    async def refresh_panel(self, guild_id: int, bot_client: commands.Bot):
        """
        Recria o embed do painel com as configurações atuais e o atualiza na mensagem.
        Este método agora também lida com a re-adição da view para persistência.
        """
        logging.info(f"[refresh_panel] Iniciando refresh do painel para guild_id: {guild_id}")
        
        panel_data = execute_query(
            "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )

        if not panel_data or panel_data[0] is None or panel_data[1] is None:
            logging.warning(f"[refresh_panel] Nenhum dado de canal/mensagem válido encontrado no DB para guild {guild_id}. Não foi possível atualizar o painel. Removendo entrada inválida.")
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
            logging.error(f"[refresh_panel] Erro inesperado ao buscar canal {channel_id} durante refresh: {e}", exc_info=True)
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
            logging.error(f"[refresh_panel] Erro inesperado ao buscar mensagem {message_id} durante refresh: {e}", exc_info=True)
            return

        current_settings = self._load_settings() # Carrega as configurações mais recentes
        enabled = current_settings['enabled']
        min_age_hours = current_settings['min_account_age_hours']
        burst_threshold = current_settings['join_burst_threshold']
        burst_time = current_settings['join_burst_time_seconds']

        status = "Ativado" if enabled else "Desativado"
        color = discord.Color.green() if enabled else discord.Color.red()

        min_age_days_display = max(0, min_age_hours // 24) # Agora pode ser 0 dias para desativar
        age_unit = "dias" if min_age_days_display != 1 else "dia"

        burst_threshold_display = f"{burst_threshold} membros" if burst_threshold > 0 else "Desativado"
        burst_time_display = f"em {burst_time} segundos" if burst_threshold > 0 else ""

        embed = discord.Embed(
            title="Painel Proteção Anti-Raid",
            description=f"Status: **{status}**\n\nGerencie as configurações do sistema Anti-Raid.",
            color=color
        )
        embed.add_field(name="Idade Mínima da Conta", value=f"{min_age_days_display} {age_unit}", inline=False)
        embed.add_field(name="Limite de Entradas por Burst", value=f"{burst_threshold_display} {burst_time_display}".strip(), inline=False)
        embed.set_footer(text="Use os botões abaixo para gerenciar.")

        # Re-cria a View para garantir que ela esteja sempre atualizada e persistente
        # É crucial que a instância da View no `bot.add_view` seja a mesma que você está usando
        # ou uma nova instância com os mesmos `custom_id`s para os botões.
        new_view_instance = RaidProtectionPanelView(bot_client, guild_id)
        new_view_instance.message = message # Garante que a nova view tenha referência à mensagem
        
        try:
            logging.info(f"[refresh_panel] Tentando editar mensagem {message.id} com NOVO embed e NOVA view...")
            await message.edit(embed=embed, view=new_view_instance)
            # Adiciona a nova instância da view para persistência. Se já existe uma, será substituída.
            bot_client.add_view(new_view_instance, message_id=message.id)
            logging.info(f"[refresh_panel] Painel Proteção Anti-Raid atualizado com sucesso com NOVA VIEW para guild {guild_id}.")
        except discord.Forbidden:
            logging.error(f"[refresh_panel] Bot sem permissão para editar a mensagem do painel {message.id} no canal {channel_id} na guild {guild_id}. Verifique as permissões 'Gerenciar Mensagens'.")
        except Exception as e:
            logging.error(f"[refresh_panel] Erro inesperado ao editar a mensagem do painel {message_id} na guild {guild_id} durante refresh: {e}", exc_info=True)

    @ui.button(label="Ativar Proteção", style=discord.ButtonStyle.success, custom_id="anti_raid_enable")
    async def enable_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        logging.info(f"[enable_button_callback] Iniciando para guild {self.guild_id} por {interaction.user.id}")
        await interaction.response.defer(ephemeral=True) 
        
        try:
            # Busca as configurações atuais para preservar os outros campos
            existing_settings = self._load_settings()
            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, ?, ?, ?, COALESCE((SELECT channel_id FROM anti_raid_settings WHERE guild_id = ?), NULL), COALESCE((SELECT message_id FROM anti_raid_settings WHERE guild_id = ?), NULL))",
                (self.guild_id, True, existing_settings['min_account_age_hours'], existing_settings['join_burst_threshold'], existing_settings['join_burst_time_seconds'], self.guild_id, self.guild_id)
            )

            if success:
                logging.info(f"[enable_button_callback] Status de 'enabled' atualizado com sucesso no DB para guild {self.guild_id}.")
                await interaction.followup.send("Proteção Anti-Raid foi **ativada**.", ephemeral=True)
                await self.refresh_panel(self.guild_id, interaction.client)
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
            # Busca as configurações atuais para preservar os outros campos
            existing_settings = self._load_settings()
            success = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds, channel_id, message_id) VALUES (?, ?, ?, ?, ?, COALESCE((SELECT channel_id FROM anti_raid_settings WHERE guild_id = ?), NULL), COALESCE((SELECT message_id FROM anti_raid_settings WHERE guild_id = ?), NULL))",
                (self.guild_id, False, existing_settings['min_account_age_hours'], existing_settings['join_burst_threshold'], existing_settings['join_burst_time_seconds'], self.guild_id, self.guild_id)
            )

            if success:
                logging.info(f"[disable_button_callback] Status de 'enabled' atualizado com sucesso no DB para guild {self.guild_id}.")
                await interaction.followup.send("Proteção Anti-Raid foi **desativada**.", ephemeral=True)
                await self.refresh_panel(self.guild_id, interaction.client)
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
        current_settings = self._load_settings() # Carrega as configurações atuais para o modal
        modal = RaidProtectionSettingsModal(current_settings, self) # Passa a própria view como parent
        await interaction.response.send_modal(modal)

# --- Cog Principal ---
class RaidProtectionSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Inicia a tarefa para garantir as views persistentes ao iniciar o bot
        self.ensure_persistent_views.start()
        logging.info("Cog 'RaidProtectionSystem' carregada com sucesso.")

    def cog_unload(self):
        """Para a tarefa quando a cog é descarregada."""
        self.ensure_persistent_views.cancel()
        logging.info("Cog 'RaidProtectionSystem' descarregada. Tarefa de persistência cancelada.")

    @tasks.loop(count=1) # Executa apenas uma vez após o bot estar pronto
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
                        logging.warning(f"[ensure_persistent_views] Guild {guild_id} não encontrada para painel persistente. Removendo do DB.")
                        execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                        continue
                    
                    channel = await guild.fetch_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        logging.warning(f"[ensure_persistent_views] Canal {channel_id} não é de texto para painel persistente na guild {guild_id}. Removendo do DB.")
                        execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                        continue

                    message = await channel.fetch_message(message_id)
                    
                    # Crie a View e adicione ao bot para persistência
                    view = RaidProtectionPanelView(self.bot, guild_id)
                    view.message = message 
                    self.bot.add_view(view, message_id=message.id)
                    
                    # Opcional: Atualizar o embed da mensagem no carregamento para garantir que ele reflita o estado atual
                    await view.refresh_panel(guild_id, self.bot) # Garante que o painel mostre as configs atuais
                    
                    logging.info(f"Painel Proteção Anti-Raid persistente carregado para guild {guild_id} no canal {channel_id}, mensagem {message_id}.")
                except discord.NotFound:
                    logging.warning(f"Mensagem do painel Proteção Anti-Raid ({message_id}) ou canal ({channel_id}) não encontrada. Removendo do DB para evitar carregamentos futuros.")
                    execute_query("DELETE FROM anti_raid_settings WHERE guild_id = ?", (guild_id,))
                except discord.Forbidden:
                    logging.error(f"Bot sem permissão para acessar o canal {channel_id} ou mensagem {message_id} na guild {guild_id}. Não foi possível carregar o painel persistente.")
                except Exception as e:
                    logging.error(f"Erro inesperado ao carregar painel persistente para guild {guild_id}, mensagem {message_id}: {e}", exc_info=True)
        else:
            logging.info("Nenhum painel Proteção Anti-Raid persistente para carregar.")

    # Evento de entrada de membro
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            logging.debug(f"Ignorando entrada de bot: {member.name} (ID: {member.id}) na guild {member.guild.id}.")
            return 

        settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (member.guild.id,),
            fetchone=True
        )

        # Se não há configurações ou a proteção está desativada, não faz nada
        if not settings or not settings[0]:
            logging.debug(f"Proteção Anti-Raid desativada ou não configurada para guild {member.guild.id}. Ignorando {member.name}.")
            return

        enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds = settings

        # --- Verificação de Idade da Conta ---
        # Apenas kicks se a idade mínima for maior que 0
        if min_account_age_hours > 0:
            account_age_timedelta = datetime.datetime.now(datetime.timezone.utc) - member.created_at
            min_account_age_timedelta = datetime.timedelta(hours=min_account_age_hours)

            if account_age_timedelta < min_account_age_timedelta:
                try:
                    reason = f"Proteção Anti-Raid: Conta muito nova ({account_age_timedelta.total_seconds() / 3600:.2f} horas). Idade mínima configurada: {min_account_age_hours} horas."
                    await member.kick(reason=reason)
                    logging.info(f"Membro {member.id} ({member.name}) chutado na guild {member.guild.id} por ter conta muito nova. Razão: {reason}")
                    # Pode adicionar um log para o canal de moderação aqui, se desejar
                    return # Não verifica burst se já foi chutado
                except discord.Forbidden:
                    logging.error(f"Bot sem permissão para chutar {member.name} na guild {member.guild.id} (conta muito nova).")
                except Exception as e:
                    logging.error(f"Erro ao chutar membro {member.name} na guild {member.guild.id} por conta muito nova: {e}", exc_info=True)
                return

        # --- Verificação de Burst de Entradas ---
        # Apenas verifica burst se o threshold for maior que 0
        if join_burst_threshold > 0:
            guild_id = member.guild.id
            current_time = time.time()

            if guild_id not in join_burst_cache:
                join_burst_cache[guild_id] = []

            # Remove entradas antigas do cache
            join_burst_cache[guild_id] = [
                t for t in join_burst_cache[guild_id] if current_time - t < join_burst_time_seconds
            ]
            
            # Adiciona o novo membro ao cache
            join_burst_cache[guild_id].append(current_time)

            if len(join_burst_cache[guild_id]) >= join_burst_threshold:
                logging.warning(f"Possível burst de entradas detectado na guild {member.guild.id}! {len(join_burst_cache[guild_id])} membros em {join_burst_time_seconds} segundos. Disparando ações de proteção...")
                
                # Reseta o cache para evitar múltiplos disparos para o mesmo burst
                join_burst_cache[guild_id] = [] 

                # Ações de proteção em caso de burst
                try:
                    # Desativar convites (se permitido)
                    if member.guild.me.guild_permissions.manage_guild:
                        invites = await member.guild.invites()
                        for invite in invites:
                            if invite.max_uses == 0 or invite.max_uses is None: # Apenas convites ilimitados ou sem limite
                                try:
                                    await invite.delete(reason="Proteção Anti-Raid: Burst de entradas detectado.")
                                    logging.info(f"Convite {invite.code} deletado na guild {member.guild.id} devido a burst de entradas.")
                                except discord.Forbidden:
                                    logging.warning(f"Bot sem permissão para deletar convite {invite.code} na guild {member.guild.id}.")
                                except Exception as e:
                                    logging.error(f"Erro ao deletar convite {invite.code} na guild {member.guild.id}: {e}")
                    else:
                        logging.warning(f"Bot sem permissão 'Gerenciar Servidor' para deletar convites na guild {member.guild.id}.")

                    # Alertar canal de moderação
                    settings_full = execute_query(
                        "SELECT channel_id FROM anti_raid_settings WHERE guild_id = ?",
                        (member.guild.id,),
                        fetchone=True
                    )
                    if settings_full and settings_full[0]:
                        alert_channel_id = settings_full[0]
                        alert_channel = member.guild.get_channel(alert_channel_id)
                        if alert_channel and isinstance(alert_channel, discord.TextChannel) and alert_channel.permissions_for(member.guild.me).send_messages:
                            embed = discord.Embed(
                                title="🚨 Alerta de Possível Raid! 🚨",
                                description=f"Detectado um **burst de entradas**: `{len(join_burst_cache[guild_id]) + 1}` membros em `{join_burst_time_seconds}` segundos.",
                                color=discord.Color.red()
                            )
                            embed.add_field(name="Ação Automática", value="Convites podem ter sido desativados.", inline=False)
                            embed.set_footer(text="Revise as entradas recentes e considere ações adicionais.")
                            await alert_channel.send(embed=embed)
                            logging.info(f"Alerta de raid enviado para o canal {alert_channel.name} na guild {member.guild.id}.")
                        else:
                            logging.warning(f"Não foi possível enviar alerta de raid no canal {alert_channel_id} para guild {member.guild.id}. Canal inválido ou sem permissão.")

                    # Opcional: Ativar modo de verificação de segurança do Discord
                    # Requires `manage_guild` permission and bot to be higher than target.
                    # This might be too aggressive for a bot to do automatically.
                    # if member.guild.me.guild_permissions.manage_guild and member.guild.verification_level < discord.VerificationLevel.highest:
                    #     await member.guild.edit(verification_level=discord.VerificationLevel.highest, reason="Proteção Anti-Raid: Burst de entradas detectado.")
                    #     logging.info(f"Nível de verificação da guild {member.guild.id} elevado para {discord.VerificationLevel.highest}.")

                except discord.Forbidden:
                    logging.error(f"Bot sem permissão para agir no burst de entradas na guild {member.guild.id}. Verifique permissões (Gerenciar Servidor, Gerenciar Canais).")
                except Exception as e:
                    logging.error(f"Erro ao lidar com burst de entradas na guild {member.guild.id}: {e}", exc_info=True)

    # --- Comandos de Slash ---
    @app_commands.command(name="setup_raid_protection", description="Configura ou move o painel de proteção anti-raid para o canal atual.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.guild_only() # Garante que o comando só pode ser usado em guilds
    async def setup_raid_protection_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        # Carrega as configurações atuais para preservar
        current_settings = execute_query(
            "SELECT enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )
        # Define padrões se não houver configurações existentes
        enabled = current_settings[0] if current_settings else False
        min_age_hours = current_settings[1] if current_settings else 24
        burst_threshold = current_settings[2] if current_settings else 10
        burst_time = current_settings[3] if current_settings else 60

        # Tenta deletar a mensagem antiga do painel, se existir
        old_panel_data = execute_query(
            "SELECT channel_id, message_id FROM anti_raid_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )

        if old_panel_data and old_panel_data[0] and old_panel_data[1]: 
            old_channel_id, old_message_id = old_panel_data
            try:
                old_channel = interaction.guild.get_channel(old_channel_id) # Usar get_channel para evitar await inicial
                if old_channel and isinstance(old_channel, discord.TextChannel):
                    old_message = await old_channel.fetch_message(old_message_id)
                    await old_message.delete()
                    logging.info(f"[setup_raid_protection_panel] Mensagem do painel anti-raid antigo ({old_message_id}) deletada do canal {old_channel_id}.")
            except discord.NotFound:
                logging.warning(f"[setup_raid_protection_panel] Mensagem do painel Proteção Anti-Raid ({old_message_id}) não encontrada para deletar no canal {old_channel_id}. Provavelmente já foi deletada.")
            except discord.Forbidden:
                logging.error(f"[setup_raid_protection_panel] Bot sem permissão para deletar a mensagem do painel antigo ({old_message_id}) no canal {old_channel_id}. Verifique as permissões 'Gerenciar Mensagens'.")
            except Exception as e:
                logging.error(f"[setup_raid_protection_panel] Erro ao deletar painel anti-raid antigo na guild {guild_id}: {e}", exc_info=True)
            
            # Limpa o DB da referência antiga do painel
            execute_query("UPDATE anti_raid_settings SET channel_id = NULL, message_id = NULL WHERE guild_id = ?", (guild_id,))
            logging.info(f"[setup_raid_protection_panel] Referências de channel_id/message_id limpadas no DB para guild {guild_id}.")
        elif old_panel_data: # Se existe entrada mas channel_id ou message_id são None
            logging.warning(f"[setup_raid_protection_panel] Entrada antiga de painel com IDs None para guild {guild_id}. Limpando do DB.")
            execute_query("UPDATE anti_raid_settings SET channel_id = NULL, message_id = NULL WHERE guild_id = ?", (guild_id,))


        # Cria o embed e a view para o novo painel
        min_age_days_display = max(0, min_age_hours // 24)
        age_unit = "dias" if min_age_days_display != 1 else "dia"

        status = "Ativado" if enabled else "Desativado"
        color = discord.Color.green() if enabled else discord.Color.red()

        burst_threshold_display = f"{burst_threshold} membros" if burst_threshold > 0 else "Desativado"
        burst_time_display = f"em {burst_time} segundos" if burst_threshold > 0 else ""

        embed = discord.Embed(
            title="Painel Proteção Anti-Raid",
            description=f"Status: **{status}**\n\nGerencie as configurações do sistema Anti-Raid.",
            color=color
        )
        embed.add_field(name="Idade Mínima da Conta", value=f"{min_age_days_display} {age_unit}", inline=False)
        embed.add_field(name="Limite de Entradas por Burst", value=f"{burst_threshold_display} {burst_time_display}".strip(), inline=False)
        embed.set_footer(text="Use os botões abaixo para gerenciar.")

        view = RaidProtectionPanelView(self.bot, guild_id) # Cria a nova View
        
        try:
            # Envia a nova mensagem do painel
            panel_message = await interaction.channel.send(embed=embed, view=view)
            view.message = panel_message # Associa a mensagem à instância da View
            
            # Salva os novos channel_id e message_id no banco de dados, preservando as outras configurações
            success_db_insert = execute_query(
                "INSERT OR REPLACE INTO anti_raid_settings (guild_id, channel_id, message_id, enabled, min_account_age_hours, join_burst_threshold, join_burst_time_seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, interaction.channel.id, panel_message.id, enabled, min_age_hours, burst_threshold, burst_time)
            )
            if success_db_insert:
                logging.info(f"[setup_raid_protection_panel] Dados do painel salvos com sucesso no DB para guild {guild_id}.")
            else:
                logging.error(f"[setup_raid_protection_panel] Falha ao salvar dados do painel no DB para guild {guild_id}.")

            # Adiciona a view ao bot para persistência
            self.bot.add_view(view, message_id=panel_message.id) 
            await interaction.followup.send(f"Painel de proteção anti-raid configurado neste canal: {interaction.channel.mention}", ephemeral=True)
            logging.info(f"Painel Proteção Anti-Raid configurado/movido por {interaction.user.id} para canal {interaction.channel.id} na guild {guild_id}. Mensagem ID: {panel_message.id}.")
        except discord.Forbidden:
            await interaction.followup.send("Não tenho permissão para enviar mensagens neste canal. Por favor, verifique as minhas permissões.", ephemeral=True)
            logging.error(f"Bot sem permissão para enviar painel anti-raid no canal {interaction.channel.id} na guild {guild_id}.")
        except Exception as e:
            await interaction.followup.send(f"Ocorreu um erro ao configurar o painel: {e}", ephemeral=True)
            logging.error(f"Erro inesperado ao configurar painel anti-raid na guild {guild_id}: {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidProtectionSystem(bot))