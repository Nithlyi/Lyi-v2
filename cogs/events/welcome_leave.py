import discord
from discord.ext import commands
from discord import app_commands, ui
import logging
import json

from database import execute_query

# --- Funções Auxiliares para Embeds ---
def _create_embed_from_data(embed_data: dict, member: discord.Member = None, guild: discord.Guild = None):
    """Cria um discord.Embed a partir de um dicionário de dados, formatando variáveis."""
    embed = discord.Embed()
    
    # Título (opcional)
    if embed_data.get('title'):
        embed.title = embed_data['title'].format(
            member=member,
            guild=guild,
            member_name=member.display_name,
            member_count=guild.member_count if guild else 'N/A'
        )
    else:
        embed.title = "" # Garante que é uma string vazia

    # Descrição (opcional)
    if embed_data.get('description'):
        embed.description = embed_data['description'].format(
            member=member,
            guild=guild,
            member_name=member.display_name,
            member_count=guild.member_count if guild else 'N/A'
        )
    else:
        embed.description = "" # Garante que é uma string vazia
    
    # Cor (opcional)
    if embed_data.get('color') is not None:
        try:
            color_value = embed_data['color']
            if isinstance(color_value, str):
                color_str = color_value.strip()
                if color_str.startswith('#'):
                    embed.color = discord.Color(int(color_str[1:], 16))
                elif color_str.startswith('0x'):
                    embed.color = discord.Color(int(color_str, 16))
                else:
                    embed.color = discord.Color(int(color_str))
            elif isinstance(color_value, int):
                embed.color = discord.Color(color_value)
        except (ValueError, TypeError):
            logging.warning(f"Cor inválida no embed: {embed_data.get('color')}. Usando cor padrão.")
            embed.color = discord.Color.default()
    else:
        embed.color = discord.Color.default()

    # Imagem (opcional)
    if embed_data.get('image_url'):
        embed.set_image(url=embed_data['image_url'])
    
    # Rodapé (opcional)
    if embed_data.get('footer_text'):
        embed.set_footer(text=embed_data['footer_text'].format(
            member=member,
            guild=guild,
            member_name=member.display_name,
            member_count=guild.member_count if guild else 'N/A'
        ), icon_url=embed_data.get('footer_icon_url'))

    # Autor (opcional)
    if embed_data.get('author_name'):
        embed.set_author(name=embed_data['author_name'].format(
            member=member,
            guild=guild,
            member_name=member.display_name,
            member_count=guild.member_count if guild else 'N/A'
        ), icon_url=embed_data.get('author_icon_url'))
    
    # Campos (opcional) - Embora não configuráveis aqui, é bom ter para consistência
    if 'fields' in embed_data:
        for field in embed_data['fields']:
            field_name = str(field.get('name', ''))
            field_value = str(field.get('value', ''))
            embed.add_field(name=field_name, value=field_value, inline=field.get('inline', False))

    return embed

# --- Views de Configuração Específicas (Boas-Vindas e Saídas) ---

