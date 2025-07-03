# cogs/utility/ticket_system.py
import discord
from discord.ext import commands
import logging
from discord.ui import Button, View
from discord import ButtonStyle, app_commands, PermissionOverwrite
from database import execute_query
import json # Para lidar com embeds
from typing import Optional # Adicionado: Importa Optional para tipagem

logger = logging.getLogger(__name__)

class TicketPanelButtons(View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Abrir Ticket", style=ButtonStyle.primary, custom_id="ticket_system:open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True) # Defer para evitar timeout

        guild_id = interaction.guild.id
        user_id = interaction.user.id

        # Verifica se o usuário já tem um ticket aberto
        existing_ticket = execute_query(
            "SELECT channel_id FROM active_tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (guild_id, user_id), fetchone=True
        )

        if existing_ticket:
            existing_channel = self.bot.get_channel(existing_ticket[0])
            if existing_channel:
                return await interaction.followup.send(f"Você já tem um ticket aberto: {existing_channel.mention}", ephemeral=True)
            else:
                # O canal não existe mais, remove do DB
                execute_query("DELETE FROM active_tickets WHERE channel_id = ?", (existing_ticket[0],))


        # Obter configurações do ticket para o guild
        settings = execute_query(
            "SELECT category_id, transcript_channel_id, ticket_role_id, ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?",
            (guild_id,), fetchone=True
        )

        if not settings:
            return await interaction.followup.send("❌ O sistema de tickets não está configurado para este servidor.", ephemeral=True)

        category_id, transcript_channel_id, ticket_role_id, initial_embed_json = settings
        category = interaction.guild.get_channel(category_id)
        
        if not category or not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("❌ A categoria de tickets configurada não é válida ou não foi encontrada.", ephemeral=True)

        # Definir permissões para o novo canal de ticket
        overwrites = {
            interaction.guild.default_role: PermissionOverwrite(read_messages=False),
            interaction.user: PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            self.bot.user: PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, manage_channels=True)
        }

        # Adicionar permissão para o cargo de suporte, se configurado
        if ticket_role_id:
            ticket_role = interaction.guild.get_role(ticket_role_id)
            if ticket_role:
                overwrites[ticket_role] = PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
            else:
                logger.warning(f"Cargo de ticket configurado ({ticket_role_id}) não encontrado no guild {guild_id}.")

        try:
            # Criar o canal de ticket
            ticket_channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name.lower().replace(' ', '-')}",
                category=category,
                overwrites=overwrites,
                topic=f"Ticket de {interaction.user.name} (ID: {user_id})"
            )

            # Inserir ticket no DB
            execute_query(
                "INSERT INTO active_tickets (guild_id, user_id, channel_id, status) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, ticket_channel.id, 'open')
            )
            
            # Enviar mensagem inicial no ticket
            ticket_initial_message_content = f"{interaction.user.mention}, seu ticket foi aberto! A equipe de suporte estará com você em breve."
            if ticket_role_id and ticket_role:
                ticket_initial_message_content += f"\n{ticket_role.mention}" # Menciona o cargo de suporte

            if initial_embed_json:
                try:
                    embed_data = json.loads(initial_embed_json)
                    # Substituir placeholders no embed inicial do ticket
                    for key, value in embed_data.items():
                        if isinstance(value, str):
                            embed_data[key] = value.replace("{user}", interaction.user.mention).replace("{guild}", interaction.guild.name)
                        elif isinstance(value, dict):
                            for sub_key, sub_value in value.items():
                                if isinstance(sub_value, str):
                                    embed_data[key][sub_key] = sub_value.replace("{user}", interaction.user.mention).replace("{guild}", interaction.guild.name)
                    
                    ticket_embed = discord.Embed.from_dict(embed_data)
                    await ticket_channel.send(content=ticket_initial_message_content, embed=ticket_embed)
                except json.JSONDecodeError:
                    logger.error(f"Erro ao decodificar JSON do embed inicial do ticket para guild {guild_id}.")
                    await ticket_channel.send(ticket_initial_message_content) # Envia apenas a mensagem se o embed falhar
                except Exception as e:
                    logger.error(f"Erro ao enviar embed inicial do ticket para guild {guild_id}: {e}", exc_info=True)
                    await ticket_channel.send(ticket_initial_message_content) # Envia apenas a mensagem se o embed falhar
            else:
                await ticket_channel.send(ticket_initial_message_content)


            await interaction.followup.send(f"✅ Seu ticket foi aberto em {ticket_channel.mention}", ephemeral=True)
            logger.info(f"Ticket aberto para {interaction.user.id} no canal {ticket_channel.id} do guild {guild_id}.")

        except discord.Forbidden:
            await interaction.followup.send("❌ Não tenho permissão para criar canais ou gerenciar permissões. Verifique minhas permissões.", ephemeral=True)
            logger.error(f"Erro de permissão ao criar ticket para {interaction.user.id} no guild {guild_id}.", exc_info=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocorreu um erro ao abrir o ticket: {e}", ephemeral=True)
            logger.error(f"Erro inesperado ao abrir ticket para {interaction.user.id} no guild {guild_id}: {e}", exc_info=True)

class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        logger.info("Cog de Sistema de Tickets inicializada.")
        self.bot.add_view(TicketPanelButtons(self.bot)) # Adiciona a view persistente

    @commands.hybrid_group(name="ticket", description="Comandos para gerenciar o sistema de tickets.")
    @commands.has_permissions(manage_channels=True)
    async def ticket_group(self, ctx: commands.Context):
        """Comandos para gerenciar o sistema de tickets."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Comando inválido para ticket. Use `setup_panel`, `remove_panel`, `set_category`, `set_transcript_channel`, `set_role`, `set_initial_embed`, `close`, `add_user`, `remove_user`.")

    @ticket_group.command(name="setup_panel", description="Configura o painel de criação de tickets em um canal.")
    @app_commands.describe(
        channel="O canal onde o painel de tickets será enviado.",
        panel_embed_name="O nome do embed salvo para o painel de tickets (opcional)."
    )
    async def setup_panel(self, ctx: commands.Context, channel: discord.TextChannel, panel_embed_name: Optional[str] = None):
        if not ctx.guild:
            return await ctx.send("Este comando só pode ser usado em um servidor.")

        panel_embed = None
        panel_embed_json = None
        if panel_embed_name:
            embed_data = execute_query("SELECT embed_json FROM saved_embeds WHERE guild_id = ? AND embed_name = ?", (ctx.guild.id, panel_embed_name), fetchone=True)
            if not embed_data:
                return await ctx.send("❌ Embed com este nome não encontrado. Use `/embed_creator list` para ver os embeds salvos.")
            
            try:
                panel_embed_json = embed_data[0]
                panel_embed = discord.Embed.from_dict(json.loads(panel_embed_json))
            except json.JSONDecodeError:
                return await ctx.send("❌ O JSON do embed salvo é inválido.")
            except Exception as e:
                logger.error(f"Erro ao carregar embed para painel de ticket: {e}", exc_info=True)
                return await ctx.send(f"❌ Ocorreu um erro ao carregar o embed: {e}")

        if not panel_embed:
            # Embed padrão se nenhum for fornecido
            panel_embed = discord.Embed(
                title="Suporte ao Servidor",
                description="Clique no botão abaixo para abrir um novo ticket de suporte.",
                color=discord.Color.blue()
            )
            panel_embed.set_footer(text="Ao abrir um ticket, um novo canal privado será criado para você.")

        try:
            message = await channel.send(embed=panel_embed, view=TicketPanelButtons(self.bot))
            
            # Salva no banco de dados
            execute_query(
                "INSERT OR REPLACE INTO ticket_settings (guild_id, ticket_channel_id, ticket_message_id, panel_embed_json) VALUES (?, ?, ?, ?)",
                (ctx.guild.id, channel.id, message.id, panel_embed_json)
            )
            await ctx.send(f"✅ Painel de tickets configurado em {channel.mention}.", ephemeral=True)
            logger.info(f"Painel de tickets configurado no guild {ctx.guild.id} no canal {channel.id} (message_id: {message.id}).")
        except discord.Forbidden:
            await ctx.send(f"🚫 Não tenho permissão para enviar mensagens no canal {channel.mention}. Verifique minhas permissões.", ephemeral=True)
            logger.error(f"Erro de permissão ao configurar painel de tickets no guild {ctx.guild.id} canal {channel.id}.")
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao configurar o painel de tickets: {e}", ephemeral=True)
            logger.error(f"Erro ao configurar painel de tickets no guild {ctx.guild.id}: {e}", exc_info=True)

    @ticket_group.command(name="remove_panel", description="Remove o painel de tickets configurado.")
    async def remove_panel(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send("Este comando só pode ser usado em um servidor.")

        settings = execute_query("SELECT ticket_channel_id, ticket_message_id FROM ticket_settings WHERE guild_id = ?", 
                                 (ctx.guild.id,), fetchone=True)

        if not settings or not settings[0] or not settings[1]:
            return await ctx.send("⚠️ Nenhum painel de tickets configurado para este servidor.", ephemeral=True)

        channel_id, message_id = settings
        channel = self.bot.get_channel(channel_id)

        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
                await ctx.send(f"✅ Painel de tickets removido de {channel.mention}.", ephemeral=True)
            except discord.NotFound:
                await ctx.send("⚠️ Mensagem do painel de tickets não encontrada. Removendo apenas do banco de dados.", ephemeral=True)
            except discord.Forbidden:
                await ctx.send(f"🚫 Não tenho permissão para apagar mensagens no canal {channel.mention}. Removendo apenas do banco de dados.", ephemeral=True)
                logger.warning(f"Não foi possível apagar mensagem do painel de tickets em {channel.id} para guild {ctx.guild.id}. Permissões insuficientes.")
            except Exception as e:
                await ctx.send(f"❌ Ocorreu um erro ao tentar apagar a mensagem: {e}", ephemeral=True)
                logger.error(f"Erro ao apagar mensagem do painel de tickets: {e}", exc_info=True)
        
        # Limpa as configurações do painel no DB (outras configs de ticket permanecem)
        execute_query(
            "UPDATE ticket_settings SET ticket_channel_id = NULL, ticket_message_id = NULL, panel_embed_json = NULL WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        logger.info(f"Painel de tickets removido do DB para guild {ctx.guild.id}.")
        
        if not channel:
            await ctx.send("✅ Configuração do painel de tickets removida do banco de dados (o canal original pode não existir mais).", ephemeral=True)


    @ticket_group.command(name="set_category", description="Define a categoria para novos canais de ticket.")
    @app_commands.describe(category="A categoria onde os tickets serão criados.")
    async def set_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        execute_query("INSERT OR REPLACE INTO ticket_settings (guild_id, category_id) VALUES (?, ?)", (ctx.guild.id, category.id))
        await ctx.send(f"✅ Categoria para tickets definida para: {category.mention}")
        logger.info(f"Categoria de tickets para guild {ctx.guild.id} definida como {category.id}.")

    @ticket_group.command(name="set_transcript_channel", description="Define o canal para transcrições de tickets fechados.")
    @app_commands.describe(channel="O canal onde as transcrições serão enviadas.")
    async def set_transcript_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        execute_query("INSERT OR REPLACE INTO ticket_settings (guild_id, transcript_channel_id) VALUES (?, ?)", (ctx.guild.id, channel.id))
        await ctx.send(f"✅ Canal de transcrições definido para: {channel.mention}")
        logger.info(f"Canal de transcrições para guild {ctx.guild.id} definido como {channel.id}.")

    @ticket_group.command(name="set_role", description="Define o cargo que terá acesso aos tickets.")
    @app_commands.describe(role="O cargo que será notificado e terá acesso aos tickets.")
    async def set_role(self, ctx: commands.Context, role: discord.Role):
        execute_query("INSERT OR REPLACE INTO ticket_settings (guild_id, ticket_role_id) VALUES (?, ?)", (ctx.guild.id, role.id))
        await ctx.send(f"✅ Cargo de suporte de tickets definido para: {role.mention}")
        logger.info(f"Cargo de suporte de tickets para guild {ctx.guild.id} definido como {role.id}.")

    @ticket_group.command(name="set_initial_embed", description="Define o embed da mensagem inicial dentro de um ticket.")
    @app_commands.describe(embed_name="O nome do embed salvo a ser usado.")
    async def set_initial_embed(self, ctx: commands.Context, embed_name: str):
        embed_data = execute_query("SELECT embed_json FROM saved_embeds WHERE guild_id = ? AND embed_name = ?", (ctx.guild.id, embed_name), fetchone=True)
        if not embed_data:
            return await ctx.send("❌ Embed com este nome não encontrado. Use `/embed_creator list` para ver os embeds salvos.")
        
        execute_query("INSERT OR REPLACE INTO ticket_settings (guild_id, ticket_initial_embed_json) VALUES (?, ?)", (ctx.guild.id, embed_data[0]))
        await ctx.send(f"✅ Embed inicial do ticket definido para '{embed_name}'.")
        logger.info(f"Embed inicial do ticket para guild {ctx.guild.id} definido como '{embed_name}'.")
    
    @ticket_group.command(name="clear_initial_embed", description="Limpa o embed inicial do ticket, usando apenas a mensagem de texto padrão.")
    async def clear_initial_embed(self, ctx: commands.Context):
        execute_query("INSERT OR REPLACE INTO ticket_settings (guild_id, ticket_initial_embed_json) VALUES (?, ?)", (ctx.guild.id, None))
        await ctx.send("✅ Embed inicial do ticket limpo. Apenas a mensagem de texto padrão será usada.")
        logger.info(f"Embed inicial do ticket limpo para guild {ctx.guild.id}.")


    @ticket_group.command(name="show", description="Mostra as configurações atuais do sistema de tickets.")
    async def show_ticket_settings(self, ctx: commands.Context):
        settings = execute_query(
            "SELECT category_id, transcript_channel_id, ticket_role_id, ticket_channel_id, ticket_message_id, panel_embed_json, ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?",
            (ctx.guild.id,), fetchone=True
        )
        if not settings:
            return await ctx.send("ℹ️ Nenhuma configuração de ticket encontrada para este servidor.")

        category_id, transcript_channel_id, ticket_role_id, panel_channel_id, panel_message_id, panel_embed_json, initial_embed_json = settings

        category_name = self.bot.get_channel(category_id).mention if category_id else "Não definido"
        transcript_channel_name = self.bot.get_channel(transcript_channel_id).mention if transcript_channel_id else "Não definido"
        ticket_role_name = ctx.guild.get_role(ticket_role_id).mention if ticket_role_id else "Não definido"
        panel_location = f"{self.bot.get_channel(panel_channel_id).mention} (Mensagem ID: {panel_message_id})" if panel_channel_id and panel_message_id else "Não definido"
        panel_embed_status = "Definido" if panel_embed_json else "Padrão"
        initial_embed_status = "Definido" if initial_embed_json else "Padrão"

        embed = discord.Embed(title="Configurações do Sistema de Tickets", color=discord.Color.gold())
        embed.add_field(name="Categoria de Tickets", value=category_name, inline=True)
        embed.add_field(name="Canal de Transcrições", value=transcript_channel_name, inline=True)
        embed.add_field(name="Cargo de Suporte", value=ticket_role_name, inline=True)
        embed.add_field(name="Local do Painel", value=panel_location, inline=False)
        embed.add_field(name="Embed do Painel", value=panel_embed_status, inline=True)
        embed.add_field(name="Embed Inicial do Ticket", value=initial_embed_status, inline=True)

        await ctx.send(embed=embed)


    @commands.hybrid_command(name="close_ticket", description="Fecha o ticket atual.")
    @commands.has_permissions(manage_channels=True)
    async def close_ticket(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send("Este comando só pode ser usado em um servidor.")

        ticket_info = execute_query(
            "SELECT ticket_id, user_id FROM active_tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,), fetchone=True
        )

        if not ticket_info:
            return await ctx.send("⚠️ Este canal não é um ticket ativo ou já foi fechado.", ephemeral=True)

        ticket_id, user_id = ticket_info
        
        # Opcional: Gerar transcrição antes de deletar
        transcript_channel_id = execute_query("SELECT transcript_channel_id FROM ticket_settings WHERE guild_id = ?", (ctx.guild.id,), fetchone=True)
        if transcript_channel_id and transcript_channel_id[0]:
            transcript_channel = self.bot.get_channel(transcript_channel_id[0])
            if transcript_channel:
                try:
                    # Implementar lógica de transcrição aqui. Ex:
                    # messages = [msg async for msg in ctx.channel.history(limit=None, oldest_first=True)]
                    # transcript_content = "\n".join([f"[{msg.created_at}] {msg.author.display_name}: {msg.clean_content}" for msg in messages])
                    # await transcript_channel.send(f"Transcrição do Ticket #{ticket_id} ({self.bot.get_user(user_id).name}):\n```\n{transcript_content}\n```")
                    await ctx.send("Gerando transcrição... (Funcionalidade de transcrição a ser implementada)")
                    logger.info(f"Transcrição para ticket {ticket_id} do usuário {user_id} gerada e enviada para {transcript_channel.id}.")
                except Exception as e:
                    logger.error(f"Erro ao gerar ou enviar transcrição para ticket {ticket_id}: {e}", exc_info=True)
                    await ctx.send("❌ Não foi possível gerar ou enviar a transcrição, mas o ticket será fechado.", ephemeral=True)
            else:
                logger.warning(f"Canal de transcrição configurado ({transcript_channel_id[0]}) não encontrado no guild {ctx.guild.id}.")

        try:
            # Atualiza o status no DB
            execute_query(
                "UPDATE active_tickets SET status = 'closed', closed_by_id = ?, closed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (ctx.author.id, ticket_id)
            )
            await ctx.channel.delete(reason=f"Ticket fechado por {ctx.author.display_name}")
            logger.info(f"Ticket {ticket_id} (canal {ctx.channel.id}) fechado por {ctx.author.id} no guild {ctx.guild.id}.")
        except discord.Forbidden:
            await ctx.send("🚫 Não tenho permissão para deletar este canal de ticket. Verifique minhas permissões.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao fechar o ticket: {e}", ephemeral=True)
            logger.error(f"Erro ao fechar ticket {ticket_id} (canal {ctx.channel.id}): {e}", exc_info=True)

    @commands.hybrid_command(name="add_user_to_ticket", description="Adiciona um usuário ao ticket atual.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(user="O usuário a ser adicionado ao ticket.")
    async def add_user_to_ticket(self, ctx: commands.Context, user: discord.Member):
        ticket_info = execute_query(
            "SELECT channel_id FROM active_tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,), fetchone=True
        )
        if not ticket_info:
            return await ctx.send("⚠️ Este canal não é um ticket ativo.", ephemeral=True)
        
        try:
            await ctx.channel.set_permissions(user, read_messages=True, send_messages=True, attach_files=True)
            await ctx.send(f"✅ {user.mention} foi adicionado ao ticket.")
            logger.info(f"Usuário {user.id} adicionado ao ticket {ctx.channel.id} por {ctx.author.id}.")
        except discord.Forbidden:
            await ctx.send("🚫 Não tenho permissão para gerenciar permissões neste canal.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao adicionar o usuário: {e}", ephemeral=True)
            logger.error(f"Erro ao adicionar usuário {user.id} ao ticket {ctx.channel.id}: {e}", exc_info=True)

    @commands.hybrid_command(name="remove_user_from_ticket", description="Remove um usuário do ticket atual.")
    @commands.has_permissions(manage_channels=True)
    @app_commands.describe(user="O usuário a ser removido do ticket.")
    async def remove_user_from_ticket(self, ctx: commands.Context, user: discord.Member):
        ticket_info = execute_query(
            "SELECT channel_id FROM active_tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,), fetchone=True
        )
        if not ticket_info:
            return await ctx.send("⚠️ Este canal não é um ticket ativo.", ephemeral=True)
        
        # Evitar remover o criador original do ticket (se o user_id for o mesmo)
        original_creator_id = execute_query("SELECT user_id FROM active_tickets WHERE channel_id = ?", (ctx.channel.id,), fetchone=True)
        if original_creator_id and original_creator_id[0] == user.id:
            return await ctx.send("❌ Você não pode remover o criador original do ticket.", ephemeral=True)

        try:
            await ctx.channel.set_permissions(user, overwrite=None) # Remove todas as sobrescritas específicas
            await ctx.send(f"✅ {user.mention} foi removido do ticket.")
            logger.info(f"Usuário {user.id} removido do ticket {ctx.channel.id} por {ctx.author.id}.")
        except discord.Forbidden:
            await ctx.send("🚫 Não tenho permissão para gerenciar permissões neste canal.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Ocorreu um erro ao remover o usuário: {e}", ephemeral=True)
            logger.error(f"Erro ao remover usuário {user.id} do ticket {ctx.channel.id}: {e}", exc_info=True)


    @commands.Cog.listener()
    async def on_ready(self):
        # Garante que as views persistentes são adicionadas ao bot ao iniciar
        self.bot.add_view(TicketPanelButtons(self.bot))
        logger.info("Views persistentes do Sistema de Tickets garantidas.")

# Esta função é CRUCIAL para o bot carregar o cog.
async def setup(bot):
    """Adiciona o cog do Sistema de Tickets ao bot."""
    await bot.add_cog(TicketSystem(bot))
    logger.info("Cog do Sistema de Tickets configurada e adicionada ao bot.")