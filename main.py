import discord
from discord.ext import commands
from discord import app_commands
import requests
import base64
from io import BytesIO
import database
from openai import OpenAI

RATIO_MAP = {
    "1:1": "1024x1024",
    "16:9": "1024x576",
    "9:16": "576x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
}

API_URL = "https://aistudio.baidu.com/llm/lmapi/v3/images/generations"
EMOJI_NAME = "ERNIE_ThumbsUp"  # must match your server's custom emoji name exactly


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        database.init_db()
        await self.tree.sync()


bot = Bot()


# ── /config ──

@bot.tree.command(name="config", description="[Admin] Set the server's Baidu AI Studio access token")
@app_commands.default_permissions(administrator=True)
async def config(interaction: discord.Interaction, token: str):
    database.set_token(token)
    await interaction.response.send_message("Global token saved.", ephemeral=True)


# ── /imagine ──

@bot.tree.command(name="imagine", description="Generate an image with ERNIE")
@app_commands.describe(prompt="Image prompt", ratio="Aspect ratio")
@app_commands.choices(ratio=[
    app_commands.Choice(name="1:1", value="1:1"),
    app_commands.Choice(name="16:9", value="16:9"),
    app_commands.Choice(name="9:16", value="9:16"),
    app_commands.Choice(name="4:3", value="4:3"),
    app_commands.Choice(name="3:4", value="3:4"),
])
async def imagine(interaction: discord.Interaction, prompt: str, ratio: str = "1:1"):
    await interaction.response.defer()

    uid = str(interaction.user.id)
    token = database.get_token()
    if not token:
        await interaction.followup.send("No token configured yet. Ask an admin to run `/config`.")
        return

    database.ensure_user(uid)

    channel_name = interaction.channel.name

    # check daily limit before calling API
    is_daily = channel_name == "daily-showcase"
    already_checked_in = is_daily and database.has_daily_checkin(uid)

    # call Baidu API
    headers = {"Authorization": f"bearer {token}", "Content-Type": "application/json"}
    payload = {
        "model": "ernie-image-turbo",
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
        "size": RATIO_MAP.get(ratio, "1024x1024"),
        "seed": 42,
        "use_pe": True,
        "num_inference_steps": 8,
        "guidance_scale": 1.0
    }
    res = requests.post(API_URL, json=payload, headers=headers, timeout=60).json()
    print(f"[API] user={uid} prompt={prompt} response={res}")

    if "data" not in res:
        error_msg = res.get("error", {}).get("message", "Unknown error")
        await interaction.followup.send(f"Image generation failed: {error_msg}")
        return

    img_data = base64.b64decode(res["data"][0]["b64_json"])

    # send image
    msg = await interaction.followup.send(
        content=f"**Prompt:** {prompt}",
        file=discord.File(fp=BytesIO(img_data), filename="ernie.png"),
        wait=True,
    )

    # record generation (daily-showcase or theme-battle or other)
    database.add_generation(str(msg.id), uid, channel_name, prompt)

    # award daily check-in points (first /imagine in #daily-showcase per day)
    if is_daily and not already_checked_in:
        database.add_points(uid, 5)
        await interaction.followup.send("Daily check-in! +5 points", ephemeral=True)


# ── /checkin ──

@bot.tree.command(name="checkin", description="Check your current points")
async def checkin(interaction: discord.Interaction):
    pts = database.get_points(str(interaction.user.id))
    await interaction.response.send_message(f"Your points: **{pts}**", ephemeral=True)


# ── /gallery ──

@bot.tree.command(name="gallery", description="Top daily-showcase creations by popularity")
async def gallery(interaction: discord.Interaction):
    rows = database.get_gallery()
    if not rows:
        await interaction.response.send_message("No gallery entries yet.")
        return
    lines = [
        f"**#{i}** <@{uid}> — {prompt} (:ERNIE_ThumbsUp: {reactions})"
        for i, (uid, prompt, reactions, _mid) in enumerate(rows, 1)
    ]
    await interaction.response.send_message("\n".join(lines))


# ── /leaderboard ──

@bot.tree.command(name="leaderboard", description="This week's theme-battle rankings")
async def leaderboard(interaction: discord.Interaction):
    rows = database.get_leaderboard()
    if not rows:
        await interaction.response.send_message("No entries this week.")
        return
    lines = [
        f"**#{i}** <@{uid}> — {prompt} (:ERNIE_ThumbsUp: {reactions})"
        for i, (uid, prompt, reactions, _mid) in enumerate(rows, 1)
    ]
    await interaction.response.send_message("\n".join(lines))


# ── Reaction listener ──

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.emoji.name != EMOJI_NAME:
        return

    gen = database.get_generation(str(payload.message_id))
    if not gen:
        return

    author_uid, channel, bonus_awarded = gen

    # ignore self-reactions
    if str(payload.user_id) == author_uid:
        return

    # fetch actual reaction count from Discord
    ch = bot.get_channel(payload.channel_id)
    msg = await ch.fetch_message(payload.message_id)
    count = 0
    for r in msg.reactions:
        if hasattr(r.emoji, "name") and r.emoji.name == EMOJI_NAME:
            count = r.count
            break

    database.update_reactions(str(payload.message_id), count)

    # +2 bonus when daily-showcase post hits 3 reactions
    if channel == "daily-showcase" and count >= 3 and not bonus_awarded:
        database.add_points(author_uid, 2)
        database.mark_bonus(str(payload.message_id))


bot.run("replace with discord bot token")