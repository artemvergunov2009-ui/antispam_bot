import os
import telebot
import google.generativeai as genai
from dotenv import load_dotenv

# Загружаем ключи из .env (сработает на твоем ПК, а на сервере проигнорируется)
load_dotenv()

# Вытягиваем переменные окружения
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("ОШИБКА: TELEGRAM_TOKEN не найден в переменных окружения!")

keys_env = os.getenv('GEMINI_API_KEYS', '')
GEMINI_API_KEYS = [k.strip() for k in keys_env.split(',') if k.strip()]
if not GEMINI_API_KEYS:
    raise ValueError("ОШИБКА: GEMINI_API_KEYS не найдены в переменных окружения!")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
BOT_ID = bot.get_me().id

system_prompt = """
Тебя зовут Ким. Ты саркастичный, прямолинейный и очень общительный. 
Ты учишься в Государственное бюджетное профессиональное образовательное учреждение города Москвы 'Колледж информационных технологий 'ИТ.Москва', но в программировании мало что смыслишь.
Ты общаешься с пользователями в Telegram. 
Твои ответы должны быть краткими, точными и без лишней воды.
"""

MODELS_TO_TRY = [
    'gemini-1.5-flash',
    'gemini-1.5-pro',
    'gemini-pro'
]

@bot.message_handler(commands=['ping', 'status'])
def ping_host(message):
    bot.reply_to(message, "✅ Бот в сети и готов принимать запросы!")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Меня зовут Ким. Обращайся ко мне по имени, отвечай на мои сообщения или просто пиши в ЛС.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if not message.text:
        return

    text = message.text
    is_private = message.chat.type == 'private'
    is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID
    starts_with_name = text.lower().startswith("ким")
    
    if is_private or is_reply or starts_with_name:
        user_query = text
        if starts_with_name:
            user_query = text[3:].strip(" .,?!")
            
        if not user_query:
            bot.reply_to(message, "Да, я слушаю. Что хотел?")
            return

        bot.send_chat_action(message.chat.id, 'typing')
        response_text = None
        
        print("\n--- Поступил новый запрос ---")
        
        for api_key in GEMINI_API_KEYS:
            genai.configure(api_key=api_key)
            
            for model_name in MODELS_TO_TRY:
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=system_prompt 
                    )
                    response = model.generate_content(user_query)
                    response_text = response.text
                    break
                except Exception as e:
                    print(f"[❌] Ошибка модели {model_name}: {e}") 
                    continue
            
            if response_text:
                break
                
        if response_text:
            bot.reply_to(message, response_text)
        else:
            bot.reply_to(message, "❌ Сейчас все нейросети перегружены. Жду следующий запрос!")

if __name__ == "__main__":
    print("Запуск бота...")
    bot.infinity_polling(none_stop=True)
