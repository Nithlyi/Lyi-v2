import discord
from discord.ext import commands
from discord import app_commands
from discord.errors import HTTPException # Adicione esta importação para capturar erros HTTP
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SayCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="say", description="Faz o bot enviar uma mensagem em um canal específico.")
    @app_commands.describe(
        channel="O canal onde a mensagem será enviada.",
        message="O conteúdo da mensagem que o bot irá enviar."
    )
    @app_commands.checks.has_permissions(manage_messages=True) # Requer permissão para gerenciar mensagens
    # Opcional: Adicione um cooldown para evitar spam, se necessário.
    # @app_commands.checks.cooldown(1, 5, key=lambda i: i.user.id) # Exemplo: 1 uso a cada 5 segundos por usuário
    async def say(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str):
        # 1. Deferir a interação para evitar timeout do Discord (correto!)
        await interaction.response.defer(ephemeral=True) 

        # 2. Verifica se o bot tem permissão para enviar mensagens no canal alvo
        # Removida a linha duplicada de `followup.send` e `logging.warning`.
        # `edit_original_response` já é a forma correta de atualizar a resposta do defer.
        if not channel.permissions_for(interaction.guild.me).send_messages:
            error_msg = f"Não tenho permissão para enviar mensagens em {channel.mention}."
            await interaction.edit_original_response(content=error_msg)
            logging.warning(f"Comando /say: Bot sem permissão para enviar mensagem no canal {channel.id} na guild {interaction.guild.id}. Mensagem: {error_msg}")
            return # Sai da função imediatamente após avisar a falta de permissão

        try:
            # 3. Tenta enviar a mensagem no canal especificado
            await channel.send(message)
            logging.info(f"Comando /say usado por {interaction.user.id} para enviar mensagem em {channel.id} na guild {interaction.guild.id}.")
            
            # 4. Tenta editar a resposta original para confirmar o envio
            try:
                await interaction.edit_original_response(content=f"Mensagem enviada com sucesso em {channel.mention}.")
            except HTTPException as http_exc_success_edit:
                # Se falhar a edição da resposta (ex: por rate limit na API de webhook da interação), loga e tenta follow-up.
                logging.error(f"Comando /say: Falha ao editar resposta original de sucesso (HTTP {http_exc_success_edit.status}): {http_exc_success_edit}", exc_info=True)
                try:
                    await interaction.followup.send(f"Mensagem enviada com sucesso em {channel.mention}, mas falha ao atualizar a resposta do comando.", ephemeral=True)
                except Exception as followup_fail:
                     logging.error(f"Comando /say: Falha ao enviar followup após falha na edição: {followup_fail}", exc_info=True)


        except HTTPException as http_exc_send:
            # 5. Captura erros HTTP específicos ao *enviar a mensagem para o canal alvo*.
            # Isso inclui o erro 429 Too Many Requests que vimos antes.
            user_error_content = "Ocorreu um erro ao enviar a mensagem para o Discord."
            if http_exc_send.status == 429:
                user_error_content = f"Estou sendo rate limited pelo Discord ao tentar enviar a mensagem em {channel.mention}. Por favor, aguarde e tente novamente."

            logging.error(f"Comando /say: Erro HTTP ({http_exc_send.status}) ao enviar mensagem em {channel.id} na guild {interaction.guild.id}: {http_exc_send}", exc_info=True)

            # Tenta editar a resposta original para mostrar o erro ao usuário.
            # Como a interação foi deferida, edit_original_response é o correto, a menos que a edição em si falhe (ex: outro rate limit).
            try:
                 # Se o envio para o canal falhou, editamos a resposta deferida com a mensagem de erro.
                await interaction.edit_original_response(content=user_error_content)
            except Exception as edit_error_after_send_fail:
                 logging.error(f"Comando /say: Falha ao editar resposta original após erro de envio (HTTP {http_exc_send.status}): {edit_error_after_send_fail}", exc_info=True)
                 # Se a edição também falhar, tentamos um followup como último recurso.
                 try:
                      await interaction.followup.send(content="❌ Erro crítico ao enviar a mensagem e ao reportar o erro. Verifique os logs.", ephemeral=True)
                 except Exception as final_followup_fail:
                      logging.critical(f"Comando /say: Falha crítica ao enviar qualquer resposta após erro de envio e erro de edição: {final_followup_fail}", exc_info=True)


        except Exception as e:
            # 6. Captura quaisquer outros erros inesperados (erros de programação, etc.)
            logging.error(f"Comando /say: Erro inesperado ao executar o comando (durante envio ou outra operação): {e}", exc_info=True)
            # Tenta editar a resposta original para mostrar o erro genérico.
            try:
                await interaction.edit_original_response(content=f"Ocorreu um erro interno inesperado ao executar o comando: `{e}`")
            except Exception as edit_error_after_generic_fail:
                 logging.error(f"Comando /say: Falha ao editar resposta original ap��s erro genérico: {edit_error_after_generic_fail}", exc_info=True)
                 # Se a edição também falhar, tentamos um followup como último recurso.
                 try:
                      await interaction.followup.send(content="❌ Erro crítico ao executar o comando e ao reportar o erro. Verifique os logs.", ephemeral=True)
                 except Exception as final_generic_followup_fail:
                      logging.critical(f"Comando /say: Falha crítica ao enviar qualquer resposta após erro genérico e erro de edição: {final_generic_followup_fail}", exc_info=True)

