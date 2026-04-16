import os
import json
import sys
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime

# Папка для хранения данных
DATA_DIR = 'db'

# Создаём папку db, если её нет
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')
BACKUP_FILE = os.path.join(DATA_DIR, 'back.json')

SAVE_LIMIT = 1000
DISPLAY_LIMIT = 50
MAX_MESSAGE_LENGTH = 500
PAGE_TITLE = "HTTP"

REDIRECT_URL = "https://www.google.com"

ADMIN_MODE = '-a' in sys.argv
SHOW_COMMANDS = '-sh' in sys.argv

REFRESH_INTERVAL = 2000
if '-cd' in sys.argv:
    try:
        idx = sys.argv.index('-cd')
        if idx + 1 < len(sys.argv):
            REFRESH_INTERVAL = int(sys.argv[idx + 1])
    except (ValueError, IndexError):
        print(f'Неверное значение для -cd, используется значение по умолчанию: {REFRESH_INTERVAL}')

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

def get_nickname_color(ip):
    # Генерируем цвет на основе IP
    hash_val = 0
    for c in ip:
        hash_val = (hash_val * 31 + ord(c)) % 360
    # Возвращаем цвет в формате HSL (насыщенность 70%, яркость 45% для читаемости на светлом фоне)
    return f"hsl({hash_val}, 70%, 35%)"

ADMIN_MODE_STR = str(ADMIN_MODE).lower()
SHOW_COMMANDS_STR = str(SHOW_COMMANDS).lower()

ARGS_LIST = []
if ADMIN_MODE:
    ARGS_LIST.append('-a')
if SHOW_COMMANDS:
    ARGS_LIST.append('-sh')
if '-cd' in sys.argv:
    try:
        idx = sys.argv.index('-cd')
        if idx + 1 < len(sys.argv):
            ARGS_LIST.append(f'-cd {sys.argv[idx + 1]}')
    except:
        pass
