import telebot
import google.generativeai as genai

# ВАЖНО: Вставь сюда НОВЫЕ ключи после их перевыпуска!
TELEGRAM_TOKEN = '8382508988:AAH35lahmKi3QRqZF2cpmY_Rb9MgbXbnUGo'
GEMINI_API_KEY = 'AIzaSyBDEvpRHGIhVgnDNWTZYvRn8s5JHyMWoEg'

bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)

# Безопасный системный промпт
system_prompt = """Тебя зовут Ким Самбоrrrскiй. Ты тупой, очень воняешь, но очень общительй человек. Тебе 16 лет, ты гей, и ты общаешься очень обидными шуточками. Но когда тебе уже говорят обидное что то то ты начинаешь обижаться!
Ты общаешься с пользователями в Telegram. 
Твои ответы должны быть краткими, точными и без лишней воды."""

# Список моделей по приоритету (от самой новой к старым)
MODELS_TO_TRY = [
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-1.5-flash'
]

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Меня зовут Ким. Обращайся ко мне по имени, если что-то нужно.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text
    
    if text.lower().startswith("ким"):
        user_query = text[3:].strip(" .,?!")
        
        if not user_query:
            bot.reply_to(message, "Да, я слушаю. Что хотел?")
            return

        bot.send_chat_action(message.chat.id, 'typing')
        
        # === ЛОГИКА ПЕРЕБОРА МОДЕЛЕЙ ===
        response_text = None
        
        # Проходимся циклом по нашему списку моделей
        for model_name in MODELS_TO_TRY:
            try:
                print(f"Пробуем модель {model_name}...")
                
                # Инициализируем конкретную модель из списка
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt 
                )
                
                # Пытаемся получить ответ
                response = model.generate_content(user_query)
                response_text = response.text
                
                # Если ошибки нет и ответ получен, прерываем цикл
                break 
                
            except Exception as e:
                # Если эта модель выдала ошибку (например, 404), выводим ее в консоль и идем к следующей
                print(f"Ошибка с {model_name}: {e}")
                continue
        
        # === ПРОВЕРКА РЕЗУЛЬТАТА ===
        if response_text:
            # Если хотя бы одна модель ответила успешно
            bot.reply_to(message, response_text)
        else:
            # Если цикл прошел по всем моделям, и все выдали ошибку
            bot.reply_to(message, "Извини, сейчас у меня технические неполадки со всеми нейросетями. Попробуй позже.")

print("Бот Ким запущен...")
bot.infinity_polling()
