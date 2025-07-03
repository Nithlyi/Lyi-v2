import discord
from discord.ext import commands
from discord import app_commands
from discord.errors import HTTPException # Adicione esta importação
import asyncio # Adicione esta importação

# Supondo que você tem seu database.py no nível superior ou em um módulo acessível
# Ajuste o caminho de importação conforme a estrutura real do seu projeto.
# Por exemplo, se database.py estiver na raiz do projeto:
# from database import connect_db, execute_query, init_db
# Ou se estiver em um pacote específico, como 'utils':
# from utils.database import connect_db, execute_query, init_db

# Vou usar um placeholder para as funções do banco de dados,
# já que você não quer modificá-lo.
# Certifique-se de que essas funções estão corretamente importadas do seu database.py.

# Exemplo de placeholders (adapte com suas funções reais do database.py)
def connect_db():
    print("Conectando ao DB (placeholder)...")
    # Sua lógica real de conexão aqui
    return None

def execute_query(query, params=(), fetchone=False, fetchall=False):
    print(f"Executando query (placeholder): {query} com {params}")
    # Sua lógica real de execução de query aqui
    return None

def init_db():
    print("Inicializando DB (placeholder)...")
    # Sua lógica real de inicialização aqui


class MyBackupView(discord.ui.View):
    def __init__(self, bot, guild_id, current_panel_data=None):
        super().__init__(timeout=None)  # Timeout None para views persistentes
        self.bot = bot
        self.guild_id = guild_id
        self.current_panel_data = current_panel_data if current_panel_data else {}
        self.message = None  # <<--- NOVO: Atributo para guardar a mensagem do painel

        # Adicione seus botões. Seus rótulos e estilos podem ser diferentes.
        self.add_item(discord.ui.Button(label="Criar Painel", custom_id="create_panel", style=discord.ButtonStyle.primary))
        self.add_item(discord.ui.Button(label="Carregar Backup", custom_id="load_backup", style=discord.ButtonStyle.secondary))
        self.add_item(discord.ui.Button(label="Gerenciar Backups", custom_id="manage_backups", style=discord.ButtonStyle.secondary))
        self.add_item(discord.ui.Button(label="Enviar Painel", custom_id="send_panel", style=discord.ButtonStyle.success))

    async def _update_display(self, interaction: discord.Interaction):
        # Lógica para construir o embed. Adapte com os dados reais do seu painel.
        embed = discord.Embed(
            title="Painel de Gerenciamento de Backup",
            description="Use os botões abaixo para gerenciar os backups do servidor.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status do Painel:", value="Pronto para interação.", inline=False)
        embed.set_footer(text="Última atualização: " + discord.utils.format_dt(discord.utils.utcnow(), "T"))

        try:
            if self.message:
                # Se a mensagem já existe, edite-a em vez de enviar uma nova
                await self.message.edit(embed=embed, view=self)
            else:
                # Se for a primeira vez, envie a mensagem e salve-a no self.message
                self.message = await interaction.followup.send(embed=embed, view=self, ephemeral=True)

            # Para garantir que a interação foi respondida
            if not interaction.response.is_done():
                await interaction.response.defer() # Apenas deferir se ainda não foi respondido.

        except HTTPException as e:
            if e.status == 429:
                print(f"RATE LIMITED ao atualizar painel de backup: Tentando novamente em {e.retry_after:.2f} segundos.")
                if not interaction.response.is_done():
                    # Tenta enviar uma resposta temporária se possível
                    await interaction.followup.send("O Discord está me limitando. Por favor, aguarde e tente interagir novamente.", ephemeral=True)
                await asyncio.sleep(e.retry_after + 1) # Espera um pouco mais do que o sugerido
                # Opcional: tentar editar/enviar novamente após o sleep, ou desabilitar botões
                # Para Views, geralmente o usuário terá que clicar de novo após o cooldown
            else:
                print(f"Erro inesperado ao atualizar painel de backup (HTTPException): {e}")
                if not interaction.response.is_done():
                    await interaction.followup.send("Ocorreu um erro desconhecido ao atualizar o painel.", ephemeral=True)
                raise # Re-lança o erro se não for rate limit ou se não puder ser tratado
        except Exception as e:
            print(f"Erro geral ao atualizar painel de backup: {e}")
            if not interaction.response.is_done():
                await interaction.followup.send("Ocorreu um erro inesperado. Por favor, tente novamente.", ephemeral=True)
            raise


class BackupCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Certifique-se de inicializar seu banco de dados ao carregar o cog
        init_db()

    # Comando de barra para iniciar o painel de backup
    @app_commands.command(name="backup_panel", description="Cria/atualiza o painel de backup no canal atual.")
    @app_commands.guild_only() # Garante que o comando só pode ser usado em guilds
    # Cooldown para o comando: 1 uso a cada 10 segundos por servidor.
    @app_commands.checks.cooldown(1, 10, key=lambda i: i.guild_id)
    async def backup_panel(self, interaction: discord.Interaction):
        # Defer a resposta da interação imediatamente para evitar o timeout de 3 segundos do Discord
        await interaction.response.defer(ephemeral=True)

        # Cria uma nova instância da View
        view = MyBackupView(self.bot, interaction.guild_id)
        
        # Chama _update_display para enviar/atualizar a mensagem do painel
        await view._update_display(interaction)
        
        # Opcional: Confirmação para o usuário que o comando foi executado
        # (se _update_display já enviou a mensagem inicial e você não precisa de outra)
        # Se interaction.followup.send já foi usado em _update_display,
        # você não deve usar interaction.followup.send aqui novamente
        # a menos que queira uma segunda mensagem de confirmação separada.

    @backup_panel.error # Handler para erros específicos do comando backup_panel
    async def backup_panel_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CommandOnCooldown):
            remaining_time = int(error.retry_after)
            await interaction.response.send_message(
                f"Este comando está em cooldown! Por favor, aguarde **{remaining_time}** segundos para usá-lo novamente.",
                ephemeral=True
            )
        elif isinstance(error, HTTPException):
            await interaction.response.send_message(
                "Ocorreu um erro de comunicação com o Discord (Rate Limit ou outro problema HTTP). Por favor, tente novamente.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Ocorreu um erro inesperado ao executar o comando backup_panel: `{error}`",
                ephemeral=True
            )
            print(f"Erro inesperado no comando backup_panel: {error}") # Log para depuração

# Função de setup para o cog
async def setup(bot):
    await bot.add_cog(BackupCommands(bot))