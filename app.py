import eventlet
eventlet.monkey_patch()  # Обязательно первым!

import os
import uuid
import requests
import google.generativeai as genai
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'samberrr-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- Настройки Прокси для Gemini ---
# Если твой прокси требует авторизации: http://user:pass@ip:port
PROXY_URL = os.environ.get("PROXY_URL") 
if PROXY_URL:
    os.environ['HTTP_PROXY'] = PROXY_URL
    os.environ['HTTPS_PROXY'] = PROXY_URL

# --- Настройки Supabase ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Настройки Gemini ---
GEMINI_KEYS = os.environ.get("GEMINI_API_KEY", "").split(",")
current_key_index = 0

def get_ai_response(prompt, media_data=None):
    global current_key_index
    try:
        key = GEMINI_KEYS[current_key_index].strip()
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        content = ["Ты — SamberrrAI, официальный бот Samberrrgram. Отвечай кратко и круто.", prompt]
        if media_data:
            content.append(media_data)
            
        response = model.generate_content(content)
        return response.text
    except Exception as e:
        print(f"Gemini Error: {e}")
        if "429" in str(e) and len(GEMINI_KEYS) > 1: # Лимит ключа
            current_key_index = (current_key_index + 1) % len(GEMINI_KEYS)
            return get_ai_response(prompt, media_data)
        return "Извини, я сейчас немного занят. Попробуй позже!"

# --- Роуты ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_pw = generate_password_hash(password)
        
        # Регистрация юзера
        supabase.table('users').insert({'username': username, 'password': hashed_pw}).execute()
        
        # АВТОМАТИЧЕСКОЕ появление бота у нового пользователя
        # Создаем первое сообщение, чтобы чат появился в списке
        chat_id = f"ai_chat_{username}"
        supabase.table('messages').insert({
            'chat_id': chat_id,
            'username': 'SamberrrAI',
            'text': f"Привет, {username}! Я твой ИИ-помощник. Чем могу помочь?",
            'is_read': False
        }).execute()
        
        return redirect(url_for('login'))
    return render_template('register.html')

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

@app.route('/chat')
def chat():
    if 'username' not in session: return redirect(url_for('login'))
    return render_template('chat.html', username=session['username'])

# --- Socket.IO ---

@socketio.on('send_message')
def handle_msg(data):
    room = data['room']
    text = data.get('text', '')
    media_url = data.get('media_url')
    username = session.get('username')

    # Сохраняем сообщение юзера
    new_msg = supabase.table('messages').insert({
        'chat_id': room, 'username': username, 'text': text, 
        'media_url': media_url, 'reply_to_id': data.get('reply_to_id')
    }).execute()
    
    emit('receive_message', new_msg.data[0], to=room)

    # Если сообщение отправлено в чат с ботом
    if "ai_chat" in room or room == f"ai_chat_{username}":
        emit('user_typing', {'username': 'SamberrrAI', 'action': 'typing'}, to=room)
        
        def ai_thread():
            media_data = None
            if media_url:
                raw = requests.get(media_url).content
                media_data = {"mime_type": "image/jpeg", "data": raw}
            
            answer = get_ai_response(text, media_data)
            
            ai_msg = supabase.table('messages').insert({
                'chat_id': room, 'username': 'SamberrrAI', 'text': answer, 'reply_to_id': new_msg.data[0]['id']
            }).execute()
            socketio.emit('receive_message', ai_msg.data[0], to=room)
            
        socketio.start_background_task(ai_thread)

@socketio.on('join')
def on_join(data):
    join_room(data['room'])

if __name__ == '__main__':
    socketio.run(app, debug=True)
