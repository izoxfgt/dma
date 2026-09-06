import discord
from discord.ext import commands
from discord import app_commands
import os
import re
import time
import datetime
from collections import defaultdict

# ── Config ──────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")

# Change ce texte pour personnaliser le nom affiché dans les footers d'embeds
BRAND_NAME = "GardeDMA"
BRAND_FOOTER = f"{BRAND_NAME} • Support"
EMBED_COLOR = 0x2ECC71  # vert Gardevoir

# ── Config vérification ────────────────────────────────────────
# Nom du rôle donné automatiquement à l'arrivée (accès limité au salon vérif)
UNVERIFIED_ROLE_NAME = "Non vérifié"
# ID du rôle donné une fois que le membre a cliqué sur "Se vérifier"
VERIFIED_ROLE_ID = 1480019293738631178

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.invites = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ══════════════════════════════════════════════════════════════
# ── ANTI-SPAM / ANTI-RAID ────────────────────────────────────
# ══════════════════════════════════════════════════════════════
SPAM_MESSAGE_THRESHOLD = 10  # nombre de messages...
SPAM_TIME_WINDOW = 5         # ...en X secondes = kick automatique
spam_tracker = defaultdict(list)  # user_id -> [timestamps]

# ══════════════════════════════════════════════════════════════
# ── ANTI-LIEN (mute progressif) ──────────────────────────────
# ══════════════════════════════════════════════════════════════
LINK_PATTERN = re.compile(
    r"(https?://|www\.|discord\.gg/|discordapp\.com/invite/|discord\.com/invite/)",
    re.IGNORECASE
)
link_warns = defaultdict(int)  # user_id -> nombre d'infractions

# (durée du mute, label affiché dans le DM)
LINK_TIMEOUT_STEPS = [
    (datetime.timedelta(minutes=1), "1 minute"),
    (datetime.timedelta(minutes=2, seconds=30), "2 minutes 30"),
    (datetime.timedelta(minutes=5), "5 minutes"),
]


def get_link_timeout(count: int):
    # 1re, 2e, 3e fois -> paliers définis ; 4e fois et + -> reste à 5 minutes
    index = min(count, len(LINK_TIMEOUT_STEPS)) - 1
    return LINK_TIMEOUT_STEPS[index]


# IDs des membres jamais concernés par l'anti-spam / anti-lien (même sans rôle Staff)
EXEMPT_USER_IDS = {1480009831606780005}


def is_staff(member: discord.Member) -> bool:
    if member.id in EXEMPT_USER_IDS:
        return True
    if member.guild_permissions.administrator:
        return True
    role_names = [r.name for r in member.roles]
    return any(r in role_names for r in STAFF_ROLES)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    member = message.author

    if not is_staff(member):
        # ── Anti-spam / anti-raid : kick automatique ─────────
        now = time.monotonic()
        history = [t for t in spam_tracker[member.id] if now - t <= SPAM_TIME_WINDOW]
        history.append(now)
        spam_tracker[member.id] = history

        if len(history) >= SPAM_MESSAGE_THRESHOLD:
            spam_tracker[member.id] = []  # reset pour ne pas re-déclencher en boucle

            try:
                await message.delete()
            except Exception:
                pass

            try:
                await member.send(
                    f"🚫 Tu as été expulsé de **{message.guild.name}** pour spam "
                    "(comportement détecté comme un raid automatisé).\n"
                    "Si c'est une erreur, tu peux revenir et éviter d'envoyer autant de messages rapidement."
                )
            except discord.Forbidden:
                pass

            try:
                await message.guild.kick(member, reason="Anti-spam / anti-raid automatique")
            except discord.Forbidden:
                pass
            except Exception:
                pass

            return  # on ne traite pas ce message plus loin

        # ── Anti-lien : mute progressif ───────────────────────
        if LINK_PATTERN.search(message.content):
            try:
                await message.delete()
            except Exception:
                pass

            link_warns[member.id] += 1
            count = link_warns[member.id]
            duration, duration_label = get_link_timeout(count)
            warn_number = min(count, 3)

            try:
                await member.timeout(duration, reason="Envoi de lien non autorisé")
            except discord.Forbidden:
                pass
            except Exception:
                pass

            try:
                await member.send(
                    f"⚠️ **Avertissement {warn_number}/3** — Les liens ne sont pas autorisés sur "
                    f"**{message.guild.name}**.\n"
                    f"Tu es mute pendant **{duration_label}**."
                )
            except discord.Forbidden:
                pass

            return

    await bot.process_commands(message)


