import discord
from discord.ext import commands
from discord import app_commands, ui
import logging
import os
import datetime
import asyncio
import json # Importar json para manipulação de dados JSON de embed

from database import execute_query

# --- Funções Auxiliares para Embeds (Reutilizadas do Welcome/Leave) ---
def _create_embed_from_data(embed_data: dict, member: discord.Member = None, guild: discord.Guild = None):
    """Cria um discord.Embed a partir de um dicionário de dados, formatando variáveis."""
    embed = discord.Embed()
    
    # Título (opcional)
    if embed_data.get('title'):
        embed.title = embed_data['title'].format(
            member=member,
            guild=guild,
            member_name=member.display_name if member else 'N/A',
            member_count=guild.member_count if guild else 'N/A'
        )
    else:
        embed.title = "" # Garante que é uma string vazia

    # Descrição (opcional)
    if embed_data.get('description'):
        embed.description = embed_data['description'].format(
            member=member,
            guild=guild,
            member_name=member.display_name if member else 'N/A',
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
            member_name=member.display_name if member else 'N/A',
            member_count=guild.member_count if guild else 'N/A'
        ), icon_url=embed_data.get('footer_icon_url'))

    # Autor (opcional)
    if embed_data.get('author_name'):
        embed.set_author(name=embed_data['author_name'].format(
            member=member,
            guild=guild,
            member_name=member.display_name if member else 'N/A',
            member_count=guild.member_count if guild else 'N/A'
        ), icon_url=embed_data.get('author_icon_url'))
    
    # Campos (opcional) - Embora não configuráveis aqui, é bom ter para consistência
    if 'fields' in embed_data:
        for field in embed_data['fields']:
            field_name = str(field.get('name', ''))
            field_value = str(field.get('value', ''))
            embed.add_field(name=field_name, value=field_value, inline=field.get('inline', False))

    return embed

