import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import logging
import re # Para validação de URL

# Importa a função de execução de query do banco de dados
from database import execute_query # Assumindo que este módulo existe e funciona

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Funções Auxiliares ---
def is_valid_url(url: str) -> bool:
    """Verifica se a string fornecida é uma URL minimamente válida."""
    if not url:
        return False
    # Regex simples para verificar URLs http(s)
    regex = re.compile(
        r'^(?:http|ftp)s?://' # http:// ou https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' # domínio...
        r'localhost|' # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...ou ip
        r'(?::\d+)?' # porta opcional
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

# View para gerenciar campos de embed
class FieldManagementView(ui.View):
    def __init__(self, parent_view: ui.View):
        super().__init__(timeout=180) # Timeout de 3 minutos
        self.parent_view = parent_view
        self.message = None # Para armazenar a mensagem do painel de gerenciamento de campos

    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão de gerenciamento de campos expirada. Use `/embed_creator` ou `/embed_load` para continuar.", view=self)
            # Re-habilitar botões na view principal se ela ainda estiver ativa
            if self.parent_view.message:
                for item in self.parent_view.children:
                    item.disabled = False
                await self.parent_view.message.edit(view=self.parent_view)

    async def _update_field_display(self, interaction: discord.Interaction):
        """Atualiza a mensagem que exibe os campos atuais."""
        embed = discord.Embed(
            title="Gerenciamento de Campos do Embed", 
            description="Use os botões para adicionar ou remover campos. Max: 25 campos."
        )
        
        fields_data = self.parent_view.current_embed_data.get('fields', [])
        if not fields_data:
            embed.add_field(name="Status", value="Nenhum campo adicionado ainda. Adicione o primeiro!", inline=False)
        else:
            for i, field in enumerate(fields_data):
                inline_status = "Inline" if field.get('inline', False) else "Bloco"
                # Limitar o valor do campo para não exceder o limite de 1024 caracteres para embeds
                field_value_display = field.get('value', 'Sem Valor')
                if len(field_value_display) > 100: # Exibir apenas o começo para não poluir o painel
                    field_value_display = field_value_display[:97] + "..."
                
                embed.add_field(name=f"Campo {i+1}: `{field.get('name', 'Sem Nome')}`", 
                                 value=f"Valor: `{field_value_display}`\nTipo: **{inline_status}**", 
                                 inline=False)
        
        # Esta lógica garante que a mensagem seja enviada uma vez e depois editada
        if self.message:
            await self.message.edit(embed=embed, view=self)
        else:
            if interaction.response.is_done(): # Se a interação já foi respondida (ex: modal submit)
                self.message = await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            else: # Se a interação ainda não foi respondida (primeira chamada do botão)
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
                self.message = await interaction.original_response()

    @ui.button(label="Adicionar Campo", style=discord.ButtonStyle.success)
    async def add_field_button(self, interaction: discord.Interaction, button: ui.Button):
        fields_data = self.parent_view.current_embed_data.get('fields', [])
        if len(fields_data) >= 25:
            await interaction.response.send_message("O limite de 25 campos por embed foi atingido.", ephemeral=True)
            return

        class AddFieldModal(ui.Modal, title="Adicionar Novo Campo"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                self.add_item(ui.TextInput(label="Nome do Campo (max 256 chars)", placeholder="Ex: Título do Campo", 
                                           style=discord.TextStyle.short, custom_id="field_name", max_length=256))
                self.add_item(ui.TextInput(label="Valor do Campo (max 1024 chars)", placeholder="Ex: Conteúdo do campo", 
                                           style=discord.TextStyle.paragraph, custom_id="field_value", max_length=1024))
                self.add_item(ui.TextInput(label="Inline? (sim/não)", placeholder="Digite 'sim' para inline, 'não' para bloco", 
                                           style=discord.TextStyle.short, custom_id="field_inline", required=False, max_length=3))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) # Deferir interação do modal para evitar timeout

                name = self.children[0].value.strip()
                value = self.children[1].value.strip()
                inline_str = self.children[2].value.lower().strip()
                inline = inline_str == 'sim'

                if not name or not value:
                    await interaction.followup.send("Nome e Valor do campo são obrigatórios.", ephemeral=True)
                    return

                if 'fields' not in self.parent_view.parent_view.current_embed_data:
                    self.parent_view.parent_view.current_embed_data['fields'] = []
                
                self.parent_view.parent_view.current_embed_data['fields'].append({
                    'name': name,
                    'value': value,
                    'inline': inline
                })
                
                await self.parent_view._update_field_display(interaction) # Atualiza o painel de campos
                await self.parent_view.parent_view.update_panel(interaction) # Atualiza o painel principal do embed
                await interaction.followup.send("Campo adicionado com sucesso!", ephemeral=True)
        
        add_field_modal = AddFieldModal(parent_view=self)
        await interaction.response.send_modal(add_field_modal)

    @ui.button(label="Remover Campo", style=discord.ButtonStyle.danger)
    async def remove_field_button(self, interaction: discord.Interaction, button: ui.Button):
        fields_data = self.parent_view.current_embed_data.get('fields', [])
        if not fields_data:
            await interaction.response.send_message("Não há campos para remover.", ephemeral=True)
            return

        options = []
        for i, field in enumerate(fields_data):
            # Limita o nome do campo para a opção do select para 100 caracteres
            field_name_display = field.get('name', 'Campo Sem Nome')
            if len(field_name_display) > 80: # Deixa espaço para "(...)" e o número
                field_name_display = field_name_display[:77] + "..."
            options.append(discord.SelectOption(label=f"{i+1}. {field_name_display}", value=str(i)))

        class RemoveFieldSelect(ui.Select):
            def __init__(self, select_options):
                # Limite de 25 opções em Select
                super().__init__(placeholder="Selecione o campo para remover...", min_values=1, max_values=1, 
                                 options=select_options[:25], custom_id="remove_field_select")
            
            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) # Deferir a interação do select
                original_view = self.view.parent_view # A view do select é a FieldManagementView
                
                index_to_remove = int(self.values[0])
                if 0 <= index_to_remove < len(original_view.parent_view.current_embed_data['fields']):
                    removed_field = original_view.parent_view.current_embed_data['fields'].pop(index_to_remove)
                    await original_view._update_field_display(interaction) # Atualiza o painel de campos
                    await original_view.parent_view.update_panel(interaction) # Atualiza o painel principal do embed
                    await interaction.followup.send(f"Campo **`{removed_field.get('name', 'Sem Nome')}`** removido com sucesso!", ephemeral=True)
                else:
                    await interaction.followup.send("Erro: Índice de campo inválido. Tente novamente.", ephemeral=True)

        class RemoveFieldSelectionView(ui.View): # Renomeado para evitar conflito e ser mais descritivo
            def __init__(self, select_options):
                super().__init__(timeout=60)
                self.add_item(RemoveFieldSelect(select_options))

        await interaction.response.send_message("Qual campo você gostaria de remover?", view=RemoveFieldSelectionView(options), ephemeral=True)

    @ui.button(label="Voltar ao Painel Principal", style=discord.ButtonStyle.secondary, row=4)
    async def back_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True) # Deferir para evitar "interação falhou"
        
        # Desabilita esta view (FieldManagementView)
        for item in self.children:
            item.disabled = True
        if self.message: # Garante que a mensagem existe antes de tentar editá-la
            await self.message.edit(content="Retornando ao criador de embeds...", view=self)

        # Reabilita os botões da view principal (EmbedCreatorMainView)
        if self.parent_view.message: # Garante que a mensagem principal existe
            for item in self.parent_view.children:
                item.disabled = False
            await self.parent_view.message.edit(view=self.parent_view)
        
        await interaction.followup.send("Retornou ao criador de embeds principal.", ephemeral=True)


