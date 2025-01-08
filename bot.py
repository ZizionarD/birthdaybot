import discord
from discord.ext import commands, tasks
import json
from datetime import datetime, timedelta, time
import asyncio
import os
import logging
from dotenv import load_dotenv
import aiofiles

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    logger.error("Токен Discord не найден. Убедитесь, что он указан в .env файле.")
    exit(1)

# Загрузка конфигурации
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    logger.error(f"Файл конфигурации {CONFIG_FILE} не найден.")
    exit(1)

with open(CONFIG_FILE, "r") as config_file:
    config = json.load(config_file)

BIRTHDAY_CHANNEL_ID = config.get("BIRTHDAY_CHANNEL_ID")
SETUP_CHANNEL_ID = config.get("SETUP_CHANNEL_ID")

if not BIRTHDAY_CHANNEL_ID or not SETUP_CHANNEL_ID:
    logger.error("ID каналов не указаны в конфигурации.")
    exit(1)

# Проверяем и создаём файл birthdays.json, если он отсутствует
BIRTHDAYS_FILE = "birthdays.json"
if not os.path.exists(BIRTHDAYS_FILE):
    with open(BIRTHDAYS_FILE, "w") as f:
        json.dump({}, f)

# Загружаем дни рождения
async def load_birthdays():
    async with aiofiles.open(BIRTHDAYS_FILE, mode="r") as f:
        return json.loads(await f.read())

async def save_birthdays():
    async with aiofiles.open(BIRTHDAYS_FILE, mode="w") as f:
        await f.write(json.dumps(birthdays))

birthdays = {}

# Инициализация бота
intents = discord.Intents.default()
intents.messages = True
intents.reactions = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Команда для указания даты рождения
@bot.command(name="set_birthday")
async def set_birthday(ctx, date: str):
    if ctx.channel.id != SETUP_CHANNEL_ID:
        await ctx.send(f"Команду можно использовать только в канале <#{SETUP_CHANNEL_ID}>.")
        return

    # Проверка на наличие даты рождения
    user_id = str(ctx.author.id)
    if user_id in birthdays:
        await ctx.send(f"{ctx.author.mention}, ваша дата рождения уже была установлена на {birthdays[user_id]}. Если вы хотите изменить её, сначала удалите старую с помощью команды !remove_birthday.")
        return

    try:
        birthday = datetime.strptime(date, "%d.%m.%Y")
        if birthday > datetime.now():
            await ctx.send(f"{ctx.author.mention}, дата рождения не может быть в будущем!")
            return
        elif (datetime.now() - birthday).days / 365 > 150:
            await ctx.send(f"{ctx.author.mention}, введите реальную дату рождения.")
            return

        # Сообщение о согласии
        consent_message = await ctx.send(
            f"\ud83d\udcdc {ctx.author.mention}, вы подтверждаете, что согласны на обработку ваших персональных данных для поздравлений с днём рождения? "
            "Пожалуйста, отреагируйте: \u2705 — согласен, \u274c — не согласен."
        )
        await consent_message.add_reaction("\u2705")
        await consent_message.add_reaction("\u274c")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["\u2705", "\u274c"] and reaction.message.id == consent_message.id

        try:
            reaction, _ = await bot.wait_for("reaction_add", timeout=60.0, check=check)
            if str(reaction.emoji) == "\u2705":
                birthdays[user_id] = date

                # Сохраняем в файл
                await save_birthdays()

                confirmation_message = await ctx.send(f"{ctx.author.mention}, ваша дата рождения успешно сохранена!")
                await asyncio.sleep(5)
                await confirmation_message.delete()
            else:
                decline_message = await ctx.send(f"{ctx.author.mention}, вы отказались от обработки данных. Дата рождения не сохранена.")
                await asyncio.sleep(5)
                await decline_message.delete()
        except asyncio.TimeoutError:
            timeout_message = await ctx.send(f"{ctx.author.mention}, вы не отреагировали вовремя. Попробуйте снова.")
            await asyncio.sleep(5)
            await timeout_message.delete()

        # Удаляем сообщение о согласии
        await consent_message.delete()
    except ValueError:
        error_message = await ctx.send("Некорректный формат даты. Используйте ДД.ММ.ГГГГ.")
        await asyncio.sleep(5)
        await error_message.delete()

    # Удаляем сообщение команды пользователя
    await ctx.message.delete()