class WelcomeConfigView(ui.View):
    def __init__(self, parent_view: ui.View, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=180)
        self.parent_view = parent_view # A WelcomeSettingsView
        self.bot = bot
        self.guild_id = guild_id
        self.message = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração de Boas-Vindas expirada.", view=self)

    async def _update_welcome_display(self, interaction: discord.Interaction):
        settings = execute_query(
            "SELECT welcome_enabled, welcome_channel_id, welcome_message, welcome_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (self.guild_id,),
            fetchone=True
        )

        embed = discord.Embed(
            title="Configurações de Boas-Vindas",
            description="Ajuste as mensagens e o embed para novos membros.\n\n**Variáveis:** `{member}`, `{member.name}`, `{guild.name}`, `{member.count}`",
            color=discord.Color.blue()
        )

        if settings:
            welcome_enabled, wc_id, wm, welcome_embed_json = settings
            
            welcome_status = "🟢 Ativado" if welcome_enabled else "🔴 Desativado"
            welcome_channel = self.bot.get_channel(wc_id) if wc_id else "Nenhum"
            welcome_message_preview = (wm[:50] + "..." if wm and len(wm) > 50 else wm) if wm else "Nenhuma"
            welcome_embed_configured = "Sim" if welcome_embed_json else "Não"
            
            embed.add_field(name="Status Geral", value=welcome_status, inline=False)
            embed.add_field(name="Canal", value=getattr(welcome_channel, 'mention', welcome_channel), inline=False)
            embed.add_field(name="Mensagem de Texto", value=f"`{welcome_message_preview}`", inline=False)
            embed.add_field(name="Embed Configurado", value=welcome_embed_configured, inline=False)

            # Pré-visualização do embed de boas-vindas (se configurado)
            preview_embed = None # Initialize preview_embed
            if welcome_embed_json:
                try:
                    embed_data = json.loads(welcome_embed_json)
                    preview_embed = _create_embed_from_data(embed_data, member=interaction.user, guild=interaction.guild) # Usar interaction.user/guild para preview
                    embed.add_field(name="Pré-visualização do Embed", value="Veja abaixo:", inline=False)
                except json.JSONDecodeError:
                    logging.error(f"Erro ao decodificar JSON do welcome embed para guild {self.guild_id} na preview.")
                    preview_embed = None
            else:
                preview_embed = None
        else:
            embed.add_field(name="Status", value="🔴 Desativado (Padrões)", inline=False)
            embed.set_footer(text="Nenhuma configuração salva. Use os botões para configurar.")
            preview_embed = None # Initialize preview_embed for this path too
        
        embeds_to_send = [embed]
        if preview_embed:
            embeds_to_send.append(preview_embed)

        if self.message:
            await self.message.edit(embeds=embeds_to_send, view=self)
        else:
            if interaction.response.is_done():
                self.message = await interaction.followup.send(embeds=embeds_to_send, view=self, ephemeral=True)
            else:
                await interaction.response.send_message(embeds=embeds_to_send, view=self, ephemeral=True)
                self.message = await interaction.original_response()

    # Helpers para carregar/salvar embed JSON
    def _get_welcome_embed_data(self):
        settings = execute_query("SELECT welcome_embed_json FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        if settings and settings[0]:
            try:
                return json.loads(settings[0])
            except json.JSONDecodeError:
                logging.error(f"Erro ao decodificar JSON do welcome embed para guild {self.guild_id}. Retornando vazio.")
                return {}
        return {}

    def _save_welcome_embed_data(self, embed_data: dict):
        embed_json = json.dumps(embed_data)
        execute_query(
            "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_embed_json) VALUES (?, ?)",
            (self.guild_id, embed_json)
        )

    @ui.button(label="Alternar Status", style=discord.ButtonStyle.primary, row=0)
    async def toggle_welcome_status(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        current_status = execute_query("SELECT welcome_enabled FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        new_status = not current_status[0] if current_status and current_status[0] is not None else True # Handle None or 0
        
        execute_query(
            "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_enabled) VALUES (?, ?)",
            (self.guild_id, new_status)
        )
        await self._update_welcome_display(interaction)
        await interaction.followup.send(f"Mensagens de Boas-Vindas {('ativadas' if new_status else 'desativadas')}!", ephemeral=True)

    @ui.button(label="Definir Canal", style=discord.ButtonStyle.secondary, row=0)
    async def set_welcome_channel(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeChannelModal(ui.Modal, title="Definir Canal de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_channel_id: int):
                super().__init__()
                self.parent_view = parent_view
                default_value = str(current_channel_id) if current_channel_id else ""
                self.add_item(ui.TextInput(label="ID do Canal", placeholder="Ex: 123456789012345678", style=discord.TextStyle.short, custom_id="channel_id", default=default_value))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                try:
                    channel_id = int(self.children[0].value)
                    channel = original_view.bot.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        await interaction.followup.send("ID de canal inválido ou não é um canal de texto.", ephemeral=True)
                        return

                    execute_query(
                        "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_channel_id) VALUES (?, ?)",
                        (original_view.guild_id, channel_id)
                    )
                    await original_view._update_welcome_display(interaction)
                    await interaction.followup.send(f"Canal de Boas-Vindas definido para {channel.mention}.", ephemeral=True)
                except ValueError:
                    await interaction.followup.send("ID de canal inválido. Por favor, insira um número.", ephemeral=True)
        
        current_settings = execute_query("SELECT welcome_channel_id FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        current_channel_id = current_settings[0] if current_settings else None
        await interaction.response.send_modal(WelcomeChannelModal(parent_view=self, current_channel_id=current_channel_id))

    @ui.button(label="Definir Mensagem de Texto", style=discord.ButtonStyle.secondary, row=0)
    async def set_welcome_message(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeMessageModal(ui.Modal, title="Definir Mensagem de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_message: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Mensagem", placeholder="Use {member}, {guild.name}, {member.count}", style=discord.TextStyle.paragraph, custom_id="welcome_message", default=current_message, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                message_content = self.children[0].value if self.children[0].value.strip() else None

                execute_query(
                    "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, welcome_message) VALUES (?, ?)",
                    (original_view.guild_id, message_content)
                )
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Mensagem de Boas-Vindas atualizada!", ephemeral=True)
        
        current_settings = execute_query("SELECT welcome_message FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        current_message = current_settings[0] if current_settings and current_settings[0] else ""
        await interaction.response.send_modal(WelcomeMessageModal(parent_view=self, current_message=current_message))

    @ui.button(label="Título do Embed", style=discord.ButtonStyle.green, row=1)
    async def set_welcome_embed_title(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeEmbedTitleModal(ui.Modal, title="Título do Embed de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_title: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Título", placeholder="Título do embed (use variáveis)", style=discord.TextStyle.short, custom_id="embed_title", default=current_title, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_welcome_embed_data()
                embed_data['title'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_welcome_embed_data(embed_data)
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Título do Embed de Boas-Vindas atualizado!", ephemeral=True)
        
        embed_data = self._get_welcome_embed_data()
        current_title = embed_data.get('title', '') or ''
        await interaction.response.send_modal(WelcomeEmbedTitleModal(parent_view=self, current_title=current_title))

    @ui.button(label="Descrição do Embed", style=discord.ButtonStyle.green, row=1)
    async def set_welcome_embed_description(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeEmbedDescriptionModal(ui.Modal, title="Descrição do Embed de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_description: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Descrição", placeholder="Descrição do embed (use variáveis)", style=discord.TextStyle.paragraph, custom_id="embed_description", default=current_description, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_welcome_embed_data()
                embed_data['description'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_welcome_embed_data(embed_data)
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Descrição do Embed de Boas-Vindas atualizada!", ephemeral=True)
        
        embed_data = self._get_welcome_embed_data()
        current_description = embed_data.get('description', '') or ''
        await interaction.response.send_modal(WelcomeEmbedDescriptionModal(parent_view=self, current_description=current_description))

    @ui.button(label="Cor do Embed", style=discord.ButtonStyle.green, row=1)
    async def set_welcome_embed_color(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeEmbedColorModal(ui.Modal, title="Cor do Embed de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_color: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Cor (Hex ou Decimal)", placeholder="#RRGGBB ou 0xRRGGBB ou número", style=discord.TextStyle.short, custom_id="embed_color", default=current_color, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_welcome_embed_data()
                color_value = self.children[0].value.strip()
                embed_data['color'] = color_value if color_value else None
                original_view._save_welcome_embed_data(embed_data)
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Cor do Embed de Boas-Vindas atualizada!", ephemeral=True)
        
        embed_data = self._get_welcome_embed_data()
        current_color = embed_data.get('color', '') or ''
        await interaction.response.send_modal(WelcomeEmbedColorModal(parent_view=self, current_color=current_color))

    @ui.button(label="Imagem do Embed", style=discord.ButtonStyle.green, row=2)
    async def set_welcome_embed_image(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeEmbedImageModal(ui.Modal, title="Imagem do Embed de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_image_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="URL da Imagem", placeholder="URL da imagem (opcional)", style=discord.TextStyle.short, custom_id="embed_image", default=current_image_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_welcome_embed_data()
                image_url = self.children[0].value.strip()
                embed_data['image_url'] = image_url if image_url else None
                original_view._save_welcome_embed_data(embed_data)
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Imagem do Embed de Boas-Vindas atualizada!", ephemeral=True)
        
        embed_data = self._get_welcome_embed_data()
        current_image_url = embed_data.get('image_url', '') or ''
        await interaction.response.send_modal(WelcomeEmbedImageModal(parent_view=self, current_image_url=current_image_url))

    @ui.button(label="Rodapé do Embed", style=discord.ButtonStyle.green, row=2)
    async def set_welcome_embed_footer(self, interaction: discord.Interaction, button: ui.Button):
        class WelcomeEmbedFooterModal(ui.Modal, title="Rodapé do Embed de Boas-Vindas"):
            def __init__(self, parent_view: ui.View, current_footer_text: str, current_footer_icon_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Texto do Rodapé", placeholder="Texto do rodapé (opcional)", style=discord.TextStyle.short, custom_id="footer_text", default=current_footer_text, required=False))
                self.add_item(ui.TextInput(label="URL do Ícone do Rodapé (Opcional)", placeholder="URL da imagem do ícone", style=discord.TextStyle.short, custom_id="footer_icon_url", default=current_footer_icon_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_welcome_embed_data()
                footer_text = self.children[0].value.strip()
                footer_icon_url = self.children[1].value.strip()
                embed_data['footer_text'] = footer_text if footer_text else None
                embed_data['footer_icon_url'] = footer_icon_url if footer_icon_url else None
                original_view._save_welcome_embed_data(embed_data)
                await original_view._update_welcome_display(interaction)
                await interaction.followup.send("Rodapé do Embed de Boas-Vindas atualizado!", ephemeral=True)
        
        embed_data = self._get_welcome_embed_data()
        current_footer_text = embed_data.get('footer_text', '') or ''
        current_footer_icon_url = embed_data.get('footer_icon_url', '') or ''
        await interaction.response.send_modal(WelcomeEmbedFooterModal(parent_view=self, current_footer_text=current_footer_text, current_footer_icon_url=current_footer_icon_url))

    @ui.button(label="Voltar ao Painel Principal", style=discord.ButtonStyle.red, row=3)
    async def back_to_main_panel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self) # Desabilita esta view

        # Re-habilita os botões da view principal e a atualiza
        for item in self.parent_view.children:
            item.disabled = False
        await self.parent_view.message.edit(view=self.parent_view)
        await interaction.followup.send("Retornando ao painel principal.", ephemeral=True)


class LeaveConfigView(ui.View):
    def __init__(self, parent_view: ui.View, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=180)
        self.parent_view = parent_view # A WelcomeSettingsView
        self.bot = bot
        self.guild_id = guild_id
        self.message = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração de Saídas expirada.", view=self)

    async def _update_leave_display(self, interaction: discord.Interaction):
        settings = execute_query(
            "SELECT leave_enabled, leave_channel_id, leave_message, leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (self.guild_id,),
            fetchone=True
        )

        embed = discord.Embed(
            title="Configurações de Saídas",
            description="Ajuste as mensagens e o embed para membros que saem.\n\n**Variáveis:** `{member}`, `{member.name}`, `{guild.name}`, `{member.count}`",
            color=discord.Color.red()
        )

        if settings:
            leave_enabled, lc_id, lm, leave_embed_json = settings
            
            leave_status = "🟢 Ativado" if leave_enabled else "🔴 Desativado"
            leave_channel = self.bot.get_channel(lc_id) if lc_id else "Nenhum"
            leave_message_preview = (lm[:50] + "..." if lm and len(lm) > 50 else lm) if lm else "Nenhuma"
            leave_embed_configured = "Sim" if leave_embed_json else "Não"
            
            embed.add_field(name="Status Geral", value=leave_status, inline=False)
            embed.add_field(name="Canal", value=getattr(leave_channel, 'mention', leave_channel), inline=False)
            embed.add_field(name="Mensagem de Texto", value=f"`{leave_message_preview}`", inline=False)
            embed.add_field(name="Embed Configurado", value=leave_embed_configured, inline=False)

            # Pré-visualização do embed de saídas (se configurado)
            preview_embed = None # Initialize preview_embed
            if leave_embed_json:
                try:
                    embed_data = json.loads(leave_embed_json)
                    preview_embed = _create_embed_from_data(embed_data, member=interaction.user, guild=interaction.guild) # Usar interaction.user/guild para preview
                    embed.add_field(name="Pré-visualização do Embed", value="Veja abaixo:", inline=False)
                except json.JSONDecodeError:
                    logging.error(f"Erro ao decodificar JSON do leave embed para guild {self.guild_id} na preview.")
                    preview_embed = None
            else:
                preview_embed = None
        else:
            embed.add_field(name="Status", value="🔴 Desativado (Padrões)", inline=False)
            embed.set_footer(text="Nenhuma configuração salva. Use os botões para configurar.")
            preview_embed = None # Initialize preview_embed for this path too
        
        embeds_to_send = [embed]
        if preview_embed:
            embeds_to_send.append(preview_embed)

        if self.message:
            await self.message.edit(embeds=embeds_to_send, view=self)
        else:
            if interaction.response.is_done():
                self.message = await interaction.followup.send(embeds=embeds_to_send, view=self, ephemeral=True)
            else:
                await interaction.response.send_message(embeds=embeds_to_send, view=self, ephemeral=True)
                self.message = await interaction.original_response()

    # Helpers para carregar/salvar embed JSON de saída
    def _get_leave_embed_data(self):
        settings = execute_query("SELECT leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        if settings and settings[0]:
            try:
                return json.loads(settings[0])
            except json.JSONDecodeError:
                logging.error(f"Erro ao decodificar JSON do leave embed para guild {self.guild_id}. Retornando vazio.")
                return {}
        return {}

    def _save_leave_embed_data(self, embed_data: dict):
        embed_json = json.dumps(embed_data)
        execute_query(
            "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_embed_json) VALUES (?, ?)",
            (self.guild_id, embed_json)
        )

    @ui.button(label="Alternar Status", style=discord.ButtonStyle.primary, row=0)
    async def toggle_leave_status(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        current_status = execute_query("SELECT leave_enabled FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        new_status = not current_status[0] if current_status and current_status[0] is not None else True # Handle None or 0

        execute_query(
            "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_enabled) VALUES (?, ?)",
            (self.guild_id, new_status)
        )
        await self._update_leave_display(interaction)
        await interaction.followup.send(f"Mensagens de Saída {('ativadas' if new_status else 'desativadas')}!", ephemeral=True)

    @ui.button(label="Definir Canal", style=discord.ButtonStyle.secondary, row=0)
    async def set_leave_channel(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveChannelModal(ui.Modal, title="Definir Canal de Saídas"):
            def __init__(self, parent_view: ui.View, current_channel_id: int):
                super().__init__()
                self.parent_view = parent_view
                default_value = str(current_channel_id) if current_channel_id else ""
                self.add_item(ui.TextInput(label="ID do Canal", placeholder="Ex: 123456789012345678", style=discord.TextStyle.short, custom_id="channel_id", default=default_value))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                try:
                    channel_id = int(self.children[0].value)
                    channel = original_view.bot.get_channel(channel_id)
                    if not isinstance(channel, discord.TextChannel):
                        await interaction.followup.send("ID de canal inválido ou não é um canal de texto.", ephemeral=True)
                        return

                    execute_query(
                        "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_channel_id) VALUES (?, ?)",
                        (original_view.guild_id, channel_id)
                    )
                    await original_view._update_leave_display(interaction)
                    await interaction.followup.send(f"Canal de Saídas definido para {channel.mention}.", ephemeral=True)
                except ValueError:
                    await interaction.followup.send("ID de canal inválido. Por favor, insira um número.", ephemeral=True)
        
        current_settings = execute_query("SELECT leave_channel_id FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        current_channel_id = current_settings[0] if current_settings else None
        await interaction.response.send_modal(LeaveChannelModal(parent_view=self, current_channel_id=current_channel_id))

    @ui.button(label="Definir Mensagem de Texto", style=discord.ButtonStyle.secondary, row=0)
    async def set_leave_message(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveMessageModal(ui.Modal, title="Definir Mensagem de Saídas"):
            def __init__(self, parent_view: ui.View, current_message: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Mensagem", placeholder="Use {member}, {guild.name}, {member.count}", style=discord.TextStyle.paragraph, custom_id="leave_message", default=current_message, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                message_content = self.children[0].value if self.children[0].value.strip() else None

                execute_query(
                    "INSERT OR REPLACE INTO welcome_leave_messages (guild_id, leave_message) VALUES (?, ?)",
                    (original_view.guild_id, message_content)
                )
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Mensagem de Saída atualizada!", ephemeral=True)
        
        current_settings = execute_query("SELECT leave_message FROM welcome_leave_messages WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        current_message = current_settings[0] if current_settings and current_settings[0] else ""
        await interaction.response.send_modal(LeaveMessageModal(parent_view=self, current_message=current_message))

    # --- Novas funcionalidades para Embed de Saídas ---
    @ui.button(label="Título do Embed", style=discord.ButtonStyle.red, row=1)
    async def set_leave_embed_title(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveEmbedTitleModal(ui.Modal, title="Título do Embed de Saídas"):
            def __init__(self, parent_view: ui.View, current_title: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Título", placeholder="Título do embed (use variáveis)", style=discord.TextStyle.short, custom_id="embed_title", default=current_title, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_leave_embed_data()
                embed_data['title'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_leave_embed_data(embed_data)
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Título do Embed de Saídas atualizado!", ephemeral=True)
        
        embed_data = self._get_leave_embed_data()
        current_title = embed_data.get('title', '') or ''
        await interaction.response.send_modal(LeaveEmbedTitleModal(parent_view=self, current_title=current_title))

    @ui.button(label="Descrição do Embed", style=discord.ButtonStyle.red, row=1)
    async def set_leave_embed_description(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveEmbedDescriptionModal(ui.Modal, title="Descrição do Embed de Saídas"):
            def __init__(self, parent_view: ui.View, current_description: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Descrição", placeholder="Descrição do embed (use variáveis)", style=discord.TextStyle.paragraph, custom_id="embed_description", default=current_description, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_leave_embed_data()
                embed_data['description'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_leave_embed_data(embed_data)
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Descrição do Embed de Saídas atualizada!", ephemeral=True)
        
        embed_data = self._get_leave_embed_data()
        current_description = embed_data.get('description', '') or ''
        await interaction.response.send_modal(LeaveEmbedDescriptionModal(parent_view=self, current_description=current_description))

    @ui.button(label="Cor do Embed", style=discord.ButtonStyle.red, row=1)
    async def set_leave_embed_color(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveEmbedColorModal(ui.Modal, title="Cor do Embed de Saídas"):
            def __init__(self, parent_view: ui.View, current_color: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Cor (Hex ou Decimal)", placeholder="#RRGGBB ou 0xRRGGBB ou número", style=discord.TextStyle.short, custom_id="embed_color", default=current_color, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_leave_embed_data()
                color_value = self.children[0].value.strip()
                embed_data['color'] = color_value if color_value else None
                original_view._save_leave_embed_data(embed_data)
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Cor do Embed de Saídas atualizada!", ephemeral=True)
        
        embed_data = self._get_leave_embed_data()
        current_color = embed_data.get('color', '') or ''
        await interaction.response.send_modal(LeaveEmbedColorModal(parent_view=self, current_color=current_color))

    @ui.button(label="Imagem do Embed", style=discord.ButtonStyle.red, row=2)
    async def set_leave_embed_image(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveEmbedImageModal(ui.Modal, title="Imagem do Embed de Saídas"):
            def __init__(self, parent_view: ui.View, current_image_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="URL da Imagem", placeholder="URL da imagem (opcional)", style=discord.TextStyle.short, custom_id="embed_image", default=current_image_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_leave_embed_data()
                image_url = self.children[0].value.strip()
                embed_data['image_url'] = image_url if image_url else None
                original_view._save_leave_embed_data(embed_data)
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Imagem do Embed de Saídas atualizada!", ephemeral=True)
        
        embed_data = self._get_leave_embed_data()
        current_image_url = embed_data.get('image_url', '') or ''
        await interaction.response.send_modal(LeaveEmbedImageModal(parent_view=self, current_image_url=current_image_url))

    @ui.button(label="Rodapé do Embed", style=discord.ButtonStyle.red, row=2)
    async def set_leave_embed_footer(self, interaction: discord.Interaction, button: ui.Button):
        class LeaveEmbedFooterModal(ui.Modal, title="Rodapé do Embed de Saídas"):
            def __init__(self, parent_view: ui.View, current_footer_text: str, current_footer_icon_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Texto do Rodapé", placeholder="Texto do rodapé (opcional)", style=discord.TextStyle.short, custom_id="footer_text", default=current_footer_text, required=False))
                self.add_item(ui.TextInput(label="URL do Ícone do Rodapé (Opcional)", placeholder="URL da imagem do ícone", style=discord.TextStyle.short, custom_id="footer_icon_url", default=current_footer_icon_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_leave_embed_data()
                footer_text = self.children[0].value.strip()
                footer_icon_url = self.children[1].value.strip()
                embed_data['footer_text'] = footer_text if footer_text else None
                embed_data['footer_icon_url'] = footer_icon_url if footer_icon_url else None
                original_view._save_leave_embed_data(embed_data)
                await original_view._update_leave_display(interaction)
                await interaction.followup.send("Rodapé do Embed de Saídas atualizado!", ephemeral=True)
        
        embed_data = self._get_leave_embed_data()
        current_footer_text = embed_data.get('footer_text', '') or ''
        current_footer_icon_url = embed_data.get('footer_icon_url', '') or ''
        await interaction.response.send_modal(LeaveEmbedFooterModal(parent_view=self, current_footer_text=current_footer_text, current_footer_icon_url=current_footer_icon_url))

    @ui.button(label="Voltar ao Painel Principal", style=discord.ButtonStyle.red, row=3)
    async def back_to_main_panel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self) # Desabilita esta view

        # Re-habilita os botões da view principal e a atualiza
        for item in self.parent_view.children:
            item.disabled = False
        await self.parent_view.message.edit(view=self.parent_view)
        await interaction.followup.send("Retornando ao painel principal.", ephemeral=True)


# --- View Principal do Painel de Boas-Vindas e Saídas ---
class WelcomeSettingsView(ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=300) # Timeout de 5 minutos
        self.bot = bot
        self.guild_id = guild_id
        self.message = None # Para armazenar a mensagem do painel

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração de Boas-Vindas/Saídas expirada.", view=self)

    async def _update_settings_display(self, interaction: discord.Interaction):
        """Busca e exibe as configurações atuais de Boas-Vindas e Saídas."""
        settings = execute_query(
            "SELECT welcome_enabled, welcome_channel_id, welcome_message, leave_enabled, leave_channel_id, leave_message, welcome_embed_json, leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (self.guild_id,),
            fetchone=True
        )

        embed = discord.Embed(
            title="Configurações de Boas-Vindas e Saídas",
            description="Use os botões abaixo para configurar as mensagens de entrada e saída.",
            color=discord.Color.blue()
        )

        if settings:
            welcome_enabled, wc_id, wm, leave_enabled, lc_id, lm, welcome_embed_json, leave_embed_json = settings
            
            # Resumo de Boas-Vindas
            welcome_status = "🟢 Ativado" if welcome_enabled else "🔴 Desativado"
            welcome_channel = self.bot.get_channel(wc_id) if wc_id else "Nenhum"
            welcome_message_preview = "Configurada" if wm else "Nenhuma"
            welcome_embed_configured = "Sim" if welcome_embed_json else "Não"
            embed.add_field(name="Boas-Vindas", value=f"Status: {welcome_status}\nCanal: {getattr(welcome_channel, 'mention', welcome_channel)}\nMensagem de Texto: {welcome_message_preview}\nEmbed: {welcome_embed_configured}", inline=False)

            # Resumo de Saídas
            leave_status = "🟢 Ativado" if leave_enabled else "🔴 Desativado"
            leave_channel = self.bot.get_channel(lc_id) if lc_id else "Nenhum"
            leave_message_preview = "Configurada" if lm else "Nenhuma"
            leave_embed_configured = "Sim" if leave_embed_json else "Não"
            embed.add_field(name="Saídas", value=f"Status: {leave_status}\nCanal: {getattr(leave_channel, 'mention', leave_channel)}\nMensagem de Texto: {leave_message_preview}\nEmbed: {leave_embed_configured}", inline=False)
        else:
            embed.add_field(name="Status", value="🔴 Desativado (Padrões)", inline=False)
            embed.set_footer(text="Nenhuma configuração salva. Use os botões para configurar.")
        
        if self.message:
            await self.message.edit(embed=embed, view=self)
        else:
            if interaction.response.is_done():
                self.message = await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
                self.message = await interaction.original_response()

    @ui.button(label="Configurar Boas-Vindas", style=discord.ButtonStyle.green, row=0)
    async def configure_welcome(self, interaction: discord.Interaction, button: ui.Button):
        # Desabilita a view principal temporariamente
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

        # Abre a nova view de configuração de boas-vindas
        welcome_config_view = WelcomeConfigView(parent_view=self, bot=self.bot, guild_id=self.guild_id)
        await interaction.response.defer(ephemeral=True)
        await welcome_config_view._update_welcome_display(interaction)

    @ui.button(label="Configurar Saídas", style=discord.ButtonStyle.red, row=0)
    async def configure_leave(self, interaction: discord.Interaction, button: ui.Button):
        # Desabilita a view principal temporariamente
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

        # Abre a nova view de configuração de saídas
        leave_config_view = LeaveConfigView(parent_view=self, bot=self.bot, guild_id=self.guild_id)
        await interaction.response.defer(ephemeral=True)
        await leave_config_view._update_leave_display(interaction)


class WelcomeLeave(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="welcome_leave_panel", description="Abre o painel de configuração de Boas-Vindas e Saídas.")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_leave_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view = WelcomeSettingsView(self.bot, interaction.guild.id) # Usar guild.id aqui
        await view._update_settings_display(interaction)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        settings = execute_query(
            "SELECT welcome_enabled, welcome_channel_id, welcome_message, welcome_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (member.guild.id,),
            fetchone=True
        )

        if settings:
            welcome_enabled, channel_id, message_template, welcome_embed_json = settings
            
            if welcome_enabled and channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        # 1. Enviar a menção de texto (se houver mensagem de texto configurada)
                        if message_template:
                            formatted_text_message = message_template.format(
                                member=member,
                                guild=member.guild,
                                member_name=member.display_name,
                                member_count=member.guild.member_count
                            )
                            await channel.send(formatted_text_message)

                        # 2. Enviar o embed (se houver embed configurado)
                        if welcome_embed_json:
                            embed_data = json.loads(welcome_embed_json)
                            embed = _create_embed_from_data(embed_data, member=member, guild=member.guild)
                            await channel.send(embed=embed)
                        
                        logging.info(f"Mensagem/Embed de boas-vindas enviada para {member.display_name} em {member.guild.name}.")
                    except discord.Forbidden:
                        logging.warning(f"Não tenho permissão para enviar mensagens no canal de boas-vindas ({channel.name}) em {member.guild.name}.")
                    except Exception as e:
                        logging.error(f"Erro ao enviar mensagem/embed de boas-vindas para {member.display_name}: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return

        settings = execute_query(
            "SELECT leave_enabled, leave_channel_id, leave_message, leave_embed_json FROM welcome_leave_messages WHERE guild_id = ?",
            (member.guild.id,),
            fetchone=True
        )

        if settings:
            leave_enabled, channel_id, message_template, leave_embed_json = settings
            
            if leave_enabled and channel_id:
                channel = self.bot.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        # 1. Enviar a menção de texto (se houver mensagem de texto configurada)
                        if message_template:
                            formatted_text_message = message_template.format(
                                member=member,
                                guild=member.guild,
                                member_name=member.display_name,
                                member_count=member.guild.member_count # Pega o count atual, não o anterior
                            )
                            await channel.send(formatted_text_message)

                        # 2. Enviar o embed (se houver embed configurado)
                        if leave_embed_json:
                            embed_data = json.loads(leave_embed_json)
                            embed = _create_embed_from_data(embed_data, member=member, guild=member.guild)
                            await channel.send(embed=embed)

                        logging.info(f"Mensagem/Embed de saída enviada para {member.display_name} em {member.guild.name}.")
                    except discord.Forbidden:
                        logging.warning(f"Não tenho permissão para enviar mensagens no canal de saída ({channel.name}) em {member.guild.name}.")
                    except Exception as e:
                        logging.error(f"Erro ao enviar mensagem/embed de saída para {member.display_name}: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeLeave(bot))
