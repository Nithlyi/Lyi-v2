import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# MUDANÇA AQUI: Lê do ambiente ou usa "!" como padrão
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# MUDANÇA AQUI: Lê do ambiente, se existir, senão é None
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")