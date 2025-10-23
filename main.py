import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import requests
from bs4 import BeautifulSoup
import asyncio
import json
from datetime import datetime

# --------------------------
# Persistent Seen Releases & Cache
# --------------------------
SEEN_FILE = "seen_releases.json"
CACHE_FILE = "releases_cache.json"


def load_seen_releases():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_releases():
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_releases), f, ensure_ascii=False, indent=2)


def load_cached_releases():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_cached_releases(releases):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(releases, f, ensure_ascii=False, indent=2)


seen_releases = load_seen_releases()
cached_releases = load_cached_releases()

# --------------------------
# Load environment variables
# --------------------------
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('discord.log', encoding='utf-8', mode='a'),
        logging.StreamHandler()
    ]
)

# Intents setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

# Bot setup
bot = commands.Bot(command_prefix='.', intents=intents)


@bot.event
async def on_ready():
    logging.info(f'✅ Bot ready: {bot.user.name}')
    logging.info(f'✅ Connected to {len(bot.guilds)} servers')
    bot.loop.create_task(monitor_new_releases())


@bot.event
async def on_member_join(member):
    embed = discord.Embed(
        title="🎉 Welcome to Manhwa 만화!",
        description=(
            f"{member.mention}, we're thrilled to have you here!\n\n"
            "🌸 Dive into the world of Manhwa and connect with fellow fans.\n"
            "📚 Be sure to check out the rules and channel guide.\n"
            "🎭 Head over to the other channels and choose what role colors you'd like!\n"
            "💬 Say hi and let us know your favorite manhwa!"
        ),
        color=discord.Color.from_rgb(204, 153, 255)
    )
    embed.set_image(
        url="https://media.discordapp.net/attachments/1256270163997888512/1423327225423466496/ba5d741935a6ad1ad678033a0d66ef72.jpg")
    channel = bot.get_channel(948140724816330782)
    if channel:
        await channel.send(embed=embed)


# --------------------------
# Fetch and Parse Releases
# --------------------------
def fetch_releases_from_page():
    """Scrape the releases page and return ALL releases exactly as shown"""
    global cached_releases

    try:
        url = "https://www.mangaupdates.com/releases.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        releases = []

        # Find all release items - they use class containing "new-release-item"
        release_divs = soup.find_all("div", class_=lambda x: x and "new-release-item" in str(x))

        logging.info(f"Found {len(release_divs)} release divs")

        for release_div in release_divs:
            try:
                # Find the three columns: col-6 (title), col-2 (release), col-4 (groups)
                columns = release_div.find_all("div", class_=lambda x: x and (
                            "col-6" in str(x) or "col-2" in str(x) or "col-4" in str(x)))

                if len(columns) >= 3:
                    # Column 1: Title (col-6)
                    title_elem = columns[0].find("span")
                    title = title_elem.get_text(strip=True) if title_elem else columns[0].get_text(strip=True)

                    # Column 2: Release/Chapter (col-2)
                    release = columns[1].get_text(strip=True)

                    # Column 3: Groups (col-4)
                    group = columns[2].get_text(strip=True)

                    if title and release:
                        releases.append({
                            "title": title,
                            "chapter": release,
                            "group": group if group else "Unknown",
                            "key": f"{title}|{release}|{group}"
                        })
                        logging.debug(f"Parsed: {title} - {release} - {group}")

            except Exception as e:
                logging.warning(f"Error parsing individual release: {e}")
                continue

        if releases:
            logging.info(f"✅ Successfully parsed {len(releases)} releases from MangaUpdates")
            cached_releases = releases
            save_cached_releases(releases)
            return releases
        else:
            logging.warning("⚠️ No releases parsed, returning cached data")
            return cached_releases if cached_releases else []

    except Exception as e:
        logging.error(f"❌ Error fetching releases: {e}, returning cached data")
        import traceback
        logging.error(traceback.format_exc())
        return cached_releases if cached_releases else []


