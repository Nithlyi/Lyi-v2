# config.py

import os
from dotenv import load_dotenv

load_dotenv() # Carrega as variáveis do arquivo .env

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
COMMAND_PREFIX = "!" # Ou o prefixo que preferir
TEST_GUILD_ID = 1387502748387377223 # Substitua pelo ID do seu servidor de testes (opcional)

# --- Adicione esta linha ---
DISCORD_BOT_APPLICATION_ID = os.getenv("DISCORD_BOT_APPLICATION_ID")
# ---------------------------