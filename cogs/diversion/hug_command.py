import discord
from discord.ext import commands
from discord import app_commands
import random
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class HugCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hug", description="Envie um abraço para outro membro!")
    @app_commands.describe(
        member="O membro que você deseja abraçar."
    )
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer() # Deferir a interação publicamente

        # Lista de GIFs de abraço (você pode adicionar mais aqui!)
        hug_gifs = [
            "https://media.giphy.com/media/wnsgfr0AxS8X6/giphy.gif", # 
            "https://media.giphy.com/media/GfXFVyS0P1qms/giphy.gif", # 
            "https://media.giphy.com/media/u9BxQbM5M0kQ/giphy.gif", # 
            "https://media.giphy.com/media/LrvnJpX2g40/giphy.gif", # 
            "https://media.giphy.com/media/qscdhWs5o3UFW/giphy.gif", # 
            "https://media.giphy.com/media/Vp3ftC4tE7mS0/giphy.gif", # 
            "https://media.giphy.com/media/ZBQhoPmIDK5Qo/giphy.gif", # 
            "https://media.giphy.com/media/sUIZWMnfd4qb6/giphy.gif", # 
            "https://media.giphy.com/media/EvYHULoN6Bd3O/giphy.gif", # 
            "https://media.giphy.com/media/l2QDM9JNxuKqBqzYs/giphy.gif", # 
            "https://media.discordapp.net/attachments/1385626050826076364/1385626612942245968/24bf9ea5632d759d4793dabbc51e89c6.gif?ex=68649898&is=68634718&hm=cb1100c8ccc590be8bc8f725f80c0ea5c8da557143c4048ec91b1778ea64b23e&=&width=400&height=186" # O GIF que você enviou
        ]
        
        chosen_gif = random.choice(hug_gifs)

        if member.id == interaction.user.id:
            response_message = f"{interaction.user.mention} se abraça! Que fofo! 🤗"
        else:
            response_message = f"{interaction.user.mention} abraçou {member.mention}! Que carinho! 🥰"

        embed = discord.Embed(
            description=response_message,
            color=discord.Color.pink()
        )
        embed.set_image(url=chosen_gif)
        embed.set_footer(text="Um abraço para você!")

        await interaction.followup.send(embed=embed)
        logging.info(f"Comando /hug usado por {interaction.user.id} para {member.id} na guild {interaction.guild.id}.")

async def setup(bot: commands.Bot):
    await bot.add_cog(HugCommand(bot))

