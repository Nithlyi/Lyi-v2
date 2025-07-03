# cogs/moderation/moderation_commands.py
import discord
from discord.ext import commands
import logging

# Certifique-se de que cada cog tenha seu próprio logger ou use o logger global
logger = logging.getLogger(__name__)

class ModerationCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Cog de Moderação inicializada.")

    # Exemplo de comando de moderação (se já não tiver um)
    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "Nenhuma razão fornecida."):
        """Kicka um membro do servidor."""
        if member.id == ctx.author.id:
            return await ctx.send("Você não pode se kickar!")
        if member.id == self.bot.user.id:
            return await ctx.send("Eu não posso me kickar!")
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send("Você não pode kickar um membro com cargo igual ou superior ao seu.")

        try:
            await member.kick(reason=reason)
            await ctx.send(f"✅ {member.display_name} foi kickado por: {reason}")
            logger.info(f"Membro {member.id} kickado por {ctx.author.id} no guild {ctx.guild.id}. Razão: {reason}")
            # Você pode adicionar uma chamada aqui para o seu sistema de logs de moderação no DB
            # from database import execute_query
            # execute_query("INSERT INTO moderation_logs (...)")
        except discord.Forbidden:
            await ctx.send("🚫 Não tenho permissão para kickar este membro. Verifique minhas permissões.")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao tentar kickar o membro: {e}")
            logger.error(f"Erro ao kickar {member.id}: {e}", exc_info=True)

    # Adicione outros comandos de moderação aqui...

# Esta função é CRUCIAL para o bot carregar o cog.
async def setup(bot):
    """Adiciona o cog de comandos de moderação ao bot."""
    await bot.add_cog(ModerationCommands(bot))
    logger.info("Cog de Moderação configurada e adicionada ao bot.")