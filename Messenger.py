import os
import json
import sys
import socket
import threading
import asyncio
import websockets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime
import time
import re

# Желательно изменить перед запуском
PAGE_TITLE = "HTTP"
REDIRECT_URL = "https://www.google.com"

# Параметры запуска
ADMIN_MODE = '-a' in sys.argv # Сразу даёт админку хосту
SHOW_COMMANDS = '-sh' in sys.argv # Включает сообщения использованных комманд
NO_ACTIVE = '-noact' in sys.argv # Выключает мониторинг активных пользователей (для снижения нагрузки на сеть)


DATA_DIR = 'data'

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
BACKUP_FILE = os.path.join(DATA_DIR, 'back.json')

SAVE_LIMIT = 1000
DISPLAY_LIMIT = 75
MAX_MESSAGE_LENGTH = 1000

if not os.path.exists(MESSAGES_FILE):
    with open(MESSAGES_FILE, 'w') as f:
        json.dump([], f)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)

def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

SERVER_IP = get_local_ip()

active_users = {}
active_users_lock = threading.Lock()

websocket_clients = {}
websocket_lock = threading.Lock()

last_message_cache = {}
last_message_lock = threading.Lock()

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def is_admin(ip):
    users = load_users()
    user_data = users.get(ip, {})
    if isinstance(user_data, dict):
        return user_data.get('is_admin', False)
    return False

def get_nickname(ip):
    users = load_users()
    user_data = users.get(ip, {})
    if isinstance(user_data, dict):
        return user_data.get('nickname', 'Unknown')
    return user_data

def get_ip_by_nickname(nickname):
    users = load_users()
    for ip, user_data in users.items():
        if isinstance(user_data, dict):
            if user_data.get('nickname') == nickname:
                return ip
        elif user_data == nickname:
            return ip
    return None

def set_nickname(ip, nickname):
    users = load_users()
    if ip in users and isinstance(users[ip], dict):
        users[ip]['nickname'] = nickname
    elif ip in users:
        old_is_admin = users[ip].get('is_admin', False) if isinstance(users[ip], dict) else False
        users[ip] = {'nickname': nickname, 'is_admin': old_is_admin}
    else:
        users[ip] = {'nickname': nickname, 'is_admin': False}
    save_users(users)

def update_nickname_in_messages(old_nickname, new_nickname):
    try:
        with open(MESSAGES_FILE, 'r') as f:
            messages = json.load(f)
        updated = False
        for msg in messages:
            if msg.get('nickname') == old_nickname:
                msg['nickname'] = new_nickname
                updated = True
        if updated:
            with open(MESSAGES_FILE, 'w') as f:
                json.dump(messages, f)
    except (json.JSONDecodeError, IOError):
        pass

def get_nickname_color(ip):
    hash_val = 0
    for c in ip:
        hash_val = (hash_val * 31 + ord(c)) % 360
    return f"hsl({hash_val}, 65%, 40%)"

ADMIN_MODE_STR = str(ADMIN_MODE).lower()

ARGS_LIST = []
if ADMIN_MODE:
    ARGS_LIST.append('-a')
if SHOW_COMMANDS:
    ARGS_LIST.append('-sh')
if NO_ACTIVE:
    ARGS_LIST.append('-noact')
ARGS_STRING = ' '.join(ARGS_LIST) if ARGS_LIST else 'нет'

