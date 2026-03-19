import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Секретный ключ тоже берем из среды, а если его нет — используем запасной
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'samberrrgram-super-secret-key') 
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Настройки Supabase (БЕЗОПАСНЫЕ) ---
# Теперь ключи не написаны текстом, сервер будет брать их из своих скрытых настроек
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ВНИМАНИЕ: Ключи Supabase не найдены! Убедитесь, что добавили их в Environment Variables.")

# Создаем клиента только если ключи есть (чтобы локально не падало с ошибкой до настройки)
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- БАЗОВЫЕ МАРШРУТЫ ---
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
        if username and password:
            user_response = supabase.table('users').select('*').eq('username', username).execute()
            if not user_response.data:
                hashed_pw = generate_password_hash(password)
                supabase.table('users').insert({'username': username, 'password_hash': hashed_pw, 'last_seen': datetime.utcnow().isoformat()}).execute()
                saved_id = f"saved_{username}"
                supabase.table('chats').insert({'id': saved_id, 'name': 'Избранные', 'type': 'saved'}).execute()
                supabase.table('chat_members').insert({'chat_id': saved_id, 'username': username}).execute()
                session['username'] = username
                return redirect(url_for('chat'))
            else:
                user = user_response.data[0]
                if not user.get('password_hash'):
                    hashed_pw = generate_password_hash(password)
                    supabase.table('users').update({'password_hash': hashed_pw, 'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
                    session['username'] = username
                    return redirect(url_for('chat'))
                elif check_password_hash(user['password_hash'], password):
                    session['username'] = username
                    supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
                    return redirect(url_for('chat'))
                else:
                    error = "Неверный пароль!"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    username = session.get('username')
    if username:
        supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/chat')
def chat():
    if 'username' not in session: return redirect(url_for('login'))
    return render_template('chat.html', username=session['username'])

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'Empty file'}), 400
    
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    try:
        file_bytes = file.read()
        supabase.storage.from_('chat_media').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('chat_media').get_public_url(filename)
        
        # МАГИЯ: Определяем тип контента (аудио, видео или картинка)
        if file.content_type.startswith('audio'): media_type = 'audio'
        elif file.content_type.startswith('video'): media_type = 'video'
        else: media_type = 'image'
        
        return jsonify({'url': url, 'type': media_type})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'Empty file'}), 400
    ext = file.filename.split('.')[-1]
    filename = f"avatar_{session['username']}_{uuid.uuid4().hex[:6]}.{ext}"
    try:
        file_bytes = file.read()
        supabase.storage.from_('avatars').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('avatars').get_public_url(filename)
        supabase.table('users').update({'avatar_url': url}).eq('username', session['username']).execute()
        return jsonify({'url': url})
    except Exception as e: return jsonify({'error': str(e)}), 500

# --- WEBSOCKETS ---
connected_clients = {}

