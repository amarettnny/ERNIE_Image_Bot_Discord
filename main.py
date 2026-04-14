import discord
from discord.ext import commands, tasks
from discord import app_commands
import requests
import base64
import os
from io import BytesIO
from datetime import datetime, time, timedelta
from dotenv import load_dotenv
import database

# 1. 加载配置
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
# 处理多管理员列表
raw_owners = os.getenv("OWNER_IDS", "")
OWNER_IDS = [i.strip() for i in raw_owners.split(",") if i.strip()]

# 2. 常量配置
API_URL = "https://aistudio.baidu.com/llm/lmapi/v3/images/generations"
EMOJI_NAME = "ERNIE_ThumbsUp" 
TARGET_CHANNEL_NAME = "🎨｜ernie-image-creator-hub"

RATIO_MAP = {
    "1:1": "1024x1024", "16:9": "1024x576", "9:16": "576x1024",
    "4:3": "1024x768", "3:4": "768x1024",
}

class ErnieBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        database.init_db()
        await self.tree.sync()
        print(f"Bot is ready. Slash commands synced.")

    
bot = ErnieBot()

# ── /imagine: 生图并存入数据库 ──
@bot.tree.command(name="imagine", description="Generate an image with ERNIE-Image 8B")
@app_commands.describe(prompt="What do you want to see?", ratio="Aspect ratio")
@app_commands.choices(ratio=[app_commands.Choice(name=k, value=k) for k in RATIO_MAP.keys()])
async def imagine(interaction: discord.Interaction, prompt: str, ratio: str = "1:1"):
    await interaction.response.defer()

    token = database.get_token()
    if not token:
        await interaction.followup.send("Error: Access Token not found.", ephemeral=True)
        return

    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}
    payload = {
        "model": "ernie-image-turbo",
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
        "size": RATIO_MAP.get(ratio, "1024x1024"),
        "use_pe": True
    }
    
    try:
        res = requests.post(API_URL, json=payload, headers=headers, timeout=60).json()
        if "data" not in res:
            raise Exception(res.get("error", {}).get("message", "API Error"))

        img_data = base64.b64decode(res["data"][0]["b64_json"])
        msg = await interaction.followup.send(
            content=f"🎨 **Prompt:** {prompt}",
            file=discord.File(fp=BytesIO(img_data), filename="ernie.png"),
            wait=True,
        )
        
        # 核心：必须存入数据库，否则 gallery 读不到
        database.add_generation(str(msg.id), str(interaction.user.id), interaction.channel.name, prompt)
        
    except Exception as e:
        await interaction.followup.send(f"Failed: {str(e)}")

# ── /gallery: 用户隐身查看实时排名 ──
@bot.tree.command(name="gallery", description="Check real-time top 10 (Only you can see this)")
async def gallery(interaction: discord.Interaction):
    top_works, mode_name = database.get_dynamic_gallery()
    
    if not top_works or mode_name == "No Data":
        await interaction.response.send_message("The gallery is empty right now!", ephemeral=True)
        return

    embed = discord.Embed(title=f"📊 Current Rankings: {mode_name}", color=0x00ffcc)
    embed.set_footer(text="Keep clapping for your favorites! Final winners announced Monday.")

    for i, (uid, prompt, votes) in enumerate(top_works, 1):
        embed.add_field(
            name=f"Rank #{i} | {votes} :{EMOJI_NAME}:",
            value=f"Artist: <@{uid}>\nPrompt: *{prompt[:60]}...*",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ── /config: 只有 OWNER_IDS 里的用户能执行 ──
@bot.tree.command(name="config", description="[Owner Only] Update Access Token")
async def config(interaction: discord.Interaction, token: str):
    if str(interaction.user.id) not in OWNER_IDS:
        await interaction.response.send_message("Denied: Owner whitelist only.", ephemeral=True)
        return

    database.set_token(token)
    await interaction.response.send_message("Token saved (Database updated).", ephemeral=True)

# ── 自动同步点赞数逻辑 ──
async def sync_reactions(payload):
    # 如果表情名字匹配，抓取最新数量更新数据库
    if payload.emoji.name == EMOJI_NAME:
        channel = bot.get_channel(payload.channel_id)
        msg = await channel.fetch_message(payload.message_id)
        count = next((r.count for r in msg.reactions if getattr(r.emoji, 'name', '') == EMOJI_NAME), 0)
        database.update_reactions(str(payload.message_id), count)

@bot.event
async def on_raw_reaction_add(payload):
    await sync_reactions(payload)

@bot.event
async def on_raw_reaction_remove(payload):
    await sync_reactions(payload)

# 启动
if DISCORD_TOKEN:
    bot.run(DISCORD_TOKEN)
else:
    print("CRITICAL: DISCORD_TOKEN not found in .env!")