# View para o painel principal do EmbedCreator
class EmbedCreatorMainView(ui.View):
    def __init__(self, bot: commands.Bot, current_embed_data: dict = None, loaded_embed_name: str = None):
        super().__init__(timeout=300) # Timeout de 5 minutos
        self.bot = bot
        self.message = None # Para armazenar a mensagem do painel
        self.loaded_embed_name = loaded_embed_name # Armazena o nome do embed carregado

        # Inicializa com valores padrão garantidos como strings vazias ou None para cor e URLs
        self.current_embed_data = {
            'title': '',
            'description': '',
            'color': None, 
            'fields': [],
            'author_name': None,
            'author_icon_url': None,
            'image_url': None,
            'footer_text': None,
            'footer_icon_url': None,
            'url': None, # Adicionado suporte para URL principal do embed
            'thumbnail_url': None # Adicionado suporte para Thumbnail
        }
        
        # Se houver dados existentes, atualiza, garantindo que title/description sejam strings e outros sejam None se vazios
        if current_embed_data:
            self.current_embed_data['title'] = str(current_embed_data.get('title', ''))
            self.current_embed_data['description'] = str(current_embed_data.get('description', ''))
            self.current_embed_data['color'] = current_embed_data.get('color', None)
            self.current_embed_data['fields'] = current_embed_data.get('fields', [])
            
            # Limpa strings vazias para None para campos opcionais com URL
            self.current_embed_data['author_name'] = current_embed_data.get('author_name', None) or None
            self.current_embed_data['author_icon_url'] = current_embed_data.get('author_icon_url', None) or None
            self.current_embed_data['image_url'] = current_embed_data.get('image_url', None) or None
            self.current_embed_data['footer_text'] = current_embed_data.get('footer_text', None) or None
            self.current_embed_data['footer_icon_url'] = current_embed_data.get('footer_icon_url', None) or None
            self.current_embed_data['url'] = current_embed_data.get('url', None) or None
            self.current_embed_data['thumbnail_url'] = current_embed_data.get('thumbnail_url', None) or None


    async def on_timeout(self):
        if self.message:
            for item in self.children:
                item.disabled = True
            await self.message.edit(content="Sessão do criador de embeds expirada. Use `/embed_creator` ou `/embed_load` para iniciar uma nova.", view=self)

    async def update_panel(self, interaction: discord.Interaction):
        """Atualiza a mensagem do painel com o embed atual."""
        embed_status = discord.Embed(
            title="🛠️ Criador de Embeds Interativo", 
            description="Use os botões abaixo para configurar seu embed. A pré-visualização é atualizada em tempo real!"
        )
        embed_status.add_field(name="Título", value=f"**`{self.current_embed_data.get('title') or 'Nenhum'}`**", inline=False)
        
        # Limita a descrição exibida no painel para não ficar muito longa
        display_description = self.current_embed_data.get('description', 'Nenhuma') or "Nenhuma"
        if len(display_description) > 100:
            display_description = display_description[:97] + "..."
        embed_status.add_field(name="Descrição", value=f"**`{display_description}`**", inline=False)
        
        embed_status.add_field(name="Cor", value=f"**`{self.current_embed_data.get('color') or 'Nenhuma'}`**", inline=True)
        embed_status.add_field(name="URL (Principal)", value="Configurada" if self.current_embed_data.get('url') else "Nenhuma", inline=True)
        embed_status.add_field(name="Autor", value=f"**`{self.current_embed_data.get('author_name') or 'Nenhum'}`**", inline=False)
        embed_status.add_field(name="Imagem (Principal)", value="Configurada" if self.current_embed_data.get('image_url') else "Nenhuma", inline=True)
        embed_status.add_field(name="Thumbnail", value="Configurada" if self.current_embed_data.get('thumbnail_url') else "Nenhuma", inline=True)
        embed_status.add_field(name="Rodapé", value="Configurado" if self.current_embed_data.get('footer_text') else "Nenhum", inline=False)
        embed_status.add_field(name="Campos", value=f"**`{len(self.current_embed_data.get('fields', []))}`** campos", inline=True)
        
        if self.loaded_embed_name:
            embed_status.set_footer(text=f"Editando embed salvo: {self.loaded_embed_name}")

        # Cria uma pré-visualização do embed
        preview_embed = self._create_preview_embed()
        
        # Lógica para enviar ou editar a mensagem do painel
        if self.message:
            await self.message.edit(embeds=[embed_status, preview_embed], view=self)
        else:
            if interaction.response.is_done():
                self.message = await interaction.followup.send(embeds=[embed_status, preview_embed], view=self, ephemeral=True)
            else:
                await interaction.response.send_message(embeds=[embed_status, preview_embed], view=self, ephemeral=True)
                self.message = await interaction.original_response()
            
    def _create_preview_embed(self) -> discord.Embed:
        """Cria um discord.Embed a partir dos dados atuais para pré-visualização ou envio."""
        data = self.current_embed_data
        embed = discord.Embed()
        
        embed.title = str(data.get('title', ''))
        # Discord exige que embed tenha pelo menos title ou description. 
        # Se ambos estiverem vazios, adicione uma descrição padrão para não dar erro na API.
        embed.description = str(data.get('description', ''))
        if not embed.title.strip() and not embed.description.strip(): 
            embed.description = "Pré-visualização do Embed (Defina Título ou Descrição)"

        # Tentar definir a cor
        if 'color' in data and data['color'] is not None: 
            try:
                color_value = str(data['color']).strip()
                if color_value.startswith('#'): # Hex com #
                    embed.color = discord.Color(int(color_value[1:], 16))
                elif color_value.startswith('0x'): # Hex com 0x
                    embed.color = discord.Color(int(color_value, 16))
                elif color_value.isdigit(): # Decimal
                    embed.color = discord.Color(int(color_value))
                else: # Fallback para string de cor inválida
                    raise ValueError("Formato de cor inválido. Use #RRGGBB, 0xRRGGBB ou um número decimal.")
            except (ValueError, TypeError) as e:
                logging.warning(f"Cor inválida fornecida ({data.get('color')}): {e}. Usando cor padrão.")
                embed.color = discord.Color.default()
        else:
            embed.color = discord.Color.default() # Cor padrão se não especificada ou None

        # Configurar Autor
        author_name = data.get('author_name')
        author_icon_url = data.get('author_icon_url')
        if author_name:
            # Apenas define o ícone se for uma URL válida
            if author_icon_url and is_valid_url(author_icon_url):
                embed.set_author(name=author_name, icon_url=author_icon_url)
            else:
                embed.set_author(name=author_name)

        # Configurar Imagem Principal
        image_url = data.get('image_url')
        if image_url and is_valid_url(image_url):
            embed.set_image(url=image_url)

        # Configurar Thumbnail
        thumbnail_url = data.get('thumbnail_url')
        if thumbnail_url and is_valid_url(thumbnail_url):
            embed.set_thumbnail(url=thumbnail_url)

        # Configurar URL principal do embed
        embed_url = data.get('url')
        if embed_url and is_valid_url(embed_url):
            embed.url = embed_url

        # Configurar Rodapé
        footer_text = data.get('footer_text')
        footer_icon_url = data.get('footer_icon_url')
        if footer_text:
            # Apenas define o ícone se for uma URL válida
            if footer_icon_url and is_valid_url(footer_icon_url):
                embed.set_footer(text=footer_text, icon_url=footer_icon_url)
            else:
                embed.set_footer(text=footer_text)

        # Adicionar Campos
        if 'fields' in data:
            for field in data['fields']:
                field_name = str(field.get('name', ''))
                field_value = str(field.get('value', ''))
                # Discord API: campos vazios podem causar erros. Garanta que não sejam vazios.
                if field_name.strip() == "":
                    field_name = "Nome Inválido"
                if field_value.strip() == "":
                    field_value = "Valor Inválido"
                
                embed.add_field(name=field_name, value=field_value, inline=field.get('inline', False))
        return embed

    # --- Botões da View Principal ---

    @ui.button(label="Definir Título", style=discord.ButtonStyle.primary, row=0)
    async def set_title_button(self, interaction: discord.Interaction, button: ui.Button):
        class TitleModal(ui.Modal, title="Definir Título do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_title = self.parent_view.current_embed_data.get('title', '')
                self.add_item(ui.TextInput(label="Título (max 256 chars)", placeholder="Digite o novo título...", 
                                           style=discord.TextStyle.short, custom_id="new_title", 
                                           default=current_title, max_length=256))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) 
                self.parent_view.current_embed_data['title'] = self.children[0].value
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Título atualizado!", ephemeral=True)
        
        title_modal = TitleModal(parent_view=self)
        await interaction.response.send_modal(title_modal)

    @ui.button(label="Definir Descrição", style=discord.ButtonStyle.primary, row=0)
    async def set_description_button(self, interaction: discord.Interaction, button: ui.Button):
        class DescriptionModal(ui.Modal, title="Definir Descrição do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_description = self.parent_view.current_embed_data.get('description', '')
                self.add_item(ui.TextInput(label="Descrição (max 4096 chars)", placeholder="Digite a nova descrição...", 
                                           style=discord.TextStyle.paragraph, custom_id="new_description", 
                                           default=current_description, max_length=4096))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) 
                self.parent_view.current_embed_data['description'] = self.children[0].value
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Descrição atualizada!", ephemeral=True)
        
        description_modal = DescriptionModal(parent_view=self)
        await interaction.response.send_modal(description_modal)

    @ui.button(label="Definir Cor", style=discord.ButtonStyle.primary, row=0)
    async def set_color_button(self, interaction: discord.Interaction, button: ui.Button):
        class ColorModal(ui.Modal, title="Definir Cor do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_color = self.parent_view.current_embed_data.get('color', '') or '' # Garante string vazia para default
                self.add_item(ui.TextInput(label="Cor (Hex #RRGGBB ou Decimal)", placeholder="#RRGGBB ou 0xRRGGBB ou número", 
                                           style=discord.TextStyle.short, required=False, custom_id="new_color", 
                                           default=str(current_color))) # Converte para string
            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                color_value = self.children[0].value.strip()
                original_view = self.parent_view
                
                if not color_value:
                    original_view.current_embed_data['color'] = None # Limpa a cor
                    await interaction.followup.send("Cor removida. Usando cor padrão do Discord.", ephemeral=True)
                else:
                    try:
                        # Tenta converter a cor para verificar se é válida
                        if color_value.startswith('#'):
                            int(color_value[1:], 16)
                        elif color_value.startswith('0x'):
                            int(color_value, 16)
                        elif color_value.isdigit():
                            int(color_value)
                        else:
                            raise ValueError("Formato de cor inválido.")
                        
                        original_view.current_embed_data['color'] = color_value
                        await interaction.followup.send(f"Cor definida para `{color_value}`.", ephemeral=True)
                    except ValueError:
                        await interaction.followup.send("Formato de cor inválido. Use um valor Hex (#RRGGBB, 0xRRGGBB) ou um número decimal.", ephemeral=True)
                        original_view.current_embed_data['color'] = None # Define como None em caso de erro
                        
                await original_view.update_panel(interaction)
        
        color_modal = ColorModal(parent_view=self)
        await interaction.response.send_modal(color_modal)

    @ui.button(label="Definir URL Principal", style=discord.ButtonStyle.primary, row=1) # Novo botão
    async def set_url_button(self, interaction: discord.Interaction, button: ui.Button):
        class URLModal(ui.Modal, title="Definir URL Principal do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_url = self.parent_view.current_embed_data.get('url', '')
                self.add_item(ui.TextInput(label="URL Principal", placeholder="Ex: https://seusite.com (Clique no título)", 
                                           style=discord.TextStyle.short, custom_id="new_url", 
                                           default=current_url, required=False))
            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                url_value = self.children[0].value.strip()
                if url_value and not is_valid_url(url_value):
                    await interaction.followup.send("URL inválida. Certifique-se de que começa com `http://` ou `https://`.", ephemeral=True)
                    return
                
                self.parent_view.current_embed_data['url'] = url_value if url_value else None
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("URL principal atualizada!", ephemeral=True)
        
        url_modal = URLModal(parent_view=self)
        await interaction.response.send_modal(url_modal)

    @ui.button(label="Definir Autor", style=discord.ButtonStyle.secondary, row=1)
    async def set_author_button(self, interaction: discord.Interaction, button: ui.Button):
        class AuthorModal(ui.Modal, title="Definir Autor do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_author_name = self.parent_view.current_embed_data.get('author_name', '')
                current_author_icon = self.parent_view.current_embed_data.get('author_icon_url', '')

                self.add_item(ui.TextInput(label="Nome do Autor (max 256 chars)", placeholder="Nome do autor", 
                                           style=discord.TextStyle.short, custom_id="author_name", 
                                           default=current_author_name, required=False, max_length=256))
                self.add_item(ui.TextInput(label="URL do Ícone do Autor (Opcional)", placeholder="URL da imagem (ex: avatar do autor)", 
                                           style=discord.TextStyle.short, custom_id="author_icon_url", 
                                           default=current_author_icon, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) 
                name = self.children[0].value.strip()
                icon_url = self.children[1].value.strip()

                if icon_url and not is_valid_url(icon_url):
                    await interaction.followup.send("URL do ícone do autor inválida. Tente novamente.", ephemeral=True)
                    return

                self.parent_view.current_embed_data['author_name'] = name if name else None
                self.parent_view.current_embed_data['author_icon_url'] = icon_url if icon_url else None
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Autor atualizado!", ephemeral=True)
        
        author_modal = AuthorModal(parent_view=self)
        await interaction.response.send_modal(author_modal)

    @ui.button(label="Definir Imagem", style=discord.ButtonStyle.secondary, row=1)
    async def set_image_button(self, interaction: discord.Interaction, button: ui.Button):
        class ImageModal(ui.Modal, title="Definir Imagem do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_image_url = self.parent_view.current_embed_data.get('image_url', '')
                self.add_item(ui.TextInput(label="URL da Imagem Principal", placeholder="URL da imagem (Ex: https://example.com/image.png)", 
                                           style=discord.TextStyle.short, custom_id="image_url", 
                                           default=current_image_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) 
                image_url = self.children[0].value.strip()
                if image_url and not is_valid_url(image_url):
                    await interaction.followup.send("URL da imagem inválida. Tente novamente.", ephemeral=True)
                    return

                self.parent_view.current_embed_data['image_url'] = image_url if image_url else None
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Imagem principal atualizada!", ephemeral=True)
        
        image_modal = ImageModal(parent_view=self)
        await interaction.response.send_modal(image_modal)

    @ui.button(label="Definir Thumbnail", style=discord.ButtonStyle.secondary, row=2) # Novo botão
    async def set_thumbnail_button(self, interaction: discord.Interaction, button: ui.Button):
        class ThumbnailModal(ui.Modal, title="Definir Thumbnail do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_thumbnail_url = self.parent_view.current_embed_data.get('thumbnail_url', '')
                self.add_item(ui.TextInput(label="URL da Thumbnail", placeholder="URL da imagem pequena no canto", 
                                           style=discord.TextStyle.short, custom_id="thumbnail_url", 
                                           default=current_thumbnail_url, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                thumbnail_url = self.children[0].value.strip()
                if thumbnail_url and not is_valid_url(thumbnail_url):
                    await interaction.followup.send("URL da thumbnail inválida. Tente novamente.", ephemeral=True)
                    return

                self.parent_view.current_embed_data['thumbnail_url'] = thumbnail_url if thumbnail_url else None
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Thumbnail atualizada!", ephemeral=True)
        
        thumbnail_modal = ThumbnailModal(parent_view=self)
        await interaction.response.send_modal(thumbnail_modal)


    @ui.button(label="Definir Rodapé", style=discord.ButtonStyle.secondary, row=2)
    async def set_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        class FooterModal(ui.Modal, title="Definir Rodapé do Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                current_footer_text = self.parent_view.current_embed_data.get('footer_text', '')
                current_footer_icon = self.parent_view.current_embed_data.get('footer_icon_url', '')

                self.add_item(ui.TextInput(label="Texto do Rodapé (max 2048 chars)", placeholder="Texto do rodapé", 
                                           style=discord.TextStyle.short, custom_id="footer_text", 
                                           default=current_footer_text, required=False, max_length=2048))
                self.add_item(ui.TextInput(label="URL do Ícone do Rodapé (Opcional)", placeholder="URL da imagem do ícone", 
                                           style=discord.TextStyle.short, custom_id="footer_icon_url", 
                                           default=current_footer_icon, required=False))

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) 
                text = self.children[0].value.strip()
                icon_url = self.children[1].value.strip()

                if icon_url and not is_valid_url(icon_url):
                    await interaction.followup.send("URL do ícone do rodapé inválida. Tente novamente.", ephemeral=True)
                    return

                self.parent_view.current_embed_data['footer_text'] = text if text else None
                self.parent_view.current_embed_data['footer_icon_url'] = icon_url if icon_url else None
                await self.parent_view.update_panel(interaction)
                await interaction.followup.send("Rodapé atualizado!", ephemeral=True)
        
        footer_modal = FooterModal(parent_view=self)
        await interaction.response.send_modal(footer_modal)

    @ui.button(label="Gerenciar Campos", style=discord.ButtonStyle.primary, row=3)
    async def manage_fields_button(self, interaction: discord.Interaction, button: ui.Button):
        # Desabilita a view principal temporariamente
        for item in self.children:
            item.disabled = True
        if self.message: # Garante que a mensagem existe antes de tentar editá-la
            await self.message.edit(view=self)

        # Abre a nova view de gerenciamento de campos
        field_view = FieldManagementView(parent_view=self)
        # Deferir a interação ANTES de chamar _update_field_display
        await interaction.response.defer(ephemeral=True) 
        await field_view._update_field_display(interaction) # Envia a mensagem inicial do painel de campos

    @ui.button(label="Limpar Embed", style=discord.ButtonStyle.danger, row=3) # Novo botão
    async def clear_embed_button(self, interaction: discord.Interaction, button: ui.Button):
        # Pergunta de confirmação antes de limpar tudo
        class ConfirmClearView(ui.View):
            def __init__(self, parent_view_ref):
                super().__init__(timeout=30)
                self.parent_view_ref = parent_view_ref
                self.confirmed = False

            @ui.button(label="Sim, Limpar Tudo", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction: discord.Interaction, button: ui.Button):
                self.confirmed = True
                self.stop() # Para o timeout da view de confirmação
                await interaction.response.defer(ephemeral=True) # Deferir interação do botão de confirmação
                self.parent_view_ref.current_embed_data = { # Reseta para o estado inicial
                    'title': '',
                    'description': '',
                    'color': None, 
                    'fields': [],
                    'author_name': None,
                    'author_icon_url': None,
                    'image_url': None,
                    'footer_text': None,
                    'footer_icon_url': None,
                    'url': None,
                    'thumbnail_url': None
                }
                self.parent_view_ref.loaded_embed_name = None # Limpa o nome do embed carregado
                await self.parent_view_ref.update_panel(interaction) # Atualiza o painel principal
                await interaction.followup.send("O embed foi completamente limpo!", ephemeral=True)
                
                # Desabilita botões da mensagem de confirmação
                for item in self.children:
                    item.disabled = True
                if self.message: await self.message.edit(view=self)


            @ui.button(label="Não, Manter Embed", style=discord.ButtonStyle.secondary)
            async def cancel(self, interaction: discord.Interaction, button: ui.Button):
                self.stop() # Para o timeout da view de confirmação
                await interaction.response.defer(ephemeral=True) # Deferir interação do botão de cancelamento
                await interaction.followup.send("Ação de limpeza cancelada.", ephemeral=True)
                
                # Desabilita botões da mensagem de confirmação
                for item in self.children:
                    item.disabled = True
                if self.message: await self.message.edit(view=self)

            async def on_timeout(self):
                if not self.confirmed:
                    if self.message:
                        for item in self.children:
                            item.disabled = True
                        await self.message.edit(content="A confirmação de limpeza expirou.", view=self)

        confirm_view = ConfirmClearView(self)
        # Armazena a mensagem da confirmação para desabilitar os botões no timeout
        await interaction.response.send_message("Tem certeza que deseja limpar **TODO** o embed atual? Isso não pode ser desfeito.", 
                                                view=confirm_view, ephemeral=True)
        confirm_view.message = await interaction.original_response()


    @ui.button(label="Salvar Embed", style=discord.ButtonStyle.success, row=4)
    async def save_embed_button(self, interaction: discord.Interaction, button: ui.Button):
        class SaveModal(ui.Modal, title="Salvar Embed"):
            def __init__(self, parent_view: ui.View):
                super().__init__()
                self.parent_view = parent_view
                # Pré-preenche o nome do embed se um foi carregado
                default_name = self.parent_view.loaded_embed_name if self.parent_view.loaded_embed_name else ""
                self.add_item(ui.TextInput(label="Nome para Salvar (único)", placeholder="Nome único para este embed", 
                                           style=discord.TextStyle.short, custom_id="embed_name", 
                                           default=default_name, max_length=50)) # Limite de caracteres para nome

            async def on_submit(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) # Deferir a interação do modal
                name = self.children[0].value.strip()
                guild_id = interaction.guild_id
                original_view = self.parent_view
                embed_json = json.dumps(original_view.current_embed_data)

                if not name:
                    await interaction.followup.send("O nome do embed não pode ser vazio.", ephemeral=True)
                    return

                # Usar INSERT OR REPLACE INTO para permitir edição de embeds existentes
                success = execute_query(
                    "INSERT OR REPLACE INTO saved_embeds (guild_id, embed_name, embed_json) VALUES (?, ?, ?)",
                    (guild_id, name, embed_json)
                )
                if success:
                    original_view.loaded_embed_name = name # Atualiza o nome do embed carregado após salvar
                    await original_view.update_panel(interaction) # Atualiza o painel para refletir o nome
                    await interaction.followup.send(f"Embed **`{name}`** salvo (ou atualizado) com sucesso!", ephemeral=True)
                else:
                    await interaction.followup.send("Erro ao salvar o embed no banco de dados. Tente novamente.", ephemeral=True)
        
        save_modal = SaveModal(parent_view=self)
        await interaction.response.send_modal(save_modal)

    @ui.button(label="Enviar Embed", style=discord.ButtonStyle.success, row=4)
    async def send_embed_button(self, interaction: discord.Interaction, button: ui.Button):
        # Validação básica: Embed deve ter título ou descrição para ser enviável
        if not self.current_embed_data.get('title') and not self.current_embed_data.get('description'):
            await interaction.response.send_message("O embed deve ter pelo menos um título ou uma descrição para ser enviado.", ephemeral=True)
            return

        embed_to_send = self._create_preview_embed()
        
        class ChannelSelect(ui.Select):
            def __init__(self, guild_channels):
                options = [
                    discord.SelectOption(label=channel.name, value=str(channel.id))
                    for channel in guild_channels 
                    if isinstance(channel, discord.TextChannel) and channel.permissions_for(interaction.guild.me).send_messages # Apenas canais de texto onde o bot pode falar
                ]
                # Adiciona uma opção de fallback se nenhum canal for encontrado
                if not options:
                    options.append(discord.SelectOption(label="Nenhum canal de texto válido encontrado", value="none", default=True))

                super().__init__(placeholder="Selecione um canal...", min_values=1, max_values=1, options=options, custom_id="send_embed_channel_select")

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True) # Deferir a interação do select
                if self.values[0] == "none":
                    await interaction.followup.send("Não há canais de texto válidos para enviar o embed ou não tenho permissão neles.", ephemeral=True)
                    return

                channel_id = int(self.values[0])
                target_channel = interaction.guild.get_channel(channel_id)
                
                if not target_channel or not isinstance(target_channel, discord.TextChannel):
                    await interaction.followup.send("Canal não encontrado ou não é um canal de texto válido.", ephemeral=True)
                    return
                
                # Permissões mais detalhadas antes de enviar
                bot_permissions = target_channel.permissions_for(interaction.guild.me)
                if not bot_permissions.send_messages:
                    await interaction.followup.send(f"Não tenho permissão para enviar mensagens em {target_channel.mention}.", ephemeral=True)
                    return
                if not bot_permissions.embed_links:
                    await interaction.followup.send(f"Não tenho permissão para incorporar links em {target_channel.mention}. O embed pode não aparecer corretamente.", ephemeral=True)
                    # No entanto, ainda tentaremos enviar, mas com aviso
                
                try:
                    await target_channel.send(embed=embed_to_send)
                    await interaction.followup.send(f"Embed enviado para {target_channel.mention} com sucesso!", ephemeral=True)
                    # Desabilita os botões após o envio bem-sucedido
                    if self.view.message: # A view do select é SendEmbedView, que tem a mensagem
                        for item in self.view.children:
                            item.disabled = True
                        await self.view.message.edit(view=self.view)

                except discord.Forbidden:
                    await interaction.followup.send(f"Erro de permissão: Não consegui enviar o embed para {target_channel.mention}.", ephemeral=True)
                except Exception as e:
                    logging.error(f"Erro ao enviar embed: {e}", exc_info=True)
                    await interaction.followup.send(f"Ocorreu um erro inesperado ao enviar o embed: `{e}`", ephemeral=True)
                
        class SendEmbedSelectionView(ui.View): # Renomeado para evitar conflito e ser mais descritivo
            def __init__(self, guild_channels):
                super().__init__(timeout=60)
                self.add_item(ChannelSelect(guild_channels))
                self.message = None # Para armazenar a mensagem do seletor de canal

            async def on_timeout(self):
                if self.message:
                    for item in self.children:
                        item.disabled = True
                    await self.message.edit(content="Sessão de seleção de canal expirada.", view=self)

        send_view = SendEmbedSelectionView(interaction.guild.text_channels)
        await interaction.response.send_message("Para onde você gostaria de enviar este embed?", view=send_view, ephemeral=True)
        send_view.message = await interaction.original_response() # Armazena a mensagem do seletor

# --- Cog Principal ---
class EmbedCreatorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Certifica-se de que a tabela `saved_embeds` existe
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Cria a tabela 'saved_embeds' se ela não existir."""
        query = """
        CREATE TABLE IF NOT EXISTS saved_embeds (
            guild_id INTEGER NOT NULL,
            embed_name TEXT NOT NULL,
            embed_json TEXT NOT NULL,
            PRIMARY KEY (guild_id, embed_name)
        )
        """
        success = execute_query(query)
        if success:
            logging.info("Tabela 'saved_embeds' verificada/criada com sucesso.")
        else:
            logging.error("Falha ao criar/verificar tabela 'saved_embeds'.")

    @app_commands.command(name="embed_creator", description="Inicia o criador de embeds interativo.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_creator(self, interaction: discord.Interaction):
        view = EmbedCreatorMainView(self.bot)
        await interaction.response.defer(ephemeral=True) # Defer para evitar timeout
        await view.update_panel(interaction) # Envia o painel inicial

    @app_commands.command(name="embed_load", description="Carrega um embed salvo para edição.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(name="O nome do embed que você quer carregar.")
    async def embed_load(self, interaction: discord.Interaction, name: str):
        guild_id = interaction.guild_id
        result = execute_query(
            "SELECT embed_json FROM saved_embeds WHERE guild_id = ? AND embed_name = ?",
            (guild_id, name),
            fetchone=True
        )
        if result:
            try:
                embed_data = json.loads(result[0])
                view = EmbedCreatorMainView(self.bot, current_embed_data=embed_data, loaded_embed_name=name)
                await interaction.response.defer(ephemeral=True)
                await view.update_panel(interaction)
                logging.info(f"Embed '{name}' carregado por {interaction.user.id} na guild {interaction.guild.id}.")
            except json.JSONDecodeError as e:
                await interaction.response.send_message(f"Erro ao carregar o embed '{name}': Dados corrompidos. `{e}`", ephemeral=True)
                logging.error(f"Erro JSON ao carregar embed '{name}' para guild {guild_id}: {e}", exc_info=True)
        else:
            await interaction.response.send_message(f"Embed **`{name}`** não encontrado. Use `/embed_list` para ver os disponíveis.", ephemeral=True)

    @app_commands.command(name="embed_list", description="Lista todos os embeds salvos no servidor.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_list(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        results = execute_query(
            "SELECT embed_name FROM saved_embeds WHERE guild_id = ?",
            (guild_id,),
            fetchall=True
        )
        if results:
            embed_names = [f"- `{r[0]}`" for r in results] # Formata com `- ` e backticks
            embed = discord.Embed(
                title="📚 Embeds Salvos",
                description="Aqui estão todos os embeds salvos neste servidor:\n" + "\n".join(embed_names),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total de {len(embed_names)} embeds salvos.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Nenhum embed salvo neste servidor. Use `/embed_creator` e depois 'Salvar Embed' para criar um!", ephemeral=True)

    @app_commands.command(name="embed_delete", description="Deleta um embed salvo.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(name="O nome do embed que você quer deletar.")
    async def embed_delete(self, interaction: discord.Interaction, name: str):
        guild_id = interaction.guild_id
        # Primeiro, verifica se o embed existe antes de tentar deletar
        check_exists = execute_query(
            "SELECT 1 FROM saved_embeds WHERE guild_id = ? AND embed_name = ?",
            (guild_id, name),
            fetchone=True
        )
        if not check_exists:
            await interaction.response.send_message(f"Embed **`{name}`** não encontrado neste servidor. Use `/embed_list` para ver os disponíveis.", ephemeral=True)
            return

        success = execute_query(
            "DELETE FROM saved_embeds WHERE guild_id = ? AND embed_name = ?",
            (guild_id, name)
        )
        if success:
            await interaction.response.send_message(f"Embed **`{name}`** deletado com sucesso!", ephemeral=True)
            logging.info(f"Embed '{name}' deletado por {interaction.user.id} na guild {interaction.guild.id}.")
        else:
            await interaction.response.send_message(f"Erro ao deletar o embed **`{name}`**. Tente novamente.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCreatorCog(bot))