# ── Slash command /send ──────────────────────────────────────
@bot.tree.command(name="send", description="Envoie un message dans un salon")
@app_commands.describe(
    message="Contenu du message à envoyer",
    salon="Salon où envoyer le message (laisser vide = salon actuel)",
    titre="Titre du message (optionnel)"
)
async def send_message(
    interaction: discord.Interaction,
    message: str,
    salon: discord.TextChannel = None,
    titre: str = BRAND_NAME
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        title=titre,
        description=message,
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /purchase ───────────────────────────────────
# Émojis custom du serveur
EMOJI_CARD = "<:card:1546168766868488303>"
EMOJI_LTC = "<:ltc:1546168778633646240>"
EMOJI_BTC = "<:btc:1546168790750994512>"
EMOJI_PAYPAL = "<:paypal:1546168804650917998>"
EMOJI_INFO = "<:info:1545513227675500544>"
EMOJI_PRICE = "<:price:1545513208725639329>"

# ID du salon #tickets (utilisé par /purchase et /chaise)
TICKET_CHANNEL_ID = 1480018356261355611

@bot.tree.command(name="purchase", description="Displays the payment methods and how to purchase")
@app_commands.describe(salon="Channel to send the message in (leave empty = current channel)")
async def purchase(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    try:
        file = discord.File("banner.png", filename="banner.png")

        embed = discord.Embed(
            description=(
                "# Payment methods:\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"# {EMOJI_CARD} Credit Card\n\n"
                f"# {EMOJI_LTC} Ltc\n\n"
                f"# {EMOJI_BTC} Btc\n\n"
                f"# {EMOJI_PAYPAL} PayPal\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
            ),
            color=EMBED_COLOR
        )
        embed.set_image(url="attachment://banner.png")
        embed.set_footer(text=BRAND_FOOTER)

        await target.send(embed=embed, file=file)
        await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)

    except FileNotFoundError:
        await interaction.response.send_message(
            "❌ Le fichier `banner.png` est introuvable. "
            "Vérifie qu'il est bien à la racine du repo, au même endroit que `bot.py`.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ── Slash command /chaise ──────────────────────────────────────
@bot.tree.command(name="chaise", description="Affiche les infos et prix de GardeDMA")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def chaise(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    try:
        file = discord.File("banner.png", filename="banner.png")

        embed = discord.Embed(
            description=(
                "# GardeDMA | Fn external\n\n"
                f"# {EMOJI_INFO} Information\n"
                "• TPM & Secure Boot Supported\n"
                "• Safe & Undetected\n"
                "• Supports Windows 10 & 11 (24H2 & 25H2)\n"
                "• Supports All CPUs & GPUs\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"# {EMOJI_PRICE} Price\n\n"
                "**3 Days — $9,99**\n"
                "**1 Week — $19,99**\n"
                "**1 Month — $49.99**\n"
                "**3 Month — $99,99**\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"To purchase, please open a ticket in <#{TICKET_CHANNEL_ID}>."
            ),
            color=EMBED_COLOR
        )
        embed.set_image(url="attachment://banner.png")
        embed.set_footer(text=BRAND_FOOTER)

        await target.send(embed=embed, file=file)
        await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)

    except FileNotFoundError:
        await interaction.response.send_message(
            "❌ Le fichier `banner.png` est introuvable. "
            "Vérifie qu'il est bien à la racine du repo, au même endroit que `bot.py`.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ── Slash command /woofer ───────────────────────────────────────
@bot.tree.command(name="woofer", description="Displays info and pricing for the Woofer spoofer")
@app_commands.describe(salon="Channel to send the message in (leave empty = current channel)")
async def woofer(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    try:
        file = discord.File("banner.png", filename="banner.png")

        embed = discord.Embed(
            description=(
                "# WOOFER — PRICING\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "## <:emoji:1545573618652549171> Spoofer | One Time — 25€\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "# Compatibility\n\n"
                "## <:emoji:1545573618652549171> AMD <:emoji:1545574263115874304>\n\n"
                "## <:emoji:1545573618652549171> Intel <:emoji:1545574263115874304>\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "# How does it work?\n\n"
                "① Open a ticket on Discord\n"
                "② Choose your offer\n"
                "③ Complete the payment\n"
                "④ Receive your installation instructions\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"To purchase, please open a ticket in <#{TICKET_CHANNEL_ID}>."
            ),
            color=EMBED_COLOR
        )
        embed.set_image(url="attachment://banner.png")
        embed.set_footer(text=BRAND_FOOTER)

        await target.send(embed=embed, file=file)
        await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)

    except FileNotFoundError:
        await interaction.response.send_message(
            "❌ Le fichier `banner.png` est introuvable. "
            "Vérifie qu'il est bien à la racine du repo, au même endroit que `bot.py`.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ── Slash command /status_fw ─────────────────────────────────────
FW_STATUS_CHANNELS = [
    (1546152732120059918, "Undetected since 7 months"),
    (1546152732120059919, "Undetected since 7 months"),
    (1546152732120059920, "Undetected since 1 year+"),
]

@bot.tree.command(name="status_fw", description="Affiche le statut en temps réel du Firmware")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def status_fw(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    lines = "\n\n".join(f"<#{cid}> | 🟢 | `{label}`" for cid, label in FW_STATUS_CHANNELS)
    embed = discord.Embed(
        description=(
            "# GardeDMA | Firmware Status\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"{lines}"
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /status_rdma ───────────────────────────────────
RDMA_STATUS_CHANNEL_IDS = [1546155810516762804]

@bot.tree.command(name="status_rdma", description="Affiche le statut en temps réel du RDMA")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def status_rdma(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    lines = "\n\n".join(f"<#{cid}> | 🟢 | `Undetected`" for cid in RDMA_STATUS_CHANNEL_IDS)
    embed = discord.Embed(
        description=(
            "# GardeDMA | RDMA Status\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"{lines}"
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /status_woofer ─────────────────────────────────
WOOFER_STATUS_CHANNEL_IDS = [1546164953097052200]

@bot.tree.command(name="status_woofer", description="Affiche le statut en temps réel du Manual Woofer")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def status_woofer(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    lines = "\n\n".join(f"<#{cid}> | 🟢 | `Undetected`" for cid in WOOFER_STATUS_CHANNEL_IDS)
    embed = discord.Embed(
        description=(
            "# GardeDMA | Manual Woofer Status\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            f"{lines}"
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /account ──────────────────────────────────────
@bot.tree.command(name="account", description="Affiche les infos sur les comptes FA / NFA")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def account(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    try:
        file = discord.File("banner.png", filename="banner.png")

        embed = discord.Embed(
            description=(
                "# FN ACCOUNT\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "## <:emoji:1546169899007873034> **FA ACCOUNT (FULL ACCESS)**\n\n"
                "Full access accounts, including access to competitive.\n"
                "Some accounts may also come with 14 Cups.\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "## <:emoji:1546169899007873034> **NFA ACCOUNT (NO FULL ACCESS)**\n\n"
                "Accounts without access to the linked email — in-game access only.\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                f"To purchase, please open a ticket in <#{TICKET_CHANNEL_ID}>."
            ),
            color=EMBED_COLOR
        )
        embed.set_image(url="attachment://banner.png")
        embed.set_footer(text=BRAND_FOOTER)

        await target.send(embed=embed, file=file)
        await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)

    except FileNotFoundError:
        await interaction.response.send_message(
            "❌ Le fichier `banner.png` est introuvable. "
            "Vérifie qu'il est bien à la racine du repo, au même endroit que `bot.py`.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


# ── Slash command /guide_en ──────────────────────────────────────
@bot.tree.command(name="guide_en", description="Displays the FN External installation guide (English)")
@app_commands.describe(salon="Channel to send the message in (leave empty = current channel)")
async def guide_en(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        description=(
            "# GUIDE | FN EXTERNAL 🇬🇧\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "① Download and install the **SteelSeries GG** application.\n\n"
            "② Enable **SteelSeries GG**.\n\n"
            "③ Temporarily disable your **antivirus**.\n\n"
            "④ Disable **Core Isolation** in Windows Security settings.\n\n"
            "⑤ If Valorant is installed, disable its anti-cheat (**Riot Vanguard**) or completely close Vanguard before launching the software.\n\n"
            "⑥ Launch the software.\n\n"
            "⑦ Launch the **SteelSeries** application.\n\n"
            "⑧ Enable **Moment**.\n\n"
            "⑨ Press **Alt + P**.\n\n"
            "⑩ Press **OK** on the software, then launch **Fortnite**, and once in the menu, press **OK**.\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "⚠️ It is **highly recommended** to keep the **\"Stream Proof\"** option enabled at all times."
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /guide_fr ──────────────────────────────────────
@bot.tree.command(name="guide_fr", description="Affiche le guide d'installation de FN External (Français)")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def guide_fr(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        description=(
            "# GUIDE | FN EXTERNAL 🇫🇷\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "① Télécharge et installe l'application **SteelSeries GG**.\n\n"
            "② Active **SteelSeries GG**.\n\n"
            "③ Désactive temporairement ton **antivirus**.\n\n"
            "④ Désactive l'**isolation du noyau** (Core Isolation) dans les paramètres de sécurité Windows.\n\n"
            "⑤ Si Valorant est installé, désactive son anti-cheat (**Riot Vanguard**) ou ferme complètement Vanguard avant de lancer le logiciel.\n\n"
            "⑥ Lance le logiciel.\n\n"
            "⑦ Lance l'application **SteelSeries**.\n\n"
            "⑧ Active **Moment**.\n\n"
            "⑨ Fais **Alt + P**.\n\n"
            "⑩ Appuie sur **OK** sur le logiciel, puis lance **Fortnite**, et une fois dans le menu, fais **OK**.\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "⚠️ Il est **fortement recommandé** de garder l'option **\"Stream Proof\"** activée en permanence."
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Message envoyé dans {target.mention} !", ephemeral=True)


# ── Slash command /topinvites ────────────────────────────────
@bot.tree.command(name="topinvites", description="Affiche le top des membres ayant invité le plus de monde")
async def top_invites(interaction: discord.Interaction):
    await interaction.response.defer()

    guild = interaction.guild
    try:
        invites = await guild.invites()
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : `{e}`", ephemeral=True)
        return

    # Regroupe les invitations par inviteur
    invite_map = {}
    for invite in invites:
        if not invite.inviter:
            continue
        uid = invite.inviter.id
        if uid not in invite_map:
            invite_map[uid] = {"user": invite.inviter, "uses": 0}
        invite_map[uid]["uses"] += invite.uses or 0

    if not invite_map:
        await interaction.followup.send("Aucune invitation trouvée sur ce serveur.")
        return

    sorted_invites = sorted(invite_map.values(), key=lambda x: x["uses"], reverse=True)[:10]

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, entry in enumerate(sorted_invites):
        rank = medals[i] if i < 3 else f"**#{i+1}**"
        invites_word = "invitation" if entry["uses"] <= 1 else "invitations"
        lines.append(f"{rank} <@{entry['user'].id}> — **{entry['uses']}** {invites_word}")

    embed = discord.Embed(
        title="🏆 Top des Invitations",
        description="\n".join(lines),
        color=0xFFD700
    )
    embed.set_footer(text=BRAND_FOOTER)

    await interaction.followup.send(embed=embed)


# ── Slash command /reglement ─────────────────────────────────
class AcceptRulesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Accept the Rules", style=discord.ButtonStyle.success, custom_id="accept_rules")
    async def accept_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "✅ You have accepted the rules. Welcome to the server!",
            ephemeral=True
        )
        try:
            dm_embed = discord.Embed(
                title=f"✅ Rules Accepted — {BRAND_NAME}",
                description=(
                    f"Hey **{interaction.user.display_name}**! 👋\n\n"
                    "You have successfully accepted the server rules.\n"
                    f"Welcome to **{BRAND_NAME}** — enjoy your stay!\n\n"
                    "If you have any questions, feel free to open a ticket."
                ),
                color=0x2ecc71
            )
            dm_embed.set_footer(text=f"{BRAND_NAME} | Règlement")
            await interaction.user.send(embed=dm_embed)
        except discord.Forbidden:
            pass  # L'utilisateur a ses DM fermés


# ══════════════════════════════════════════════════════════════
# ── SYSTÈME DE VÉRIFICATION ──────────────────────────────────
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_member_join(member: discord.Member):
    # Donne automatiquement le rôle "Non vérifié" à l'arrivée.
    # Ce rôle doit être configuré (par toi, une seule fois, sur Discord) pour
    # ne voir QUE le salon de vérification :
    #   - dans les permissions du rôle "Non vérifié" -> décocher "Voir les salons" par défaut
    #   - sur le salon #verification -> ajouter une permission spécifique pour ce rôle : "Voir le salon" = ✅
    unverified_role = discord.utils.get(member.guild.roles, name=UNVERIFIED_ROLE_NAME)
    if unverified_role:
        try:
            await member.add_roles(unverified_role, reason="Nouveau membre - en attente de vérification")
        except discord.Forbidden:
            pass
        except Exception:
            pass


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Se vérifier", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        guild = interaction.guild

        verified_role = guild.get_role(VERIFIED_ROLE_ID)
        unverified_role = discord.utils.get(guild.roles, name=UNVERIFIED_ROLE_NAME)

        if verified_role is None:
            await interaction.response.send_message(
                f"❌ Le rôle avec l'ID `{VERIFIED_ROLE_ID}` est introuvable sur ce serveur. "
                "Vérifie que l'ID est correct.",
                ephemeral=True
            )
            return

        if verified_role in member.roles:
            await interaction.response.send_message("✅ Tu es déjà vérifié !", ephemeral=True)
            return

        try:
            await member.add_roles(verified_role, reason="Vérification effectuée")
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Vérification effectuée")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Je n'ai pas la permission de te donner ce rôle. "
                "Vérifie que mon rôle bot est bien placé au-dessus de ce rôle "
                "dans la hiérarchie des rôles.",
                ephemeral=True
            )
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)
            return

        await interaction.response.send_message(
            "✅ Tu as été vérifié avec succès ! Bienvenue sur le serveur 🎉",
            ephemeral=True
        )


@bot.tree.command(name="verif_panel", description="Envoie le panel de vérification dans ce salon")
@app_commands.describe(salon="Salon où envoyer le panel (laisser vide = salon actuel)")
async def send_verif_panel(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        title=f"🔐 Vérification — {BRAND_NAME}",
        description=(
            "Bienvenue sur le serveur !\n\n"
            "Clique sur le bouton ci-dessous pour te vérifier et débloquer l'accès au reste du serveur."
        ),
        color=EMBED_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    try:
        file = discord.File("banner.png", filename="banner.png")
        embed.set_image(url="attachment://banner.png")
        await target.send(embed=embed, file=file, view=VerifyView())
        await interaction.response.send_message(
            f"✅ Panel de vérification envoyé dans {target.mention} !", ephemeral=True
        )
    except FileNotFoundError:
        await interaction.response.send_message(
            "❌ Le fichier `banner.png` est introuvable. "
            "Vérifie qu'il est bien à la racine du repo, au même endroit que `bot.py`.",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Je n'ai pas la permission d'envoyer des messages dans {target.mention}.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Erreur : `{e}`", ephemeral=True)


@bot.tree.command(name="reglement", description="Envoie le règlement du serveur")
@app_commands.describe(salon="Salon où envoyer le message (laisser vide = salon actuel)")
async def send_reglement(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True)
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        title=f"📋 SERVER RULES — {BRAND_NAME.upper()}",
        description=(
            f"Welcome to **{BRAND_NAME}**.\n"
            "Please read the following rules carefully before participating in the server. "
            "By staying here, you agree to comply with them at all times.\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
        ),
        color=EMBED_COLOR
    )

    embed.add_field(name="【 1 】 🤝 Mutual Respect", value=(
        "All members and staff must be treated with respect at all times.\n"
        "Insults, harassment, discriminatory remarks, and toxic behavior of any kind "
        "will not be tolerated and may result in immediate action."
    ), inline=False)

    embed.add_field(name="【 2 】 🚫 Spam & Advertising", value=(
        "Spamming, flooding, or excessive use of caps is prohibited.\n"
        "Unauthorized advertising — including invite links, external servers, or promotions — "
        "will result in a **permanent ban**."
    ), inline=False)

    embed.add_field(name="【 3 】 🔞 Appropriate Content", value=(
        "NSFW, shocking, violent, or illegal content is strictly forbidden — "
        "in messages, media, usernames, or profile pictures."
    ), inline=False)

    embed.add_field(name="【 4 】 🎫 Tickets & Purchases", value=(
        "Tickets are reserved for legitimate requests only (support, purchases, HWID resets).\n"
        "Please avoid spamming or pinging staff — a team member will assist you as soon as possible.\n"
        "Any attempt at fraud or chargeback will result in a permanent ban."
    ), inline=False)

    embed.add_field(name="【 5 】 🔒 Security", value=(
        "Never share personal information, passwords, or payment details.\n"
        "Staff will **never** ask for your credentials in DMs."
    ), inline=False)

    embed.add_field(name="【 6 】 🛡️ Staff Authority", value=(
        "Staff decisions are final.\n"
        "If you disagree with a decision, contact a staff member privately and respectfully via a ticket — "
        "public disputes will not be tolerated."
    ), inline=False)

    embed.add_field(name="【 7 】 ⚖️ Sanctions", value=(
        "Depending on the severity of the offense:\n"
        "⚠️ Warning → 🔇 Mute → 👢 Kick → 🔨 Permanent Ban\n"
        "Staff reserves the right to adjust sanctions based on context and severity."
    ), inline=False)

    embed.add_field(name="\u200b", value="▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", inline=False)

    embed.set_footer(text=f"{BRAND_NAME} | Rules • By accepting, you agree to follow these rules.")

    try:
        file = discord.File("banner.png", filename="banner.png")
        embed.set_image(url="attachment://banner.png")
        await target.send(embed=embed, file=file, view=AcceptRulesView())
        await interaction.response.send_message(f"✅ Règlement envoyé dans {target.mention} !", ephemeral=True)
    except FileNotFoundError:
        # Fallback : envoie quand même le règlement sans image si le fichier est introuvable
        await target.send(embed=embed, view=AcceptRulesView())
        await interaction.response.send_message(
            f"✅ Règlement envoyé dans {target.mention} (sans image — `banner.png` introuvable) !",
            ephemeral=True
        )


# ══════════════════════════════════════════════════════════════
# ── TICKET SYSTEM ─────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════

STAFF_ROLES = ["Staff", "Owner"]  # Rôles qui peuvent voir les tickets
TICKET_COLOR = EMBED_COLOR

# ── Modal pour renommer un ticket ────────────────────────────
class RenameTicketModal(discord.ui.Modal, title="Rename Ticket"):
    new_name = discord.ui.TextInput(
        label="New ticket name",
        placeholder="e.g. general-support-john",
        min_length=2,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Nettoie le nom (Discord n'accepte que minuscules, tirets, chiffres)
        clean = self.new_name.value.lower().replace(" ", "-")
        try:
            await interaction.channel.edit(name=clean)
            await interaction.response.send_message(
                f"✅ Ticket renamed to **{clean}**.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to rename this channel.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)


# ── Bouton Fermer un ticket ───────────────────────────────────
class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✏️ Rename Ticket",
        style=discord.ButtonStyle.secondary,
        custom_id="rename_ticket"
    )
    async def rename_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role_names = [r.name for r in interaction.user.roles]
        is_staff = any(r in staff_role_names for r in STAFF_ROLES)
        if not is_staff and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only staff can rename a ticket.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RenameTicketModal())

    @discord.ui.button(
        label="🔒 Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="close_ticket"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Vérif staff
        staff_role_names = [r.name for r in interaction.user.roles]
        is_staff = any(r in staff_role_names for r in STAFF_ROLES)
        if not is_staff and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Seul le staff peut fermer un ticket.", ephemeral=True
            )
            return

        channel = interaction.channel
        await interaction.response.send_message("🔒 Fermeture du ticket dans 5 secondes...", ephemeral=False)
        await discord.utils.sleep_until(
            discord.utils.utcnow() + discord.utils.datetime.timedelta(seconds=5)
        )
        await channel.delete(reason=f"Ticket fermé par {interaction.user}")


# ── Select Menu pour choisir le type de ticket ───────────────
class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="GardeDMA | General Support",
                description="For general support concerns.",
                emoji="🟢",
                value="general"
            ),
            discord.SelectOption(
                label="GardeDMA | FW Support",
                description="For Firmware issues or concerns.",
                emoji="🟢",
                value="fw"
            ),
            discord.SelectOption(
                label="GardeDMA | RDMA Support",
                description="For RDMA issues or concerns.",
                emoji="🟢",
                value="rdma"
            ),
            discord.SelectOption(
                label="GardeDMA | Woofer Support",
                description="For Woofer issues or concerns.",
                emoji="🟢",
                value="woofer"
            ),
            discord.SelectOption(
                label="GardeDMA | FN Account Support",
                description="For FN Account issues or concerns.",
                emoji="🟢",
                value="fn_account"
            ),
        ]
        super().__init__(
            placeholder="| Select an option...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_select"
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        ticket_type = self.values[0]

        # Labels et descriptions selon le type
        type_labels = {
            "general":    ("GardeDMA | General Support",     "🟢"),
            "fw":         ("GardeDMA | FW Support",           "🟢"),
            "rdma":       ("GardeDMA | RDMA Support",         "🟢"),
            "woofer":     ("GardeDMA | Woofer Support",       "🟢"),
            "fn_account": ("GardeDMA | FN Account Support",   "🟢"),
        }
        label, emoji = type_labels[ticket_type]

        # Catégorie : cherche une catégorie "Tickets" (ou la crée)
        category = discord.utils.get(guild.categories, name="Tickets")
        if category is None:
            category = await guild.create_category("Tickets")

        # Vérifie si l'utilisateur a déjà un ticket ouvert (cherche dans tous les channels de la catégorie)
        tickets_category = discord.utils.get(guild.categories, name="Tickets")
        if tickets_category:
            existing = discord.utils.find(
                lambda c: user.name.lower() in c.name and c.category_id == tickets_category.id,
                guild.text_channels
            )
            if existing:
                await interaction.response.send_message(
                    f"❌ You already have an open ticket: {existing.mention}",
                    ephemeral=True
                )
                return

        # Permissions du salon de ticket
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        for role_name in STAFF_ROLES:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    read_messages=True, send_messages=True, manage_channels=True
                )

        # Nom du channel selon le type choisi
        type_channel_prefix = {
            "general":    "general-support",
            "fw":         "fw-support",
            "rdma":       "rdma-support",
            "woofer":     "woofer-support",
            "fn_account": "fn-account-support",
        }
        channel_name = f"{type_channel_prefix[ticket_type]}-{user.name.lower()}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"{label} | {user} | {user.id}"
        )

        # Embed d'accueil dans le ticket
        embed = discord.Embed(
            title=f"{emoji} {label}",
            description=(
                f"Welcome, {user.mention}! Thank you for reaching out.\n\n"
                "Please describe your request in as much detail as possible — "
                "a staff member will be with you shortly.\n\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
                "⏳ Kindly avoid spamming or pinging staff, it won't speed things up.\n"
                "🔒 Once your request is resolved, staff can close this ticket."
            ),
            color=TICKET_COLOR
        )
        embed.set_footer(text=BRAND_FOOTER)

        await ticket_channel.send(
            content=f"{user.mention} | " + " ".join(
                f"<@&{r.id}>"
                for name in STAFF_ROLES
                for r in [discord.utils.get(guild.roles, name=name)]
                if r
            ),
            embed=embed,
            view=CloseTicketView()
        )

        await interaction.response.send_message(
            f"✅ Your ticket has been created: {ticket_channel.mention}",
            ephemeral=True
        )


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# ── Slash command /ticket_panel ───────────────────────────────
@bot.tree.command(name="ticket_panel", description="Envoie le panel de tickets dans ce salon")
@app_commands.describe(salon="Salon où envoyer le panel (laisser vide = salon actuel)")
async def send_ticket_panel(interaction: discord.Interaction, salon: discord.TextChannel = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    target = salon or interaction.channel

    embed = discord.Embed(
        title=f"🎫 {BRAND_NAME} — Support Tickets",
        description=(
            "Welcome to our support center.\n\n"
            "Select the category that best matches your request from the menu below "
            "to open a private ticket with our team.\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "🟢 **General Support** — General questions or concerns\n"
            "🟢 **FW Support** — Firmware issues or concerns\n"
            "🟢 **RDMA Support** — RDMA issues or concerns\n"
            "🟢 **Woofer Support** — Woofer issues or concerns\n"
            "🟢 **FN Account Support** — FN Account issues or concerns\n\n"
            "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n\n"
            "Please only open one ticket at a time and avoid pinging staff — "
            "a team member will be with you shortly."
        ),
        color=TICKET_COLOR
    )
    embed.set_footer(text=BRAND_FOOTER)

    try:
        file = discord.File("banner.png", filename="banner.png")
        embed.set_image(url="attachment://banner.png")
        await target.send(embed=embed, file=file, view=TicketView())
        await interaction.response.send_message(
            f"✅ Ticket panel sent in {target.mention} !", ephemeral=True
        )
    except FileNotFoundError:
        await target.send(embed=embed, view=TicketView())
        await interaction.response.send_message(
            f"✅ Ticket panel sent in {target.mention} (no image — `banner.png` not found) !",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ I don't have permission to send messages in {target.mention}. "
            "Check my permissions in this channel (View Channel / Send Messages / Embed Links).",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)


# ── Démarrage ────────────────────────────────────────────────
@bot.event
async def on_ready():
    bot.add_view(AcceptRulesView())
    bot.add_view(VerifyView())
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    await bot.tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user} !")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=BRAND_NAME
    ))


bot.run(TOKEN)