def save_message_to_file(message):
    try:
        with open(MESSAGES_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                messages = []
            else:
                messages = json.loads(content)
    except (json.JSONDecodeError, IOError):
        messages = []
    
    messages.append(message)
    
    if len(messages) > SAVE_LIMIT:
        messages = messages[-SAVE_LIMIT:]
    
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(messages, f)

def add_command_message(nickname, text):
    if not SHOW_COMMANDS:
        return
    messages = []
    try:
        with open(MESSAGES_FILE, 'r') as f:
            content = f.read().strip()
            if content:
                messages = json.loads(content)
    except (json.JSONDecodeError, IOError):
        pass
    
    messages.append({
        'id': int(time.time() * 1000) + len(messages),
        'time': datetime.now().strftime('%H:%M:%S'),
        'nickname': nickname,
        'text': text,
        'originalText': text,
        'ip': '0.0.0.0',
        'nicknameColor': '#888',
        'isAdmin': True,
        'isCommand': True,
        'isDeleted': False
    })
    
    if len(messages) > SAVE_LIMIT:
        messages = messages[-SAVE_LIMIT:]
    
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(messages, f)

def add_whisper_message(from_nickname, to_nickname, to_ip, text, from_ip):
    try:
        with open(MESSAGES_FILE, 'r') as f:
            content = f.read().strip()
            if not content:
                messages = []
            else:
                messages = json.loads(content)
    except (json.JSONDecodeError, IOError):
        messages = []
    
    from_color = get_nickname_color(from_ip)
    whisper_text = f"→ {to_nickname}: {text}"
    
    messages.append({
        'id': int(time.time() * 1000) + len(messages),
        'time': datetime.now().strftime('%H:%M:%S'),
        'nickname': from_nickname,
        'text': whisper_text,
        'originalText': text,
        'ip': from_ip,
        'nicknameColor': from_color,
        'isAdmin': is_admin(from_ip),
        'isWhisper': True,
        'whisperTarget': to_nickname,
        'isDeleted': False
    })
    
    if len(messages) > SAVE_LIMIT:
        messages = messages[-SAVE_LIMIT:]
    
    with open(MESSAGES_FILE, 'w') as f:
        json.dump(messages, f)

async def broadcast_message(data, exclude_ip=None):
    with websocket_lock:
        clients = list(websocket_clients.items())
    
    for client_ip, websocket in clients:
        if exclude_ip and client_ip == exclude_ip:
            continue
        try:
            await websocket.send(json.dumps(data))
        except Exception:
            pass

async def broadcast_active_users():
    with active_users_lock:
        users_copy = []
        for ip, data in active_users.items():
            users_copy.append({
                'nickname': data.get('nickname', 'Unknown'),
                'ip': ip,
                'isAdmin': is_admin(ip)
            })
    
    with websocket_lock:
        clients = list(websocket_clients.items())
    
    data = {'type': 'active_users', 'users': users_copy}
    for ip, websocket in clients:
        try:
            await websocket.send(json.dumps(data))
        except Exception:
            pass

async def handle_websocket(websocket):
    client_ip = websocket.remote_address[0]
    
    with websocket_lock:
        websocket_clients[client_ip] = websocket
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get('type')
                
                if msg_type == 'heartbeat':
                    nickname = data.get('nickname', 'Unknown')
                    with active_users_lock:
                        active_users[client_ip] = {'nickname': nickname, 'ip': client_ip, 'last_seen': datetime.now().timestamp()}
                    await broadcast_active_users()
                    continue
                
                elif msg_type == 'send_message':
                    text = data.get('text', '').strip()
                    if not text:
                        continue
                    
                    users = load_users()
                    if client_ip not in users:
                        continue
                    
                    if len(text) > MAX_MESSAGE_LENGTH:
                        continue
                    
                    if text.startswith('/tell'):
                        match = re.match(r'^/tell\s+@?(\w+)\s+(.+)$', text)
                        if match:
                            target_nickname = match.group(1)
                            whisper_text = match.group(2)
                            sender_nickname = get_nickname(client_ip)
                            target_ip = get_ip_by_nickname(target_nickname)
                            if target_ip and target_ip != client_ip:
                                add_whisper_message(sender_nickname, target_nickname, target_ip, whisper_text, client_ip)
                                with open(MESSAGES_FILE, 'r') as f:
                                    content = f.read().strip()
                                    if content:
                                        msgs = json.loads(content)
                                        last_msg = msgs[-1] if msgs else None
                                        if last_msg:
                                            await broadcast_message({'type': 'new_message', 'message': last_msg})
                                        if SHOW_COMMANDS:
                                            add_command_message(sender_nickname, text)
                            continue
                    
                    if is_admin(client_ip) and text.startswith('/'):
                        parts = text.split()
                        cmd = parts[0].lower()
                        sender_nickname = get_nickname(client_ip)
                        
                        if cmd == '/a' and len(parts) == 2:
                            target_ip = parts[1]
                            users = load_users()
                            if target_ip in users:
                                user_data = users[target_ip]
                                if isinstance(user_data, dict):
                                    user_data['is_admin'] = True
                                else:
                                    users[target_ip] = {'nickname': user_data, 'is_admin': True}
                            else:
                                users[target_ip] = {'nickname': 'Unknown', 'is_admin': True}
                            save_users(users)
                            if SHOW_COMMANDS:
                                add_command_message(sender_nickname, text)
                                await broadcast_message({'type': 'new_messages'})
                            continue
                        
                        elif cmd == '/cl':
                            try:
                                with open(MESSAGES_FILE, 'r') as f:
                                    current_messages = json.load(f)
                                with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
                                    json.dump(current_messages, f, ensure_ascii=False, indent=2)
                                with open(MESSAGES_FILE, 'w') as f:
                                    json.dump([], f)
                                if SHOW_COMMANDS:
                                    add_command_message(sender_nickname, text)
                                await broadcast_message({'type': 'clear_chat'})
                            except Exception:
                                pass
                            continue
                        
                        elif cmd == '/ret':
                            try:
                                if not os.path.exists(BACKUP_FILE):
                                    continue
                                with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
                                    backup_messages = json.load(f)
                                with open(MESSAGES_FILE, 'r') as f:
                                    current_messages = json.load(f)
                                combined = backup_messages + current_messages
                                if len(combined) > SAVE_LIMIT:
                                    combined = combined[-SAVE_LIMIT:]
                                with open(MESSAGES_FILE, 'w') as f:
                                    json.dump(combined, f)
                                with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
                                    json.dump([], f)
                                if SHOW_COMMANDS:
                                    add_command_message(sender_nickname, text)
                                await broadcast_message({'type': 'new_messages'})
                            except Exception:
                                pass
                            continue
                        
                        elif cmd == '/ch' and len(parts) == 3:
                            target_ip = parts[1]
                            new_nickname = parts[2]
                            if len(new_nickname) <= 20:
                                users = load_users()
                                if target_ip in users:
                                    user_data = users[target_ip]
                                    if isinstance(user_data, dict):
                                        user_data['nickname'] = new_nickname
                                    else:
                                        users[target_ip] = {'nickname': new_nickname, 'is_admin': False}
                                    save_users(users)
                                    if SHOW_COMMANDS:
                                        add_command_message(sender_nickname, text)
                                    await broadcast_message({'type': 'new_messages'})
                            continue
                        
                        elif cmd == '/ch-u' and len(parts) == 3:
                            target_ip = parts[1]
                            new_nickname = parts[2]
                            if len(new_nickname) <= 20:
                                users = load_users()
                                if target_ip in users:
                                    old_nickname = get_nickname(target_ip)
                                    user_data = users[target_ip]
                                    if isinstance(user_data, dict):
                                        user_data['nickname'] = new_nickname
                                    else:
                                        users[target_ip] = {'nickname': new_nickname, 'is_admin': False}
                                    save_users(users)
                                    update_nickname_in_messages(old_nickname, new_nickname)
                                    if SHOW_COMMANDS:
                                        add_command_message(sender_nickname, text)
                                    await broadcast_message({'type': 'new_messages'})
                            continue
                        
                        else:
                            continue
                    
                    try:
                        with open(MESSAGES_FILE, 'r') as f:
                            content = f.read().strip()
                            if not content:
                                messages = []
                            else:
                                messages = json.loads(content)
                    except (json.JSONDecodeError, IOError):
                        messages = []
                    
                    nickname_color = get_nickname_color(client_ip)
                    new_msg = {
                        'id': int(time.time() * 1000) + len(messages),
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'nickname': get_nickname(client_ip),
                        'text': text,
                        'originalText': text,
                        'ip': client_ip,
                        'nicknameColor': nickname_color,
                        'isAdmin': is_admin(client_ip),
                        'isDeleted': False
                    }
                    
                    messages.append(new_msg)
                    if len(messages) > SAVE_LIMIT:
                        messages = messages[-SAVE_LIMIT:]
                    
                    with open(MESSAGES_FILE, 'w') as f:
                        json.dump(messages, f)
                    
                    await broadcast_message({'type': 'new_message', 'message': new_msg})
                    continue
                
                elif msg_type == 'delete_message':
                    msg_id = data.get('msg_id')
                    hard_delete = data.get('hard', False)
                    
                    if msg_id:
                        try:
                            with open(MESSAGES_FILE, 'r') as f:
                                messages = json.load(f)
                            
                            if hard_delete:
                                messages = [msg for msg in messages if msg.get('id') != msg_id]
                            else:
                                for msg in messages:
                                    if msg.get('id') == msg_id:
                                        msg['isDeleted'] = True
                                        break
                            
                            with open(MESSAGES_FILE, 'w') as f:
                                json.dump(messages, f)
                            
                            await broadcast_message({
                                'type': 'delete_message',
                                'msg_id': msg_id,
                                'hard': hard_delete
                            })
                        except Exception as e:
                            print(f'Ошибка удаления: {e}')
                    continue
                
                elif msg_type == 'restore_message':
                    msg_id = data.get('msg_id')
                    
                    if msg_id:
                        try:
                            with open(MESSAGES_FILE, 'r') as f:
                                messages = json.load(f)
                            
                            for msg in messages:
                                if msg.get('id') == msg_id:
                                    msg['isDeleted'] = False
                                    break
                            
                            with open(MESSAGES_FILE, 'w') as f:
                                json.dump(messages, f)
                            
                            await broadcast_message({
                                'type': 'restore_message',
                                'msg_id': msg_id
                            })
                        except Exception as e:
                            print(f'Ошибка восстановления: {e}')
                    continue
                    
            except json.JSONDecodeError:
                pass
                
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        with websocket_lock:
            if client_ip in websocket_clients:
                del websocket_clients[client_ip]
        with active_users_lock:
            if client_ip in active_users:
                del active_users[client_ip]
        await broadcast_active_users()

HTML = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{PAGE_TITLE}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; height: 100vh; display: flex; flex-direction: column; }}
        #chat {{ flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; background: #fff8e1; margin-bottom: 0; }}
        .msg {{ 
            margin: 5px 0; 
            padding: 8px; 
            border-bottom: 1px solid #ffe0b2; 
            word-wrap: break-word; 
            background: #fffef7; 
            border-radius: 4px;
            border: 1px solid #e0c080;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            position: relative;
        }}
        .msg:hover {{ background: #fff3e0; }}
        .msg.own-message {{
            background: #e8f4e8;
            border-left: 3px solid #4ec9b0;
        }}
        .msg.mention {{
            background: #fff0d0;
            border-left: 3px solid #d4a017;
            box-shadow: 0 0 5px rgba(212,160,23,0.3);
        }}
        .msg.mention.own-message {{
            background: #fff0d0;
            border-left: 3px solid #d4a017;
            box-shadow: 0 0 5px rgba(212,160,23,0.3);
        }}
        .msg.command-message {{
            background: #e0e0e0;
            border-left: 3px solid #888;
        }}
        .msg.whisper {{
            background: #e8e0f0;
            border-left: 3px solid #9b59b6;
        }}
        .msg.deleted-for-host {{
            background: #d0d0d0 !important;
            border: 1px dashed #666;
            opacity: 0.8;
        }}
        .time {{ color: #8B6914; font-size: 12px; font-weight: 500; }}
        .ip {{ color: #888; font-size: 10px; margin-left: 5px; cursor: pointer; }}
        .ip:hover {{ text-decoration: underline; }}
        .nickname {{ font-weight: bold; cursor: pointer; }}
        .nickname:hover {{ text-decoration: underline; }}
        .text {{ color: #333; white-space: pre-wrap; }}
        .whisper-label {{
            color: #9b59b6;
            font-size: 10px;
            font-weight: bold;
            margin-right: 6px;
        }}
        .mention-highlight {{
            background-color: #ffeb3b;
            color: #333;
            padding: 0 2px;
            border-radius: 3px;
            font-weight: bold;
        }}
        .admin-badge-inline {{
            background: #8B0000;
            color: white;
            font-size: 10px;
            font-weight: bold;
            padding: 2px 5px;
            border-radius: 10px;
            margin-left: 6px;
            display: inline-block;
        }}
        .msg-actions {{
            position: absolute;
            right: 8px;
            top: 8px;
            display: none;
            gap: 5px;
        }}
        .msg:hover .msg-actions {{
            display: flex;
        }}
        .action-btn {{
            background: #3c3c3c;
            border: none;
            color: #d4d4d4;
            cursor: pointer;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
        }}
        .action-btn:hover {{
            background: #555;
        }}
        .copy-btn {{
            background: #0e639c;
        }}
        .copy-btn:hover {{
            background: #1177bb;
        }}
        .delete-btn {{
            background: #8B0000;
        }}
        .delete-btn:hover {{
            background: #a00000;
        }}
        .restore-btn {{
            background: #0e639c;
        }}
        .restore-btn:hover {{
            background: #1177bb;
        }}
        .panel {{
            background: #3c3c3c;
            padding: 15px;
            border-top: 1px solid #4a4a4a;
            display: flex;
            gap: 20px;
            align-items: flex-start;
            resize: vertical;
            overflow: auto;
            min-height: 150px;
        }}
        .left-panel {{
            flex: 1;
        }}
        .right-panel {{
            width: 180px;
            background: #2d2d2d;
            border-radius: 8px;
            padding: 10px;
            border: 1px solid #4a4a4a;
            max-height: 150px;
            overflow-y: auto;
            resize: horizontal;
            min-width: 120px;
            max-width: 300px;
        }}
        .nickname-row {{ display: flex; gap: 10px; margin-bottom: 10px; align-items: center; }}
        .nickname-row label {{ font-weight: bold; color: #4ec9b0; }}
        #nicknameInput {{ width: 200px; padding: 8px; border: 1px solid #555; border-radius: 4px; font-size: 14px; font-family: monospace; background: #3c3c3c; color: #d4d4d4; }}
        #nicknameInput:disabled {{ background: #2a2a2a; color: #858585; }}
        #nicknameInput:focus {{ outline: none; border-color: #4ec9b0; }}
        #saveNicknameBtn {{ padding: 8px 15px; background: #0e639c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-family: monospace; }}
        #saveNicknameBtn:hover {{ background: #1177bb; }}
        .warning {{ 
            color: #f48771; 
            font-size: 13px; 
            margin-bottom: 10px; 
            font-weight: bold;
            background: #2d2d2d;
            padding: 6px;
            border-radius: 4px;
            border-left: 3px solid #f48771;
        }}
        .warning.success {{ color: #4ec9b0; background: #1e3a2f; border-left-color: #4ec9b0; }}
        .input-row {{ position: relative; display: flex; gap: 10px; align-items: flex-end; }}
        #messageInput {{ flex: 1; padding: 8px; border: 1px solid #555; border-radius: 4px; font-size: 14px; font-family: monospace; resize: vertical; background: #3c3c3c; color: #d4d4d4; }}
        #messageInput:focus {{ outline: none; border-color: #4ec9b0; }}
        #messageInput:disabled {{ background: #2a2a2a; color: #858585; }}
        textarea {{
            resize: vertical;
        }}
        button {{ padding: 8px 20px; background: #0e639c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-family: monospace; }}
        button:hover {{ background: #1177bb; }}
        button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .admin-badge {{ background: #d4a017; color: #1e1e1e; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 8px; }}
        
        .right-menus {{
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 10px;
        }}
        .menu-wrapper {{
            display: flex;
            gap: 10px;
            align-items: center;
        }}
        .menu-btn {{
            background: #888;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            font-family: monospace;
            min-width: 120px;
        }}
        .menu-btn:hover {{
            background: #777;
        }}
        .admin-btn {{
            background: #8B0000;
            color: white;
        }}
        .admin-btn:hover {{
            background: #a00000;
        }}
        .host-btn {{
            background: #888;
            color: white;
        }}
        .host-btn:hover {{
            background: #777;
        }}
        .menu-content {{
            display: none;
            position: absolute;
            top: 45px;
            right: 0;
            background: #2d2d2d;
            min-width: 280px;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.3);
            border: 1px solid #4a4a4a;
        }}
        .menu-content.show {{
            display: block;
        }}
        .menu-item {{
            padding: 10px 15px;
            border-bottom: 1px solid #4a4a4a;
            font-size: 13px;
            color: #d4d4d4;
            cursor: pointer;
        }}
        .menu-item:last-child {{
            border-bottom: none;
        }}
        .menu-item strong {{
            color: #4ec9b0;
        }}
        .menu-item:hover {{
            background: #3c3c3c;
        }}
        .active-users-title {{
            color: #4ec9b0;
            font-weight: bold;
            margin-bottom: 8px;
            border-bottom: 1px solid #4a4a4a;
            padding-bottom: 4px;
            cursor: ns-resize;
        }}
        .active-user {{
            padding: 3px 0;
            color: #d4d4d4;
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
        }}
        .active-user:hover {{
            text-decoration: underline;
        }}
        .active-user-badge {{
            background: #8B0000;
            color: white;
            font-size: 9px;
            font-weight: bold;
            padding: 1px 4px;
            border-radius: 8px;
        }}
        .char-counter {{
            font-size: 11px;
            color: #858585;
            margin-top: 4px;
            text-align: right;
        }}
        .char-counter.warning {{
            color: #f48771;
        }}
        .suggestions {{
            position: absolute;
            bottom: 100%;
            left: 0;
            background: #2d2d2d;
            border: 1px solid #4a4a4a;
            border-radius: 6px;
            max-height: 150px;
            overflow-y: auto;
            z-index: 1001;
            min-width: 150px;
        }}
        .suggestion-item {{
            padding: 6px 10px;
            cursor: pointer;
            color: #d4d4d4;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .suggestion-item:hover, .suggestion-item.selected {{
            background: #3c3c3c;
        }}
        .toast {{
            position: fixed;
            bottom: 30px;
            left: 50%;
            transform: translateX(-50%);
            background: #4ec9b0;
            color: #1e1e1e;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 2000;
            opacity: 0;
            transition: opacity 0.2s;
            pointer-events: none;
        }}
        .toast.show {{
            opacity: 1;
        }}
        .resize-handle {{
            cursor: ns-resize;
            text-align: center;
            font-size: 10px;
            color: #888;
            margin-top: 5px;
        }}
        .ws-status {{
            position: fixed;
            bottom: 10px;
            left: 10px;
            font-size: 11px;
            color: #858585;
            z-index: 999;
        }}
    </style>
</head>
<body id="mainBody">
    <div class="right-menus" id="rightMenus">
        <div class="menu-wrapper">
            <div class="admin-menu" id="adminMenuContainer" style="display: none;">
                <button class="menu-btn admin-btn" id="adminMenuBtn">Админ</button>
                <div class="menu-content" id="adminMenuContent">
                    <div class="menu-item" id="cmdClear"><strong>/cl</strong> — Очистить чат (сохранить в back.json)</div>
                    <div class="menu-item" id="cmdRestore"><strong>/ret</strong> — Восстановить чат из back.json</div>
                    <div class="menu-item" id="cmdAddAdmin"><strong>/a "ip"</strong> — Сделать пользователя администратором</div>
                    <div class="menu-item" id="cmdChangeNick"><strong>/ch "ip" "ник"</strong> — Сменить ник пользователю</div>
                    <div class="menu-item" id="cmdChangeNickAll"><strong>/ch-u "ip" "новый_ник"</strong> — Сменить ник и обновить в сообщениях</div>
                </div>
            </div>
            <div class="tools-menu">
                <button class="menu-btn" id="menuBtn">Инструменты</button>
                <div class="menu-content" id="menuContent">
                    <div class="menu-item"><strong>+ / =</strong> — Нажмите + или =, чтобы закрыть сайт (не работает при вводе текста)</div>
                    <div class="menu-item" id="cmdTell"><strong>/tell @ник сообщение</strong> — Отправить личное сообщение (Шёпот)</div>
                </div>
            </div>
        </div>
        <div class="host-menu" id="hostMenuContainer" style="display: none;">
            <button class="menu-btn host-btn" id="hostMenuBtn">Хост</button>
            <div class="menu-content" id="hostMenuContent">
                <div class="menu-item">Аргументы запуска: {ARGS_STRING}</div>
                <div class="menu-item"><strong>-a</strong> — дать хосту статус админа (до регистрации)</div>
                <div class="menu-item"><strong>-sh</strong> — показывать команды в чате</div>
                <div class="menu-item"><strong>-noact</strong> — отключить систему активных пользователей</div>
            </div>
        </div>
    </div>

    <div id="chat"></div>
    <div class="panel" id="panel">
        <div class="left-panel">
            <div class="nickname-row">
                <label>Имя:</label>
                <input type="text" id="nicknameInput" placeholder="Введите имя" maxlength="20">
                <button id="saveNicknameBtn">Сохранить</button>
            </div>
            <div class="warning" id="warning">⚠️ Никнейм не может быть изменен</div>
            <div class="input-row" id="inputRow">
                <textarea id="messageInput" rows="2" placeholder="Сообщение... (используйте @ник для упоминания)"></textarea>
                <button id="sendBtn">Отправить</button>
                <div id="suggestions" class="suggestions" style="display: none;"></div>
            </div>
            <div class="char-counter" id="charCounter">0 / {MAX_MESSAGE_LENGTH}</div>
        </div>
        <div class="right-panel" id="rightPanel" style="display: {'none' if NO_ACTIVE else 'block'}">
            <div class="active-users-title">Активные пользователи</div>
            <div id="activeUsersList">Загрузка...</div>
            <div class="resize-handle">⋮</div>
        </div>
    </div>
    <div id="toast" class="toast">Скопировано!</div>
    <div id="wsStatus" class="ws-status">● Подключено</div>

    <script>
        let registered = false;
        let scrollPosition = 0;
        let isAdmin = false;
        let nickname = '';
        let currentUserIp = null;
        let allUsers = [];
        let currentSuggestionIndex = -1;
        let currentSuggestions = [];
        let isSending = false;
        let ws = null;

        let NO_ACTIVE_MODE = {'true' if NO_ACTIVE else 'false'};
        let ADMIN_MODE_ACTIVE = {'true' if ADMIN_MODE else 'false'};
        let SERVER_IP_ADDR = '{SERVER_IP}';

        function getWebSocketUrl() {{
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            return protocol + '//' + window.location.hostname + ':8001' + '/ws';
        }}

        function connectWebSocket() {{
            ws = new WebSocket(getWebSocketUrl());
            
            ws.onopen = function() {{
                document.getElementById('wsStatus').textContent = '● Подключено';
                document.getElementById('wsStatus').style.color = '#4ec9b0';
                if (registered && nickname) {{
                    sendHeartbeat();
                }}
            }};
            
            ws.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    handleWebSocketMessage(data);
                }} catch (e) {{
                    console.log('Ошибка разбора WebSocket-сообщения:', e);
                }}
            }};
            
            ws.onclose = function() {{
                document.getElementById('wsStatus').textContent = '● Отключено (переподключение...)';
                document.getElementById('wsStatus').style.color = '#f48771';
                setTimeout(connectWebSocket, 3000);
            }};
            
            ws.onerror = function() {{
                document.getElementById('wsStatus').textContent = '● Ошибка соединения';
                document.getElementById('wsStatus').style.color = '#f48771';
            }};
        }}

        function handleWebSocketMessage(data) {{
            if (data.type === 'new_message') {{
                const msg = data.message;
                const isOwn = (msg.ip === currentUserIp);
                const hasMention = msg.text && msg.text.includes('@' + nickname);
                const isDeleted = msg.isDeleted || false;
                msg.isOwn = isOwn;
                msg.hasMention = hasMention;
                msg.isDeleted = isDeleted;
                addMessageToChat(msg);
            }} else if (data.type === 'delete_message') {{
                loadMessages();
            }} else if (data.type === 'restore_message') {{
                loadMessages();
            }} else if (data.type === 'new_messages') {{
                loadMessages();
            }} else if (data.type === 'clear_chat') {{
                document.getElementById('chat').innerHTML = '';
                loadMessages();
            }} else if (data.type === 'active_users') {{
                allUsers = data.users.filter(u => u.nickname !== nickname);
                updateActiveUsersList(data.users);
            }}
        }}

        function addMessageToChat(msg) {{
            const chat = document.getElementById('chat');
            const wasScrolledToBottom = (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 10;
            
            const div = createMessageElement(msg);
            chat.appendChild(div);
            
            if (wasScrolledToBottom) {{
                chat.scrollTop = chat.scrollHeight;
            }}
        }}

        function createMessageElement(msg) {{
            const div = document.createElement('div');
            div.className = 'msg';
            const isHost = (currentUserIp === SERVER_IP_ADDR);
            
            const isOwn = (msg.ip === currentUserIp);
            const hasMention = msg.text && msg.text.includes('@' + nickname);
            const isDeleted = msg.isDeleted || false;
            
            if (isOwn) {{
                div.classList.add('own-message');
            }}
            if (hasMention) {{
                div.classList.add('mention');
            }}
            if (msg.isCommand) {{
                div.classList.add('command-message');
            }}
            if (msg.isWhisper) {{
                div.classList.add('whisper');
            }}
            if (isDeleted && isHost) {{
                div.classList.add('deleted-for-host');
            }}
            
            let ipHtml = '';
            if (ADMIN_MODE_ACTIVE && msg.showIp && msg.ip) {{
                ipHtml = `<span class="ip" data-ip="${{escapeHtml(msg.ip)}}">(${{escapeHtml(msg.ip)}})</span>`;
            }}
            
            const nicknameColor = msg.nicknameColor || '#B8860B';
            const adminBadge = msg.isAdmin ? '<span class="admin-badge-inline">A</span>' : '';
            const whisperLabel = msg.isWhisper ? '<span class="whisper-label">[Шёпот]</span>' : '';
            const highlightedText = highlightMentions(escapeHtml(msg.text), nickname);
            
            let actionsHtml = `<div class="msg-actions">
                <button class="action-btn copy-btn" data-text="${{escapeHtml(msg.originalText || msg.text)}}">📋</button>`;
            
            if (isDeleted && isHost) {{
                actionsHtml += `<button class="action-btn restore-btn" data-id="${{msg.id}}">↩️</button>`;
                actionsHtml += `<button class="action-btn delete-btn" data-id="${{msg.id}}" data-hard="true">🗑</button>`;
            }} else if ((isOwn || isAdmin) && !isDeleted) {{
                actionsHtml += `<button class="action-btn delete-btn" data-id="${{msg.id}}" data-hard="false">🗑</button>`;
            }}
            actionsHtml += `</div>`;
            
            div.innerHTML = `<span class="time">[${{escapeHtml(msg.time)}}]</span>${{ipHtml}} ${{whisperLabel}}<span class="nickname" style="color: ${{nicknameColor}};" data-ip="${{msg.ip || ''}}">${{escapeHtml(msg.nickname)}}${{adminBadge}}:</span> <span class="text">${{highlightedText}}</span>${{actionsHtml}}`;
            
            div.querySelector('.copy-btn')?.addEventListener('click', function(e) {{
                e.stopPropagation();
                const text = this.dataset.text;
                if (text) copyMessage(text);
            }});
            
            div.querySelector('.delete-btn')?.addEventListener('click', function(e) {{
                e.stopPropagation();
                const msgId = this.dataset.id;
                const isHard = this.dataset.hard === 'true';
                if (confirm(isHard ? 'Полностью удалить это сообщение? (будет удалено навсегда)' : 'Удалить это сообщение?')) {{
                    deleteMessage(msgId, isHard);
                }}
            }});
            
            div.querySelector('.restore-btn')?.addEventListener('click', function(e) {{
                e.stopPropagation();
                const msgId = this.dataset.id;
                if (confirm('Восстановить это сообщение?')) {{
                    restoreMessage(msgId);
                }}
            }});
            
            div.querySelector('.ip')?.addEventListener('click', function(e) {{
                e.stopPropagation();
                const ip = this.dataset.ip;
                if (ip) copyToClipboard(ip);
            }});
            
            div.querySelector('.nickname')?.addEventListener('click', function(e) {{
                e.stopPropagation();
                const ip = this.dataset.ip;
                if (ip) copyToClipboard(ip);
            }});
            
            return div;
        }}

        function updateActiveUsersList(users) {{
            const container = document.getElementById('activeUsersList');
            if (!container) return;
            if (users.length === 0) {{
                container.innerHTML = '<div class="active-user">Нет активных</div>';
                return;
            }}
            let html = '';
            users.forEach(user => {{
                const adminBadge = user.isAdmin ? '<span class="active-user-badge">A</span>' : '';
                html += `<div class="active-user" data-ip="${{user.ip}}" data-nickname="${{escapeHtml(user.nickname)}}">${{adminBadge}}${{escapeHtml(user.nickname)}}</div>`;
            }});
            container.innerHTML = html;
            document.querySelectorAll('.active-user').forEach(el => {{
                el.addEventListener('click', (e) => {{
                    e.stopPropagation();
                    const ip = el.dataset.ip;
                    if (ip && isAdmin) copyToClipboard(ip);
                }});
            }});
        }}

        function sendHeartbeat() {{
            if (ws && ws.readyState === WebSocket.OPEN && registered && nickname) {{
                ws.send(JSON.stringify({{
                    type: 'heartbeat',
                    nickname: nickname
                }}));
            }}
        }}

        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.textContent = message || 'Скопировано!';
            toast.classList.add('show');
            setTimeout(() => {{
                toast.classList.remove('show');
            }}, 550);
        }}

        function fallbackCopy(text) {{
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.top = '-9999px';
            textarea.style.left = '-9999px';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }}

        function copyToClipboard(text) {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(text).then(() => {{
                    showToast('Скопировано!');
                }}).catch(() => {{
                    fallbackCopy(text);
                    showToast('Скопировано!');
                }});
            }} else {{
                fallbackCopy(text);
                showToast('Скопировано!');
            }}
        }}

        function copyMessage(text) {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(text).then(() => {{
                    showToast('Сообщение скопировано!');
                }}).catch(() => {{
                    fallbackCopy(text);
                    showToast('Сообщение скопировано!');
                }});
            }} else {{
                fallbackCopy(text);
                showToast('Сообщение скопировано!');
            }}
        }}

        function deleteMessage(msgId, isHard) {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify({{
                    type: 'delete_message',
                    msg_id: parseInt(msgId),
                    hard: isHard
                }}));
            }}
        }}

        function restoreMessage(msgId) {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify({{
                    type: 'restore_message',
                    msg_id: parseInt(msgId)
                }}));
            }}
        }}

        function trackActivity() {{
            lastActivityTime = Date.now();
        }}
        document.addEventListener('keydown', trackActivity);
        document.addEventListener('mousedown', trackActivity);
        document.addEventListener('input', trackActivity);

        const rightPanel = document.getElementById('rightPanel');
        let isResizing = false;
        let startX, startWidth;
        
        if (rightPanel && !NO_ACTIVE_MODE) {{
            rightPanel.addEventListener('mousedown', (e) => {{
                if (e.target.classList.contains('resize-handle') || e.target === rightPanel) {{
                    isResizing = true;
                    startX = e.clientX;
                    startWidth = rightPanel.offsetWidth;
                    document.body.style.cursor = 'ew-resize';
                    e.preventDefault();
                }}
            }});
        }}
        
        document.addEventListener('mousemove', (e) => {{
            if (!isResizing) return;
            const newWidth = startWidth + (startX - e.clientX);
            if (newWidth >= 100 && newWidth <= 350) {{
                rightPanel.style.width = newWidth + 'px';
            }}
        }});
        
        document.addEventListener('mouseup', () => {{
            isResizing = false;
            document.body.style.cursor = '';
        }});

        const panel = document.getElementById('panel');
        let isResizingPanel = false;
        let startY, startHeight;
        
        panel.addEventListener('mousedown', (e) => {{
            if (e.target.classList.contains('resize-handle')) {{
                isResizingPanel = true;
                startY = e.clientY;
                startHeight = panel.offsetHeight;
                document.body.style.cursor = 'ns-resize';
                e.preventDefault();
            }}
        }});
        
        document.addEventListener('mousemove', (e) => {{
            if (!isResizingPanel) return;
            const newHeight = startHeight + (startY - e.clientY);
            if (newHeight >= 100 && newHeight <= 400) {{
                panel.style.height = newHeight + 'px';
            }}
        }});
        
        document.addEventListener('mouseup', () => {{
            isResizingPanel = false;
            document.body.style.cursor = '';
        }});

        const hostMenuContainer = document.getElementById('hostMenuContainer');
        fetch('/api/get_my_ip')
            .then(res => res.json())
            .then(data => {{
                if (data.ip === SERVER_IP_ADDR) {{
                    if (hostMenuContainer) hostMenuContainer.style.display = 'block';
                }}
            }});

        const hostMenuBtn = document.getElementById('hostMenuBtn');
        const hostMenuContent = document.getElementById('hostMenuContent');
        if (hostMenuBtn && hostMenuContent) {{
            hostMenuBtn.addEventListener('click', () => {{
                hostMenuContent.classList.toggle('show');
            }});
            document.addEventListener('click', (e) => {{
                if (!hostMenuBtn.contains(e.target) && !hostMenuContent.contains(e.target)) {{
                    hostMenuContent.classList.remove('show');
                }}
            }});
        }}

        const menuBtn = document.getElementById('menuBtn');
        const menuContent = document.getElementById('menuContent');
        if (menuBtn && menuContent) {{
            menuBtn.addEventListener('click', () => {{
                menuContent.classList.toggle('show');
            }});
            document.addEventListener('click', (e) => {{
                if (!menuBtn.contains(e.target) && !menuContent.contains(e.target)) {{
                    menuContent.classList.remove('show');
                }}
            }});
        }}

        function sendCommand(cmd) {{
            if (ws && ws.readyState === WebSocket.OPEN) {{
                ws.send(JSON.stringify({{
                    type: 'send_message',
                    text: cmd
                }}));
            }}
        }}

        if (document.getElementById('adminMenuContainer')) {{
            const adminMenuBtn = document.getElementById('adminMenuBtn');
            const adminMenuContent = document.getElementById('adminMenuContent');
            if (adminMenuBtn && adminMenuContent) {{
                adminMenuBtn.addEventListener('click', () => {{
                    adminMenuContent.classList.toggle('show');
                }});
                document.addEventListener('click', (e) => {{
                    if (!adminMenuBtn.contains(e.target) && !adminMenuContent.contains(e.target)) {{
                        adminMenuContent.classList.remove('show');
                    }}
                }});
            }}
            document.getElementById('cmdClear')?.addEventListener('click', () => sendCommand('/cl'));
            document.getElementById('cmdRestore')?.addEventListener('click', () => sendCommand('/ret'));
            document.getElementById('cmdAddAdmin')?.addEventListener('click', () => {{
                const ip = prompt('Введите IP пользователя:');
                if (ip) sendCommand('/a ' + ip);
            }});
            document.getElementById('cmdChangeNick')?.addEventListener('click', () => {{
                const ip = prompt('Введите IP пользователя:');
                if (!ip) return;
                const newNick = prompt('Введите новый ник:');
                if (newNick) sendCommand('/ch ' + ip + ' ' + newNick);
            }});
            document.getElementById('cmdChangeNickAll')?.addEventListener('click', () => {{
                const ip = prompt('Введите IP пользователя:');
                if (!ip) return;
                const newNick = prompt('Введите новый ник:');
                if (newNick) sendCommand('/ch-u ' + ip + ' ' + newNick);
            }});
        }}

        document.getElementById('cmdTell')?.addEventListener('click', () => {{
            const nick = prompt('Введите ник получателя (без @):');
            if (!nick) return;
            const message = prompt('Введите сообщение:');
            if (message) sendCommand('/tell @' + nick + ' ' + message);
        }});

        function saveScrollPosition() {{
            const chat = document.getElementById('chat');
            scrollPosition = chat.scrollTop;
        }}

        function restoreScrollPosition() {{
            const chat = document.getElementById('chat');
            chat.scrollTop = scrollPosition;
        }}

        function highlightMentions(text, currentNickname) {{
            if (!text) return text;
            const regex = /@(\\w+)/g;
            return text.replace(regex, (match, mentionNick) => {{
                if (mentionNick === currentNickname) {{
                    return `<span class="mention-highlight">${{match}}</span>`;
                }}
                return match;
            }});
        }}

        function showWarning(message, isError = true) {{
            const warningEl = document.getElementById('warning');
            warningEl.innerHTML = (isError ? '❌ ' : '⚠️ ') + message;
            warningEl.className = 'warning';
            setTimeout(() => {{
                if (registered) {{
                    warningEl.innerHTML = '✅ Ваше имя "' + escapeHtml(nickname) + '" закреплено, изменить нельзя. Напишите в чат с просьбой об изменении.' + (isAdmin ? ' (администратор)' : '');
                    warningEl.className = 'warning success';
                }} else {{
                    warningEl.innerHTML = '⚠️ Никнейм не может быть изменен';
                    warningEl.className = 'warning';
                }}
            }}, 3000);
        }}

        function updateCharCounter() {{
            const input = document.getElementById('messageInput');
            const counter = document.getElementById('charCounter');
            const length = input.value.length;
            counter.textContent = length + ' / {MAX_MESSAGE_LENGTH}';
            if (length > {MAX_MESSAGE_LENGTH}) {{
                counter.classList.add('warning');
            }} else {{
                counter.classList.remove('warning');
            }}
        }}

        function updateSuggestions(query) {{
            const filtered = allUsers.filter(user => 
                user.nickname.toLowerCase().startsWith(query.toLowerCase())
            ).slice(0, 5);
            currentSuggestions = filtered;
            const suggestionsBox = document.getElementById('suggestions');
            
            if (filtered.length > 0) {{
                suggestionsBox.innerHTML = '';
                filtered.forEach((user, index) => {{
                    const div = document.createElement('div');
                    div.className = 'suggestion-item' + (index === currentSuggestionIndex ? ' selected' : '');
                    div.innerHTML = `<span>@${{escapeHtml(user.nickname)}}</span>`;
                    div.addEventListener('click', () => {{
                        insertSuggestion(user.nickname);
                    }});
                    suggestionsBox.appendChild(div);
                }});
                suggestionsBox.style.display = 'block';
            }} else {{
                suggestionsBox.style.display = 'none';
                currentSuggestionIndex = -1;
            }}
        }}

        function insertSuggestion(nicknameValue) {{
            const input = document.getElementById('messageInput');
            const value = input.value;
            const cursorPos = input.selectionStart;
            const textBeforeCursor = value.substring(0, cursorPos);
            const lastAtIndex = textBeforeCursor.lastIndexOf('@');
            if (lastAtIndex !== -1) {{
                const newValue = value.substring(0, lastAtIndex) + '@' + nicknameValue + ' ' + value.substring(cursorPos);
                input.value = newValue;
                document.getElementById('suggestions').style.display = 'none';
                currentSuggestionIndex = -1;
                input.focus();
                updateCharCounter();
            }}
        }}

        const messageInput = document.getElementById('messageInput');
        const suggestionsBox = document.getElementById('suggestions');
        
        messageInput.addEventListener('input', function() {{
            const value = messageInput.value;
            const cursorPos = messageInput.selectionStart;
            const textBeforeCursor = value.substring(0, cursorPos);
            const lastAtIndex = textBeforeCursor.lastIndexOf('@');
            
            if (lastAtIndex !== -1) {{
                const query = textBeforeCursor.substring(lastAtIndex + 1);
                if (!query.includes(' ')) {{
                    updateSuggestions(query);
                }} else {{
                    suggestionsBox.style.display = 'none';
                    currentSuggestionIndex = -1;
                }}
            }} else {{
                suggestionsBox.style.display = 'none';
                currentSuggestionIndex = -1;
            }}
        }});

        messageInput.addEventListener('keydown', function(e) {{
            if (suggestionsBox.style.display === 'block') {{
                if (e.key === 'Tab') {{
                    e.preventDefault();
                    if (currentSuggestions.length > 0) {{
                        currentSuggestionIndex = (currentSuggestionIndex + 1) % currentSuggestions.length;
                        const items = suggestionsBox.querySelectorAll('.suggestion-item');
                        items.forEach((item, idx) => {{
                            if (idx === currentSuggestionIndex) {{
                                item.classList.add('selected');
                            }} else {{
                                item.classList.remove('selected');
                            }}
                        }});
                    }}
                }} else if (e.key === 'Enter') {{
                    e.preventDefault();
                    if (currentSuggestionIndex >= 0 && currentSuggestions[currentSuggestionIndex]) {{
                        insertSuggestion(currentSuggestions[currentSuggestionIndex].nickname);
                        return;
                    }}
                }}
            }}
            if (!registered) return;
            if (e.key === 'Enter' && !e.shiftKey && suggestionsBox.style.display !== 'block') {{
                e.preventDefault();
                sendMessage();
            }}
        }});

        document.addEventListener('click', function(e) {{
            if (suggestionsBox && !suggestionsBox.contains(e.target) && e.target !== messageInput) {{
                suggestionsBox.style.display = 'none';
                currentSuggestionIndex = -1;
            }}
        }});

        function loadMessages() {{
            saveScrollPosition();
            fetch('/api/messages')
                .then(res => res.json())
                .then(messages => {{
                    const chat = document.getElementById('chat');
                    const wasScrolledToBottom = (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 10;
                    chat.innerHTML = '';
                    messages.forEach(msg => {{
                        const div = createMessageElement(msg);
                        chat.appendChild(div);
                    }});
                    if (wasScrolledToBottom) {{
                        chat.scrollTop = chat.scrollHeight;
                    }} else {{
                        restoreScrollPosition();
                    }}
                }})
                .catch(e => console.log('Ошибка загрузки:', e));
        }}

        function checkRegistration() {{
            fetch('/api/check')
                .then(res => res.json())
                .then(data => {{
                    if (data.registered) {{
                        registered = true;
                        isAdmin = data.isAdmin;
                        nickname = data.nickname;
                        currentUserIp = data.ip;
                        document.getElementById('nicknameInput').value = data.nickname;
                        document.getElementById('nicknameInput').disabled = true;
                        document.getElementById('saveNicknameBtn').style.display = 'none';
                        if (isAdmin) {{
                            const badge = document.createElement('span');
                            badge.className = 'admin-badge';
                            badge.textContent = 'ADMIN';
                            document.querySelector('.nickname-row').appendChild(badge);
                            const adminMenu = document.getElementById('adminMenuContainer');
                            if (adminMenu) adminMenu.style.display = 'block';
                        }}
                        document.getElementById('warning').innerHTML = '✅ Ваше имя "' + escapeHtml(data.nickname) + '" закреплено, изменить нельзя. Напишите в чат с просьбой об изменении.' + (isAdmin ? ' (администратор)' : '');
                        document.getElementById('warning').className = 'warning success';
                        sendHeartbeat();
                        loadMessages();
                    }}
                }})
                .catch(e => console.log('Ошибка проверки:', e));
        }}

        function escapeHtml(str) {{
            return str.replace(/[&<>]/g, function(m) {{
                if (m === '&') return '&amp;';
                if (m === '<') return '&lt;';
                if (m === '>') return '&gt;';
                return m;
            }});
        }}

        function sendMessage() {{
            if (isSending) {{
                showWarning('Подождите, сообщение уже отправляется...', true);
                return;
            }}
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (!text || !registered) return;
            
            if (text.length > {MAX_MESSAGE_LENGTH}) {{
                showWarning('Сообщение слишком длинное! Максимум {MAX_MESSAGE_LENGTH} символов. Сейчас: ' + text.length, true);
                return;
            }}
            
            isSending = true;
            const sendBtn = document.getElementById('sendBtn');
            sendBtn.disabled = true;
            sendBtn.textContent = 'Отправка...';
            
            try {{
                if (ws && ws.readyState === WebSocket.OPEN) {{
                    ws.send(JSON.stringify({{
                        type: 'send_message',
                        text: text
                    }}));
                    input.value = '';
                    updateCharCounter();
                    suggestionsBox.style.display = 'none';
                    currentSuggestionIndex = -1;
                    input.blur();
                }} else {{
                    showWarning('Нет соединения с сервером', true);
                }}
            }} catch (e) {{
                console.log('Ошибка отправки:', e);
                showWarning('Ошибка отправки. Попробуйте ещё раз.', true);
            }} finally {{
                isSending = false;
                sendBtn.disabled = false;
                sendBtn.textContent = 'Отправить';
            }}
        }}

        function registerNickname() {{
            const nicknameInput = document.getElementById('nicknameInput');
            const nicknameVal = nicknameInput.value.trim();
            if (!nicknameVal) return;
            fetch('/api/register', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                body: 'nickname=' + encodeURIComponent(nicknameVal)
            }}).then(res => res.json()).then(data => {{
                if (data.success) {{
                    registered = true;
                    isAdmin = data.isAdmin;
                    nickname = nicknameVal;
                    currentUserIp = data.ip;
                    nicknameInput.disabled = true;
                    document.getElementById('saveNicknameBtn').style.display = 'none';
                    if (isAdmin) {{
                        const badge = document.createElement('span');
                        badge.className = 'admin-badge';
                        badge.textContent = 'ADMIN';
                        document.querySelector('.nickname-row').appendChild(badge);
                        const adminMenu = document.getElementById('adminMenuContainer');
                        if (adminMenu) adminMenu.style.display = 'block';
                    }}
                    document.getElementById('warning').innerHTML = '✅ Имя "' + escapeHtml(nicknameVal) + '" закреплено, изменить нельзя. Напишите в чат с просьбой об изменении.' + (isAdmin ? ' (администратор)' : '');
                    document.getElementById('warning').className = 'warning success';
                    sendHeartbeat();
                    loadMessages();
                }} else {{
                    showWarning(data.error, true);
                }}
            }}).catch(e => console.log('Ошибка регистрации:', e));
        }}

        document.addEventListener('keydown', function(e) {{
            const activeElement = document.activeElement;
            const isInputFocused = activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA';
            if ((e.key === '+' || e.key === '=' || e.key === 'Equal') && !isInputFocused) {{
                e.preventDefault();
                window.location.href = '{REDIRECT_URL}';
            }}
        }});

        document.getElementById('saveNicknameBtn').addEventListener('click', registerNickname);
        document.getElementById('nicknameInput').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') registerNickname();
        }});

        const msgInput = document.getElementById('messageInput');
        msgInput.addEventListener('input', updateCharCounter);

        document.getElementById('sendBtn').addEventListener('click', sendMessage);

        connectWebSocket();
        setInterval(sendHeartbeat, 5000);
        checkRegistration();
        updateCharCounter();
    </script>
