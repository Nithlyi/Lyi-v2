import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import logging

# Sua configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mantido caso precise para logs ou futuras extensões (se database.py existir)
# from database import execute_query 

class AvatarDownloadView(ui.View):
    def __init__(self, avatar_url: str):
        super().__init__(timeout=600) # Timeout de 10 minutos (600 segundos)
        self.avatar_url = avatar_url
        # O botão é adicionado aqui para que possamos referenciá-lo facilmente no timeout
        self.download_button = ui.Button(label="Baixar Avatar", style=discord.ButtonStyle.link, url=avatar_url, emoji="💾")
        self.add_item(self.download_button)
        self.message = None # Para armazenar a mensagem após o envio

    async def on_timeout(self):
        # Desabilita o botão e atualiza a mensagem para indicar o timeout
        if self.message:
            self.download_button.disabled = True
            self.download_button.label = "Link Expirado" # Muda o texto do botão
            # Remove o emoji, se desejar, ou mantenha
            # self.download_button.emoji = None 
            await self.message.edit(view=self)
            logging.info(f"Botão de avatar para {self.avatar_url} expirou.")

class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="avatar", description="Exibe o avatar de um usuário e oferece a opção de download.")
    @app_commands.describe(member="O membro cujo avatar você deseja ver (opcional, padrão: você).")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        # A resposta efêmera inicial pode ser deferida para não mostrar "O bot está pensando..."
        await interaction.response.defer(ephemeral=False) # Mudado para False para que a mensagem e o botão sejam públicos

        target_member = member or interaction.user # Se nenhum membro for especificado, usa o autor

        # Pega a URL do avatar. Usa um avatar padrão do Discord se não houver um.
        avatar_url = target_member.display_avatar.url if target_member.display_avatar else target_member.default_avatar.url

        embed = discord.Embed(
            title=f"Avatar de {target_member.display_name}",
            color=discord.Color.blue()
        )
        embed.set_image(url=avatar_url) # Define o avatar como a imagem principal do embed
        embed.set_footer(text=f"ID do Usuário: {target_member.id}")

        # Cria a view com o botão de download
        view = AvatarDownloadView(avatar_url)

        # Envia a mensagem com o embed e a view (botão)
        # É importante armazenar a mensagem retornada pelo followup.send
        sent_message = await interaction.followup.send(embed=embed, view=view, ephemeral=False)
        view.message = sent_message # Armazena a mensagem na view para o timeout

        logging.info(f"Comando /avatar usado por {interaction.user.id} para {target_member.id} na guild {interaction.guild.id}.")


    @app_commands.command(name="serverinfo", description="Exibe informações detalhadas sobre o servidor.")
    async def serverinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False) # Pode ser público, não há problema

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("Este comando só pode ser usado em um servidor.", ephemeral=True)
            return

        # Contagem de membros
        total_members = guild.member_count
        human_members = len([m for m in guild.members if not m.bot])
        bot_members = len([m for m in guild.members if m.bot])

        # Contagem de canais
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        total_channels = text_channels + voice_channels + categories

        # Data de criação do servidor
        created_at_unix = int(guild.created_at.timestamp())

        embed = discord.Embed(
            title=f"Informações do Servidor: {guild.name}",
            color=discord.Color.green()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.add_field(name="ID do Servidor", value=guild.id, inline=True)
        embed.add_field(name="Proprietário", value=guild.owner.mention if guild.owner else "Desconhecido", inline=True)
        embed.add_field(name="Criado em", value=f"<t:{created_at_unix}:F>", inline=False)
        
        embed.add_field(name="Membros", value=(
            f"Total: **{total_members}**\n"
            f"Humanos: **{human_members}**\n"
            f"Bots: **{bot_members}**"
        ), inline=True)
        
        embed.add_field(name="Canais", value=(
            f"Total: **{total_channels}**\n"
            f"Texto: **{text_channels}**\n"
            f"Voz: **{voice_channels}**\n"
            f"Categorias: **{categories}**"
        ), inline=True)

        embed.add_field(name="Cargos", value=f"**{len(guild.roles)}**", inline=True)
        # Melhorando a legibilidade do nível de boost
        boost_tier = f"Nível {guild.premium_tier} ({guild.premium_subscription_count} boosts)" if guild.premium_subscription_count else "Nenhum boost"
        embed.add_field(name="Nível de Boost", value=boost_tier, inline=True)
        
        # Mapeamento para nomes de verificação mais amigáveis
        verification_levels = {
            discord.VerificationLevel.none: "Nenhum",
            discord.VerificationLevel.low: "Baixo (Email verificado)",
            discord.VerificationLevel.medium: "Médio (Registrado há >5 mins)",
            discord.VerificationLevel.high: "Alto (No servidor há >10 mins)",
            discord.VerificationLevel.highest: "Mais Alto (Telefone verificado)"
        }
        embed.add_field(name="Nível de Verificação", value=verification_levels.get(guild.verification_level, "Desconhecido"), inline=True)
        
        # Mapeamento para nomes de notificação mais amigáveis
        notification_levels = {
            discord.NotificationLevel.all_messages: "Todas as Mensagens",
            discord.NotificationLevel.only_mentions: "Somente Menções"
        }
        embed.add_field(name="Notificações Padrão", value=notification_levels.get(guild.default_notifications, "Desconhecido"), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=False)
        logging.info(f"Comando /serverinfo usado por {interaction.user.id} na guild {interaction.guild.id}.")


    @app_commands.command(name="userinfo", description="Exibe informações detalhadas sobre um usuário.")
    @app_commands.describe(member="O membro cujas informações você deseja ver (opcional, padrão: você).")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer(ephemeral=False) # Pode ser público, não há problema

        target_member = member or interaction.user # Se nenhum membro for especificado, usa o autor

        # Data de criação da conta
        account_created_unix = int(target_member.created_at.timestamp())
        
        # Data de entrada no servidor (se for um membro)
        joined_at_unix = None
        if isinstance(target_member, discord.Member) and target_member.joined_at:
            joined_at_unix = int(target_member.joined_at.timestamp())

        embed = discord.Embed(
            title=f"Informações de {target_member.display_name}",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=target_member.display_avatar.url)

        embed.add_field(name="Nome de Usuário", value=f"@{target_member.name}", inline=True) # Adiciona @ para melhor visualização
        embed.add_field(name="ID do Usuário", value=target_member.id, inline=True)
        embed.add_field(name="Bot?", value="Sim" if target_member.bot else "Não", inline=True)
        
        embed.add_field(name="Conta Criada em", value=f"<t:{account_created_unix}:F>", inline=False)
        if joined_at_unix:
            embed.add_field(name="Entrou no Servidor em", value=f"<t:{joined_at_unix}:F>", inline=False)
        
        if isinstance(target_member, discord.Member):
            # Cargos (excluindo @everyone e ordenando por posição)
            # Verifica se há outros cargos além de @everyone
            roles_excluding_everyone = [role for role in target_member.roles if role.name != "@everyone"]
            if roles_excluding_everyone:
                roles = sorted(roles_excluding_everyone, key=lambda r: r.position, reverse=True)
                embed.add_field(name="Cargos", value=", ".join([role.mention for role in roles]), inline=False)
            else:
                embed.add_field(name="Cargos", value="Nenhum cargo especial (apenas @everyone)", inline=False) # Mais específico

            # Cargo mais alto (excluindo @everyone)
            top_role = target_member.top_role
            if top_role and top_role.name != "@everyone":
                embed.add_field(name="Cargo Mais Alto", value=top_role.mention, inline=True)
            else:
                embed.add_field(name="Cargo Mais Alto", value="Nenhum (apenas @everyone)", inline=True)

            # Status de Boost
            if target_member.premium_since:
                embed.add_field(name="Impulsionando o Servidor", value=f"Desde <t:{int(target_member.premium_since.timestamp())}:D>", inline=True)
            else:
                embed.add_field(name="Impulsionando o Servidor", value="Não", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=False)
        logging.info(f"Comando /userinfo usado por {interaction.user.id} para {target_member.id} na guild {interaction.guild.id}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCommands(bot))