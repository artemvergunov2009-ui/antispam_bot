import asyncio
import re
from aiogram import Bot, Dispatcher, types, F

# Твой токен от BotFather
TOKEN = "8650702643:AAEjW4RwItxTHHuKbhUn1IHJ6B-vUfxTzqE"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Регулярное выражение для поиска упоминаний ботов и ссылок на них
BOT_PATTERN = re.compile(r"(@\w+bot)|(t\.me/\w+bot)", re.IGNORECASE)

@dp.message(F.chat.type.in_({"group", "supergroup"}))
@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def filter_bot_ads(message: types.Message, bot: Bot):
    # --- 1. ПРОВЕРКА ОТПРАВИТЕЛЯ (Если пишет другой бот) ---
    if message.from_user.is_bot:
        # Если это не наш собственный бот (чтобы он не удалял свои же ответы)
        if message.from_user.id != bot.id:
            try:
                await message.delete()
            except Exception as e:
                print(f"Не смог удалить сообщение от бота: {e}")
            return # Удалили и выходим, дальше проверять не нужно

    # --- 2. ПРОВЕРКА ОБЫЧНЫХ ПОЛЬЗОВАТЕЛЕЙ ---
    text_to_check = message.text or message.caption or ""
    
    # Игнорируем команды (чтобы твои сообщения с командами не удалялись)
    if text_to_check.startswith("/"):
        return

    # Проверка текста на прямые ссылки (@bot или t.me/bot)
    has_bot_link = bool(BOT_PATTERN.search(text_to_check))
    
    # Проверка кнопок (ищем ссылки на ботов внутри кнопок под постом)
    has_button_link = False
    if message.reply_markup and message.reply_markup.inline_keyboard:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.url and ("bot" in button.url.lower() or "t.me/" in button.url.lower()):
                    has_button_link = True
                    break

    # Проверка, переслано ли сообщение от бота (в aiogram 3 это делается через forward_origin)
    is_forwarded_from_bot = False
    if message.forward_origin and message.forward_origin.type == "hidden_user":
        # Иногда боты скрывают свое происхождение при пересылке
        pass 
    elif message.forward_origin and getattr(message.forward_origin, 'sender_user', None):
        if message.forward_origin.sender_user.is_bot:
            is_forwarded_from_bot = True

    # Если нашли хоть одно нарушение — сносим!
    if has_bot_link or has_button_link or is_forwarded_from_bot:
        try:
            await message.delete()
        except Exception as e:
            print(f"Ошибка при удалении спама: {e}")
async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())