ARGS_STRING = ' '.join(ARGS_LIST) if ARGS_LIST else 'нет'

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
        }}
        .msg:hover {{ background: #fff3e0; }}
        .time {{ color: #8B6914; font-size: 12px; font-weight: 500; }}
        .ip {{ color: #888; font-size: 10px; margin-left: 5px; cursor: pointer; }}
        .ip:hover {{ text-decoration: underline; }}
        .nickname {{ font-weight: bold; cursor: pointer; }}
        .nickname:hover {{ text-decoration: underline; }}
        .text {{ color: #333; white-space: pre-wrap; }}
        .panel {{ background: #3c3c3c; padding: 15px; border-top: 1px solid #4a4a4a; }}
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
        .input-row {{ display: flex; gap: 10px; align-items: flex-end; }}
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
        .active-users {{
            position: fixed;
            bottom: 100px;
            right: 20px;
            background: #2d2d2d;
            border-radius: 8px;
            padding: 10px;
            min-width: 150px;
            border: 1px solid #4a4a4a;
            z-index: 1000;
            font-size: 12px;
            max-height: 200px;
            overflow-y: auto;
        }}
        .active-users-title {{
            color: #4ec9b0;
            font-weight: bold;
            margin-bottom: 8px;
            border-bottom: 1px solid #4a4a4a;
            padding-bottom: 4px;
        }}
        .active-user {{
            padding: 3px 0;
            color: #d4d4d4;
            cursor: pointer;
        }}
        .active-user.online {{
            color: #4ec9b0;
        }}
        .active-user:hover {{
            text-decoration: underline;
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
            transition: opacity 0.3s;
            pointer-events: none;
        }}
        .toast.show {{
            opacity: 1;
        }}
    </style>
</head>
<body>
    <div class="right-menus">
        <div class="menu-wrapper">
            <div class="admin-menu" id="adminMenuContainer" style="display: none;">
                <button class="menu-btn admin-btn" id="adminMenuBtn">Админ</button>
                <div class="menu-content" id="adminMenuContent">
                    <div class="menu-item" id="cmdClear"><strong>/cl</strong> — Очистить чат (сохранить в back.json)</div>
                    <div class="menu-item" id="cmdRestore"><strong>/ret</strong> — Восстановить чат из back.json</div>
                    <div class="menu-item" id="cmdAddAdmin"><strong>/a "ip"</strong> — Сделать пользователя администратором</div>
                    <div class="menu-item" id="cmdChangeNick"><strong>/ch "ip" "ник"</strong> — Сменить ник пользователю</div>
                </div>
            </div>
            <div class="tools-menu">
                <button class="menu-btn" id="menuBtn">Инструменты</button>
                <div class="menu-content" id="menuContent">
                    <div class="menu-item"><strong>+ / =</strong> — Нажмите + или =, чтобы закрыть сайт (не работает при вводе текста)</div>
                </div>
            </div>
        </div>
        <div class="host-menu" id="hostMenuContainer" style="display: none;">
            <button class="menu-btn host-btn" id="hostMenuBtn">Хост</button>
            <div class="menu-content" id="hostMenuContent">
                <div class="menu-item">Аргументы запуска: {ARGS_STRING}</div>
                <div class="menu-item"><strong>-a</strong> — режим админа (видно IP)</div>
                <div class="menu-item"><strong>-sh</strong> — показывать команды в чате</div>
                <div class="menu-item"><strong>-cd "мс"</strong> — интервал обновления сообщений</div>
            </div>
        </div>
    </div>

    <div id="chat"></div>
    <div class="active-users" id="activeUsersPanel">
        <div class="active-users-title">Активные пользователи (нажмите для копирования IP)</div>
        <div id="activeUsersList">Загрузка...</div>
    </div>
    <div class="panel">
        <div class="nickname-row">
            <label>Имя:</label>
            <input type="text" id="nicknameInput" placeholder="Введите имя" maxlength="20">
            <button id="saveNicknameBtn">Сохранить</button>
        </div>
        <div class="warning" id="warning">⚠️ Никнейм не может быть изменен</div>
        <div class="input-row">
            <textarea id="messageInput" rows="2" placeholder="Сообщение..."></textarea>
            <button id="sendBtn">Отправить</button>
        </div>
        <div class="char-counter" id="charCounter">0 / {MAX_MESSAGE_LENGTH}</div>
    </div>
    <div class="toast" id="toast">IP скопирован!</div>

    <script>
        let registered = false;
        let scrollPosition = 0;
        let isAdmin = false;
        let nickname = '';
        let heartbeatInterval = null;
        let currentUserIp = null;

        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('show');
            setTimeout(() => {{
                toast.classList.remove('show');
            }}, 2000);
        }}

        function copyToClipboard(text) {{
            navigator.clipboard.writeText(text).then(() => {{
                showToast('IP скопирован: ' + text);
            }}).catch(() => {{
                showToast('Не удалось скопировать');
            }});
        }}

        const hostMenuContainer = document.getElementById('hostMenuContainer');
        // Хост-меню видно только если текущий IP равен SERVER_IP
        fetch('/api/get_my_ip')
            .then(res => res.json())
            .then(data => {{
                if (data.ip === '{SERVER_IP}') {{
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
            fetch('/api/send', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                body: 'text=' + encodeURIComponent(cmd)
            }}).then(() => {{
                loadMessages();
            }}).catch(e => console.log('Ошибка отправки команды:', e));
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
        }}

        function startHeartbeat() {{
            if (heartbeatInterval) clearInterval(heartbeatInterval);
            heartbeatInterval = setInterval(() => {{
                if (registered && nickname) {{
                    fetch('/api/heartbeat', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                        body: 'nickname=' + encodeURIComponent(nickname)
                    }}).catch(e => console.log('Heartbeat error:', e));
                }}
            }}, 10000);
        }}

        function loadActiveUsers() {{
            fetch('/api/active_users')
                .then(res => res.json())
                .then(users => {{
                    const container = document.getElementById('activeUsersList');
                    if (!container) return;
                    if (users.length === 0) {{
                        container.innerHTML = '<div class="active-user offline">Нет активных</div>';
                        return;
                    }}
                    let html = '';
                    users.forEach(user => {{
                        html += `<div class="active-user online" data-ip="${{user.ip}}">${{escapeHtml(user.nickname)}}</div>`;
                    }});
                    container.innerHTML = html;
                    document.querySelectorAll('.active-user').forEach(el => {{
                        el.addEventListener('click', (e) => {{
                            e.stopPropagation();
                            const ip = el.dataset.ip;
                            if (ip) copyToClipboard(ip);
                        }});
                    }});
                }})
                .catch(e => console.log('Ошибка загрузки активных пользователей:', e));
        }}

        function saveScrollPosition() {{
            const chat = document.getElementById('chat');
            scrollPosition = chat.scrollTop;
        }}

        function restoreScrollPosition() {{
            const chat = document.getElementById('chat');
            chat.scrollTop = scrollPosition;
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

        function loadMessages() {{
            saveScrollPosition();
            fetch('/api/messages')
                .then(res => res.json())
                .then(messages => {{
                    const chat = document.getElementById('chat');
                    const wasScrolledToBottom = (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 10;
                    chat.innerHTML = '';
                    messages.forEach(msg => {{
                        const div = document.createElement('div');
                        div.className = 'msg';
                        let ipHtml = '';
                        if ({ADMIN_MODE_STR} && msg.ip) {{
                            ipHtml = `<span class="ip" data-ip="${{escapeHtml(msg.ip)}}">(${{escapeHtml(msg.ip)}})</span>`;
                        }}
                        const nicknameColor = msg.nicknameColor || '#B8860B';
                        div.innerHTML = `<span class="time">[${{escapeHtml(msg.time)}}]</span>${{ipHtml}} <span class="nickname" style="color: ${{nicknameColor}};" data-ip="${{msg.ip || ''}}">${{escapeHtml(msg.nickname)}}:</span> <span class="text">${{escapeHtml(msg.text)}}</span>`;
                        chat.appendChild(div);
                    }});
                    document.querySelectorAll('.nickname').forEach(el => {{
                        el.addEventListener('click', (e) => {{
                            e.stopPropagation();
                            const ip = el.dataset.ip;
                            if (ip && {ADMIN_MODE_STR}) {{
                                copyToClipboard(ip);
                            }}
                        }});
                    }});
                    document.querySelectorAll('.ip').forEach(el => {{
                        el.addEventListener('click', (e) => {{
                            e.stopPropagation();
                            const ip = el.dataset.ip;
                            if (ip) copyToClipboard(ip);
                        }});
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
                        startHeartbeat();
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
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (!text || !registered) return;
            
            if (text.length > {MAX_MESSAGE_LENGTH}) {{
                showWarning('Сообщение слишком длинное! Максимум {MAX_MESSAGE_LENGTH} символов. Сейчас: ' + text.length, true);
                return;
            }}
            
            fetch('/api/send', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }},
                body: 'text=' + encodeURIComponent(text)
            }}).then(res => res.json()).then(data => {{
                if (data.success) {{
                    input.value = '';
                    updateCharCounter();
                    loadMessages();
                }} else if (data.error) {{
                    showWarning(data.error, true);
                }}
            }}).catch(e => console.log('Ошибка отправки:', e));
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
                    startHeartbeat();
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
        msgInput.addEventListener('keydown', function(e) {{
            if (!registered) return;
            if (e.key === 'Enter' && !e.shiftKey) {{
                e.preventDefault();
                sendMessage();
            }}
        }});

        document.getElementById('sendBtn').addEventListener('click', sendMessage);

        setInterval(loadMessages, {REFRESH_INTERVAL});
        setInterval(loadActiveUsers, 5000);
        checkRegistration();
        loadMessages();
        updateCharCounter();
    </script>
</body>
</html>'''

class MessengerHandler(BaseHTTPRequestHandler):
    def send_system_message(self, text):
        if not SHOW_COMMANDS:
            return
        try:
            with open(MESSAGES_FILE, 'r') as f:
                content = f.read().strip()
                if not content:
                    messages = []
                else:
                    messages = json.loads(content)
        except (json.JSONDecodeError, IOError):
            messages = []
        
        messages.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'nickname': 'СИСТЕМА',
            'text': text,
            'ip': '0.0.0.0',
            'nicknameColor': '#888'
        })
        
        if len(messages) > SAVE_LIMIT:
            messages = messages[-SAVE_LIMIT:]
        
        with open(MESSAGES_FILE, 'w') as f:
            json.dump(messages, f)

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
            try:
                with open(MESSAGES_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        messages = []
                    else:
                        messages = json.loads(content)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                if ADMIN_MODE:
                    self.wfile.write(json.dumps(messages[-DISPLAY_LIMIT:]).encode())
                else:
                    messages_without_ip = []
                    for msg in messages[-DISPLAY_LIMIT:]:
                        msg_copy = msg.copy()
                        msg_copy.pop('ip', None)
                        messages_without_ip.append(msg_copy)
                    self.wfile.write(json.dumps(messages_without_ip).encode())
            except (json.JSONDecodeError, IOError):
                messages = []
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(messages).encode())
        elif self.path == '/api/active_users':
            with active_users_lock:
                users_copy = list(active_users.values())
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(users_copy).encode())
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
        
        if self.path == '/api/heartbeat':
            nickname = params.get('nickname', ['Unknown'])[0].strip()
            with active_users_lock:
                active_users[client_ip] = {'nickname': nickname, 'ip': client_ip, 'last_seen': datetime.now().timestamp()}
            self._send_json({'success': True})
            return
            
        elif self.path == '/api/register':
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
            
        elif self.path == '/api/send':
            users = load_users()
            
            if client_ip not in users:
                self._send_json({'success': False, 'error': 'Сначала зарегистрируйтесь'})
                return
            
            text = params.get('text', [''])[0].strip()
            if not text:
                self._send_json({'success': False, 'error': 'Сообщение пустое'})
                return
            if len(text) > MAX_MESSAGE_LENGTH:
                self._send_json({'success': False, 'error': f'Сообщение слишком длинное! Максимум {MAX_MESSAGE_LENGTH} символов'})
                return
            
            if is_admin(client_ip) and text.startswith('/'):
                parts = text.split()
                cmd = parts[0].lower()
                
                if cmd == '/a' and len(parts) == 2:
                    target_ip = parts[1]
                    users = load_users()
                    if target_ip in users:
                        user_data = users[target_ip]
                        if isinstance(user_data, dict):
                            user_data['is_admin'] = True
                        else:
                            users[target_ip] = {'nickname': user_data, 'is_admin': True}
                        save_users(users)
                        self.send_system_message(f'Администратор {get_nickname(client_ip)} добавил админа {target_ip}')
                    else:
                        users[target_ip] = {'nickname': 'Unknown', 'is_admin': True}
                        save_users(users)
                        self.send_system_message(f'Администратор {get_nickname(client_ip)} добавил админа {target_ip}')
                    self._send_json({'success': True})
                    return
                
                elif cmd == '/cl':
                    try:
                        with open(MESSAGES_FILE, 'r') as f:
                            current_messages = json.load(f)
                        with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
                            json.dump(current_messages, f, ensure_ascii=False, indent=2)
                        with open(MESSAGES_FILE, 'w') as f:
                            json.dump([], f)
                        self.send_system_message(f'Администратор {get_nickname(client_ip)} очистил чат')
                        self._send_json({'success': True})
                    except Exception as e:
                        self._send_json({'success': False, 'error': f'Ошибка: {e}'})
                    return
                
                elif cmd == '/ret':
                    try:
                        if not os.path.exists(BACKUP_FILE):
                            self._send_json({'success': False, 'error': 'Файл back.json не найден'})
                            return
                        
                        with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
                            backup_messages = json.load(f)
                        
                        with open(MESSAGES_FILE, 'r') as f:
                            current_messages = json.load(f)
                        
                        combined = backup_messages + current_messages
                        
                        if len(combined) > SAVE_LIMIT:
                            combined = combined[-SAVE_LIMIT:]
                        
                        with open(MESSAGES_FILE, 'w') as f:
                            json.dump(combined, f)
                        
                        self.send_system_message(f'Администратор {get_nickname(client_ip)} восстановил чат из бэкапа')
                        self._send_json({'success': True})
                    except Exception as e:
                        self._send_json({'success': False, 'error': f'Ошибка: {e}'})
                    return
                
                elif cmd == '/ch' and len(parts) == 3:
                    target_ip = parts[1]
                    new_nickname = parts[2]
                    
                    if len(new_nickname) > 20:
                        self._send_json({'success': False, 'error': 'Новый ник слишком длинный (макс 20)'})
                        return
                    
                    users = load_users()
                    
                    if target_ip not in users:
                        self._send_json({'success': False, 'error': f'IP {target_ip} не найден'})
                        return
                    
                    old_nickname = get_nickname(target_ip)
                    user_data = users[target_ip]
                    if isinstance(user_data, dict):
                        user_data['nickname'] = new_nickname
                    else:
                        old_is_admin = users[target_ip].get('is_admin', False) if isinstance(users[target_ip], dict) else False
                        users[target_ip] = {'nickname': new_nickname, 'is_admin': old_is_admin}
                    
                    save_users(users)
                    self.send_system_message(f'Администратор {get_nickname(client_ip)} сменил ник {target_ip} с "{old_nickname}" на "{new_nickname}"')
                    self._send_json({'success': True})
                    return
                
                else:
                    self._send_json({'success': True})
                    return
            
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
            
            messages.append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'nickname': get_nickname(client_ip),
                'text': text,
                'ip': client_ip,
                'nicknameColor': nickname_color
            })
            
            if len(messages) > SAVE_LIMIT:
                messages = messages[-SAVE_LIMIT:]
            
            with open(MESSAGES_FILE, 'w') as f:
                json.dump(messages, f)
            
            self._send_json({'success': True})
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

def cleanup_active_users():
    import time
    while True:
        time.sleep(30)
        with active_users_lock:
            now = datetime.now().timestamp()
            to_remove = [ip for ip, data in active_users.items() if now - data.get('last_seen', 0) > 30]
            for ip in to_remove:
                del active_users[ip]

def run_server():
    cleanup_thread = threading.Thread(target=cleanup_active_users, daemon=True)
    cleanup_thread.start()
    
    print(f'Мессенджер запущен на http://localhost:8000')
    print(f'  - http://{SERVER_IP}:8000')
    print(f'Данные хранятся в папке: {DATA_DIR}')
    print(f'Сохраняется максимум {SAVE_LIMIT} сообщений')
    print(f'Показывается последние {DISPLAY_LIMIT} сообщений')
    print(f'Максимальная длина сообщения: {MAX_MESSAGE_LENGTH} символов')
    print(f'Интервал обновления чата: {REFRESH_INTERVAL} мс')
    print(f'При нажатии + или = (не в полях ввода) переход на: {REDIRECT_URL}')
    print(f'Показывать команды в чате: {"Да" if SHOW_COMMANDS else "Нет"}')
    if ADMIN_MODE:
        print(f'РЕЖИМ АДМИНА: Включён (IP сервера: {SERVER_IP})')
    else:
        print(f'РЕЖИМ АДМИНА: Выключен')
    HTTPServer(('', 8000), MessengerHandler).serve_forever()

if __name__ == '__main__':
    run_server()