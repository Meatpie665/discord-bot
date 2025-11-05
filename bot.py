import os
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import asyncio
from flask import Flask
import threading

# ================= Flask サーバー =================
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    # Flask のログを抑止するために 'use_reloader=False' を設定
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# Flask を別スレッドで起動
threading.Thread(target=run_flask).start()
# ================================================

# --- 設定値 ---
TICKET_EMOJI = "🎫"          # チケット作成のリアクション
CLOSE_EMOJI = "🔒"           # チャンネル削除のリアクション
ADMIN_ROLE_NAME = "Admin"    # 管理者ロール名
CHANNEL_NAME_PREFIX = "kujo-ticket"
# --- 設定値終 ---

# intents設定
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# --- 起動時 ---
@bot.event
async def on_ready():
    print(f"✅ ログイン成功: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔧 スラッシュコマンド同期完了 ({len(synced)}個)")
    except Exception as e:
        print(f"❌ コマンド同期エラー: {e}")

# --- エラーハンドリング ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(
            f"❌ **エラー:** このコマンドを使用するには、ロール **`{error.missing_role}`** が必要です。",
            ephemeral=True
        )
    else:
        print(f"予期せぬエラーが発生しました: {error}")
        await interaction.response.send_message(
            "❌ コマンドの実行中に予期せぬエラーが発生しました。",
            ephemeral=True
        )

# --- スラッシュコマンド ---
@bot.tree.command(name="complaint", description="苦情受付用のリアクションメッセージを送信します。")
@app_commands.checks.has_role(ADMIN_ROLE_NAME)
async def complaint(interaction: discord.Interaction):
    message = await interaction.channel.send(
        f"苦情はこちらのメッセージに **{TICKET_EMOJI}** でリアクションしてください。\n"
        f"専用の対応チャンネルが作成されます。"
    )
    await message.add_reaction(TICKET_EMOJI)
    await interaction.response.send_message("苦情受付メッセージを送信しました。", ephemeral=True)