# --------------------------
# Monitor for New Releases (Hourly)
# --------------------------
async def monitor_new_releases():
    """Check for new releases every hour and post only NEW ones"""
    await bot.wait_until_ready()
    channel = bot.get_channel(1071812515945783397)

    if not channel:
        logging.error("❌ Release channel not found!")
        return

    logging.info("🔄 Starting hourly release monitor...")

    while not bot.is_closed():
        try:
            releases = fetch_releases_from_page()
            new_releases = []

            # Check for new releases
            for release in releases:
                if release["key"] not in seen_releases:
                    seen_releases.add(release["key"])
                    new_releases.append(release)

            if new_releases:
                logging.info(f"🆕 Found {len(new_releases)} new releases")
                save_seen_releases()

                # Post new releases in batches of 5
                chunk_size = 5
                for i in range(0, len(new_releases), chunk_size):
                    embed = discord.Embed(
                        title="🆕 New Manga/Manhwa Releases",
                        description="Fresh updates from MangaUpdates!",
                        color=discord.Color.from_rgb(204, 153, 255),
                        timestamp=datetime.utcnow()
                    )

                    for release in new_releases[i:i + chunk_size]:
                        embed.add_field(
                            name=f"📖 {release['title']}",
                            value=f"**Release:** {release['chapter']}\n**Group:** {release['group']}",
                            inline=False
                        )

                    embed.set_footer(text="MangaUpdates Release Monitor")
                    await channel.send(embed=embed)
                    await asyncio.sleep(1)  # Avoid rate limits

            else:
                logging.info("✅ No new releases found this check")

        except Exception as e:
            logging.error(f"❌ Error in release monitor: {e}")

        # Wait 1 hour before checking again
        await asyncio.sleep(3600)


# --------------------------
# Command: .latestrelease
# --------------------------
@bot.command(name='latestrelease')
async def latestrelease(ctx):
    """Display ALL current releases from MangaUpdates"""
    logging.info(f"📢 .latestrelease triggered by {ctx.author}")

    loading_msg = await ctx.send("🔍 Fetching all releases from MangaUpdates...")

    releases = fetch_releases_from_page()

    await loading_msg.delete()

    if releases:
        # Display ALL releases in chunks of 10
        chunk_size = 10
        total_releases = len(releases)

        for i in range(0, total_releases, chunk_size):
            chunk = releases[i:i + chunk_size]

            embed = discord.Embed(
                title="📚 MangaUpdates Releases",
                url="https://www.mangaupdates.com/releases.html",
                description=f"Showing {i + 1}-{min(i + chunk_size, total_releases)} of {total_releases} total releases",
                color=discord.Color.from_rgb(204, 153, 255),
                timestamp=datetime.utcnow()
            )

            for release in chunk:
                # Truncate extremely long titles to fit Discord limits
                title_display = release['title']
                if len(title_display) > 80:
                    title_display = title_display[:77] + "..."

                embed.add_field(
                    name=f"📖 {title_display}",
                    value=f"**Release:** {release['chapter']}\n**Groups:** {release['group']}",
                    inline=False
                )

            embed.set_footer(text="Live data from MangaUpdates")
            await ctx.send(embed=embed)
            await asyncio.sleep(0.5)
    else:
        await ctx.send("📢 No release data available. Please try again in a moment!")


# --------------------------
# Command: .lookup
# --------------------------
@bot.command(name='lookup')
async def lookup(ctx, *, query):
    """Search for a series on MangaUpdates and display results"""
    logging.info(f"🔍 .lookup triggered for: {query}")

    loading_msg = await ctx.send(f"🔍 Searching for '{query}' on MangaUpdates...")

    try:
        search_url = f"https://www.mangaupdates.com/series.html?search={query.replace(' ', '+')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Find search results
        results = []
        series_items = soup.find_all("div", class_=lambda x: x and any(
            word in str(x).lower() for word in ["series", "result", "item"]))

        for item in series_items[:10]:
            title_elem = item.find("a") or item.find("span")
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get('href', '') if item.find("a") else ""
                info_text = item.get_text(strip=True)

                if title and len(title) > 2:
                    results.append({
                        "title": title,
                        "link": f"https://www.mangaupdates.com{link}" if link and not link.startswith('http') else link,
                        "info": info_text[:200] if len(info_text) > len(title) else ""
                    })

        await loading_msg.delete()

        if results:
            embed = discord.Embed(
                title=f"🔎 Search Results for '{query}'",
                url=search_url,
                description=f"Found {len(results)} results",
                color=discord.Color.from_rgb(204, 153, 255)
            )

            for result in results[:8]:
                title_display = result['title'][:100]
                embed.add_field(
                    name=f"📚 {title_display}",
                    value=result['link'] if result['link'] else "No link available",
                    inline=False
                )

            embed.set_footer(text="Click the title link above to see all results")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title=f"🔎 Search Results for '{query}'",
                url=search_url,
                description="No results found. Click the link above to search directly on MangaUpdates.",
                color=discord.Color.from_rgb(204, 153, 255)
            )
            await ctx.send(embed=embed)

    except Exception as e:
        logging.error(f"Error in lookup: {e}")
        await loading_msg.delete()
        embed = discord.Embed(
            title=f"🔎 Search for '{query}'",
            url=search_url,
            description="Click the link above to view results directly on MangaUpdates.",
            color=discord.Color.from_rgb(204, 153, 255)
        )
        await ctx.send(embed=embed)