@socketio.on('user_connected')
def user_connected():
    username = session.get('username')
    if username:
        connected_clients[request.sid] = username
        supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
        join_room(f"user_{username}")
        emit('status_update', {'username': username, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    username = connected_clients.pop(request.sid, None)
    if username:
        if username not in connected_clients.values():
            last_seen_time = datetime.utcnow().isoformat()
            supabase.table('users').update({'last_seen': last_seen_time}).eq('username', username).execute()
            emit('status_update', {'username': username, 'status': 'offline', 'last_seen': last_seen_time}, broadcast=True)

@socketio.on('get_my_chats')
def get_my_chats():
    me = session.get('username')
    memberships = supabase.table('chat_members').select('chat_id').eq('username', me).execute()
    chat_ids = [m['chat_id'] for m in memberships.data]
    if chat_ids:
        chats = supabase.table('chats').select('*').in_('id', chat_ids).execute()
        unread_res = supabase.table('messages').select('chat_id').in_('chat_id', chat_ids).neq('username', me).eq('is_read', False).execute()
        unread_counts = {}
        for msg in unread_res.data:
            cid = msg['chat_id']
            unread_counts[cid] = unread_counts.get(cid, 0) + 1
            
        for chat in chats.data:
            chat['unread_count'] = unread_counts.get(chat['id'], 0)
            last_msg = supabase.table('messages').select('username, text, media_url, media_type, created_at, is_read').eq('chat_id', chat['id']).order('created_at', desc=True).limit(1).execute()
            if last_msg.data:
                chat['last_message'] = last_msg.data[0]
                chat['last_msg_time'] = last_msg.data[0]['created_at']
            else:
                chat['last_message'] = None
                chat['last_msg_time'] = '1970-01-01T00:00:00Z'
                
        chats_sorted = sorted(chats.data, key=lambda x: x['last_msg_time'], reverse=True)
        emit('update_chat_list', chats_sorted)

@socketio.on('search_users')
def search_users(data):
    query = data.get('query', '')
    me = session.get('username')
    users = supabase.table('users').select('username').ilike('username', f'%{query}%').execute()
    results = [u['username'] for u in users.data if u['username'] != me]
    emit('search_results', results)

@socketio.on('search_for_group')
def search_for_group(data):
    query = data.get('query', '')
    me = session.get('username')
    users = supabase.table('users').select('username, avatar_url').ilike('username', f'%{query}%').limit(10).execute()
    results = [u for u in users.data if u['username'] != me]
    emit('group_search_results', results)

@socketio.on('delete_messages')
def delete_messages(data):
    msg_ids = data.get('ids', [])
    room = data.get('room')
    if msg_ids:
        supabase.table('messages').delete().in_('id', msg_ids).execute()
        emit('messages_deleted', {'ids': msg_ids}, to=room)

@socketio.on('edit_message')
def edit_message(data):
    msg_id = data.get('id')
    new_text = data.get('text')
    room = data.get('room')
    supabase.table('messages').update({'text': new_text}).eq('id', msg_id).execute()
    emit('message_edited', {'id': msg_id, 'text': new_text}, to=room)

@socketio.on('pin_message')
def pin_message(data):
    msg_id = data.get('id')
    room = data.get('room')
    # Сначала открепляем всё в этом чате (если хочешь только один закреп)
    supabase.table('messages').update({'is_pinned': False}).eq('chat_id', room).execute()
    # Закрепляем новое
    supabase.table('messages').update({'is_pinned': True}).eq('id', msg_id).execute()
    emit('message_pinned', {'id': msg_id}, to=room)

@socketio.on('update_group_info')
def update_group_info(data):
    room = data.get('room')
    new_name = data.get('name')
    new_avatar = data.get('avatar_url')
    update_data = {}
    if new_name: update_data['name'] = new_name
    if new_avatar: update_data['avatar_url'] = new_avatar
    
    supabase.table('chats').update(update_data).eq('id', room).execute()
    emit('group_updated', {'room': room, 'name': new_name, 'avatar_url': new_avatar}, broadcast=True)

@socketio.on('start_dm')
def start_dm(data):
    target = data['target']
    me = session.get('username')
    participants = sorted([me, target])
    chat_id = f"dm_{participants[0]}_{participants[1]}"
    existing = supabase.table('chats').select('*').eq('id', chat_id).execute()
    if not existing.data:
        chat_name = f"{participants[0]} & {participants[1]}"
        supabase.table('chats').insert({'id': chat_id, 'name': chat_name, 'type': 'dm'}).execute()
        supabase.table('chat_members').insert([{'chat_id': chat_id, 'username': me}, {'chat_id': chat_id, 'username': target}]).execute()
    emit('chat_created')

@socketio.on('create_group')
def create_group(data):
    group_name = data.get('name', 'Новая группа').strip()
    members = data.get('members', []) 
    me = session.get('username')
    if not group_name or not members: return
    if me not in members: members.append(me)
    valid_users = supabase.table('users').select('username').in_('username', members).execute()
    valid_usernames = [u['username'] for u in valid_users.data]
    chat_id = f"group_{uuid.uuid4().hex[:8]}"
    supabase.table('chats').insert({'id': chat_id, 'name': group_name, 'type': 'group'}).execute()
    members_data = [{'chat_id': chat_id, 'username': user} for user in valid_usernames]
    supabase.table('chat_members').insert(members_data).execute()
    emit('chat_created')

@socketio.on('join')
def on_join(data):
    room = data['room']
    me = session.get('username')
    join_room(room)
    supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
    emit('messages_read', {'room': room, 'by': me}, to=room)
    history = supabase.table('messages').select('id, chat_id, username, text, media_url, media_type, created_at, is_read, users(avatar_url)').eq('chat_id', room).order('created_at').execute()
    emit('load_history', history.data)

@socketio.on('mark_read')
def mark_read(data):
    room = data['room']
    me = session.get('username')
    supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
    emit('messages_read', {'room': room, 'by': me}, to=room)

@socketio.on('leave')
def on_leave(data):
    room = data['room']
    leave_room(room)

@socketio.on('typing')
def handle_typing(data):
    room = data['room']
    emit('user_typing', {'username': session.get('username')}, to=room, include_self=False)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    room = data['room']
    emit('user_stop_typing', {'username': session.get('username')}, to=room, include_self=False)

@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    text = data.get('text', '')
    media_url = data.get('media_url')
    media_type = data.get('media_type')
    username = session.get('username')
    
    new_msg = supabase.table('messages').insert({'chat_id': room, 'username': username, 'text': text, 'media_url': media_url, 'media_type': media_type, 'is_read': False}).execute()
    user_data = supabase.table('users').select('avatar_url').eq('username', username).execute()
    avatar_url = user_data.data[0].get('avatar_url') if user_data.data else None
    
    msg_data = {
        'id': new_msg.data[0]['id'] if new_msg.data else None,
        'room': room, 'username': username, 'text': text, 
        'media_url': media_url, 'media_type': media_type, 
        'is_read': False, 'users': {'avatar_url': avatar_url}
    }
    
    emit('receive_message', msg_data, to=room)
    
    members_res = supabase.table('chat_members').select('username').eq('chat_id', room).execute()
    for m in members_res.data:
        target_user = m['username']
        if target_user != username:
            emit('new_message_notification', msg_data, to=f"user_{target_user}")

@socketio.on('get_profile')
def get_profile(data):
    target_user = data.get('username')
    res = supabase.table('users').select('username, avatar_url, bio, custom_status, last_seen').eq('username', target_user).execute()
    if res.data: 
        profile_data = res.data[0]
        profile_data['is_online'] = profile_data['username'] in connected_clients.values()
        emit('profile_data', profile_data)

@socketio.on('update_settings')
def update_settings(data):
    me = session.get('username')
    bio = data.get('bio', '').strip()
    custom_status = data.get('custom_status', '').strip()
    supabase.table('users').update({'bio': bio, 'custom_status': custom_status}).eq('username', me).execute()
    emit('status_update', {'username': me, 'custom_status': custom_status}, broadcast=True)

@socketio.on('check_user_status')
def check_user_status(data):
    target = data.get('username')
    if target:
        is_online = target in connected_clients.values()
        user_db = supabase.table('users').select('custom_status, last_seen').eq('username', target).execute()
        if user_db.data:
            custom_status = user_db.data[0].get('custom_status', '')
            last_seen = user_db.data[0].get('last_seen', '')
            emit('receive_user_status', {'username': target, 'is_online': is_online, 'custom_status': custom_status, 'last_seen': last_seen})

@socketio.on('get_group_info')
def get_group_info(data):
    room = data.get('room')
    res = supabase.table('chat_members').select('username').eq('chat_id', room).execute()
    members = [m['username'] for m in res.data]
    emit('group_info_data', {'members': members})

# --- ЗВОНКИ (АУДИО) ---
@socketio.on('call_user')
def call_user(data):
    emit('incoming_call', {'from': session.get('username')}, to=f"user_{data.get('target')}")

@socketio.on('answer_call')
def answer_call(data):
    emit('call_accepted', {'by': session.get('username')}, to=f"user_{data.get('caller')}")

@socketio.on('reject_call')
def reject_call(data):
    emit('call_rejected', {'by': session.get('username')}, to=f"user_{data.get('caller')}")

@socketio.on('webrtc_offer')
def webrtc_offer(data):
    emit('webrtc_offer', {'offer': data['offer'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('webrtc_answer')
def webrtc_answer(data):
    emit('webrtc_answer', {'answer': data['answer'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('webrtc_ice_candidate')
def webrtc_ice_candidate(data):
    emit('webrtc_ice_candidate', {'candidate': data['candidate'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('end_call')
def end_call(data):
    emit('call_ended', {'by': session.get('username')}, to=f"user_{data['target']}")

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
