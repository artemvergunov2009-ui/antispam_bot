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
                supabase.table('chat_members').insert({'chat_id': saved_id, 'username': username, 'role': 'owner'}).execute()
                
                # --- АВТОПОДПИСКА НА КАНАЛ ПРИ РЕГИСТРАЦИИ ---
                try:
                    official = supabase.table('chats').select('id').eq('name', 'Samberrrgram Official').execute()
                    if official.data:
                        # Проверяем, не состоит ли уже
                        existing = supabase.table('chat_members').select('*').eq('chat_id', official.data[0]['id']).eq('username', username).execute()
                        if not existing.data:
                            supabase.table('chat_members').insert({'chat_id': official.data[0]['id'], 'username': username, 'role': 'member'}).execute()
                except Exception:
                    pass

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
    if username: supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
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
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    try:
        file_bytes = file.read()
        supabase.storage.from_('chat_media').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('chat_media').get_public_url(filename)
        if file.content_type.startswith('audio'): media_type = 'audio'
        elif file.content_type.startswith('video'): media_type = 'video'
        else: media_type = 'image'
        return jsonify({'url': url, 'type': media_type})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    file = request.files['file']
    ext = file.filename.split('.')[-1]
    filename = f"avatar_{session['username']}_{uuid.uuid4().hex[:6]}.{ext}"
    try:
        file_bytes = file.read()
        supabase.storage.from_('avatars').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('avatars').get_public_url(filename)
        supabase.table('users').update({'avatar_url': url}).eq('username', session['username']).execute()
        return jsonify({'url': url})
    except Exception as e: return jsonify({'error': str(e)}), 500

@app.route('/upload_group_avatar', methods=['POST'])
def upload_group_avatar():
    if 'username' not in session: return jsonify({'error': 'Unauthorized'}), 401
    file = request.files['file']
    chat_id = request.form.get('chat_id')
    ext = file.filename.split('.')[-1]
    filename = f"group_{chat_id}_{uuid.uuid4().hex[:6]}.{ext}"
    try:
        file_bytes = file.read()
        supabase.storage.from_('avatars').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('avatars').get_public_url(filename)
        supabase.table('chats').update({'avatar_url': url}).eq('id', chat_id).execute()
        return jsonify({'url': url})
    except Exception as e: return jsonify({'error': str(e)}), 500

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
    memberships = supabase.table('chat_members').select('chat_id, role').eq('username', me).execute()
    my_roles = {m['chat_id']: m['role'] for m in memberships.data}
    chat_ids = list(my_roles.keys())
    
    if chat_ids:
        chats = supabase.table('chats').select('*').in_('id', chat_ids).execute()
        unread_res = supabase.table('messages').select('chat_id').in_('chat_id', chat_ids).neq('username', me).eq('is_read', False).execute()
        unread_counts = {}
        for msg in unread_res.data:
            cid = msg['chat_id']
            unread_counts[cid] = unread_counts.get(cid, 0) + 1
            
        for chat in chats.data:
            chat['my_role'] = my_roles.get(chat['id'], 'member')
            chat['unread_count'] = unread_counts.get(chat['id'], 0)
            last_msg = supabase.table('messages').select('username, text, media_url, media_type, created_at, is_read, is_pinned').eq('chat_id', chat['id']).order('created_at', desc=True).limit(1).execute()
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
    supabase.table('messages').update({'text': data.get('text'), 'is_edited': True}).eq('id', data.get('id')).execute()
    emit('message_edited', {'id': data.get('id'), 'text': data.get('text')}, to=data.get('room'))

@socketio.on('change_font')
def change_font(data):
    supabase.table('messages').update({'font_style': data.get('font')}).eq('id', data.get('id')).execute()
    emit('message_font_changed', {'id': data.get('id'), 'font_style': data.get('font')}, to=data.get('room'))

@socketio.on('pin_message')
def pin_message(data):
    msg_id = data.get('id')
    room = data.get('room')
    if data.get('action') == 'pin':
        supabase.table('messages').update({'is_pinned': True}).eq('id', msg_id).execute()
        emit('message_pinned', {'id': msg_id, 'text': data.get('text')}, to=room)
    else:
        supabase.table('messages').update({'is_pinned': False}).eq('id', msg_id).execute()
        emit('message_unpinned', {'id': msg_id}, to=room)

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
        supabase.table('chat_members').insert([{'chat_id': chat_id, 'username': me, 'role': 'owner'}, {'chat_id': chat_id, 'username': target, 'role': 'member'}]).execute()
    emit('chat_created')

@socketio.on('create_group')
def create_group(data):
    group_name = data.get('name', 'Новая группа').strip()
    is_channel = data.get('is_channel', False)
    members = data.get('members', []) 
    me = session.get('username')
    if not group_name: return
    
    chat_type = 'channel' if is_channel else 'group'
    chat_id = f"{chat_type}_{uuid.uuid4().hex[:8]}"
    
    supabase.table('chats').insert({'id': chat_id, 'name': group_name, 'type': chat_type, 'description': data.get('desc', '')}).execute()
    
    members_data = [{'chat_id': chat_id, 'username': me, 'role': 'owner'}]
    valid_users = supabase.table('users').select('username').in_('username', members).execute()
    for u in valid_users.data:
        if u['username'] != me:
            members_data.append({'chat_id': chat_id, 'username': u['username'], 'role': 'member'})
            
    supabase.table('chat_members').insert(members_data).execute()
    emit('chat_created')

