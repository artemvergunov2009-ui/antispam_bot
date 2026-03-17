
BOT_ID = bot.get_me().id

system_prompt = """
Тебя зовут Ким Самбоrrrскiй. Ты тупой, очень воняешь, но очень общительй человек. Тебе 16 лет, ты гей, и ты общаешься очень обидными шуточками. Также ты учишься в колледже информационных технологий "ИТ.Москва"(но в программировании ничего не смыслет), ходишь туда только чтобы сосаться с преподавателем попрограммированию Максимом Маратовичем, про него он говорит редко, но метко!
Ты ростом примерно 160 см, с микропенисом, но ты про это не говоришь пока не спросят. У тебя тёмный оттенок русых волос. Иногда использует гейские шутки
Ты общаешься с пользователями в Telegram. 
Твои ответы должны быть краткими, точными и без лишней воды.
"""

MODELS_TO_TRY = [
    'gemini-2.5-flash',
    'gemini-2.5-pro',
    'gemini-1.5-flash-latest',
    'gemini-1.5-pro-latest',
    'gemini-3.1-pro-preview',
    'gemini-3-flash-preview'
]

@bot.message_handler(commands=['ping', 'status'])
def ping_host(message):
    bot.reply_to(message, "✅ Бот в сети и готов принимать запросы!")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Меня зовут Ким. Обращайся ко мне по имени, отвечай на мои сообщения или просто пиши в ЛС.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
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
        
        print(f"\n--- Поступил новый запрос от пользователя ---")
        
        # === БЫСТРЫЙ ПОИСК ===
        for api_key in GEMINI_API_KEYS:
            genai.configure(api_key=api_key)
            print(f"[🔄] Подключили ключ: {api_key[:10]}...") 
            
            for model_name in MODELS_TO_TRY:
                try:
                    print(f"  -> Пробуем модель {model_name}...")
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=system_prompt 
                    )
                    response = model.generate_content(user_query)
                    response_text = response.text
                    
                    print(f"  [✅] Успех! Модель {model_name} ответила.")
                    break 
                except Exception as e:
                    print(f"  [❌] Неудача ({model_name}): {e}") 
                    continue 
            
            if response_text:
                break 
                
        if response_text:
            bot.reply_to(message, response_text)
        else:
            bot.reply_to(message, "❌ Сейчас все нейросети перегружены. Жду следующий запрос!")

print("Бот Ким запущен. Ожидание сообщений...")
bot.infinity_polling(none_stop=True)
