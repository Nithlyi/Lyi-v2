import discord
from discord.ext import commands
import logging

# Configuração de logging (garante que o logging seja configurado, se não estiver globalmente)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TicketEvents(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # A mensagem de log reforça que este cog está intencionalmente leve
        logging.info("Cog 'TicketEvents' inicializada. (Atualmente sem ouvintes de eventos ativos para evitar conflitos, a menos que explicitamente adicionados).")

    # --- Se você precisar de ouvintes de eventos para tickets que NÃO estão no `ticket_system.py` ---
    #
    # Por exemplo, se `ticket_system.py` lida com a criação/fechamento
    # e você quer um sistema de log DE AUDITORIA de tickets mais granular aqui,
    # ou eventos de interação que não são parte do ciclo de vida principal.
    #
    # Mantenha este arquivo DESATIVADO (sem listeners) se `ticket_system.py` já cobre tudo.
    # Se você ativar um listener aqui, REMOVA-O de `ticket_system.py` para evitar duplicação.

    # Exemplo: Registrar quando um ticket é criado, mas a lógica de criação está em outro lugar
    # @commands.Cog.listener()
    # async def on_ticket_created_event(self, ticket_channel: discord.TextChannel, creator: discord.Member):
    #     """
    #     Este é um exemplo de um ouvinte para um evento CUSTOMIZADO 'on_ticket_created_event'
    #     que você dispararia do seu `ticket_system.py` (usando `self.bot.dispatch`).
    #     Isso desacopla a criação do ticket do logging ou de outras ações secundárias.
    #     """
    #     logging.info(f"Evento 'ticket_created' detectado para o ticket {ticket_channel.name} (ID: {ticket_channel.id}) criado por {creator.name} (ID: {creator.id}).")
    #     # Exemplo: Enviar log para um canal de auditoria
    #     # log_channel = self.bot.get_channel(SEU_ID_CANAL_DE_LOG)
    #     # if log_channel:
    #     #     await log_channel.send(f"Novo ticket criado: {ticket_channel.mention} por {creator.mention}")

    # Exemplo: Monitorar reações, mas SOMENTE para mensagens que NÃO são o painel principal de tickets
    # (se o painel principal já é monitorado em `ticket_system.py`).
    # @commands.Cog.listener()
    # async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
    #     """
    #     Lógica para reagir a reações em mensagens de ticket, por exemplo,
    #     para adicionar um membro ao ticket ou para registrar uma ação específica.
    #     Certifique-se de que isso não conflite com `ticket_system.py`!
    #     """
    #     if payload.guild_id is None:
    #         return # Ignora DMs

    #     # Evite que o bot reaja às suas próprias reações
    #     if payload.user_id == self.bot.user.id:
    #         return

    #     guild = self.bot.get_guild(payload.guild_id)
    #     if not guild:
    #         return

    #     channel = guild.get_channel(payload.channel_id)
    #     if not channel or not isinstance(channel, discord.TextChannel):
    #         return

    #     # Exemplo: Verifique se a reação é em uma mensagem de ticket ESPECÍFICA,
    #     # não no painel de criação de tickets.
    #     # Você precisaria de alguma forma de identificar mensagens de ticket aqui.
    #     # if "ticket" in channel.name and payload.emoji.name == "✅":
    #     #     message = await channel.fetch_message(payload.message_id)
    #     #     user = guild.get_member(payload.user_id)
    #     #     if user and not user.bot:
    #     #         logging.info(f"Reação '{payload.emoji.name}' detectada de {user.name} em mensagem de ticket {message.id} no canal {channel.name}.")
    #     #         # Lógica adicional aqui, ex: adicionar função ao usuário no ticket

async def setup(bot: commands.Bot):
    """
    Função de setup para adicionar a cog ao bot.
    """
    await bot.add_cog(TicketEvents(bot))