# --- リアクション検知 (古いメッセージにも対応) ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return

    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return

    channel = guild.get_channel(payload.channel_id)
    if not channel:
        return

    user = guild.get_member(payload.user_id)
    if not user or user.bot:
        return

    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return

    emoji = str(payload.emoji.name)

    # ==========================
    # 🎫 チケット作成処理
    # ==========================
    if emoji == TICKET_EMOJI:
        if message.author == bot.user and "苦情はこちらのメッセージに" in message.content:
            # チャンネル名に使用できない文字を除外
            safe_user_name = "".join(c for c in user.name.lower() if c.isalnum() or c in ('-', '_')).replace(' ', '-')
            channel_name = f"{CHANNEL_NAME_PREFIX}-{safe_user_name}-{user.id}"

            # すでにチケットを持っているか確認
            has_existing_ticket = any(c.name.startswith(f"{CHANNEL_NAME_PREFIX}-{safe_user_name}") and str(user.id) in c.name for c in guild.text_channels)
            
            if has_existing_ticket:
                try:
                    await user.send(f"⚠️ {guild.name} サーバーで、あなたは既にチケットチャンネルを持っています。")
                except discord.Forbidden:
                    print(f"ユーザー {user} へのDM送信に失敗しました。")
                
                # 📌 既にチケットがある場合もリアクションを削除してユーザーを隠す
                try:
                    await message.remove_reaction(payload.emoji, user)
                except:
                    pass # 削除失敗は無視
                
                return

            admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
            if not admin_role:
                print(f"❌ ロール '{ADMIN_ROLE_NAME}' が見つかりません。")
                return

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
                admin_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            }

            new_channel = None # チャンネルオブジェクトを初期化
            try:
                category = channel.category
                new_channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"チケット作成者ID: {user.id} | 作成日時: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )

                close_message = await new_channel.send(
                    f"{user.mention} 様、チケットチャンネルを作成しました。\n"
                    f"このチャンネルは {admin_role.mention} とあなたのみが閲覧できます。\n\n"
                    f"**対応が完了したら、このメッセージに {CLOSE_EMOJI} でリアクションしてチャンネルを削除してください。**"
                )
                await close_message.add_reaction(CLOSE_EMOJI)

                # ----------------------------------------------------------------------------------
                # 📌 修正点: チケット作成完了通知（メンション付き）の送信処理を削除しました。
                # await channel.send(f"🎫 {user.mention} さんのチケットチャンネル {new_channel.mention} を作成しました。", delete_after=10)
                # ----------------------------------------------------------------------------------
                
                # --- 🔑 追加したコード: リアクションしたユーザーを隠す ---
                try:
                    # ユーザーが追加したリアクションを削除
                    await message.remove_reaction(payload.emoji, user)
                    print(f"✅ リアクション {TICKET_EMOJI} をユーザー {user} から削除しました。")
                except discord.Forbidden:
                    print("❌ リアクション削除権限が不足しています。")
                except Exception as e:
                    print(f"❌ リアクション削除中にエラーが発生しました: {e}")
                # ---------------------------------------------------

            except discord.Forbidden:
                print("❌ チャンネル作成または権限設定に失敗しました。")
                await channel.send(f"❌ チャンネル作成中にエラーが発生しました。", delete_after=10)
            except Exception as e:
                print(f"チャンネル作成またはメッセージ送信エラー: {e}")
                await channel.send(f"❌ チャンネル作成中に予期せぬエラーが発生しました。", delete_after=10)

    # ==========================
    # 🔒 チケット削除処理
    # ==========================
    elif emoji == CLOSE_EMOJI:
        # チケットチャンネルでのみ有効
        if not channel.name.startswith(CHANNEL_NAME_PREFIX):
            return

        # チャンネル削除メッセージ（Botのメッセージ）であるか確認
        if message.author != bot.user or CLOSE_EMOJI not in message.content:
             # Botの削除指示メッセージでなければ、リアクションを削除して終了
            try:
                await message.remove_reaction(payload.emoji, user)
            except:
                pass
            return

        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        is_member = isinstance(user, discord.Member)
        is_admin = admin_role in user.roles if (is_member and admin_role) else False

        creator_id = None
        if channel.topic and "チケット作成者ID:" in channel.topic:
            try:
                creator_id = int(channel.topic.split("チケット作成者ID:")[1].split('|')[0].strip())
            except:
                print(f"❌ チャンネル '{channel.name}' のトピックから作成者IDをパースできませんでした。")

        is_creator = creator_id == user.id
        can_delete = is_admin or is_creator

        if can_delete:
            try:
                await channel.send("🔒 チケットクローズが承認されました。**5秒後にこのチャンネルを削除します。**")
                
                # --- 🔑 追加したコード: 削除リアクションしたユーザーを隠す ---
                try:
                    # ユーザーが追加したリアクションを削除
                    await message.remove_reaction(payload.emoji, user)
                    print(f"✅ リアクション {CLOSE_EMOJI} をユーザー {user} から削除しました。")
                except discord.Forbidden:
                    print("❌ リアクション削除権限が不足しています。")
                except Exception as e:
                    print(f"❌ 削除リアクション削除中にエラーが発生しました: {e}")
                # ---------------------------------------------------
                
                await asyncio.sleep(5)
                await channel.delete()
                print(f"🗑️ チャンネル '{channel.name}' を削除しました。")
            except discord.Forbidden:
                print(f"❌ チャンネル削除権限が不足しています。")
                await channel.send(f"❌ チャンネル削除中にエラーが発生しました。", delete_after=10)
            except Exception as e:
                print(f"削除中に予期せぬエラーが発生: {e}")
        else:
            await channel.send(f"❌ {user.mention} さん、このチャンネルを削除できるのはAdminロールまたは作成者本人です。", delete_after=10)
            
            # 権限がないユーザーのリアクションも削除
            try:
                await message.remove_reaction(payload.emoji, user)
            except:
                pass


# --- トークンの読み込み ---
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("❌ 環境変数 DISCORD_TOKEN が設定されていません。")

# --- Bot 実行 ---
bot.run(TOKEN)