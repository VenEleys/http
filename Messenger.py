import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime

MESSAGES_FILE = 'messages.json'
USERS_FILE = 'users.json'

SAVE_LIMIT = 1000
DISPLAY_LIMIT = 50

if not os.path.exists(MESSAGES_FILE):
    with open(MESSAGES_FILE, 'w') as f:
        json.dump([], f)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)

HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>HTTP Мессенджер</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; height: 100vh; display: flex; flex-direction: column; }
        #chat { flex: 1; overflow-y: auto; padding: 15px; display: flex; flex-direction: column; background: #fff8e1; }
        .msg { 
            margin: 5px 0; 
            padding: 8px; 
            border-bottom: 1px solid #ffe0b2; 
            word-wrap: break-word; 
            background: #fffef7; 
            border-radius: 4px;
            border: 1px solid #e0c080;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        .msg:hover { background: #fff3e0; }
        .time { color: #8B6914; font-size: 12px; font-weight: 500; }
        .nickname { color: #B8860B; font-weight: bold; }
        .text { color: #333; white-space: pre-wrap; }
        .panel { background: #3c3c3c; padding: 15px; border-top: 1px solid #4a4a4a; }
        .nickname-row { display: flex; gap: 10px; margin-bottom: 10px; align-items: center; }
        .nickname-row label { font-weight: bold; color: #4ec9b0; }
        #nicknameInput { width: 200px; padding: 8px; border: 1px solid #555; border-radius: 4px; font-size: 14px; font-family: monospace; background: #3c3c3c; color: #d4d4d4; }
        #nicknameInput:disabled { background: #2a2a2a; color: #858585; }
        #nicknameInput:focus { outline: none; border-color: #4ec9b0; }
        .warning { 
            color: #f48771; 
            font-size: 13px; 
            margin-bottom: 10px; 
            font-weight: bold;
            background: #2d2d2d;
            padding: 6px;
            border-radius: 4px;
            border-left: 3px solid #f48771;
        }
        .warning.success { color: #4ec9b0; background: #1e3a2f; border-left-color: #4ec9b0; }
        .input-row { display: flex; gap: 10px; align-items: flex-end; }
        #messageInput { flex: 1; padding: 8px; border: 1px solid #555; border-radius: 4px; font-size: 14px; font-family: monospace; resize: vertical; background: #3c3c3c; color: #d4d4d4; }
        #messageInput:focus { outline: none; border-color: #4ec9b0; }
        #messageInput:disabled { background: #2a2a2a; color: #858585; }
        button { padding: 8px 20px; background: #0e639c; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-family: monospace; }
        button:hover { background: #1177bb; }
        button:disabled { opacity: 0.5; cursor: not-allowed; }
    </style>
</head>
<body>
    <div id="chat"></div>
    <div class="panel">
        <div class="nickname-row">
            <label>Имя:</label>
            <input type="text" id="nicknameInput" placeholder="Введите имя" maxlength="20">
        </div>
        <div class="warning" id="warning">⚠️ Никнейм не может быть изменен</div>
        <div class="input-row">
            <textarea id="messageInput" rows="2" placeholder="Сообщение..." disabled></textarea>
            <button id="sendBtn" disabled>Отправить</button>
        </div>
    </div>

    <script>
        let registered = false;
        let scrollPosition = 0;

        function saveScrollPosition() {
            const chat = document.getElementById('chat');
            scrollPosition = chat.scrollTop;
        }

        function restoreScrollPosition() {
            const chat = document.getElementById('chat');
            chat.scrollTop = scrollPosition;
        }

        function loadMessages() {
            saveScrollPosition();
            fetch('/api/messages')
                .then(res => res.json())
                .then(messages => {
                    const chat = document.getElementById('chat');
                    const wasScrolledToBottom = (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < 10;
                    
                    chat.innerHTML = '';
                    messages.forEach(msg => {
                        const div = document.createElement('div');
                        div.className = 'msg';
                        div.innerHTML = `<span class="time">[${escapeHtml(msg.time)}]</span> <span class="nickname">${escapeHtml(msg.nickname)}:</span> <span class="text">${escapeHtml(msg.text)}</span>`;
                        chat.appendChild(div);
                    });
                    
                    if (wasScrolledToBottom) {
                        chat.scrollTop = chat.scrollHeight;
                    } else {
                        restoreScrollPosition();
                    }
                })
                .catch(e => console.log('Ошибка загрузки:', e));
        }

        function checkRegistration() {
            fetch('/api/check')
                .then(res => res.json())
                .then(data => {
                    if (data.registered) {
                        registered = true;
                        document.getElementById('nicknameInput').value = data.nickname;
                        document.getElementById('nicknameInput').disabled = true;
                        document.getElementById('messageInput').disabled = false;
                        document.getElementById('sendBtn').disabled = false;
                        document.getElementById('warning').innerHTML = '✅ Ваше имя "' + escapeHtml(data.nickname) + '" закреплено, изменить нельзя. Напишите в чат с просьбой об изменении.';
                        document.getElementById('warning').className = 'warning success';
                    }
                })
                .catch(e => console.log('Ошибка проверки:', e));
        }

        function escapeHtml(str) {
            return str.replace(/[&<>]/g, function(m) {
                if (m === '&') return '&amp;';
                if (m === '<') return '&lt;';
                if (m === '>') return '&gt;';
                return m;
            });
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (!text || !registered) return;
            
            fetch('/api/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'text=' + encodeURIComponent(text)
            }).then(() => {
                input.value = '';
                loadMessages();
            }).catch(e => console.log('Ошибка отправки:', e));
        }

        function registerNickname() {
            const nicknameInput = document.getElementById('nicknameInput');
            const nickname = nicknameInput.value.trim();
            if (!nickname) return;
            
            fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'nickname=' + encodeURIComponent(nickname)
            }).then(res => res.json()).then(data => {
                if (data.success) {
                    registered = true;
                    nicknameInput.disabled = true;
                    document.getElementById('messageInput').disabled = false;
                    document.getElementById('sendBtn').disabled = false;
                    document.getElementById('warning').innerHTML = '✅ Имя "' + escapeHtml(nickname) + '" закреплено, изменить нельзя. Напишите в чат с просьбой об изменении.';
                    document.getElementById('warning').className = 'warning success';
                } else {
                    document.getElementById('warning').innerHTML = '❌ ' + escapeHtml(data.error);
                    document.getElementById('warning').className = 'warning';
                }
            }).catch(e => console.log('Ошибка регистрации:', e));
        }

        document.getElementById('nicknameInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') registerNickname();
        });

        const msgInput = document.getElementById('messageInput');
        msgInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        document.getElementById('sendBtn').addEventListener('click', sendMessage);

        setInterval(loadMessages, 2000);
        checkRegistration();
        loadMessages();
    </script>
</body>
</html>'''

class MessengerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
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
                self.wfile.write(json.dumps(messages[-DISPLAY_LIMIT:]).encode())
            except (json.JSONDecodeError, IOError):
                messages = []
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(messages).encode())
        elif self.path == '/api/check':
            client_ip = self.client_address[0]
            try:
                with open(USERS_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        users = {}
                    else:
                        users = json.loads(content)
                if client_ip in users:
                    self._send_json({'registered': True, 'nickname': users[client_ip]})
                else:
                    self._send_json({'registered': False})
            except (json.JSONDecodeError, IOError):
                self._send_json({'registered': False})
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
            
            try:
                with open(USERS_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        users = {}
                    else:
                        users = json.loads(content)
            except (json.JSONDecodeError, IOError):
                users = {}
            
            if client_ip in users:
                self._send_json({'success': False, 'error': f'Ваш IP уже привязан к имени "{users[client_ip]}"'})
                return
            
            for ip, existing_nickname in users.items():
                if existing_nickname == nickname:
                    self._send_json({'success': False, 'error': f'Имя "{nickname}" уже занято'})
                    return
            
            users[client_ip] = nickname
            with open(USERS_FILE, 'w') as f:
                json.dump(users, f)
            self._send_json({'success': True, 'nickname': nickname})
            
        elif self.path == '/api/send':
            try:
                with open(USERS_FILE, 'r') as f:
                    content = f.read().strip()
                    if not content:
                        users = {}
                    else:
                        users = json.loads(content)
            except (json.JSONDecodeError, IOError):
                users = {}
            
            if client_ip not in users:
                self._send_json({'success': False, 'error': 'Сначала зарегистрируйтесь'})
                return
            
            text = params.get('text', [''])[0].strip()
            if not text:
                self._send_json({'success': False, 'error': 'Сообщение пустое'})
                return
            if len(text) > 500:
                self._send_json({'success': False, 'error': 'Сообщение слишком длинное'})
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
                'nickname': users[client_ip],
                'text': text,
                'ip': client_ip
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

def run_server(PORT: int = 8000):
    print(f'Мессенджер запущен на http://localhost:{PORT}')
    print(f'Сохраняется максимум {SAVE_LIMIT} сообщений в messages.json')
    print(f'Показывается последние {DISPLAY_LIMIT} сообщений')
    print(f'Привязка IP -> имя в users.json')
    HTTPServer(('', 8000), MessengerHandler).serve_forever()

if __name__ == '__main__':
    run_server()