# 7. Handler de erro para o comando /say (captura erros *antes* da execução do comando, como MissingPermissions, Cooldown, etc.)
# Este handler já está bem implementado para usar edit_original_response ou send_message conforme necessário.
@SayCommand.say.error
async def say_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Verifica se a interação já foi respondida ou deferida.
    if interaction.response.is_done():
        # Se já foi deferido ou respondido, edite a resposta original ou envie um follow-up.
        # O check interaction.response.is_done() já cuida da lógica entre edit_original_response e followup.send após defer.
        # Para este handler de erro (que ocorre ANTES do corpo do comando), interaction.response.is_done() será False
        # a menos que a Interaction for respondida por outro meio antes de chegar aqui (cenário raro mas possível).
        send_func = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    else:
        # Se não foi respondido/deferido, use send_message.
        send_func = interaction.response.send_message

    # Lida com tipos específicos de erros
    if isinstance(error, app_commands.CommandOnCooldown):
        remaining_time = int(error.retry_after)
        # Garante que estamos usando a função correta (send_func) determinada acima
        await send_func(
            f"Este comando está em cooldown! Por favor, aguarde **{remaining_time}** segundos para usá-lo novamente.",
            ephemeral=True
        )
        logging.warning(f"Comando /say em cooldown para {interaction.user.id} na guild {interaction.guild.id}. Tempo restante: {remaining_time}s.")
    elif isinstance(error, app_commands.MissingPermissions):
        missing_perms = [p.replace('_', ' ').title() for p in error.missing_permissions]
         # Garante que estamos usando a função correta (send_func)
        await send_func(
            f"Você não tem as permissões necessárias para usar este comando. Permissões exigidas: **{', '.join(missing_perms)}**.",
            ephemeral=True
        )
        logging.warning(f"Comando /say: Usuário {interaction.user.id} sem permissões ({error.missing_permissions}) na guild {interaction.guild.id}.")
    elif isinstance(error, app_commands.NoPrivateMessage):
         # Garante que estamos usando a função correta (send_func)
        await send_func("Este comando não pode ser usado em mensagens privadas.", ephemeral=True)
        logging.warning(f"Comando /say: Tentativa de uso em DM por {interaction.user.id}.")
    elif isinstance(error, app_commands.CheckFailure):
         # Para outros check failures (como checks customizados que não levantam exceções mais específicas)
         # Garante que estamos usando a função correta (send_func)
        await send_func("Você não tem permissão para usar este comando aqui.", ephemeral=True)
        logging.warning(f"Comando /say: Check failure para o usuário {interaction.user.id} na guild {interaction.guild.id}.")
    else:
        # Erros genéricos ou não tratados neste handler (exceto os tratados no corpo do comando)
        logging.error(f"Erro inesperado no comando /say (handler de erro PRE-EXECUÇÃO): {error}", exc_info=True)
         # Garante que estamos usando a função correta (send_func)
        await send_func(f"Ocorreu um erro inesperado ao executar o comando: `{error}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SayCommand(bot))