</body>
</html>'''

class HTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/api/get_my_ip':
            client_ip = self.client_address[0]
            self._send_json({'ip': client_ip})
        elif self.path == '/api/messages':
            client_ip = self.client_address[0]
            is_host = (client_ip == SERVER_IP)
            client_nickname = get_nickname(client_ip)
            try:
                with open(MESSAGES_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        messages = []
                    else:
                        messages = json.loads(content)
                
                processed_messages = []
                for msg in messages[-DISPLAY_LIMIT:]:
                    msg_copy = msg.copy()
                    
                    if msg_copy.get('isWhisper'):
                        target = msg_copy.get('whisperTarget')
                        is_sender = (msg_copy.get('ip') == client_ip)
                        is_target = (target == client_nickname)
                        is_server_host = is_host
                        
                        if not (is_sender or is_target or is_server_host):
                            continue
                    
                    is_deleted = msg_copy.get('isDeleted', False)
                    if is_deleted:
                        is_server_host = is_host
                        if not is_server_host:
                            continue
                        msg_copy['isDeleted'] = True
                    
                    msg_copy['isOwn'] = (msg_copy.get('ip') == client_ip)
                    msg_copy['hasMention'] = (f'@{get_nickname(client_ip)}' in msg_copy.get('text', ''))
                    msg_copy['isAdmin'] = is_admin(msg_copy.get('ip', '0.0.0.0'))
                    msg_copy['showIp'] = is_host
                    msg_copy['nicknameColor'] = get_nickname_color(msg_copy.get('ip', '0.0.0.0'))
                    
                    if not ADMIN_MODE:
                        msg_copy.pop('ip', None)
                    
                    processed_messages.append(msg_copy)
                
                self._send_json(processed_messages)
            except (json.JSONDecodeError, IOError):
                self._send_json([])
        elif self.path == '/api/check':
            client_ip = self.client_address[0]
            try:
                users = load_users()
                if client_ip in users:
                    user_data = users[client_ip]
                    if isinstance(user_data, dict):
                        nickname = user_data.get('nickname', 'Unknown')
                        admin_status = user_data.get('is_admin', False)
                    else:
                        nickname = user_data
                        admin_status = False
                    self._send_json({'registered': True, 'nickname': nickname, 'isAdmin': admin_status, 'ip': client_ip})
                else:
                    self._send_json({'registered': False, 'isAdmin': False, 'ip': client_ip})
            except (json.JSONDecodeError, IOError):
                self._send_json({'registered': False, 'isAdmin': False, 'ip': client_ip})
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        client_ip = self.client_address[0]
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode()
        params = parse_qs(body)
        
        if self.path == '/api/register':
            nickname = params.get('nickname', [''])[0].strip()
            if not nickname:
                self._send_json({'success': False, 'error': 'Имя не может быть пустым'})
                return
            if len(nickname) > 20:
                self._send_json({'success': False, 'error': 'Имя слишком длинное (макс 20)'})
                return
            
            users = load_users()
            
            if client_ip in users:
                self._send_json({'success': False, 'error': f'Ваш IP уже привязан к имени "{get_nickname(client_ip)}"'})
                return
            
            for ip, user_data in users.items():
                if isinstance(user_data, dict):
                    existing_nickname = user_data.get('nickname', '')
                else:
                    existing_nickname = user_data
                if existing_nickname == nickname:
                    self._send_json({'success': False, 'error': f'Имя "{nickname}" уже занято'})
                    return
            
            is_admin_status = (ADMIN_MODE and client_ip == SERVER_IP)
            users[client_ip] = {'nickname': nickname, 'is_admin': is_admin_status}
            save_users(users)
            
            self._send_json({'success': True, 'nickname': nickname, 'isAdmin': is_admin_status, 'ip': client_ip})
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_json(self, data):
        try:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
            pass

async def cleanup_active_users():
    while True:
        await asyncio.sleep(30)
        with active_users_lock:
            now = datetime.now().timestamp()
            to_remove = [ip for ip, data in active_users.items() if now - data.get('last_seen', 0) > 30]
            for ip in to_remove:
                del active_users[ip]
        await broadcast_active_users()

async def start_websocket_server():
    async with websockets.serve(handle_websocket, "0.0.0.0", 8001):
        await asyncio.Future()

def run_http_server():
    httpd = HTTPServer(('', 8000), HTTPHandler)
    httpd.serve_forever()

async def main():
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    
    asyncio.create_task(cleanup_active_users())
    
    print(f'HTTP сервер: http://{SERVER_IP}:8000')
    print(f'Данные: {DATA_DIR}')
    print(f'Сохраняется сообщений: {SAVE_LIMIT} (макс), отображается: {DISPLAY_LIMIT}')
    print(f'Макс. длина сообщения: {MAX_MESSAGE_LENGTH} символов')
    print(f'Выход: {REDIRECT_URL}')
    print(f'Команды в чате: {"Да" if SHOW_COMMANDS else "Нет"}')
    print(f'Активные пользователи: {"Выключена" if NO_ACTIVE else "Включена"}')
    print(f'Режим админа: {"Включён" if ADMIN_MODE else "Выключен"}')
    
    await start_websocket_server()

if __name__ == '__main__':
    asyncio.run(main())