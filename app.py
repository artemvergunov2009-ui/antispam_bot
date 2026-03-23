import os
import uuid
import traceback
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Секретный ключ тоже берем из среды, а если его нет — используем запасной
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'samberrrgram-super-secret-key') 
socketio = SocketIO(app, cors_allowed_origins="*")
# --- Настройки Supabase (БЕЗОПАСНЫЕ) -
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
            try:
                user_response = supabase.table('users').select('*').eq('username', username).execute()
                if not user_response.data:
                    hashed_pw = generate_password_hash(password)
                    supabase.table('users').insert({'username': username, 'password_hash': hashed_pw, 'last_seen': datetime.utcnow().isoformat()}).execute()
                    saved_id = f"saved_{username}"
                    supabase.table('chats').insert({'id': saved_id, 'name': 'Избранные', 'type': 'saved'}).execute()
                    supabase.table('chat_members').insert({'chat_id': saved_id, 'username': username, 'role': 'owner'}).execute()
                    
                    try:
                        official = supabase.table('chats').select('id').eq('name', 'Samberrrgram Official').execute()
                        if official.data:
                            existing = supabase.table('chat_members').select('*').eq('chat_id', official.data[0]['id']).eq('username', username).execute()
                            if not existing.data:
                                supabase.table('chat_members').insert({'chat_id': official.data[0]['id'], 'username': username, 'role': 'member'}).execute()
                    except Exception: pass

                    # === НОВОЕ: АКТИВИРУЕМ ДОЛГУЮ СЕССИЮ ===
                    session.permanent = True
                    session['username'] = username
                    return redirect(url_for('chat'))
                else:
                    user = user_response.data[0]
                    if user.get('is_banned'): return render_template('login.html', error="Ваш аккаунт заблокирован администратором.")
                    
                    if not user.get('password_hash'):
                        hashed_pw = generate_password_hash(password)
                        supabase.table('users').update({'password_hash': hashed_pw, 'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
                        session.permanent = True
                        session['username'] = username
                        return redirect(url_for('chat'))
                    elif check_password_hash(user['password_hash'], password):
                        session.permanent = True
                        session['username'] = username
                        supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
                        return redirect(url_for('chat'))
                    else:
                        error = "Неверный пароль!"
            except Exception as e:
                print(f"Ошибка БД: {e}")
                error = "Ошибка подключения к базе."
    return render_template('login.html', error=error)

@app.route('/sw.js')
def sw():
    return app.send_static_file('sw.js') # Если положил файл в папку static

@app.route('/logout')
def logout():
    username = session.get('username')
    if username: 
        try: supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
        except: pass
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
    
    # Сохраняем оригинальное имя файла для красивого отображения в чате
    safe_name = urllib.parse.quote(file.filename)
    filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    
    try:
        file_bytes = file.read()
        # Всё сохраняем в chat_media, чтобы базу не трогать!
        supabase.storage.from_('chat_media').upload(path=filename, file=file_bytes, file_options={"content-type": file.content_type})
        url = supabase.storage.from_('chat_media').get_public_url(filename)
        
        # Определяем тип файла для верной отрисовки в HTML
        if file.content_type.startswith('audio'): media_type = 'audio'
        elif file.content_type.startswith('video'): media_type = 'video'
        elif file.content_type.startswith('image'): media_type = 'image'
        else: media_type = 'file' # Для apk, pdf, docx и т.д.
        
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
active_group_calls = {} 

@socketio.on('user_connected')
def user_connected():
    username = session.get('username')
    if username:
        try:
            connected_clients[request.sid] = username
            supabase.table('users').update({'last_seen': datetime.utcnow().isoformat()}).eq('username', username).execute()
            join_room(f"user_{username}")
            emit('status_update', {'username': username, 'status': 'online'}, broadcast=True)
            
            user_info = supabase.table('users').select('is_verified, role').eq('username', username).execute()
            if user_info.data:
                emit('client_init_data', {'is_verified': user_info.data[0].get('is_verified'), 'role': user_info.data[0].get('role')})
            
            verified = supabase.table('users').select('username').eq('is_verified', True).execute()
            v_list = [u['username'] for u in verified.data]
            emit('update_verified_list', v_list)
        except Exception: pass

@socketio.on('disconnect')
def handle_disconnect():
    username = connected_clients.pop(request.sid, None)
    if username:
        try:
            if username not in connected_clients.values():
                last_seen_time = datetime.utcnow().isoformat()
                supabase.table('users').update({'last_seen': last_seen_time}).eq('username', username).execute()
                emit('status_update', {'username': username, 'status': 'offline', 'last_seen': last_seen_time}, broadcast=True)
            for room, participants in active_group_calls.items():
                if username in participants:
                    participants.remove(username)
                    emit('group_call_left', {'username': username, 'room': room}, to=room)
        except Exception: pass

# ================= АДМИН ПАНЕЛЬ =================
@socketio.on('get_admin_users')
def get_admin_users():
    me = session.get('username')
    try:
        my_info = supabase.table('users').select('is_verified, role').eq('username', me).execute()
        if my_info.data and my_info.data[0].get('is_verified'):
            users = supabase.table('users').select('username, avatar_url, is_verified, role, is_banned').execute()
            emit('admin_users_data', users.data)
    except Exception: pass

@socketio.on('toggle_verification')
def toggle_verification(data):
    me = session.get('username')
    try:
        my_info = supabase.table('users').select('is_verified, role').eq('username', me).execute()
        if my_info.data and my_info.data[0].get('is_verified'):
            target = data.get('target')
            current_status = data.get('current_status')
            supabase.table('users').update({'is_verified': not current_status}).eq('username', target).execute()
            verified = supabase.table('users').select('username').eq('is_verified', True).execute()
            v_list = [u['username'] for u in verified.data]
            emit('update_verified_list', v_list, broadcast=True)
            get_admin_users()
    except Exception: pass

@socketio.on('toggle_ban')
def toggle_ban(data):
    me = session.get('username')
    try:
        my_info = supabase.table('users').select('is_verified, role').eq('username', me).execute()
        if my_info.data and my_info.data[0].get('is_verified'):
            target = data.get('target')
            current_status = data.get('current_status')
            supabase.table('users').update({'is_banned': not current_status}).eq('username', target).execute()
            get_admin_users()
    except Exception: pass

@socketio.on('change_role')
def change_role(data):
    me = session.get('username')
    try:
        my_info = supabase.table('users').select('is_verified, role').eq('username', me).execute()
        if my_info.data and my_info.data[0].get('is_verified'):
            target = data.get('target')
            new_role = data.get('role')
            supabase.table('users').update({'role': new_role}).eq('username', target).execute()
            get_admin_users()
    except Exception: pass
# ================================================

@socketio.on('get_my_chats')
def get_my_chats():
    try:
        me = session.get('username')
        if not me: return
        memberships = supabase.table('chat_members').select('chat_id, role').eq('username', me).execute()
        my_roles = {m['chat_id']: m['role'] for m in memberships.data}
        chat_ids = list(my_roles.keys())
        
        if not chat_ids:
            emit('update_chat_list', [])
            return

        chats = supabase.table('chats').select('*').in_('id', chat_ids).execute()
        unread_res = supabase.table('messages').select('chat_id').in_('chat_id', chat_ids).neq('username', me).eq('is_read', False).execute()
        unread_counts = {}
        for msg in unread_res.data:
            cid = msg['chat_id']
            unread_counts[cid] = unread_counts.get(cid, 0) + 1
            
        for chat in chats.data:
            chat['my_role'] = my_roles.get(chat['id'], 'member')
            chat['unread_count'] = unread_counts.get(chat['id'], 0)
            if chat.get('type') == 'dm':
                parts = [p.strip() for p in chat['name'].split('&')]
                target = parts[0] if len(parts) > 1 and parts[1] == me else (parts[1] if len(parts) > 1 else parts[0])
                try:
                    target_db = supabase.table('users').select('avatar_url').eq('username', target).execute()
                    if target_db.data and target_db.data[0].get('avatar_url'):
                        chat['avatar_url'] = target_db.data[0]['avatar_url']
                except: pass

            try:
                last_msg = supabase.table('messages').select('username, text, media_url, media_type, created_at, is_read, is_pinned').eq('chat_id', chat['id']).order('created_at', desc=True).limit(1).execute()
                if last_msg.data:
                    chat['last_message'] = last_msg.data[0]
                    chat['last_msg_time'] = last_msg.data[0]['created_at']
                else:
                    chat['last_message'] = None
                    chat['last_msg_time'] = '1970-01-01T00:00:00Z'
            except: 
                chat['last_message'] = None
                chat['last_msg_time'] = '1970-01-01T00:00:00Z'

        chats_sorted = sorted(chats.data, key=lambda x: x['last_msg_time'], reverse=True)
        emit('update_chat_list', chats_sorted)
    except Exception as e:
        print("Ошибка в get_my_chats:", e)
        traceback.print_exc()
        emit('update_chat_list', [])

@socketio.on('search_users')
def search_users(data):
    query = data.get('query', '')
    me = session.get('username')
    try:
        users = supabase.table('users').select('username, avatar_url').ilike('username', f'%{query}%').limit(20).execute()
        results = [u for u in users.data if u['username'] != me]
        emit('search_results', results)
    except Exception: pass

@socketio.on('search_for_group')
def search_for_group(data):
    query = data.get('query', '')
    me = session.get('username')
    try:
        users = supabase.table('users').select('username, avatar_url').ilike('username', f'%{query}%').limit(10).execute()
        results = [u for u in users.data if u['username'] != me]
        emit('group_search_results', results)
    except Exception: pass

@socketio.on('delete_messages')
def delete_messages(data):
    msg_ids = data.get('ids', [])
    room = data.get('room')
    if msg_ids:
        try:
            supabase.table('messages').delete().in_('id', msg_ids).execute()
            emit('messages_deleted', {'ids': msg_ids}, to=room)
        except Exception: pass

@socketio.on('edit_message')
def edit_message(data):
    msg_id = data.get('id')
    new_text = data.get('text')
    room = data.get('room')
    try:
        supabase.table('messages').update({'text': new_text, 'is_edited': True}).eq('id', msg_id).execute()
        emit('message_edited', {'id': msg_id, 'text': new_text}, to=room)
    except Exception: pass

@socketio.on('change_font')
def change_font(data):
    msg_id = data.get('id')
    font = data.get('font')
    room = data.get('room')
    try:
        supabase.table('messages').update({'font_style': font}).eq('id', msg_id).execute()
        emit('message_font_changed', {'id': msg_id, 'font_style': font}, to=room)
    except Exception: pass

@socketio.on('pin_message')
def pin_message(data):
    msg_id = data.get('id')
    room = data.get('room')
    action = data.get('action')
    try:
        if action == 'pin':
            supabase.table('messages').update({'is_pinned': True}).eq('id', msg_id).execute()
            emit('message_pinned', {'id': msg_id, 'text': data.get('text')}, to=room)
        else:
            supabase.table('messages').update({'is_pinned': False}).eq('id', msg_id).execute()
            emit('message_unpinned', {'id': msg_id}, to=room)
    except Exception: pass

@socketio.on('start_dm')
def start_dm(data):
    target = data['target']
    me = session.get('username')
    participants = sorted([me, target])
    chat_id = f"dm_{participants[0]}_{participants[1]}"
    try:
        existing = supabase.table('chats').select('*').eq('id', chat_id).execute()
        if not existing.data:
            chat_name = f"{participants[0]} & {participants[1]}"
            supabase.table('chats').insert({'id': chat_id, 'name': chat_name, 'type': 'dm'}).execute()
            supabase.table('chat_members').insert([{'chat_id': chat_id, 'username': me, 'role': 'owner'}, {'chat_id': chat_id, 'username': target, 'role': 'member'}]).execute()
        emit('chat_created')
    except Exception: pass

@socketio.on('create_group')
def create_group(data):
    group_name = data.get('name', 'Новая группа').strip()
    is_channel = data.get('is_channel', False)
    members = data.get('members', []) 
    me = session.get('username')
    if not group_name: return
    chat_type = 'channel' if is_channel else 'group'
    chat_id = f"{chat_type}_{uuid.uuid4().hex[:8]}"
    try:
        supabase.table('chats').insert({'id': chat_id, 'name': group_name, 'type': chat_type, 'description': data.get('desc', '')}).execute()
        members_data = [{'chat_id': chat_id, 'username': me, 'role': 'owner'}]
        valid_users = supabase.table('users').select('username').in_('username', members).execute()
        for u in valid_users.data:
            if u['username'] != me:
                members_data.append({'chat_id': chat_id, 'username': u['username'], 'role': 'member'})
        supabase.table('chat_members').insert(members_data).execute()
        emit('chat_created')
    except Exception: pass

@socketio.on('leave_chat_completely')
def leave_chat_completely(data):
    me = session.get('username')
    room = data.get('room')
    try:
        supabase.table('chat_members').delete().eq('chat_id', room).eq('username', me).execute()
        emit('chat_left_success', {'room': room}, to=request.sid)
    except Exception: pass

@socketio.on('delete_chat_for_everyone')
def delete_chat_for_everyone(data):
    room = data.get('room')
    try:
        supabase.table('messages').delete().eq('chat_id', room).execute()
        supabase.table('chat_members').delete().eq('chat_id', room).execute()
        supabase.table('chats').delete().eq('id', room).execute()
        emit('chat_deleted_for_everyone', {'room': room}, broadcast=True)
    except Exception: pass

@socketio.on('manage_member')
def manage_member(data):
    me = session.get('username')
    room = data.get('room')
    target = data.get('target')
    action = data.get('action') 
    try:
        my_mem = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', me).execute()
        if not my_mem.data or my_mem.data[0]['role'] not in ['owner', 'admin']: return
        if action == 'kick': supabase.table('chat_members').delete().eq('chat_id', room).eq('username', target).execute()
        elif action == 'promote': supabase.table('chat_members').update({'role': 'admin'}).eq('chat_id', room).eq('username', target).execute()
        elif action == 'demote': supabase.table('chat_members').update({'role': 'member'}).eq('chat_id', room).eq('username', target).execute()
        elif action == 'add':
            exists = supabase.table('chat_members').select('*').eq('chat_id', room).eq('username', target).execute()
            if not exists.data: supabase.table('chat_members').insert({'chat_id': room, 'username': target, 'role': 'member'}).execute()
        emit('group_members_updated', {'room': room}, broadcast=True)
    except Exception: pass

@socketio.on('update_group_info')
def update_group_info(data):
    me = session.get('username')
    room = data.get('room')
    try:
        my_mem = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', me).execute()
        if not my_mem.data or my_mem.data[0]['role'] not in ['owner', 'admin']: return
        update_data = {}
        if data.get('name'): update_data['name'] = data.get('name')
        if data.get('desc') is not None: update_data['description'] = data.get('desc')
        if data.get('show_members') is not None: update_data['show_members'] = data.get('show_members')
        if update_data:
            supabase.table('chats').update(update_data).eq('id', room).execute()
            emit('group_updated', {'room': room, 'name': update_data.get('name')}, broadcast=True)
    except Exception: pass

@socketio.on('get_group_info')
def get_group_info(data):
    room = data.get('room')
    try:
        res = supabase.table('chat_members').select('username, role').eq('chat_id', room).execute()
        chat_res = supabase.table('chats').select('name, avatar_url, description, type, show_members').eq('id', room).execute()
        if chat_res.data:
            members_with_avatars = []
            for m in res.data:
                u_db = supabase.table('users').select('avatar_url').eq('username', m['username']).execute()
                avatar = u_db.data[0].get('avatar_url') if u_db.data else None
                members_with_avatars.append({'username': m['username'], 'role': m['role'], 'avatar_url': avatar})
            emit('group_info_data', {
                'room': room, 'members': members_with_avatars, 'name': chat_res.data[0].get('name'),
                'desc': chat_res.data[0].get('description', ''), 'type': chat_res.data[0].get('type'),
                'show_members': chat_res.data[0].get('show_members', True), 'avatar_url': chat_res.data[0].get('avatar_url')
            })
    except Exception: pass

@socketio.on('join')
def on_join(data):
    try:
        room = data['room']
        me = session.get('username')
        if not me: return
        join_room(room)
        
        try:
            unread_msgs = supabase.table('messages').select('id').eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
            if unread_msgs.data:
                for m in unread_msgs.data:
                    supabase.table('message_reads').insert({'message_id': m['id'], 'username': me}).execute()
        except: pass
        
        try:
            supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
        except: pass
        
        emit('messages_read', {'room': room, 'by': me}, to=room)
        
        try:
            history = supabase.table('messages').select('id, chat_id, username, text, media_url, media_type, created_at, is_read, reply_to_id, font_style, is_pinned, is_edited, users(avatar_url)').eq('chat_id', room).order('created_at').execute()
            emit('load_history', history.data)
        except Exception as query_err:
            print("Ошибка при получении истории:", query_err)
            emit('load_history', [])
    except Exception as e:
        print("Ошибка в on_join:", e)
        emit('load_history', [])

@socketio.on('mark_read')
def mark_read(data):
    room = data['room']
    me = session.get('username')
    try:
        unread_msgs = supabase.table('messages').select('id').eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
        for m in unread_msgs.data:
            try: supabase.table('message_reads').insert({'message_id': m['id'], 'username': me}).execute()
            except: pass
        supabase.table('messages').update({'is_read': True}).eq('chat_id', room).neq('username', me).eq('is_read', False).execute()
        emit('messages_read', {'room': room, 'by': me}, to=room)
    except Exception: pass

@socketio.on('get_message_views')
def get_message_views(data):
    msg_id = data.get('id')
    try:
        views = supabase.table('message_reads').select('username, read_at').eq('message_id', msg_id).execute()
        emit('message_views_data', {'id': msg_id, 'views': views.data})
    except Exception: pass

@socketio.on('leave')
def on_leave(data): leave_room(data['room'])

@socketio.on('typing')
def handle_typing(data): emit('user_typing', {'username': session.get('username'), 'action': data.get('action', 'typing')}, to=data['room'], include_self=False)

@socketio.on('stop_typing')
def handle_stop_typing(data): emit('user_stop_typing', {'username': session.get('username')}, to=data['room'], include_self=False)

@socketio.on('send_message')
def handle_message(data):
    try:
        room = data['room']
        text = data.get('text', '')
        media_url = data.get('media_url')
        media_type = data.get('media_type')
        reply_to = data.get('reply_to_id')
        font = data.get('font_style', 'default')
        username = session.get('username')
        
        chat_info = supabase.table('chats').select('type').eq('id', room).execute()
        if chat_info.data and chat_info.data[0].get('type') == 'channel':
            my_role = supabase.table('chat_members').select('role').eq('chat_id', room).eq('username', username).execute()
            if not my_role.data or my_role.data[0].get('role') not in ['owner', 'admin']:
                emit('server_error', {'message': 'Только администраторы могут публиковать в канал!'}, to=request.sid)
                return 
                
        new_msg = supabase.table('messages').insert({
            'chat_id': room, 'username': username, 'text': text, 'media_url': media_url, 'media_type': media_type, 'reply_to_id': reply_to, 'font_style': font, 'is_read': False
        }).execute()
        user_data = supabase.table('users').select('avatar_url').eq('username', username).execute()
        avatar_url = user_data.data[0].get('avatar_url') if user_data.data else None
        msg_data = new_msg.data[0]
        msg_data['users'] = {'avatar_url': avatar_url}
        emit('receive_message', msg_data, to=room)
        
        members_res = supabase.table('chat_members').select('username').eq('chat_id', room).execute()
        for m in members_res.data:
            target_user = m['username']
            if target_user != username: emit('new_message_notification', msg_data, to=f"user_{target_user}")
    except Exception: pass

@socketio.on('get_profile')
def get_profile(data):
    target_user = data.get('username')
    try:
        res = supabase.table('users').select('username, avatar_url, bio, custom_status, last_seen').eq('username', target_user).execute()
        if res.data: 
            profile_data = res.data[0]
            profile_data['is_online'] = profile_data['username'] in connected_clients.values()
            emit('profile_data', profile_data)
    except Exception: pass

@socketio.on('update_settings')
def update_settings(data):
    me = session.get('username')
    bio = data.get('bio', '').strip()
    custom_status = data.get('custom_status', '').strip()
    try:
        supabase.table('users').update({'bio': bio, 'custom_status': custom_status}).eq('username', me).execute()
        emit('status_update', {'username': me, 'custom_status': custom_status}, broadcast=True)
    except Exception: pass

@socketio.on('check_user_status')
def check_user_status(data):
    target = data.get('username')
    if target:
        is_online = target in connected_clients.values()
        try:
            user_db = supabase.table('users').select('custom_status, last_seen').eq('username', target).execute()
            if user_db.data:
                custom_status = user_db.data[0].get('custom_status', '')
                last_seen = user_db.data[0].get('last_seen', '')
                emit('receive_user_status', {'username': target, 'is_online': is_online, 'custom_status': custom_status, 'last_seen': last_seen})
        except Exception: pass

@socketio.on('get_stories')
def get_stories():
    me = session.get('username')
    try: 
        try: supabase.table('stories').delete().lt('expires_at', datetime.utcnow().isoformat()).execute()
        except: pass
        stories_res = supabase.table('stories').select('*').gt('expires_at', datetime.utcnow().isoformat()).order('created_at', desc=False).execute()
        views_res = supabase.table('story_views').select('story_id').eq('viewer_username', me).execute()
        viewed_ids = [v['story_id'] for v in views_res.data]
        authors_avatars = {}
        for st in stories_res.data:
            if st['author_type'] == 'user' and st['author_id'] not in authors_avatars:
                udb = supabase.table('users').select('avatar_url').eq('username', st['author_id']).execute()
                authors_avatars[st['author_id']] = udb.data[0].get('avatar_url') if udb.data else None
            elif st['author_type'] == 'channel' and st['author_id'] not in authors_avatars:
                cdb = supabase.table('chats').select('avatar_url').eq('id', st['author_id']).execute()
                authors_avatars[st['author_id']] = cdb.data[0].get('avatar_url') if cdb.data else None
            st['author_avatar'] = authors_avatars.get(st['author_id'])
            st['is_viewed'] = st['id'] in viewed_ids
        emit('update_stories', stories_res.data)
    except Exception: 
        emit('update_stories', [])

@socketio.on('create_story')
def create_story(data):
    me = session.get('username')
    expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    try:
        new_story = supabase.table('stories').insert({
            'author_id': data.get('author_id', me), 'author_type': data.get('author_type', 'user'),
            'media_url': data.get('media_url'), 'media_type': data.get('media_type'),
            'text': data.get('text', ''), 'expires_at': expires
        }).execute()
        emit('story_created', broadcast=True)
    except Exception: pass

@socketio.on('mark_story_seen')
def mark_story_seen(data):
    me = session.get('username')
    try: supabase.table('story_views').insert({'story_id': data['id'], 'viewer_username': me}).execute()
    except: pass
    
@socketio.on('get_story_views')
def get_story_views(data):
    story_id = data.get('id')
    try:
        views = supabase.table('story_views').select('viewer_username, viewed_at').eq('story_id', story_id).execute()
        emit('story_views_data', {'id': story_id, 'views': views.data})
    except Exception: pass

# --- ЗВОНКИ (АБСОЛЮТНО ТВОЙ КОД) ---
@socketio.on('call_user')
def call_user(data): emit('incoming_call', {'from': session.get('username')}, to=f"user_{data.get('target')}")

@socketio.on('answer_call')
def answer_call(data): emit('call_accepted', {'by': session.get('username')}, to=f"user_{data.get('caller')}")

@socketio.on('reject_call')
def reject_call(data): emit('call_rejected', {'by': session.get('username')}, to=f"user_{data.get('caller')}")

@socketio.on('webrtc_offer')
def webrtc_offer(data): emit('webrtc_offer', {'offer': data['offer'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('webrtc_answer')
def webrtc_answer(data): emit('webrtc_answer', {'answer': data['answer'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('webrtc_ice_candidate')
def webrtc_ice_candidate(data): emit('webrtc_ice_candidate', {'candidate': data['candidate'], 'from': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('end_call')
def end_call(data): emit('call_ended', {'by': session.get('username')}, to=f"user_{data['target']}")

@socketio.on('call_action')
def call_action(data):
    # Пересылаем действие собеседнику
    emit('call_action', {'state': data.get('state'), 'action': data.get('action')}, to=f"user_{data.get('target')}")

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
