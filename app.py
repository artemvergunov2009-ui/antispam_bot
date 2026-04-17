import os
import uuid
import traceback
import urllib.parse
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

# Импорт Gemini
import google.generativeai as genai

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'samberrrgram-super-secret-key') 
# Используем eventlet для стабильной работы сокетов и фоновых задач
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- Настройки Supabase ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# --- Настройки Gemini (Поддержка нескольких ключей) ---
# Ключи вводить через запятую в переменной окружения, например: "KEY1,KEY2,KEY3"
GEMINI_KEYS = os.environ.get("GEMINI_API_KEY", "").split(",")
current_key_index = 0

def get_next_model():
    """Переключает ключи, если один выдает ошибку лимита"""
    global current_key_index
    if not GEMINI_KEYS or GEMINI_KEYS[0] == "":
        return None
    
    key = GEMINI_KEYS[current_key_index].strip()
    genai.configure(api_key=key)
    # Используем 1.5-flash — она быстрее и лучше понимает файлы/фото
    return genai.GenerativeModel('gemini-1.5-flash')

# Твой системный промпт
AI_SYSTEM_PROMPT = """Ты — SamberrrAI, встроенный ИИ мессенджера Samberrrgram. 
Ты анализируешь сообщения, фото и файлы. Отвечай кратко, помогай с кодом и будь полезным.
Если тебе прислали файл, изучи его содержимое и ответь на вопрос пользователя."""

active_qr_sessions = {}

# --- Логика ИИ ---
def process_ai_request(room, user_text, media_url, reply_to_id):
    global current_key_index
    try:
        model = get_next_model()
        if not model:
            print("Ошибка: API ключи Gemini не настроены")
            return

        contents = [AI_SYSTEM_PROMPT]

        # Если есть медиа (фото или файл)
        if media_url:
            response = requests.get(media_url)
            if response.status_code == 200:
                # Определяем тип файла
                mime_type = response.headers.get('Content-Type', 'image/jpeg')
                contents.append({
                    "mime_type": mime_type,
                    "data": response.content
                })

        # Добавляем текст пользователя (команду после /ai)
        contents.append(user_text if user_text else "Что на этом файле/фото?")

        # Генерация
        ai_response = model.generate_content(contents)
        answer = ai_response.text

        # Сохранение ответа в БД
        new_msg = supabase.table('messages').insert({
            'chat_id': room, 
            'username': 'SamberrrAI', 
            'text': answer, 
            'reply_to_id': reply_to_id,
            'is_read': False
        }).execute()

        msg_data = new_msg.data[0]
        # Кастомная аватарка для бота
        msg_data['users'] = {'avatar_url': 'https://api.dicebear.com/7.x/bottts/svg?seed=SamberrrAI'}
        
        socketio.emit('receive_message', msg_data, to=room)

    except Exception as e:
        print(f"Ошибка ИИ: {e}")
        # Если ошибка связана с лимитом (429), пробуем переключить ключ на следующий
        if "429" in str(e) and len(GEMINI_KEYS) > 1:
            current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
            process_ai_request(room, user_text, media_url, reply_to_id)
        else:
            socketio.emit('receive_message', {
                'chat_id': room, 'username': 'SamberrrAI', 
                'text': '❌ Не удалось обработать запрос. Попробуйте позже.',
                'reply_to_id': reply_to_id,
                'users': {'avatar_url': 'https://api.dicebear.com/7.x/bottts/svg?seed=error'}
            }, to=room)

# --- Роуты ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = supabase.table('users').select('*').eq('username', username).execute()
        if user.data and check_password_hash(user.data[0]['password'], password):
            session['username'] = username
            return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = generate_password_hash(password)
        supabase.table('users').insert({'username': username, 'password': hashed_pw}).execute()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html', username=session['username'])

# --- Socket.IO события ---

@socketio.on('join')
def on_join(data):
    join_room(data['room'])

@socketio.on('send_message')
def handle_message(data):
    try:
        room = data['room']
        text = data.get('text', '')
        media_url = data.get('media_url')
        username = session.get('username')

        # Сохраняем сообщение юзера
        new_msg = supabase.table('messages').insert({
            'chat_id': room, 'username': username, 'text': text, 
            'media_url': media_url, 'media_type': data.get('media_type'),
            'reply_to_id': data.get('reply_to_id'), 'font_style': data.get('font_style', 'default')
        }).execute()

        # Получаем аватарку юзера
        user_info = supabase.table('users').select('avatar_url').eq('username', username).execute()
        msg_data = new_msg.data[0]
        msg_data['users'] = {'avatar_url': user_info.data[0].get('avatar_url') if user_info.data else None}
        
        emit('receive_message', msg_data, to=room)

        # Проверка команды /ai
        if text.strip().lower().startswith('/ai'):
            ai_prompt = text.lower().replace('/ai', '', 1).strip()
            emit('user_typing', {'username': 'SamberrrAI', 'action': 'typing'}, to=room)
            
            # Запуск обработки в фоне
            socketio.start_background_task(process_ai_request, room, ai_prompt, media_url, msg_data['id'])

    except Exception as e:
        print(f"Error: {e}")

@socketio.on('request_qr')
def request_qr():
    token = uuid.uuid4().hex
    active_qr_sessions[token] = {'status': 'pending', 'username': None}
    join_room(f"qr_{token}")
    emit('qr_generated', {'token': token})

@socketio.on('approve_qr')
def approve_qr(data):
    token = data.get('token')
    username = session.get('username')
    if username and token in active_qr_sessions:
        active_qr_sessions[token] = {'status': 'approved', 'username': username}
        emit('qr_approved', {'token': token}, to=f"qr_{token}")

if __name__ == '__main__':
    socketio.run(app, debug=True)