# --- Views para Configuração do Painel de Tickets ---
class TicketPanelConfigView(ui.View):
    def __init__(self, parent_view: ui.View, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=180)
        self.parent_view = parent_view # A TicketSystemMainView
        self.bot = bot
        self.guild_id = guild_id
        self.message = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração do painel de tickets expirada.", view=self)

    async def _update_panel_display(self, interaction: discord.Interaction):
        # Pega os dados do embed do painel
        panel_embed_data = self._get_panel_embed_data()
        
        # Verifica se há dados de personalização (qualquer chave com valor não nulo/vazio)
        has_custom_data = False
        if panel_embed_data:
            for key, value in panel_embed_data.items():
                if value is not None and value != "" and key not in ["fields"]: # Ignora campos vazios que são strings vazias
                    has_custom_data = True
                    break
        
        panel_embed_configured = "Sim" if has_custom_data else "Não"
        
        embed = discord.Embed(
            title="Configuração do Painel de Tickets",
            description="Ajuste o embed que aparece no canal para abrir tickets.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Embed do Painel Configurado", value=panel_embed_configured, inline=False)

        preview_embed = None
        if has_custom_data: # Apenas cria preview se houver dados personalizados
            try:
                # Usamos interaction.guild para a preview, pois não há membro específico aqui
                preview_embed = _create_embed_from_data(panel_embed_data, guild=interaction.guild)
                embed.add_field(name="Pré-visualização do Painel", value="Veja abaixo:", inline=False)
            except Exception as e: # Captura qualquer erro na criação do embed de preview
                logging.error(f"Erro ao criar embed de pré-visualização para guild {self.guild_id}: {e}")
                preview_embed = discord.Embed(
                    title="Erro na Pré-visualização",
                    description=f"Não foi possível gerar a pré-visualização do embed. Erro: {e}",
                    color=discord.Color.red()
                )
        
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

    def _get_panel_embed_data(self):
        settings = execute_query("SELECT panel_embed_json FROM ticket_settings WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        if settings and settings[0]:
            try:
                return json.loads(settings[0])
            except json.JSONDecodeError:
                logging.error(f"Erro ao decodificar JSON do panel embed para guild {self.guild_id}. Retornando vazio.")
                return {}
        return {}

    def _save_panel_embed_data(self, embed_data: dict):
        has_content = False
        for key, value in embed_data.items():
            if value is not None and value != "" and key not in ["fields"]:
                has_content = True
                break
        
        embed_json = json.dumps(embed_data) if has_content else None

        # UPSERT logic: Tenta inserir uma linha básica se não existir, depois atualiza a coluna específica.
        execute_query(
            "INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)",
            (self.guild_id,)
        )
        execute_query(
            "UPDATE ticket_settings SET panel_embed_json = ? WHERE guild_id = ?",
            (embed_json, self.guild_id)
        )

    @ui.button(label="Título do Embed", style=discord.ButtonStyle.green, row=0, custom_id="panel_embed_title")
    async def set_panel_embed_title(self, interaction: discord.Interaction, button: ui.Button):
        class PanelEmbedTitleModal(ui.Modal, title="Título do Embed do Painel"):
            def __init__(self, parent_view: ui.View, current_title: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Título", placeholder="Título do embed", style=discord.TextStyle.short, custom_id="embed_title", default=current_title, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_panel_embed_data()
                embed_data['title'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_panel_embed_data(embed_data)
                await original_view._update_panel_display(interaction)
                await interaction.followup.send("Título do Embed do Painel atualizado!", ephemeral=True)
        
        embed_data = self._get_panel_embed_data()
        current_title = embed_data.get('title', '') or ''
        await interaction.response.send_modal(PanelEmbedTitleModal(parent_view=self, current_title=current_title))

    @ui.button(label="Descrição do Embed", style=discord.ButtonStyle.green, row=0, custom_id="panel_embed_description")
    async def set_panel_embed_description(self, interaction: discord.Interaction, button: ui.Button):
        class PanelEmbedDescriptionModal(ui.Modal, title="Descrição do Embed do Painel"):
            def __init__(self, parent_view: ui.View, current_description: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Descrição", placeholder="Descrição do embed", style=discord.TextStyle.paragraph, custom_id="embed_description", default=current_description, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_panel_embed_data()
                embed_data['description'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_panel_embed_data(embed_data)
                await original_view._update_panel_display(interaction)
                await interaction.followup.send("Descrição do Embed do Painel atualizada!", ephemeral=True)
        
        embed_data = self._get_panel_embed_data()
        current_description = embed_data.get('description', '') or ''
        await interaction.response.send_modal(PanelEmbedDescriptionModal(parent_view=self, current_description=current_description))

    @ui.button(label="Cor do Embed", style=discord.ButtonStyle.green, row=0, custom_id="panel_embed_color")
    async def set_panel_embed_color(self, interaction: discord.Interaction, button: ui.Button):
        class PanelEmbedColorModal(ui.Modal, title="Cor do Embed do Painel"):
            def __init__(self, parent_view: ui.View, current_color: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Cor (Hex ou Decimal)", placeholder="#RRGGBB ou 0xRRGGBB ou número", style=discord.TextStyle.short, custom_id="embed_color", default=current_color, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_panel_embed_data()
                color_value = self.children[0].value.strip()
                embed_data['color'] = color_value if color_value else None
                original_view._save_panel_embed_data(embed_data)
                await original_view._update_panel_display(interaction)
                await interaction.followup.send("Cor do Embed do Painel atualizada!", ephemeral=True)
        
        embed_data = self._get_panel_embed_data()
        current_color = embed_data.get('color', '') or ''
        await interaction.response.send_modal(PanelEmbedColorModal(parent_view=self, current_color=current_color))

    @ui.button(label="Imagem do Embed", style=discord.ButtonStyle.green, row=1, custom_id="panel_embed_image")
    async def set_panel_embed_image(self, interaction: discord.Interaction, button: ui.Button):
        class PanelEmbedImageModal(ui.Modal, title="Imagem do Embed do Painel"):
            def __init__(self, parent_view: ui.View, current_image_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="URL da Imagem", placeholder="URL da imagem (opcional)", style=discord.TextStyle.short, custom_id="embed_image", default=current_image_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_panel_embed_data()
                image_url = self.children[0].value.strip()
                embed_data['image_url'] = image_url if image_url else None
                original_view._save_panel_embed_data(embed_data)
                await original_view._update_panel_display(interaction)
                await interaction.followup.send("Imagem do Embed do Painel atualizada!", ephemeral=True)
        
        embed_data = self._get_panel_embed_data()
        current_image_url = embed_data.get('image_url', '') or ''
        await interaction.response.send_modal(PanelEmbedImageModal(parent_view=self, current_image_url=current_image_url))

    @ui.button(label="Rodapé do Embed", style=discord.ButtonStyle.green, row=1, custom_id="panel_embed_footer")
    async def set_panel_embed_footer(self, interaction: discord.Interaction, button: ui.Button):
        class PanelEmbedFooterModal(ui.Modal, title="Rodapé do Embed do Painel"):
            def __init__(self, parent_view: ui.View, current_footer_text: str, current_footer_icon_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Texto do Rodapé", placeholder="Texto do rodapé (opcional)", style=discord.TextStyle.short, custom_id="footer_text", default=current_footer_text, required=False))
                self.add_item(ui.TextInput(label="URL do Ícone do Rodapé (Opcional)", placeholder="URL da imagem do ícone", style=discord.TextStyle.short, custom_id="footer_icon_url", default=current_footer_icon_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_panel_embed_data()
                footer_text = self.children[0].value.strip()
                footer_icon_url = self.children[1].value.strip()
                embed_data['footer_text'] = footer_text if footer_text else None
                embed_data['footer_icon_url'] = footer_icon_url if footer_icon_url else None
                original_view._save_panel_embed_data(embed_data)
                await original_view._update_panel_display(interaction)
                await interaction.followup.send("Rodapé do Embed do Painel atualizado!", ephemeral=True)
        
        embed_data = self._get_panel_embed_data()
        current_footer_text = embed_data.get('footer_text', '') or ''
        current_footer_icon_url = embed_data.get('footer_icon_url', '') or ''
        await interaction.response.send_modal(PanelEmbedFooterModal(parent_view=self, current_footer_text=current_footer_text, current_footer_icon_url=current_footer_icon_url))

    @ui.button(label="Redefinir Embed", style=discord.ButtonStyle.red, row=2, custom_id="reset_panel_embed")
    async def reset_panel_embed(self, interaction: discord.Interaction, button: ui.Button):
        class ResetConfirmView(ui.View):
            def __init__(self, parent_view_ref):
                super().__init__(timeout=30)
                self.parent_view_ref = parent_view_ref # Referência à TicketPanelConfigView

            @ui.button(label="Confirmar Redefinição", style=discord.ButtonStyle.danger, custom_id="confirm_reset_panel_embed")
            async def confirm_reset(self, interaction_confirm: discord.Interaction, button_confirm: ui.Button):
                await interaction_confirm.response.defer(ephemeral=True)
                self.parent_view_ref._save_panel_embed_data({}) # Salva um dicionário vazio para redefinir
                await self.parent_view_ref._update_panel_display(interaction_confirm)
                await interaction_confirm.followup.send("Embed do Painel redefinido para o padrão!", ephemeral=True)
                # Não tentamos editar a mensagem efêmera aqui, pois ela pode desaparecer
                # e os botões serão desabilitados no timeout da view.
                self.stop() # Parar a view de confirmação

            @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, custom_id="cancel_reset_panel_embed")
            async def cancel_reset(self, interaction_cancel: discord.Interaction, button_cancel: ui.Button):
                await interaction_cancel.response.defer(ephemeral=True)
                await interaction_cancel.followup.send("Redefinição do Embed do Painel cancelada.", ephemeral=True)
                # Não tentamos editar a mensagem efêmera aqui.
                self.stop() # Parar a view de confirmação
                
        await interaction.response.send_message(
            "Tem certeza que deseja redefinir o embed do painel para o padrão? Todas as personalizações serão perdidas.",
            view=ResetConfirmView(self), ephemeral=True
        )

    @ui.button(label="Voltar ao Painel Principal", style=discord.ButtonStyle.secondary, row=2, custom_id="back_to_main_panel_from_panel_config")
    async def back_to_main_panel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self) # Desabilita esta view

        # Re-habilita os botões da view principal e a atualiza
        # A TicketSystemMainView é o o parent_view
        for item in self.parent_view.children:
            item.disabled = False
        await self.parent_view._update_main_display(interaction) # Chama o método de atualização da view principal
        await interaction.followup.send("Retornando ao painel principal do Ticket.", ephemeral=True)


# Nova View para Configuração da Mensagem Inicial do Ticket
class TicketInitialEmbedConfigView(ui.View):
    def __init__(self, parent_view: ui.View, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=180) # Esta view NÃO é persistente globalmente, então o timeout é OK
        self.parent_view = parent_view # A TicketSystemMainView
        self.bot = bot
        self.guild_id = guild_id
        self.message = None

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração da mensagem inicial do ticket expirada.", view=self)

    async def _update_initial_embed_display(self, interaction: discord.Interaction):
        initial_embed_data = self._get_initial_embed_data()
        
        has_custom_data = False
        if initial_embed_data:
            for key, value in initial_embed_data.items():
                if value is not None and value != "" and key not in ["fields"]:
                    has_custom_data = True
                    break
        
        initial_embed_configured = "Sim" if has_custom_data else "Não"
        
        embed = discord.Embed(
            title="Configuração da Mensagem Inicial do Ticket",
            description="Ajuste o embed que aparece dentro do canal do ticket quando ele é aberto.",
            color=discord.Color.orange()
        )
        embed.add_field(name="Embed da Mensagem Inicial Configurado", value=initial_embed_configured, inline=False)

        preview_embed = None
        if has_custom_data:
            try:
                # Usamos interaction.guild para a preview, pois não há membro específico aqui
                preview_embed = _create_embed_from_data(initial_embed_data, guild=interaction.guild)
                embed.add_field(name="Pré-visualização da Mensagem Inicial", value="Veja abaixo:", inline=False)
            except Exception as e:
                logging.error(f"Erro ao criar embed de pré-visualização da mensagem inicial para guild {self.guild_id}: {e}")
                preview_embed = discord.Embed(
                    title="Erro na Pré-visualização",
                    description=f"Não foi possível gerar a pré-visualização do embed. Erro: {e}",
                    color=discord.Color.red()
                )
        
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

    def _get_initial_embed_data(self):
        settings = execute_query("SELECT ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?", (self.guild_id,), fetchone=True)
        if settings and settings[0]:
            try:
                return json.loads(settings[0])
            except json.JSONDecodeError:
                logging.error(f"Erro ao decodificar JSON da mensagem inicial do ticket para guild {self.guild_id}. Retornando vazio.")
                return {}
        return {}

    def _save_initial_embed_data(self, embed_data: dict):
        has_content = False
        for key, value in embed_data.items():
            if value is not None and value != "" and key not in ["fields"]:
                has_content = True
                break
        
        embed_json = json.dumps(embed_data) if has_content else None
        
        # UPSERT logic: Tenta inserir uma linha básica se não existir, depois atualiza a coluna específica.
        execute_query(
            "INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)",
            (self.guild_id,)
        )
        execute_query(
            "UPDATE ticket_settings SET ticket_initial_embed_json = ? WHERE guild_id = ?",
            (embed_json, self.guild_id)
        )

    # Botões e Modais para personalizar a mensagem inicial do ticket (similar ao painel)
    @ui.button(label="Título", style=discord.ButtonStyle.green, row=0, custom_id="initial_embed_title")
    async def set_initial_embed_title(self, interaction: discord.Interaction, button: ui.Button):
        class InitialEmbedTitleModal(ui.Modal, title="Título da Mensagem Inicial"):
            def __init__(self, parent_view: ui.View, current_title: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Título", placeholder="Título do embed", style=discord.TextStyle.short, custom_id="initial_embed_title_input", default=current_title, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_initial_embed_data()
                embed_data['title'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_initial_embed_data(embed_data)
                await original_view._update_initial_embed_display(interaction)
                await interaction.followup.send("Título da Mensagem Inicial atualizado!", ephemeral=True)
        
        embed_data = self._get_initial_embed_data()
        current_title = embed_data.get('title', '') or ''
        await interaction.response.send_modal(InitialEmbedTitleModal(parent_view=self, current_title=current_title))

    @ui.button(label="Descrição", style=discord.ButtonStyle.green, row=0, custom_id="initial_embed_description")
    async def set_initial_embed_description(self, interaction: discord.Interaction, button: ui.Button):
        class InitialEmbedDescriptionModal(ui.Modal, title="Descrição da Mensagem Inicial"):
            def __init__(self, parent_view: ui.View, current_description: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Descrição", placeholder="Descrição do embed", style=discord.TextStyle.paragraph, custom_id="initial_embed_description_input", default=current_description, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_initial_embed_data()
                embed_data['description'] = self.children[0].value if self.children[0].value.strip() else None
                original_view._save_initial_embed_data(embed_data)
                await original_view._update_initial_embed_display(interaction)
                await interaction.followup.send("Descrição da Mensagem Inicial atualizada!", ephemeral=True)
        
        embed_data = self._get_initial_embed_data()
        current_description = embed_data.get('description', '') or ''
        await interaction.response.send_modal(InitialEmbedDescriptionModal(parent_view=self, current_description=current_description))

    @ui.button(label="Cor", style=discord.ButtonStyle.green, row=0, custom_id="initial_embed_color")
    async def set_initial_embed_color(self, interaction: discord.Interaction, button: ui.Button):
        class InitialEmbedColorModal(ui.Modal, title="Cor da Mensagem Inicial"):
            def __init__(self, parent_view: ui.View, current_color: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Cor (Hex ou Decimal)", placeholder="#RRGGBB ou 0xRRGGBB ou número", style=discord.TextStyle.short, custom_id="initial_embed_color_input", default=current_color, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_initial_embed_data()
                color_value = self.children[0].value.strip()
                embed_data['color'] = color_value if color_value else None
                original_view._save_initial_embed_data(embed_data)
                await original_view._update_initial_embed_display(interaction)
                await interaction.followup.send("Cor da Mensagem Inicial atualizada!", ephemeral=True)
        
        embed_data = self._get_initial_embed_data()
        current_color = embed_data.get('color', '') or ''
        await interaction.response.send_modal(InitialEmbedColorModal(parent_view=self, current_color=current_color))

    @ui.button(label="Imagem", style=discord.ButtonStyle.green, row=1, custom_id="initial_embed_image")
    async def set_initial_embed_image(self, interaction: discord.Interaction, button: ui.Button):
        class InitialEmbedImageModal(ui.Modal, title="Imagem da Mensagem Inicial"):
            def __init__(self, parent_view: ui.View, current_image_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="URL da Imagem", placeholder="URL da imagem (opcional)", style=discord.TextStyle.short, custom_id="initial_embed_image_input", default=current_image_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_initial_embed_data()
                image_url = self.children[0].value.strip()
                embed_data['image_url'] = image_url if image_url else None
                original_view._save_initial_embed_data(embed_data)
                await original_view._update_initial_embed_display(interaction)
                await interaction.followup.send("Imagem da Mensagem Inicial atualizada!", ephemeral=True)
        
        embed_data = self._get_initial_embed_data()
        current_image_url = embed_data.get('image_url', '') or ''
        await interaction.response.send_modal(InitialEmbedImageModal(parent_view=self, current_image_url=current_image_url))

    @ui.button(label="Rodapé", style=discord.ButtonStyle.green, row=1, custom_id="initial_embed_footer")
    async def set_initial_embed_footer(self, interaction: discord.Interaction, button: ui.Button):
        class InitialEmbedFooterModal(ui.Modal, title="Rodapé da Mensagem Inicial"):
            def __init__(self, parent_view: ui.View, current_footer_text: str, current_footer_icon_url: str):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Texto do Rodapé", placeholder="Texto do rodapé (opcional)", style=discord.TextStyle.short, custom_id="initial_embed_footer_text_input", default=current_footer_text, required=False))
                self.add_item(ui.TextInput(label="URL do Ícone do Rodapé (Opcional)", placeholder="URL da imagem do ícone", style=discord.TextStyle.short, custom_id="initial_embed_footer_icon_url_input", default=current_footer_icon_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer()
                original_view = self.parent_view
                embed_data = original_view._get_initial_embed_data()
                footer_text = self.children[0].value.strip()
                footer_icon_url = self.children[1].value.strip()
                embed_data['footer_text'] = footer_text if footer_text else None
                embed_data['footer_icon_url'] = footer_icon_url if footer_icon_url else None
                original_view._save_initial_embed_data(embed_data)
                await original_view._update_initial_embed_display(interaction)
                await interaction.followup.send("Rodapé da Mensagem Inicial atualizado!", ephemeral=True)
        
        embed_data = self._get_initial_embed_data()
        current_footer_text = embed_data.get('footer_text', '') or ''
        current_footer_icon_url = embed_data.get('footer_icon_url', '') or ''
        await interaction.response.send_modal(InitialEmbedFooterModal(parent_view=self, current_footer_text=current_footer_text, current_footer_icon_url=current_footer_icon_url))

    @ui.button(label="Redefinir Embed", style=discord.ButtonStyle.red, row=2, custom_id="reset_initial_embed")
    async def reset_initial_embed(self, interaction: discord.Interaction, button: ui.Button):
        class ResetInitialEmbedConfirmView(ui.View):
            def __init__(self, parent_view_ref):
                super().__init__(timeout=30)
                self.parent_view_ref = parent_view_ref

            @ui.button(label="Confirmar Redefinição", style=discord.ButtonStyle.danger, custom_id="confirm_reset_initial_embed")
            async def confirm_reset(self, interaction_confirm: discord.Interaction, button_confirm: ui.Button):
                await interaction_confirm.response.defer(ephemeral=True)
                self.parent_view_ref._save_initial_embed_data({})
                await self.parent_view_ref._update_initial_embed_display(interaction_confirm)
                await interaction_confirm.followup.send("Embed da Mensagem Inicial redefinido para o padrão!", ephemeral=True)
                self.stop()

            @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, custom_id="cancel_reset_initial_embed")
            async def cancel_reset(self, interaction_cancel: discord.Interaction, button_cancel: ui.Button):
                await interaction_cancel.response.defer(ephemeral=True)
                await interaction_cancel.followup.send("Redefinição da Mensagem Inicial cancelada.", ephemeral=True)
                self.stop()
        
        await interaction.response.send_message(
            "Tem certeza que deseja redefinir o embed da mensagem inicial do ticket para o padrão? Todas as personalizações serão perdidas.",
            view=ResetInitialEmbedConfirmView(self), ephemeral=True
        )

    @ui.button(label="Voltar ao Painel Principal", style=discord.ButtonStyle.secondary, row=2, custom_id="back_to_main_panel_from_initial_config")
    async def back_to_main_panel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

        for item in self.parent_view.children:
            item.disabled = False
        await self.parent_view._update_main_display(interaction)
        await interaction.followup.send("Retornando ao painel principal do Ticket.", ephemeral=True)


# Nova View Principal para o Sistema de Tickets
class TicketSystemMainView(ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None) # Timeout=None para views persistentes
        self.bot = bot
        self.guild_id = guild_id
        self.message = None # Para armazenar a mensagem do painel

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de configuração do sistema de tickets expirada.", view=self)

    async def _update_main_display(self, interaction: discord.Interaction):
        """Atualiza a exibição do painel principal de configurações de tickets."""
        embed = discord.Embed(
            title="Painel Principal do Sistema de Tickets",
            description="Selecione uma opção para gerenciar o sistema de tickets.",
            color=discord.Color.dark_blue()
        )
        embed.add_field(name="Configurações do Painel", value="Personalize a mensagem de abertura de ticket.", inline=False)
        embed.add_field(name="Logs de Tickets", value="Visualize e gerencie os registros de tickets fechados.", inline=False)
        embed.add_field(name="Mensagem Inicial do Ticket", value="Personalize o embed que aparece ao abrir um ticket.", inline=False)


        if self.message:
            await self.message.edit(embed=embed, view=self)
        else:
            if interaction.response.is_done():
                self.message = await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
                self.message = await interaction.original_response()

    @ui.button(label="Configurar Painel de Tickets", style=discord.ButtonStyle.primary, row=0, custom_id="config_ticket_panel_button")
    async def configure_ticket_panel(self, interaction: discord.Interaction, button: ui.Button):
        # Desabilita a view principal temporariamente
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

        # Abre a nova view de configuração do painel
        panel_config_view = TicketPanelConfigView(parent_view=self, bot=self.bot, guild_id=self.guild_id)
        await interaction.response.defer(ephemeral=True)
        await panel_config_view._update_panel_display(interaction)

    @ui.button(label="Configurar Mensagem Inicial", style=discord.ButtonStyle.primary, row=1, custom_id="config_initial_message_button")
    async def configure_initial_message(self, interaction: discord.Interaction, button: ui.Button):
        # Desabilita a view principal temporariamente
        for item in self.children:
            item.disabled = True
        await self.message.edit(view=self)

        # Abre a nova view de configuração da mensagem inicial
        initial_embed_config_view = TicketInitialEmbedConfigView(parent_view=self, bot=self.bot, guild_id=self.guild_id)
        await interaction.response.defer(ephemeral=True)
        await initial_embed_config_view._update_initial_embed_display(interaction)


# View para o painel principal de tickets (este é o painel que os usuários veem para abrir tickets)
class TicketPanelView(ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int):
        super().__init__(timeout=None) # View persistente
        self.bot = bot # Adicionado self.bot para acesso
        self.guild_id = guild_id # Adicionado self.guild_id para acesso

    @ui.button(label="Abrir Ticket", style=discord.ButtonStyle.primary, custom_id="open_ticket_button")
    async def open_ticket(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await asyncio.sleep(0.1) 
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            logging.error(f"Unknown interaction ao deferir open_ticket para o usuário {interaction.user.id} na guild {interaction.guild_id}.")
            return

        # Verifica se o usuário já tem um ticket aberto
        existing_ticket = execute_query(
            "SELECT channel_id FROM active_tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'", # Apenas tickets abertos
            (interaction.guild_id, interaction.user.id), # Usar interaction.guild_id
            fetchone=True
        )
        if existing_ticket:
            channel = self.bot.get_channel(existing_ticket[0]) # Usar self.bot
            if channel:
                await interaction.followup.send(f"Você já tem um ticket aberto em {channel.mention}.", ephemeral=True)
                return
            else:
                # Se o canal não existe mas o registro sim, remove o registro antigo
                execute_query("DELETE FROM active_tickets WHERE channel_id = ?", (existing_ticket[0],))
                logging.warning(f"Registro de ticket obsoleto para o usuário {interaction.user.id} na guild {interaction.guild_id} removido.")

        settings = execute_query(
            "SELECT category_id, ticket_role_id, ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?",
            (interaction.guild_id,), # Usar interaction.guild_id
            fetchone=True
        )

        if not settings or not settings[0]: # Se category_id for None, o sistema não está configurado
            await interaction.followup.send("O sistema de tickets não está configurado (categoria não definida). Use `/set_ticket_channel` primeiro.", ephemeral=True)
            return

        category_id, ticket_role_id, ticket_initial_embed_json_raw = settings
        category = self.bot.get_channel(category_id) # Usar self.bot
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("A categoria de tickets configurada é inválida ou não existe. Por favor, reconfigure com `/set_ticket_channel`.", ephemeral=True)
            return

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        if ticket_role_id:
            ticket_role = interaction.guild.get_role(ticket_role_id)
            if ticket_role:
                overwrites[ticket_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            else:
                await interaction.followup.send("O cargo de ticket configurado não foi encontrado. O ticket será criado sem permissões para o cargo.", ephemeral=True)

        try:
            ticket_channel = await category.create_text_channel(f"ticket-{interaction.user.name}", overwrites=overwrites)
            
            # Salva o ticket no banco de dados
            execute_query(
                "INSERT INTO active_tickets (guild_id, user_id, channel_id) VALUES (?, ?, ?)",
                (interaction.guild_id, interaction.user.id, ticket_channel.id) # Usar interaction.guild_id
            )

            # Prepara o embed da mensagem inicial do ticket
            ticket_embed = None
            if ticket_initial_embed_json_raw:
                try:
                    ticket_embed = _create_embed_from_data(json.loads(ticket_initial_embed_json_raw), member=interaction.user, guild=interaction.guild)
                except json.JSONDecodeError:
                    logging.error(f"Erro ao decodificar JSON da mensagem inicial do ticket para guild {interaction.guild_id} ao abrir ticket.")
                    ticket_embed = None
            
            if not ticket_embed: # Se não houver embed personalizado ou se for inválido, usa o padrão
                ticket_embed = discord.Embed(
                    title=f"Ticket de Suporte - {interaction.user.display_name}",
                    description="Por favor, descreva seu problema ou questão aqui. Um membro da equipe de suporte irá atendê-lo em breve.",
                    color=discord.Color.blue()
                )
                ticket_embed.set_footer(text=f"ID do Usuário: {interaction.user.id} | Ticket ID: {ticket_channel.id}")


            close_view = CloseTicketView()
            await ticket_channel.send(f"{interaction.user.mention}", embed=ticket_embed, view=close_view)
            await interaction.followup.send(f"Seu ticket foi criado em {ticket_channel.mention}!", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("Não tenho permissão para criar canais nesta categoria.", ephemeral=True)
        except Exception as e:
            logging.error(f"Erro ao criar ticket: {e}")
            await interaction.followup.send(f"Ocorreu um erro ao criar o ticket: {e}", ephemeral=True)

# View para o botão de fechar ticket dentro do canal do ticket
class CloseTicketView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) # View persistente

    @ui.button(label="Fechar Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_button")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await asyncio.sleep(0.1)
            await interaction.response.send_message("Tem certeza que deseja fechar este ticket? Isso o deletará permanentemente.", view=CloseTicketConfirmView(), ephemeral=True)
        except discord.NotFound:
            logging.error(f"Unknown interaction ao enviar confirmação de fechar ticket para o canal {interaction.channel_id}.")
            return

# View para confirmação de fechamento de ticket
class CloseTicketConfirmView(ui.View):
    def __init__(self):
        super().__init__(timeout=60) # Timeout de 60 segundos para a confirmação

    @ui.button(label="Confirmar Fechamento", style=discord.ButtonStyle.danger, custom_id="confirm_close_ticket")
    async def confirm_close(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        ticket_channel = interaction.channel
        guild_id = interaction.guild_id

        ticket_info = execute_query(
            "SELECT ticket_id, user_id, channel_id FROM active_tickets WHERE channel_id = ? AND status = 'open'",
            (ticket_channel.id,),
            fetchone=True
        )

        if not ticket_info:
            await interaction.followup.send("Este canal não é um ticket ativo ou já foi fechado.", ephemeral=True)
            return

        ticket_id, user_id, channel_id = ticket_info

        # Fetch transcript channel ID before deletion
        settings = execute_query(
            "SELECT transcript_channel_id FROM ticket_settings WHERE guild_id = ?",
            (guild_id,),
            fetchone=True
        )
        transcript_channel_id = settings[0] if settings else None

        try:
            # 1. Enviar mensagem de sucesso ANTES de tentar deletar o canal.
            await interaction.followup.send("Ticket fechado com sucesso! O canal será deletado em breve.", ephemeral=True)

            # 2. Criar transcrição ANTES de deletar o canal
            if transcript_channel_id:
                # Acessa o bot através do cog para chamar _create_transcript
                cog = interaction.client.get_cog("TicketSystem")
                if cog:
                    await cog._create_transcript(ticket_channel, transcript_channel_id, ticket_id)
                else:
                    logging.error("Cog 'TicketSystem' não encontrado para criar transcrição.")

            # 3. Agora, tentar deletar o canal.
            await ticket_channel.delete()
            logging.info(f"Canal do ticket {channel_id} deletado com sucesso.")
            
            # 4. Remover o ticket do banco de dados APENAS SE o canal foi deletado com sucesso
            # CORREÇÃO: Atualizar status para 'closed' e registrar closed_by_id e closed_at
            execute_query(
                "UPDATE active_tickets SET status = 'closed', closed_by_id = ?, closed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (interaction.user.id, ticket_id)
            )
            logging.info(f"Ticket {ticket_id} (Channel ID: {channel_id}) fechado e status atualizado no DB.")

        except discord.NotFound:
            # O canal já não existe, então apenas atualiza o status no DB
            execute_query(
                "UPDATE active_tickets SET status = 'closed', closed_by_id = ?, closed_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
                (interaction.user.id, ticket_id)
            )
            logging.warning(f"Canal do ticket {channel_id} não encontrado (já deletado). Status do ticket {ticket_id} atualizado para 'closed' no DB.")
            await interaction.followup.send("Ticket já estava fechado ou canal inexistente. Status atualizado no registro.", ephemeral=True)
        except discord.Forbidden:
            logging.error(f"Não tenho permissão para deletar o canal do ticket {channel_id} na guild {guild_id}.")
            await interaction.followup.send("Não tenho permissão para deletar este canal. Por favor, verifique minhas permissões.", ephemeral=True)
        except Exception as e:
            logging.error(f"Erro inesperado ao fechar o ticket {ticket_id} (Channel ID: {channel_id}): {e}")
            await interaction.followup.send(f"Ocorreu um erro inesperado ao fechar o ticket: {e}", ephemeral=True)

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, custom_id="cancel_close_ticket")
    async def cancel_close(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Fechamento de ticket cancelado.", ephemeral=True)


class TicketSystem(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Adiciona as views persistentes
        self.bot.add_view(TicketSystemMainView(bot, guild_id=None)) 
        self.bot.add_view(TicketPanelView(bot, guild_id=None)) 
        self.bot.add_view(CloseTicketView()) 

        # Define o grupo de comandos de barra
        self.ticket_logs_group = app_commands.Group(name="ticket_logs", description="Comandos para gerenciar logs de tickets.")
        self.bot.tree.add_command(self.ticket_logs_group)


    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("Views persistentes de ticket garantidas.")
        # Re-envia o painel de tickets se já configurado
        for guild in self.bot.guilds:
            settings = execute_query(
                "SELECT ticket_channel_id, ticket_message_id, panel_embed_json FROM ticket_settings WHERE guild_id = ?",
                (guild.id,),
                fetchone=True
            )
            if settings and settings[0] and settings[1]:
                channel_id, message_id, panel_embed_json_raw = settings
                channel = self.bot.get_channel(channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        message = await channel.fetch_message(message_id)
                        panel_embed = None
                        if panel_embed_json_raw:
                            try:
                                panel_embed = _create_embed_from_data(json.loads(panel_embed_json_raw), guild=guild)
                            except json.JSONDecodeError:
                                logging.error(f"Erro ao decodificar JSON do panel embed para guild {guild.id} no on_ready.")
                        
                        if not panel_embed:
                            panel_embed = discord.Embed(
                                title="Sistema de Tickets",
                                description="Clique no botão abaixo para abrir um novo ticket de suporte.",
                                color=discord.Color.blue()
                            )
                        
                        await message.edit(embed=panel_embed, view=TicketPanelView(self.bot, guild.id))
                        logging.info(f"Painel de tickets na guild {guild.name} ({guild.id}) atualizado no on_ready.")
                    except discord.NotFound:
                        logging.warning(f"Mensagem do painel de tickets não encontrada no canal {channel_id} da guild {guild.id}. O registro pode estar obsoleto.")
                        # Limpar o ticket_message_id e ticket_channel_id do DB se a mensagem não existe
                        execute_query(
                            "UPDATE ticket_settings SET ticket_message_id = NULL, ticket_channel_id = NULL WHERE guild_id = ?",
                            (guild.id,)
                        )
                    except discord.Forbidden:
                        logging.warning(f"Não tenho permissão para editar a mensagem do painel de tickets no canal {channel_id} da guild {guild.id}.")
                    except Exception as e:
                        logging.error(f"Erro inesperado ao atualizar painel de tickets no on_ready para guild {guild.id}: {e}")

    async def _create_transcript(self, channel: discord.TextChannel, transcript_channel_id: int, ticket_id: int):
        """Cria uma transcrição do canal do ticket e envia para o canal de transcrição."""
        transcript_dir = "transcripts"
        os.makedirs(transcript_dir, exist_ok=True) # Garante que o diretório exista

        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{transcript_dir}/ticket-{ticket_id}-{timestamp}.txt"

        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"--- Transcrição do Ticket {ticket_id} ({channel.name}) ---\n")
                f.write(f"Aberto em: {channel.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n") 
                f.write(f"Fechado em: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
                for msg in messages:
                    f.write(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name}: {msg.clean_content}\n")
                    for attachment in msg.attachments:
                        f.write(f"    Anexo: {attachment.url}\n")
            
            transcript_channel = self.bot.get_channel(transcript_channel_id)
            if transcript_channel and isinstance(transcript_channel, discord.TextChannel):
                await transcript_channel.send(
                    f"Transcrição do Ticket {ticket_id} ({channel.name})", 
                    file=discord.File(filename)
                )
                logging.info(f"Transcrição do ticket {ticket_id} enviada para o canal {transcript_channel.name}.")
            else:
                logging.warning(f"Canal de transcrição {transcript_channel_id} não encontrado ou não é um canal de texto. Transcrição salva localmente.")

        except discord.Forbidden:
            logging.error(f"Não tenho permissão para ler o histórico de mensagens no canal {channel.name} ou enviar no canal de transcrição {transcript_channel_id}.")
        except Exception as e:
            logging.error(f"Erro ao criar ou enviar transcrição do ticket {ticket_id}: {e}")
        finally:
            if os.path.exists(filename):
                os.remove(filename) # Limpa o arquivo local
                logging.info(f"Arquivo de transcrição local {filename} removido.")

    @app_commands.command(name="set_ticket_channel", description="Define o canal para o painel de tickets e outras configurações.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="O canal onde o painel de tickets será enviado.",
                            category_id="ID da categoria onde os tickets serão criados.", 
                            ticket_role_id="ID do cargo que terá acesso aos tickets (opcional).",
                            transcript_channel_id="ID do canal para enviar transcrições de tickets (opcional).")
    async def set_ticket_channel(self, interaction: discord.Interaction, channel: discord.TextChannel, category_id: str, ticket_role_id: str = None, transcript_channel_id: str = None):
        await interaction.response.defer(ephemeral=True)

        try:
            category_id = int(category_id)
            category = self.bot.get_channel(category_id)
            if not isinstance(category, discord.CategoryChannel):
                await interaction.followup.send("O ID da categoria fornecido é inválido.", ephemeral=True)
                return

            if ticket_role_id:
                ticket_role_id = int(ticket_role_id)
                ticket_role = interaction.guild.get_role(ticket_role_id)
                if not ticket_role:
                    await interaction.followup.send("O ID do cargo de ticket fornecido é inválido.", ephemeral=True)
                    return
            
            if transcript_channel_id:
                transcript_channel_id = int(transcript_channel_id)
                transcript_channel = self.bot.get_channel(transcript_channel_id)
                if not isinstance(transcript_channel, discord.TextChannel):
                    await interaction.followup.send("O ID do canal de transcrição fornecido é inválido.", ephemeral=True)
                    return

            # 1. Carregar todas as configurações existentes para preservar o ticket_initial_embed_json
            existing_settings = execute_query(
                "SELECT category_id, transcript_channel_id, ticket_role_id, ticket_channel_id, ticket_message_id, panel_embed_json, ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?",
                (interaction.guild_id,),
                fetchone=True
            )

            # Inicializa com valores existentes ou None
            current_category_id = existing_settings[0] if existing_settings else None
            current_transcript_channel_id = existing_settings[1] if existing_settings else None
            current_ticket_role_id = existing_settings[2] if existing_settings else None
            current_ticket_channel_id = existing_settings[3] if existing_settings else None
            current_ticket_message_id = existing_settings[4] if existing_settings else None
            current_panel_embed_json_raw = existing_settings[5] if existing_settings else None
            current_ticket_initial_embed_json_raw = existing_settings[6] if existing_settings else None # O MAIS IMPORTANTE: PRESERVAR ESTE

            # 2. Atualizar as configurações com os novos valores do comando
            new_category_id = int(category_id)
            new_ticket_role_id = int(ticket_role_id) if ticket_role_id else current_ticket_role_id
            new_transcript_channel_id = int(transcript_channel_id) if transcript_channel_id else current_transcript_channel_id
            new_ticket_channel_id = channel.id # O canal onde o painel será enviado
            
            # 3. Preparar o embed do painel (usar o atual se existir, senão o padrão)
            panel_embed = None
            if current_panel_embed_json_raw:
                try:
                    panel_embed = _create_embed_from_data(json.loads(current_panel_embed_json_raw), guild=interaction.guild)
                except json.JSONDecodeError:
                    logging.error(f"Erro ao decodificar JSON do panel embed para guild {interaction.guild_id} ao setar canal do painel.")
                    panel_embed = None
            
            if not panel_embed: # Se não houver embed personalizado ou se for inválido, usa o padrão
                panel_embed = discord.Embed(
                    title="Sistema de Tickets",
                    description="Clique no botão abaixo para abrir um novo ticket de suporte.",
                    color=discord.Color.blue()
                )

            view = TicketPanelView(self.bot, interaction.guild_id)
            
            panel_message = None
            # 4. Tentar editar a mensagem antiga se o canal for o mesmo
            if current_ticket_message_id and current_ticket_channel_id == new_ticket_channel_id:
                try:
                    old_message = await channel.fetch_message(current_ticket_message_id)
                    await old_message.edit(embed=panel_embed, view=view)
                    panel_message = old_message
                    logging.info(f"Painel de tickets existente na guild {interaction.guild_id} editado no canal {channel.name}.")
                except discord.NotFound:
                    logging.warning(f"Mensagem do painel de tickets antiga {current_ticket_message_id} não encontrada no canal {channel.name}. Enviando nova mensagem.")
                except discord.Forbidden:
                    logging.warning(f"Não tenho permissão para editar a mensagem do painel de tickets antiga no canal {channel.name}. Enviando nova mensagem.")
                except Exception as e:
                    logging.error(f"Erro ao tentar editar painel de tickets existente no canal {channel.name}: {e}. Enviando nova mensagem.")

            if not panel_message: # Se a mensagem não foi editada (porque não existia ou houve erro, ou canal diferente)
                panel_message = await channel.send(embed=panel_embed, view=view)
                logging.info(f"Novo painel de tickets enviado para o canal {channel.name} na guild {interaction.guild_id}.")

            new_panel_embed_json = json.dumps(panel_embed.to_dict()) if panel_embed else None
            new_ticket_message_id = panel_message.id

            # 5. Atualizar ou inserir todas as configurações, PRESERVANDO ticket_initial_embed_json
            execute_query(
                """
                INSERT OR REPLACE INTO ticket_settings 
                (guild_id, category_id, transcript_channel_id, ticket_role_id, ticket_channel_id, ticket_message_id, panel_embed_json, ticket_initial_embed_json) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interaction.guild_id, new_category_id, new_transcript_channel_id, new_ticket_role_id, new_ticket_channel_id, new_ticket_message_id, new_panel_embed_json, current_ticket_initial_embed_json_raw)
            )

            await interaction.followup.send(f"Painel de tickets configurado e enviado com sucesso para {channel.mention}!", ephemeral=True)

        except ValueError:
            await interaction.followup.send("Por favor, forneça IDs de categoria, cargo e canal válidos (apenas números).", ephemeral=True)
        except Exception as e:
            logging.error(f"Erro ao configurar painel de ticket: {e}")
            await interaction.followup.send(f"Ocorreu um erro ao configurar o painel de tickets: {e}", ephemeral=True)

    @app_commands.command(name="send_ticket_panel", description="Envia o painel de criação de tickets para um canal específico.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="O canal para onde o painel de tickets será enviado.")
    async def send_ticket_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)

        # 1. Carregar configurações existentes do DB
        settings = execute_query(
            "SELECT category_id, ticket_role_id, panel_embed_json FROM ticket_settings WHERE guild_id = ?",
            (interaction.guild_id,),
            fetchone=True
        )

        if not settings or not settings[0]: # Verifica se a categoria está configurada
            await interaction.followup.send("O sistema de tickets não está configurado (categoria não definida). Use `/set_ticket_channel` primeiro.", ephemeral=True)
            return

        category_id, ticket_role_id, panel_embed_json_raw = settings

        # 2. Preparar o embed do painel (personalizado ou padrão)
        panel_embed = None
        if panel_embed_json_raw:
            try:
                panel_embed = _create_embed_from_data(json.loads(panel_embed_json_raw), guild=interaction.guild)
            except json.JSONDecodeError:
                logging.error(f"Erro ao decodificar JSON do panel embed para guild {interaction.guild_id} ao enviar painel manualmente.")
                panel_embed = None
        
        if not panel_embed:
            panel_embed = discord.Embed(
                title="Sistema de Tickets",
                description="Clique no botão abaixo para abrir um novo ticket de suporte.",
                color=discord.Color.blue()
            )

        view = TicketPanelView(self.bot, interaction.guild_id)

        try:
            # 3. Enviar a mensagem do painel para o canal especificado
            new_panel_message = await channel.send(embed=panel_embed, view=view)
            logging.info(f"Painel de tickets enviado manualmente para o canal {channel.name} ({channel.id}) na guild {interaction.guild_id}.")

            # 4. Atualizar o DB com o novo ID da mensagem e do canal do painel
            # Aqui, precisamos carregar as configurações existentes para preservar a mensagem inicial do ticket
            existing_full_settings = execute_query(
                "SELECT category_id, transcript_channel_id, ticket_role_id, ticket_channel_id, ticket_message_id, panel_embed_json, ticket_initial_embed_json FROM ticket_settings WHERE guild_id = ?",
                (interaction.guild_id,),
                fetchone=True
            )
            
            # Usar os valores existentes, exceto os que estamos atualizando
            updated_category_id = existing_full_settings[0] if existing_full_settings else None
            updated_transcript_channel_id = existing_full_settings[1] if existing_full_settings else None
            updated_ticket_role_id = existing_full_settings[2] if existing_full_settings else None
            updated_ticket_initial_embed_json_raw = existing_full_settings[6] if existing_full_settings else None

            execute_query(
                """
                INSERT OR REPLACE INTO ticket_settings 
                (guild_id, category_id, transcript_channel_id, ticket_role_id, ticket_channel_id, ticket_message_id, panel_embed_json, ticket_initial_embed_json) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (interaction.guild_id, updated_category_id, updated_transcript_channel_id, updated_ticket_role_id, channel.id, new_panel_message.id, json.dumps(panel_embed.to_dict()), updated_ticket_initial_embed_json_raw)
            )

            await interaction.followup.send(f"Painel de tickets enviado com sucesso para {channel.mention}!", ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send(f"Não tenho permissão para enviar mensagens no canal {channel.mention}.", ephemeral=True)
        except Exception as e:
            logging.error(f"Erro ao enviar painel de tickets manualmente: {e}")
            await interaction.followup.send(f"Ocorreu um erro ao enviar o painel de tickets: {e}", ephemeral=True)

    @app_commands.command(name="close_ticket", description="Fecha o ticket atual (apenas para canais de ticket).")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def close_ticket_command(self, interaction: discord.Interaction):
        # Verifica se o comando foi usado em um canal de ticket
        ticket_info = execute_query(
            "SELECT channel_id FROM active_tickets WHERE channel_id = ? AND status = 'open'",
            (interaction.channel_id,),
            fetchone=True
        )
        if not ticket_info:
            await interaction.response.send_message("Este comando só pode ser usado em um canal de ticket ativo.", ephemeral=True)
            return
        
        await interaction.response.send_message("Tem certeza que deseja fechar este ticket? Isso o deletará permanentemente.", view=CloseTicketConfirmView(), ephemeral=True)

    @app_commands.command(name="ticket_settings", description="Abre o painel de configurações do sistema de tickets.")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_settings_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Abre a nova view principal de configurações de tickets
        main_view = TicketSystemMainView(self.bot, interaction.guild_id)
        await main_view._update_main_display(interaction)


    # Define os comandos do grupo ticket_logs como métodos do cog
    # e os adiciona ao grupo self.ticket_logs_group
    @app_commands.default_permissions(manage_channels=True) # Permissão padrão para o comando
    async def list_ticket_logs(self, interaction: discord.Interaction):
        # Implementação do comando list_ticket_logs
        await interaction.response.defer(ephemeral=True)

        closed_tickets = execute_query(
            "SELECT ticket_id, user_id, opened_at, closed_by_id, closed_at FROM active_tickets WHERE guild_id = ? AND status = 'closed' ORDER BY closed_at DESC LIMIT 10",
            (interaction.guild_id,),
            fetchall=True
        )

        if not closed_tickets:
            await interaction.followup.send("Nenhum ticket fechado encontrado para este servidor.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Logs de Tickets Fechados",
            description="Aqui estão os últimos 10 tickets fechados:",
            color=discord.Color.purple()
        )

        for ticket in closed_tickets:
            ticket_id, user_id, opened_at, closed_by_id, closed_at = ticket
            
            # Tenta buscar os objetos de usuário
            opener = self.bot.get_user(user_id)
            closer = self.bot.get_user(closed_by_id)

            opener_name = opener.display_name if opener else f"ID: {user_id}"
            closer_name = closer.display_name if closer else f"ID: {closed_by_id}"

            embed.add_field(
                name=f"Ticket #{ticket_id}",
                value=(
                    f"Aberto por: {opener_name}\n"
                    f"Aberto em: <t:{int(datetime.datetime.strptime(opened_at, '%Y-%m-%d %H:%M:%S').timestamp())}:F>\n"
                    f"Fechado por: {closer_name}\n"
                    f"Fechado em: <t:{int(datetime.datetime.strptime(closed_at, '%Y-%m-%d %H:%M:%S').timestamp())}:F>"
                ),
                inline=False
            )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.default_permissions(administrator=True) # Permissão padrão para o comando
    async def clear_ticket_logs(self, interaction: discord.Interaction):
        # Implementação do comando clear_ticket_logs
        await interaction.response.defer(ephemeral=True)

        # Confirmação antes de apagar
        class ClearConfirmView(ui.View):
            def __init__(self):
                super().__init__(timeout=30)
            
            @ui.button(label="Confirmar Limpeza", style=discord.ButtonStyle.danger, custom_id="confirm_clear_logs")
            async def confirm(self, interaction_confirm: discord.Interaction, button_confirm: ui.Button):
                await interaction_confirm.response.defer(ephemeral=True)
                success = execute_query(
                    "DELETE FROM active_tickets WHERE guild_id = ? AND status = 'closed'",
                    (interaction.guild_id,)
                )
                if success:
                    await interaction_confirm.followup.send("Todos os logs de tickets fechados foram limpos com sucesso!", ephemeral=True)
                else:
                    await interaction_confirm.followup.send("Ocorreu um erro ao limpar os logs de tickets.", ephemeral=True)
                self.stop() # Parar a view de confirmação

            @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, custom_id="cancel_clear_logs")
            async def cancel(self, interaction_cancel: discord.Interaction, button_cancel: ui.Button):
                await interaction_cancel.response.defer(ephemeral=True)
                await interaction_cancel.followup.send("Limpeza de logs de tickets cancelada.", ephemeral=True)
                self.stop() # Parar a view de confirmação
                
        await interaction.followup.send("Tem certeza que deseja limpar **todos** os logs de tickets fechados? Esta ação é irreversível.", view=ClearConfirmView(), ephemeral=True)

    # Adiciona os comandos ao grupo no setup do cog
    def cog_load(self):
        # Adiciona os comandos ao grupo ticket_logs_group
        # Os comandos list_ticket_logs e clear_ticket_logs já são métodos do cog
        # e o decorador @app_commands.default_permissions já define as permissões
        # Não é necessário passar default_permissions aqui.
        self.ticket_logs_group.add_command(
            app_commands.Command(
                name="list",
                description="Lista os tickets fechados neste servidor.",
                callback=self.list_ticket_logs
            )
        )
        self.ticket_logs_group.add_command(
            app_commands.Command(
                name="clear",
                description="Limpa todos os logs de tickets fechados para este servidor.",
                callback=self.clear_ticket_logs
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystem(bot))