@socketio.on('leave_chat_completely')
def leave_chat_completely(data):
    me = session.get('username')
    room = data.get('room')
    supabase.table('chat_members').delete().eq('chat_id', room).eq('username', me).execute()
    emit('chat_left_success', {'room': room}, to=request.sid)

@socketio.on('manage_member')
def manage_member(data):
    me = session.get('username')
    room = data.get('room')
    target = data.get('target')
    action = data.get('action') 
    
    my_mem = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', me).execute()
    if not my_mem.data or my_mem.data[0]['role'] not in ['owner', 'admin']: return
    
    if action == 'kick':
        supabase.table('chat_members').delete().eq('chat_id', room).eq('username', target).execute()
    elif action == 'promote':
        supabase.table('chat_members').update({'role': 'admin'}).eq('chat_id', room).eq('username', target).execute()
    elif action == 'demote':
        supabase.table('chat_members').update({'role': 'member'}).eq('chat_id', room).eq('username', target).execute()
    elif action == 'add':
        exists = supabase.table('chat_members').select('*').eq('chat_id', room).eq('username', target).execute()
        if not exists.data:
            supabase.table('chat_members').insert({'chat_id': room, 'username': target, 'role': 'member'}).execute()
            
    emit('group_members_updated', {'room': room}, broadcast=True)

@socketio.on('update_group_info')
def update_group_info(data):
    me = session.get('username')
    room = data.get('room')
    my_mem = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', me).execute()
    if not my_mem.data or my_mem.data[0]['role'] not in ['owner', 'admin']: return

    update_data = {}
    if data.get('name'): update_data['name'] = data.get('name')
    if data.get('desc') is not None: update_data['description'] = data.get('desc')
    if data.get('show_members') is not None: update_data['show_members'] = data.get('show_members')
    
    if update_data:
        supabase.table('chats').update(update_data).eq('id', room).execute()
        emit('group_updated', {'room': room, 'name': update_data.get('name')}, broadcast=True)

@socketio.on('get_group_info')
def get_group_info(data):
    room = data.get('room')
    res = supabase.table('chat_members').select('username, role').eq('chat_id', room).execute()
    chat_res = supabase.table('chats').select('name, avatar_url, description, type, show_members').eq('id', room).execute()
    
    if chat_res.data:
        emit('group_info_data', {
            'room': room,
            'members': res.data, 
            'name': chat_res.data[0].get('name'),
            'desc': chat_res.data[0].get('description', ''),
            'type': chat_res.data[0].get('type'),
            'show_members': chat_res.data[0].get('show_members', True),
            'avatar_url': chat_res.data[0].get('avatar_url')
        })

@socketio.on('join')
def on_join(data):
    room = data['room']
    me = session.get('username')
    join_room(room)
    supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
    emit('messages_read', {'room': room, 'by': me}, to=room)
    history = supabase.table('messages').select('id, chat_id, username, text, media_url, media_type, created_at, is_read, reply_to_id, font_style, is_pinned, is_edited, users(avatar_url)').eq('chat_id', room).order('created_at').execute()
    emit('load_history', history.data)

@socketio.on('mark_read')
def mark_read(data):
    room = data['room']
    me = session.get('username')
    supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
    emit('messages_read', {'room': room, 'by': me}, to=room)

@socketio.on('leave')
def on_leave(data):
    leave_room(data['room'])

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {'username': session.get('username'), 'action': data.get('action', 'typing')}, to=data['room'], include_self=False)

@socketio.on('stop_typing')
def handle_stop_typing(data):
    emit('user_stop_typing', {'username': session.get('username')}, to=data['room'], include_self=False)

@socketio.on('send_message')
def handle_message(data):
    room = data['room']
    text = data.get('text', '')
    media_url = data.get('media_url')
    media_type = data.get('media_type')
    reply_to = data.get('reply_to_id')
    font = data.get('font_style', 'default')
    username = session.get('username')
    
    # Check permissions for channels
    chat_info = supabase.table('chats').select('type').eq('id', room).execute()
    if chat_info.data and chat_info.data[0].get('type') == 'channel':
        my_role = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', username).execute()
        if not my_role.data or my_role.data[0].get('role') not in ['owner', 'admin']:
            return # Block message
    
    new_msg = supabase.table('messages').insert({
        'chat_id': room, 'username': username, 'text': text, 
        'media_url': media_url, 'media_type': media_type, 
        'reply_to_id': reply_to, 'font_style': font, 'is_read': False
    }).execute()
    
    user_data = supabase.table('users').select('avatar_url').eq('username', username).execute()
    avatar_url = user_data.data[0].get('avatar_url') if user_data.data else None
    
    msg_data = new_msg.data[0]
    msg_data['users'] = {'avatar_url': avatar_url}
    
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

# --- ЗВОНКИ (ИДЕАЛЬНО ТВОИ, РОДНЫЕ) ---
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