# Команда для вывода списка дней рождения
@bot.command(name="list")
async def list_birthdays(ctx):
    if not birthdays:
        await ctx.send("Список дней рождений пуст.")
        return

    sorted_birthdays = sorted(
        birthdays.items(), 
        key=lambda item: datetime.strptime(item[1], "%d.%m.%Y")
    )
    grouped_birthdays = {}
    for user_id, date in sorted_birthdays:
        month = datetime.strptime(date, "%d.%m.%Y").strftime("%B")
        if month not in grouped_birthdays:
            grouped_birthdays[month] = []
        grouped_birthdays[month].append((user_id, date))

    embed = discord.Embed(
        title="📅 Список дней рождений", 
        color=discord.Color.blue()
    )

    for month, users in grouped_birthdays.items():
        value = "\n".join(
            f"<@{user_id}> — {date}" for user_id, date in users
        )
        embed.add_field(name=month, value=value, inline=False)

    await ctx.send(embed=embed)

# Команда для удаления даты рождения
@bot.command(name="remove_birthday")
async def remove_birthday(ctx):
    user_id = str(ctx.author.id)
    if user_id in birthdays:
        del birthdays[user_id]
        await save_birthdays()
        await ctx.send(f"{ctx.author.mention}, ваша дата рождения удалена.")
    else:
        await ctx.send(f"{ctx.author.mention}, вы ещё не добавили дату рождения.")

# Задача для проверки дней рождения
@tasks.loop(hours=24)
async def check_birthdays():
    today = datetime.now().strftime("%d.%m")
    channel = bot.get_channel(BIRTHDAY_CHANNEL_ID)

    if not channel:
        logger.error("Канал для поздравлений не найден. Проверьте конфигурацию.")
        return

    birthday_users = [
        await bot.fetch_user(int(user_id))
        for user_id, birthday in birthdays.items()
        if birthday.startswith(today)
    ]

    if birthday_users:
        mentions = ', '.join(user.mention for user in birthday_users)
        await channel.send(f"@everyone \ud83c\udf89 Сегодня День Рождения у {mentions}! \ud83c\udf82 Не забудьте поздравить!")

@check_birthdays.before_loop
async def before_check_birthdays():
    await bot.wait_until_ready()
    now = datetime.now()
    midnight = datetime.combine(now + timedelta(days=1), time.min)
    await discord.utils.sleep_until(midnight)

@tasks.loop(hours=24)
async def notify_upcoming_birthdays():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m")
    channel = bot.get_channel(BIRTHDAY_CHANNEL_ID)

    if not channel:
        logger.error("Канал для уведомлений не найден.")
        return

    upcoming_users = [
        await bot.fetch_user(int(user_id))
        for user_id, birthday in birthdays.items()
        if birthday.startswith(tomorrow)
    ]

    if upcoming_users:
        mentions = ', '.join(user.mention for user in upcoming_users)
        await channel.send(f"🔔 Завтра день рождения у {mentions}! 🎉")
        
@notify_upcoming_birthdays.before_loop
async def before_notify_upcoming_birthdays():
    await bot.wait_until_ready()
    now = datetime.now()
    next_run = datetime.combine(now + timedelta(days=1), time.min)
    await discord.utils.sleep_until(next_run)

# Цикл смены статуса бота
@tasks.loop(minutes=1)
async def change_status():
    statuses = [
        discord.Status.online,
        discord.Status.idle,
        discord.Status.dnd
    ]
    current_status = statuses[change_status.current_index]
    await bot.change_presence(status=current_status, activity=discord.Game(name="!set_birthday"))
    change_status.current_index = (change_status.current_index + 1) % len(statuses)

change_status.current_index = 0

# Запуск бота
@bot.event
async def on_ready():
    global birthdays
    birthdays = await load_birthdays()
    logger.info(f"Бот {bot.user} запущен!")
    await bot.change_presence(activity=discord.Game(name="!set_birthday"))
    check_birthdays.start()
    notify_upcoming_birthdays.start()
    change_status.start()

try:
    bot.run(TOKEN)
except discord.LoginFailure:
    logger.error("Ошибка: Неверный токен.")
except Exception as e:
    logger.error(f"Непредвиденная ошибка: {e}")