# --------------------------
# Command: .randomseries
# --------------------------
@bot.command(name='randomseries')
async def randomseries(ctx):
    """Get a random Manhwa from MangaUpdates"""
    import random

    logging.info(f"🎲 .randomseries triggered - searching for random Manhwa")

    loading_msg = await ctx.send("🎲 Finding a random Manhwa for you...")

    try:
        letter = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0")
        url = f"https://www.mangaupdates.com/series.html?letter={letter}&type=manhwa"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        manhwa_list = []
        series_links = soup.find_all("a", href=lambda x: x and "/series.html?id=" in str(x))

        for link in series_links:
            title = link.get_text(strip=True)
            series_url = link.get('href', '')

            if title and len(title) > 2:
                full_url = f"https://www.mangaupdates.com{series_url}" if not series_url.startswith(
                    'http') else series_url
                manhwa_list.append({
                    "title": title,
                    "url": full_url
                })

        attempts = 0
        while len(manhwa_list) == 0 and attempts < 3:
            letter = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
            url = f"https://www.mangaupdates.com/series.html?letter={letter}&type=manhwa"
            response = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(response.text, "html.parser")
            series_links = soup.find_all("a", href=lambda x: x and "/series.html?id=" in str(x))

            for link in series_links:
                title = link.get_text(strip=True)
                series_url = link.get('href', '')
                if title and len(title) > 2:
                    full_url = f"https://www.mangaupdates.com{series_url}" if not series_url.startswith(
                        'http') else series_url
                    manhwa_list.append({"title": title, "url": full_url})

            attempts += 1

        await loading_msg.delete()

        if manhwa_list:
            random_manhwa = random.choice(manhwa_list)

            try:
                detail_response = requests.get(random_manhwa['url'], headers=headers, timeout=10)
                detail_soup = BeautifulSoup(detail_response.text, "html.parser")

                description = "Click the title to read more on MangaUpdates!"
                desc_elem = detail_soup.find("div", class_=lambda x: x and "description" in str(x).lower())
                if desc_elem:
                    desc_text = desc_elem.get_text(strip=True)
                    description = desc_text[:300] + "..." if len(desc_text) > 300 else desc_text

            except:
                description = "Click the title to read more on MangaUpdates!"

            embed = discord.Embed(
                title=f"🎲 Random Manhwa: {random_manhwa['title']}",
                url=random_manhwa['url'],
                description=description,
                color=discord.Color.from_rgb(204, 153, 255)
            )

            if len(manhwa_list) > 1:
                other_manhwa = random.sample(manhwa_list, min(5, len(manhwa_list)))
                other_titles = "\n".join([f"• [{m['title']}]({m['url']})" for m in other_manhwa])
                embed.add_field(
                    name="🎯 More Random Manhwa:",
                    value=other_titles,
                    inline=False
                )

            embed.set_footer(text="🇰🇷 Random Manhwa from MangaUpdates")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="🎲 Random Manhwa",
                url="https://www.mangaupdates.com/series.html?type=manhwa",
                description="Click the link above to browse all Manhwa on MangaUpdates!",
                color=discord.Color.from_rgb(204, 153, 255)
            )
            await ctx.send(embed=embed)

    except Exception as e:
        logging.error(f"Error in randomseries: {e}")
        await loading_msg.delete()

        embed = discord.Embed(
            title="🎲 Random Manhwa",
            url="https://www.mangaupdates.com/series.html?type=manhwa",
            description="Click the link above to browse all Manhwa on MangaUpdates!",
            color=discord.Color.from_rgb(204, 153, 255)
        )
        await ctx.send(embed=embed)


# --------------------------
# Debug Commands
# --------------------------
@bot.command(name='testfetch')
@commands.has_permissions(administrator=True)
async def testfetch(ctx):
    """Test the scraping function (Admin only)"""
    await ctx.send("🧪 Testing fetch function...")
    releases = fetch_releases_from_page()

    if releases:
        await ctx.send(
            f"✅ Successfully fetched {len(releases)} releases!\n**First release:** {releases[0]['title']} - {releases[0]['chapter']} by {releases[0]['group']}")
    else:
        await ctx.send("❌ Fetch returned no results. Check logs for details.")


# --------------------------
# Run Bot
# --------------------------
if __name__ == "__main__":
    if DISCORD_TOKEN:
        try:
            bot.run(DISCORD_TOKEN)
        except Exception as e:
            logging.error(f"❌ Failed to start bot: {e}")
    else:
        logging.error("❌ DISCORD_TOKEN not found. Make sure it's set in your environment variables.")

from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()



