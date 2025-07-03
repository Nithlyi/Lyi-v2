import discord
from discord.ext import commands
import os
import asyncio
import logging
from typing import Optional
from discord import app_commands, Object
import http.server
import socketserver
import threading
from flask import Flask

# Importa as configurações e o banco de dados
from config import DISCORD_BOT_TOKEN, COMMAND_PREFIX, TEST_GUILD_ID
from database import init_db # Já est�� correto

# Configurações de logging para o bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MyBot(commands.Bot):
    def __init__(self):
        # Define os Intents necessários.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True
        intents.moderation = True
        # intents.integrations = True # Este intent não existe diretamente no discord.py 2.x
        intents.guilds = True
        intents.reactions = True
        intents.messages = True

        super().__init__(command_prefix=COMMAND_PREFIX, intents=intents, application_id=os.getenv("DISCORD_BOT_APPLICATION_ID"))
        
        self.TEST_GUILD_ID = TEST_GUILD_ID 

        self.initial_extensions = []
        self.load_cogs_from_folders()

    def load_cogs_from_folders(self):
        """
        Carrega todos os cogs das pastas especificadas, garantindo a ordem para cogs dependentes.
        """
        base_path = "cogs"
        
        # Ordem de carregamento é importante para cogs com dependências.
        # Por exemplo, lockdown_panel depende de lockdown_core.
        # Coloque os cogs aqui na ordem em que eles devem ser carregados.
        cogs_to_load_ordered = [
            # Cogs essenciais ou sem dependências pesadas
            ("owner", ["owner_commands"]),
            ("moderation", ["moderation_commands"]), # Se moderation_commands tiver apenas comandos gerais e não depender de lockdown_core, pode ficar aqui.
            
            # Cogs do sistema de Lockdown (core antes do painel)
            ("moderation", ["lockdown_core"]),      # Adicionado: Lógica principal do lockdown
            ("moderation", ["lockdown_panel"]),     # Adicionado: Painel de lockdown (depende de lockdown_core)

            # Cogs de eventos (proteção de raid antes de listeners gerais)
            ("events", ["raid_protection"]),
            ("events", ["welcome_leave"]),
            ("events", ["event_listeners"]),
            
            # Outros cogs
            ("diversion", ["diversion_commands", "marriage_system", "hug_command"]),
            ("utility", ["backup_commands", "embed_creator", "say_command", "ticket_system", "utility_commands"])
        ]

        # Limpa initial_extensions para garantir que estamos construindo a lista do zero
        self.initial_extensions = []

        for folder_name, cog_files in cogs_to_load_ordered:
            folder_full_path = os.path.join(base_path, folder_name)
            if os.path.exists(folder_full_path) and os.path.isdir(folder_full_path):
                for cog_file in cog_files:
                    module_name = f"{base_path}.{folder_name}.{cog_file}"
                    self.initial_extensions.append(module_name)
                    logging.info(f"Programado para carregar: {module_name}")
            else:
                logging.warning(f"Pasta de cogs não encontrada: {folder_full_path}")
        
        logging.info(f"Ordem final de carregamento dos Cogs: {self.initial_extensions}")


    async def setup_hook(self):
        """Chamado quando o bot está pronto para carregar extensões (cogs)."""
        # Inicializa o banco de dados
        logging.info("Inicializando o banco de dados...")
        init_db() # Já está correto e chamará o init_db do seu database.py
        logging.info("Banco de dados inicializado.")
        
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                logging.info(f"Cog '{extension}' carregado com sucesso.")
            except Exception as e:
                logging.error(f"Falha ao carregar cog '{extension}': {e}", exc_info=True) # Adicionado exc_info=True para stack trace
        
        # Sincroniza comandos de barra (slash commands)
        logging.info("Sincronizando comandos de barra...")
        if self.TEST_GUILD_ID:
            test_guild = Object(id=self.TEST_GUILD_ID)
            # await self.tree.sync(guild=test_guild) # Comente ou remova esta linha se você usa copy_global_to
            self.tree.copy_global_to(guild=test_guild) # Já está correto
            await self.tree.sync(guild=test_guild) # Sincroniza para o guild de teste
            logging.info(f"Comandos de barra sincronizados com o servidor de testes: {self.TEST_GUILD_ID}")
        else:
            await self.tree.sync()
            logging.info("Comandos de barra sincronizados globalmente.")

    async def on_ready(self):
        """Evento acionado quando o bot está online e pronto."""
        logging.info(f"Logado como: {self.user.name} (ID: {self.user.id})")
        logging.info(f"Versão do discord.py: {discord.__version__}")
        logging.info("Bot está pronto!")
        await self.change_presence(activity=discord.Game(name="Gerenciando o servidor!")) # Exemplo de status

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Tratamento de erros globais para comandos de texto."""
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Argumento faltando! Uso correto: `{COMMAND_PREFIX}{ctx.command.name} {ctx.command.signature}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("⚠️ Argumento inválido fornecido. Por favor, verifique o tipo de dado.")
        elif isinstance(error, commands.CommandNotFound):
            return # Ignora se o comando não existe
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(f"🚫 Você não tem permissão para usar este comando: `{', '.join(error.missing_permissions)}`")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"🚫 Eu não tenho permissão para executar esta ação: `{', '.join(error.missing_permissions)}`. Por favor, me conceda as permissões necessárias.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("🚫 Este comando não pode ser usado em mensagens diretas.")
        elif isinstance(error, commands.NotOwner):
            await ctx.send("🚫 Você não é o proprietário do bot.")
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Este comando está em cooldown. Tente novamente em {error.retry_after:.2f} segundos.")
        else:
            logging.error(f"Erro inesperado no comando {ctx.command}: {error}", exc_info=True) # Adicionado exc_info=True
            await ctx.send(f"Um erro inesperado ocorreu: `{error}`")

    async def on_interaction_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Tratamento de erros para comandos de barra (slash commands)."""
        if interaction.response.is_done(): # Verifica se a resposta já foi enviada
            # Se a resposta já foi enviada (ex: defer), tente editar ou enviar uma follow-up
            try:
                await interaction.followup.send(f"❌ Ocorreu um erro: {error}", ephemeral=True)
            except discord.InteractionResponded: # Já interagiu com follow-up também
                 pass
            except Exception as e:
                logging.error(f"Erro ao enviar follow-up de erro na interação: {e}", exc_info=True)
            logging.error(f"Erro na interação após resposta (já feita): {interaction.command}: {error}", exc_info=True)
            return

        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(f"🚫 Você não tem permissão para usar este comando: `{', '.join(error.missing_permissions)}`", ephemeral=True)
        elif isinstance(error, app_commands.BotMissingPermissions):
            await interaction.response.send_message(f"🚫 Eu não tenho permissão para executar esta ação: `{', '.join(error.missing_permissions)}`. Por favor, me conceda as permissões necessárias.", ephemeral=True)
        elif isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(f"⏳ Este comando está em cooldown. Tente novamente em {error.retry_after:.2f} segundos.", ephemeral=True)
        elif isinstance(error, app_commands.NoPrivateMessage):
            await interaction.response.send_message("🚫 Este comando não pode ser usado em mensagens diretas.", ephemeral=True)
        elif isinstance(error, app_commands.CheckFailure): # Catch all custom check failures
            await interaction.response.send_message("🚫 Você não pode usar este comando.", ephemeral=True)
        else:
            logging.error(f"Erro inesperado na interação {interaction.command}: {error}", exc_info=True) # Adicionado exc_info=True
            await interaction.response.send_message(f"Um erro inesperado ocorreu: `{error}`", ephemeral=True)

app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Bot is running!'

def start_server():
    """Starts a Flask HTTP server to satisfy port binding requirement."""
    try:
        port = int(os.environ.get("PORT", 8080)) # Default to 8080 if PORT not set
        # Use a different port for Flask if the bot needs 8080 for something else,
        # but for simple port binding, 8080 is fine.
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logging.error(f"Failed to start Flask server: {e}", exc_info=True)


if __name__ == "__main__":
    bot = MyBot()

    # Inicia o servidor Flask em uma thread separada
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True  # Permite que a thread do servidor feche quando o bot principal fechar
    server_thread.start()
    logging.info("Flask server thread started.")
    
    # Certifique-se de que DISCORD_BOT_TOKEN está definido em seu .env
    if DISCORD_BOT_TOKEN is None:
        logging.error("O token do bot não foi encontrado. Certifique-se de que a variável de ambiente DISCORD_BOT_TOKEN está definida no arquivo .env")
    else:
        try:
            bot.run(DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logging.error("O token do bot é inválido. Por favor, verifique seu .env")
        except Exception as e:
            logging.critical(f"Ocorreu um erro crítico ao iniciar o bot: {e}", exc_info=True) # Erro crítico com stack trace