import discord
from discord.ext import commands, tasks # Importa tasks para uso futuro, se necessário
import os
import asyncio
import logging
from typing import Optional
from discord import app_commands, Object
import threading
from flask import Flask

# Importa as configurações e o banco de dados
from config import DISCORD_BOT_TOKEN, COMMAND_PREFIX, TEST_GUILD_ID, DISCORD_BOT_APPLICATION_ID
from database import init_db 

# Configurações de logging para o bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler()]) # Garante que logs vão para o console

class MyBot(commands.Bot):
    def __init__(self):
        # Define os Intents necessários.
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True 
        intents.moderation = True
        intents.guilds = True
        intents.reactions = True
        intents.messages = True

        super().__init__(command_prefix=COMMAND_PREFIX, intents=intents, application_id=DISCORD_BOT_APPLICATION_ID)
        
        self.TEST_GUILD_ID = TEST_GUILD_ID 

        self.initial_extensions = []
        self.load_cogs_from_folders()

    def load_cogs_from_folders(self):
        """
        Carrega todos os cogs das pastas especificadas, garantindo a ordem para cogs dependentes.
        """
        base_path = "cogs"
        
        # Ordem de carregamento é importante para cogs com dependências.
        # Se você não tiver a pasta 'cogs/logs' ou o arquivo 'log_system.py',
        # remova ou comente a linha correspondente para evitar o warning de "Pasta de cogs não encontrada".
        cogs_to_load_ordered = [
            ("owner", ["owner_commands"]),
            ("logs", ["log_system"]), # Remova ou comente se não tiver 'cogs/logs/log_system.py'
            ("moderation", ["moderation_commands", "lockdown_core", "lockdown_panel"]), # Coloque core antes do panel
            ("events", ["raid_protection", "welcome_leave", "event_listeners"]),
            ("utility", ["ticket_system", "embed_creator", "backup_commands", "say_command", "utility_commands"]),
            ("diversion", ["diversion_commands", "hug_command", "marriage_system"]),
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
        logging.info("Inicializando o banco de dados...")
        init_db() 
        logging.info("Banco de dados inicializado.")
        
        for extension in self.initial_extensions:
            try:
                await self.load_extension(extension)
                logging.info(f"Cog '{extension}' carregado com sucesso.")
            except Exception as e:
                logging.error(f"Falha ao carregar cog '{extension}': {e}", exc_info=True)
        
        logging.info("Sincronizando comandos de barra...")
        if self.TEST_GUILD_ID:
            test_guild = Object(id=self.TEST_GUILD_ID)
            self.tree.copy_global_to(guild=test_guild) 
            await self.tree.sync(guild=test_guild) 
            logging.info(f"Comandos de barra sincronizados com o servidor de testes: {self.TEST_GUILD_ID}")
        else:
            await self.tree.sync()
            logging.info("Comandos de barra sincronizados globalmente.")

    async def on_ready(self):
        """Evento acionado quando o bot está online e pronto."""
        logging.info(f"Logado como: {self.user.name} (ID: {self.user.id})")
        logging.info(f"Versão do discord.py: {discord.__version__}")
        logging.info("Bot está pronto!")
        await self.change_presence(activity=discord.Game(name="Gerenciando o servidor!"))

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Tratamento de erros globais para comandos de texto (prefix commands)."""
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Argumento faltando! Uso correto: `{COMMAND_PREFIX}{ctx.command.name} {ctx.command.signature}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("⚠️ Argumento inválido fornecido. Por favor, verifique o tipo de dado.")
        elif isinstance(error, commands.CommandNotFound):
            return 
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
            logging.error(f"Erro inesperado no comando {ctx.command}: {error}", exc_info=True)
            await ctx.send(f"❌ Ocorreu um erro inesperado ao executar o comando. Por favor, tente novamente mais tarde ou contate o suporte.")

    async def on_interaction_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Tratamento de erros para comandos de barra (slash commands)."""
        if interaction.response.is_done():
            send_func = interaction.followup.send
        else:
            send_func = interaction.response.send_message

        try:
            if isinstance(error, app_commands.MissingPermissions):
                await send_func(f"🚫 Você não tem permissão para usar este comando: `{', '.join(error.missing_permissions)}`", ephemeral=True)
            elif isinstance(error, app_commands.BotMissingPermissions):
                await send_func(f"🚫 Eu não tenho permissão para executar esta ação: `{', '.join(error.missing_permissions)}`. Por favor, me conceda as permissões necessárias.", ephemeral=True)
            elif isinstance(error, app_commands.CommandOnCooldown):
                await send_func(f"⏳ Este comando está em cooldown. Tente novamente em {error.retry_after:.2f} segundos.", ephemeral=True)
            elif isinstance(error, app_commands.NoPrivateMessage):
                await send_func("🚫 Este comando não pode ser usado em mensagens diretas.", ephemeral=True)
            elif isinstance(error, app_commands.CheckFailure):
                await send_func("🚫 Você não pode usar este comando.", ephemeral=True)
            else:
                logging.error(f"Erro inesperado na interação {interaction.command}: {error}", exc_info=True)
                await send_func(f"❌ Ocorreu um erro inesperado ao executar o comando. Por favor, tente novamente mais tarde ou contate o suporte.", ephemeral=True)
        except discord.InteractionResponded:
            logging.warning(f"Tentativa de responder a interação que já foi respondida: {interaction.command} com erro: {error}")
        except Exception as e:
            logging.error(f"Erro ao tentar enviar mensagem de erro para interação {interaction.command}: {e}", exc_info=True)


app = Flask(__name__)

@app.route('/')
def hello_world():
    return 'Bot is running!'

def start_server():
    """Starts a Flask HTTP server to satisfy port binding requirement."""
    try:
        port = int(os.environ.get("PORT", 8080))
        app.run(host='0.0.0.0', port=port, debug=False)
    except Exception as e:
        logging.error(f"Falha ao iniciar o servidor Flask: {e}", exc_info=True)


if __name__ == "__main__":
    bot = MyBot()

    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True 
    server_thread.start()
    logging.info("Flask server thread started.")
    
    if DISCORD_BOT_TOKEN is None:
        logging.error("O token do bot não foi encontrado. Certifique-se de que a variável de ambiente DISCORD_BOT_TOKEN está definida no arquivo .env")
    else:
        try:
            bot.run(DISCORD_BOT_TOKEN)
        except discord.LoginFailure:
            logging.critical("O token do bot é inválido. Por favor, verifique seu .env. Encerrando o bot.", exc_info=True)
        except Exception as e:
            logging.critical(f"Ocorreu um erro crítico ao iniciar o bot: {e}", exc_info=True)