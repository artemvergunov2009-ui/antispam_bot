import asyncio
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# 1. НАСТРОЙКИ БОТА
# Замени на свой токен
TOKEN = "8650702643:AAEjW4RwItxTHHuKbhUn1IHJ6B-vUfxTzqE" 
# Впиши сюда свой ID (только цифры, без кавычек)
ADMIN_ID = 7070204958 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Регулярное выражение для поиска упоминаний ботов
BOT_PATTERN = re.compile(r"(@\w+bot)|(t\.me/\w+bot)", re.IGNORECASE)

# =====================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА (Работает только в личных сообщениях с ботом)
# =====================================================================

@dp.message(F.chat.type == "private", Command("start"))
async def cmd_start_admin(message: types.Message):
    """Обработка команды /start в личке"""
    if message.from_user.id == ADMIN_ID:
        # Создаем кнопку
        kb = [[KeyboardButton(text="Статус работы 🟢")]]
        keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        
        await message.answer(
            "Привет, Kimpi Dor! Бот на связи. Нажми кнопку ниже, чтобы проверить мой статус.", 
            reply_markup=keyboard
        )
    else:
        await message.answer("Извините, у вас нет доступа к управлению этим ботом.")

@dp.message(F.chat.type == "private", F.text == "Статус работы 🟢")
async def check_bot_status(message: types.Message):
    """Ответ на нажатие кнопки администратором"""
    if message.from_user.id == ADMIN_ID:
        await message.answer("Всё отлично! Я работаю, мониторю чаты и готов удалять рекламу. 🛡")


# =====================================================================
# АНТИСПАМ ФИЛЬТР (Работает только в группах/супергруппах)
# =====================================================================

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def filter_bot_ads(message: types.Message):
    """Проверка всех сообщений в группе"""
    
    # 1. Если пишет другой бот напрямую — сносим сообщение
    if message.from_user.is_bot:
        if message.from_user.id != bot.id: # Не удаляем свои же сообщения
            try:
                await message.delete()
            except Exception as e:
                print(f"Не смог удалить сообщение от бота: {e}")
        return # Выходим, дальше проверять нет смысла

    text_to_check = message.text or message.caption or ""
    
    # 2. Игнорируем команды (чтобы не удалялись системные сообщения и твои команды)
    if text_to_check.startswith("/"):
        return

    # 3. Проверка текста на прямые ссылки
    has_bot_link = bool(BOT_PATTERN.search(text_to_check))
    
    # 4. Проверка кнопок (ищем ссылки на ботов внутри inline-кнопок)
    has_button_link = False
    if message.reply_markup and message.reply_markup.inline_keyboard:
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.url and ("bot" in button.url.lower() or "t.me/" in button.url.lower()):
                    has_button_link = True
                    break

    # 5. Проверка пересланных сообщений (от других ботов)
    is_forwarded_from_bot = False
    if message.forward_origin:
        if getattr(message.forward_origin, 'sender_user', None):
            if message.forward_origin.sender_user.is_bot:
                is_forwarded_from_bot = True

    # 6. ИТОГ: Если нашли хоть одно нарушение — удаляем
    if has_bot_link or has_button_link or is_forwarded_from_bot:
        try:
            await message.delete()
        except Exception as e:
            print(f"Ошибка при удалении спама: {e}")

# =====================================================================
# ЗАПУСК БОТА
# =====================================================================

async def main():
    print("Бот запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
