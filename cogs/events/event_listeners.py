import discord
from discord.ext import commands
import logging

# Configuração de logging (garante que o logging seja configurado uma vez, se não estiver global)
# Embora você já possa ter isso no seu arquivo principal, é bom garantir.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GeneralEventListeners(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logging.info("Cog 'GeneralEventListeners' carregada com sucesso.")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """
        Ações a serem executadas quando o bot entra em um novo servidor.
        Tenta enviar uma mensagem de boas-vindas com instruções iniciais.
        """
        logging.info(f"O bot entrou no servidor: {guild.name} (ID: {guild.id}).")

        # Prioriza o canal do sistema, depois o primeiro canal de texto onde o bot pode enviar mensagens.
        # Isso garante que a mensagem seja enviada em um local visível e acessível.
        target_channel = guild.system_channel
        if not target_channel or not target_channel.permissions_for(guild.me).send_messages:
            # Se o canal do sistema não existe ou o bot não tem permissão, procura outro canal de texto
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target_channel = channel
                    break
            else:
                target_channel = None # Nenhum canal adequado encontrado

        if target_channel:
            try:
                embed = discord.Embed(
                    title=f"🎉 Olá, {guild.name}! 🎉",
                    description=(
                        "Obrigado por me adicionar! Sou um bot multifuncional projetado para ajudar "
                        "na moderação, engajamento e organização do seu servidor."
                    ),
                    color=discord.Color.brand_green() # Uma cor mais moderna
                )
                embed.add_field(
                    name="➡️ Primeiros Passos:", 
                    value=(
                        "Para começar, aqui estão alguns comandos essenciais:\n"
                        "• Use `/help` para ver todos os meus comandos disponíveis.\n"
                        "• Configure seu sistema de **tickets** com `/ticket_setup`.\n"
                        "• Crie um **painel de boas-vindas e saídas** com `/welcome_leave_panel`.\n\n"
                        "Se precisar de ajuda, não hesite em perguntar!"
                    ), 
                    inline=False
                )
                embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None) # Adiciona o ícone do bot
                embed.set_footer(text=f"ID do Servidor: {guild.id}")

                await target_channel.send(embed=embed)
                logging.info(f"Mensagem de boas-vindas enviada para o servidor {guild.name} no canal {target_channel.name}.")
            except discord.Forbidden:
                logging.warning(f"Não foi possível enviar mensagem de boas-vindas no servidor {guild.name} (ID: {guild.id}) devido a permissões insuficientes no canal {target_channel.name}.")
            except Exception as e:
                logging.error(f"Erro inesperado ao enviar mensagem de boas-vindas no servidor {guild.name} (ID: {guild.id}): {e}", exc_info=True)
        else:
            logging.warning(f"Não foi encontrado um canal adequado para enviar a mensagem de boas-vindas no servidor: {guild.name} (ID: {guild.id}).")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        """
        Ações a serem executadas quando o bot é removido de um servidor.
        Ideal para limpeza de dados associados àquela guilda no seu banco de dados.
        """
        logging.info(f"O bot foi removido do servidor: {guild.name} (ID: {guild.id}).")
        # Exemplo de limpeza de dados (adapte conforme sua implementação de DB)
        # from database import execute_query # Assumindo que você tem uma função para isso
        # try:
        #     success = execute_query("DELETE FROM settings WHERE guild_id = ?", (guild.id,))
        #     if success:
        #         logging.info(f"Dados do servidor {guild.name} (ID: {guild.id}) limpos do banco de dados.")
        #     else:
        #         logging.warning(f"Falha ao limpar dados do servidor {guild.name} (ID: {guild.id}) do banco de dados.")
        # except Exception as e:
        #     logging.error(f"Erro ao limpar dados do servidor {guild.name} (ID: {guild.id}) no DB: {e}", exc_info=True)

async def setup(bot: commands.Bot):
    """Função de setup para adicionar a cog ao bot."""
    await bot.add_cog(GeneralEventListeners(bot))