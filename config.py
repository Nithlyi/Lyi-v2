import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Token do seu bot do Discord
# Certifique-se de criar um arquivo .env na mesma pasta do main.py com:
# DISCORD_BOT_TOKEN="SEU_TOKEN_AQUI"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# ID do seu servidor de testes (opcional, mas recomendado para slash commands)
# Se você tiver um servidor específico para testar os slash commands, coloque o ID aqui.
# Isso fará com que os comandos de barra sejam registrados instantaneamente lá.
# Ex: TEST_GUILD_ID = 123456789012345678
TEST_GUILD_ID = None # Mude para o ID do seu servidor de testes se quiser.

# Prefixo para comandos de texto (se você for usar)
COMMAND_PREFIX = "!"