# cogs/events/welcome_leave.py
import discord
from discord.ext import commands
import logging
from database import execute_query # Importe conforme necessário
import json # Para lidar com embeds em formato JSON
from discord import app_commands # Adicionado: Importa app_commands

logger = logging.getLogger(__name__)

class WelcomeLeaveMessages(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Cog de Boas-Vindas/Saída inicializada.")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id: # Garante que estamos em um guild
            settings = execute_query(
                "SELECT welcome_enabled, welcome_channel_id, welcome_message, welcome_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
                (member.guild.id,), fetchone=True
            )

            if settings and settings[0]:  # welcome_enabled é True
                welcome_channel_id = settings[1]
                welcome_message_content = settings[2]
                welcome_embed_json = settings[3]

                channel = member.guild.get_channel(welcome_channel_id)
                if not channel:
                    logger.warning(f"Canal de boas-vindas para guild {member.guild.id} não encontrado: {welcome_channel_id}")
                    return

                try:
                    message_to_send = welcome_message_content.replace("{user}", member.mention).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))
                    
                    if welcome_embed_json:
                        try:
                            embed_data = json.loads(welcome_embed_json)
                            # Substituir placeholders no embed também
                            for key, value in embed_data.items():
                                if isinstance(value, str):
                                    embed_data[key] = value.replace("{user}", member.mention).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))
                                elif isinstance(value, dict):
                                    for sub_key, sub_value in value.items():
                                        if isinstance(sub_value, str):
                                            embed_data[key][sub_key] = sub_value.replace("{user}", member.mention).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))

                            embed = discord.Embed.from_dict(embed_data)
                            await channel.send(content=message_to_send if message_to_send else None, embed=embed)
                        except json.JSONDecodeError:
                            logger.error(f"Erro ao decodificar JSON do embed de boas-vindas para guild {member.guild.id}.")
                            await channel.send(f"{message_to_send}") # Envia apenas a mensagem de texto se o embed falhar
                        except Exception as e:
                            logger.error(f"Erro ao enviar embed de boas-vindas para guild {member.guild.id}: {e}", exc_info=True)
                            await channel.send(f"{message_to_send}") # Envia apenas a mensagem de texto se o embed falhar
                    else:
                        await channel.send(f"{message_to_send}")
                    
                    logger.info(f"Mensagem de boas-vindas enviada para {member.display_name} no guild {member.guild.name}.")
                except discord.Forbidden:
                    logger.warning(f"Não tenho permissão para enviar mensagens no canal {channel.name} ({channel.id}) para o evento on_member_join.")
                except Exception as e:
                    logger.error(f"Erro ao processar on_member_join para {member.id} no guild {member.guild.id}: {e}", exc_info=True)


    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id:
            settings = execute_query(
                "SELECT leave_enabled, leave_channel_id, leave_message, leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
                (member.guild.id,), fetchone=True
            )

            if settings and settings[0]: # leave_enabled é True
                leave_channel_id = settings[1]
                leave_message_content = settings[2]
                leave_embed_json = settings[3]

                channel = member.guild.get_channel(leave_channel_id)
                if not channel:
                    logger.warning(f"Canal de saída para guild {member.guild.id} não encontrado: {leave_channel_id}")
                    return

                try:
                    message_to_send = leave_message_content.replace("{user}", member.display_name).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))
                    
                    if leave_embed_json:
                        try:
                            embed_data = json.loads(leave_embed_json)
                            # Substituir placeholders no embed também
                            for key, value in embed_data.items():
                                if isinstance(value, str):
                                    embed_data[key] = value.replace("{user}", member.display_name).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))
                                elif isinstance(value, dict):
                                    for sub_key, sub_value in value.items():
                                        if isinstance(sub_value, str):
                                            embed_data[key][sub_key] = sub_value.replace("{user}", member.display_name).replace("{guild}", member.guild.name).replace("{member_count}", str(member.guild.member_count))
                            
                            embed = discord.Embed.from_dict(embed_data)
                            await channel.send(content=message_to_send if message_to_send else None, embed=embed)
                        except json.JSONDecodeError:
                            logger.error(f"Erro ao decodificar JSON do embed de saída para guild {member.guild.id}.")
                            await channel.send(f"{message_to_send}")
                        except Exception as e:
                            logger.error(f"Erro ao enviar embed de saída para guild {member.guild.id}: {e}", exc_info=True)
                            await channel.send(f"{message_to_send}")
                    else:
                        await channel.send(f"{message_to_send}")
                    
                    logger.info(f"Mensagem de saída enviada para {member.display_name} no guild {member.guild.name}.")
                except discord.Forbidden:
                    logger.warning(f"Não tenho permissão para enviar mensagens no canal {channel.name} ({channel.id}) para o evento on_member_remove.")
                except Exception as e:
                    logger.error(f"Erro ao processar on_member_remove para {member.id} no guild {member.guild.id}: {e}", exc_info=True)

    @commands.hybrid_group(name="welcome", description="Comandos para gerenciar mensagens de boas-vindas.")
    @commands.has_permissions(manage_guild=True)
    async def welcome_group(self, ctx: commands.Context):
        """Comandos para gerenciar mensagens de boas-vindas."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Comando inválido para boas-vindas. Use `enable`, `disable`, `set_channel`, `set_message`, `set_embed`, ou `show`.")

    @welcome_group.command(name="enable", description="Ativa o sistema de boas-vindas.")
    async def welcome_enable(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_enabled) VALUES (?, ?)", (ctx.guild.id, 1))
        await ctx.send("✅ Sistema de boas-vindas ativado!")
        logger.info(f"Sistema de boas-vindas ativado para guild {ctx.guild.id}.")

    @welcome_group.command(name="disable", description="Desativa o sistema de boas-vindas.")
    async def welcome_disable(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_enabled) VALUES (?, ?)", (ctx.guild.id, 0))
        await ctx.send("✅ Sistema de boas-vindas desativado!")
        logger.info(f"Sistema de boas-vindas desativado para guild {ctx.guild.id}.")

    @welcome_group.command(name="set_channel", description="Define o canal para mensagens de boas-vindas.")
    @app_commands.describe(channel="O canal onde as mensagens de boas-vindas serão enviadas.")
    async def welcome_set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_channel_id) VALUES (?, ?)", (ctx.guild.id, channel.id))
        await ctx.send(f"✅ Canal de boas-vindas definido para {channel.mention}.")
        logger.info(f"Canal de boas-vindas para guild {ctx.guild.id} definido como {channel.id}.")

    @welcome_group.command(name="set_message", description="Define a mensagem de texto de boas-vindas. Use {user}, {guild}, {member_count}.")
    @app_commands.describe(message="A mensagem de boas-vindas.")
    async def welcome_set_message(self, ctx: commands.Context, *, message: str):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_message) VALUES (?, ?)", (ctx.guild.id, message))
        await ctx.send(f"✅ Mensagem de boas-vindas definida.")
        logger.info(f"Mensagem de boas-vindas para guild {ctx.guild.id} atualizada.")

    @welcome_group.command(name="set_embed", description="Define o embed de boas-vindas usando um JSON de um embed salvo.")
    @app_commands.describe(embed_name="O nome do embed salvo a ser usado.")
    async def welcome_set_embed(self, ctx: commands.Context, embed_name: str):
        embed_data = execute_query("SELECT embed_json FROM saved_embeds WHERE guild_id = ? AND embed_name = ?", (ctx.guild.id, embed_name), fetchone=True)
        if not embed_data:
            return await ctx.send("❌ Embed com este nome não encontrado. Use `/embed_creator list` para ver os embeds salvos.")
        
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_embed_json) VALUES (?, ?)", (ctx.guild.id, embed_data[0]))
        await ctx.send(f"✅ Embed de boas-vindas definido para '{embed_name}'.")
        logger.info(f"Embed de boas-vindas para guild {ctx.guild.id} definido como '{embed_name}'.")

    @welcome_group.command(name="clear_embed", description="Limpa o embed de boas-vindas, usando apenas a mensagem de texto.")
    async def welcome_clear_embed(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_embed_json) VALUES (?, ?)", (ctx.guild.id, None))
        await ctx.send("✅ Embed de boas-vindas limpo. Agora apenas a mensagem de texto será usada.")
        logger.info(f"Embed de boas-vindas limpo para guild {ctx.guild.id}.")


    @welcome_group.command(name="show", description="Mostra as configurações atuais de boas-vindas.")
    async def welcome_show(self, ctx: commands.Context):
        settings = execute_query(
            "SELECT welcome_enabled, welcome_channel_id, welcome_message, welcome_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (ctx.guild.id,), fetchone=True
        )
        if not settings:
            return await ctx.send("ℹ️ Nenhuma configuração de boas-vindas encontrada para este servidor.")

        enabled, channel_id, message, embed_json = settings
        channel_name = self.bot.get_channel(channel_id).mention if channel_id else "Não definido"
        embed_status = "Definido" if embed_json else "Não definido (usando apenas texto)"

        embed = discord.Embed(title="Configurações de Boas-Vindas", color=discord.Color.blue())
        embed.add_field(name="Ativado", value="Sim" if enabled else "Não", inline=True)
        embed.add_field(name="Canal", value=channel_name, inline=True)
        embed.add_field(name="Mensagem", value=f"```\n{message or 'Nenhuma mensagem definida.'}\n```", inline=False)
        embed.add_field(name="Embed", value=embed_status, inline=True)

        await ctx.send(embed=embed)


    @commands.hybrid_group(name="leave", description="Comandos para gerenciar mensagens de saída.")
    @commands.has_permissions(manage_guild=True)
    async def leave_group(self, ctx: commands.Context):
        """Comandos para gerenciar mensagens de saída."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Comando inválido para saída. Use `enable`, `disable`, `set_channel`, `set_message`, `set_embed`, ou `show`.")

    @leave_group.command(name="enable", description="Ativa o sistema de saída.")
    async def leave_enable(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_enabled) VALUES (?, ?)", (ctx.guild.id, 1))
        await ctx.send("✅ Sistema de saída ativado!")
        logger.info(f"Sistema de saída ativado para guild {ctx.guild.id}.")

    @leave_group.command(name="disable", description="Desativa o sistema de saída.")
    async def leave_disable(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_enabled) VALUES (?, ?)", (ctx.guild.id, 0))
        await ctx.send("✅ Sistema de saída desativado!")
        logger.info(f"Sistema de saída desativado para guild {ctx.guild.id}.")

    @leave_group.command(name="set_channel", description="Define o canal para mensagens de saída.")
    @app_commands.describe(channel="O canal onde as mensagens de saída serão enviadas.")
    async def leave_set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_channel_id) VALUES (?, ?)", (ctx.guild.id, channel.id))
        await ctx.send(f"✅ Canal de saída definido para {channel.mention}.")
        logger.info(f"Canal de saída para guild {ctx.guild.id} definido como {channel.id}.")

    @leave_group.command(name="set_message", description="Define a mensagem de texto de saída. Use {user}, {guild}, {member_count}.")
    @app_commands.describe(message="A mensagem de saída.")
    async def leave_set_message(self, ctx: commands.Context, *, message: str):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_message) VALUES (?, ?)", (ctx.guild.id, message))
        await ctx.send(f"✅ Mensagem de saída definida.")
        logger.info(f"Mensagem de saída para guild {ctx.guild.id} atualizada.")

    @leave_group.command(name="set_embed", description="Define o embed de saída usando um JSON de um embed salvo.")
    @app_commands.describe(embed_name="O nome do embed salvo a ser usado.")
    async def leave_set_embed(self, ctx: commands.Context, embed_name: str):
        embed_data = execute_query("SELECT embed_json FROM saved_embeds WHERE guild_id = ? AND embed_name = ?", (ctx.guild.id, embed_name), fetchone=True)
        if not embed_data:
            return await ctx.send("❌ Embed com este nome não encontrado. Use `/embed_creator list` para ver os embeds salvos.")
        
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_embed_json) VALUES (?, ?)", (ctx.guild.id, embed_data[0]))
        await ctx.send(f"✅ Embed de saída definido para '{embed_name}'.")
        logger.info(f"Embed de saída para guild {ctx.guild.id} definido como '{embed_name}'.")

    @leave_group.command(name="clear_embed", description="Limpa o embed de saída, usando apenas a mensagem de texto.")
    async def leave_clear_embed(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_embed_json) VALUES (?, ?)", (ctx.guild.id, None))
        await ctx.send("✅ Embed de saída limpo. Agora apenas a mensagem de texto será usada.")
        logger.info(f"Embed de saída limpo para guild {ctx.guild.id}.")

    @leave_group.command(name="show", description="Mostra as configurações atuais de saída.")
    async def leave_show(self, ctx: commands.Context):
        settings = execute_query(
            "SELECT leave_enabled, leave_channel_id, leave_message, leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (ctx.guild.id,), fetchone=True
        )
        if not settings:
            return await ctx.send("ℹ️ Nenhuma configuração de saída encontrada para este servidor.")

        enabled, channel_id, message, embed_json = settings
        channel_name = self.bot.get_channel(channel_id).mention if channel_id else "Não definido"
        embed_status = "Definido" if embed_json else "Não definido (usando apenas texto)"

        embed = discord.Embed(title="Configurações de Saída", color=discord.Color.orange())
        embed.add_field(name="Ativado", value="Sim" if enabled else "Não", inline=True)
        embed.add_field(name="Canal", value=channel_name, inline=True)
        embed.add_field(name="Mensagem", value=f"```\n{message or 'Nenhuma mensagem definida.'}\n```", inline=False)
        embed.add_field(name="Embed", value=embed_status, inline=True)

        await ctx.send(embed=embed)


# Esta função é CRUCIAL para o bot carregar o cog.
async def setup(bot):
    """Adiciona o cog de mensagens de Boas-Vindas/Saída ao bot."""
    await bot.add_cog(WelcomeLeaveMessages(bot))
    logger.info("Cog de Boas-Vindas/Saída configurada e adicionada ao bot.")