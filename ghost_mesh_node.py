import hashlib
import json
import time
import sqlite3
import base64
import random
import socket
import threading
import sys
import logging
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for
from uuid import uuid4
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

# --- LOGLAMA AYARLARI (Hata tespiti için) ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GhostNode")

# --- GÜVENLİ IMPORTLAR ---
# Cryptography ve Bluetooth yoksa sistemin çökmesini engelle
try:
    from cryptography.hazmat.primitives.asymmetric import rsa, padding
    from cryptography.hazmat.primitives import serialization, hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    logger.warning("UYARI: 'cryptography' kütüphanesi eksik. İmzalama çalışmayacak.")

try:
    import bluetooth
    BLUETOOTH_AVAILABLE = True
except ImportError:
    BLUETOOTH_AVAILABLE = False
    logger.warning("UYARI: 'pybluez' eksik. Bluetooth Mesh devre dışı.")

# --- YAPILANDIRMA ---
MAX_SUPPLY = 100_000_000
STORAGE_COST_PER_MB_MONTHLY = 0.001
GRACE_PERIOD_SECONDS = 86400
DB_FILE = "ghost_v5.db"
MESH_PORT = 9999
GHOST_PORT = 5000
GHOST_BEACON_MSG = b"GHOST_PROTOCOL_NODE_HERE"
BLUETOOTH_UUID = "00001101-0000-1000-8000-00805F9B34FB"

app = Flask(__name__)
app.secret_key = "super_secret_mesh_key"

# --- IP TESPİTİ ---
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return '127.0.0.1'

GHOST_HOST_IP = get_local_ip()

# --- VERİTABANI YÖNETİCİSİ (Düzeltildi: Timeout Eklendi) ---
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        # timeout=10 ekleyerek "Database is locked" hatalarını engelliyoruz
        conn = sqlite3.connect(self.db_file, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, name TEXT, surname TEXT, phone TEXT, email TEXT, is_verified INTEGER DEFAULT 0, verification_code TEXT, wallet_private_key TEXT, wallet_public_key TEXT UNIQUE, balance REAL DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (block_index INTEGER PRIMARY KEY, timestamp REAL, proof INTEGER, previous_hash TEXT, block_hash TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, last_payment_time REAL, status TEXT DEFAULT 'active')''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS mesh_peers (ip_address TEXT PRIMARY KEY, last_seen REAL, method TEXT)''')
        conn.commit()
        conn.close()

# --- MANAGER SINIFLARI ---
class MeshManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.running = True

    def start(self):
        threading.Thread(target=self.listen_udp_broadcast, daemon=True).start()
        threading.Thread(target=self.broadcast_presence, daemon=True).start()
        if BLUETOOTH_AVAILABLE:
            threading.Thread(target=self.start_bluetooth_server, daemon=True).start()

    def register_peer(self, ip, method="WIFI"):
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT OR REPLACE INTO mesh_peers (ip_address, last_seen, method) VALUES (?, ?, ?)", 
                         (ip, time.time(), method))
            conn.commit()
        except Exception as e:
            logger.error(f"Peer Kayıt Hatası: {e}")
        finally:
            conn.close()

    def broadcast_presence(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while self.running:
            try:
                msg = f"{GHOST_BEACON_MSG.decode()}|{GHOST_PORT}|{GHOST_HOST_IP}".encode()
                sock.sendto(msg, ('<broadcast>', MESH_PORT))
                time.sleep(5)
            except Exception:
                time.sleep(10)

    def listen_udp_broadcast(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('', MESH_PORT))
        except Exception as e:
            logger.error(f"UDP Portu ({MESH_PORT}) bağlanamadı: {e}")
            return

        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                decoded = data.decode().split('|')
                if decoded[0] == GHOST_BEACON_MSG.decode() and len(decoded) == 3:
                    peer_ip = decoded[2]
                    peer_port = decoded[1]
                    if peer_ip != GHOST_HOST_IP:
                        self.register_peer(f"http://{peer_ip}:{peer_port}", "WIFI")
            except Exception:
                pass

    def start_bluetooth_server(self):
        try:
            server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            server_sock.bind(("", bluetooth.PORT_ANY))
            server_sock.listen(1)
            port = server_sock.getsockname()[1]
            bluetooth.advertise_service(server_sock, "GhostProtocolMesh", service_id=BLUETOOTH_UUID,
                                        service_classes=[BLUETOOTH_UUID, bluetooth.SERIAL_PORT_CLASS],
                                        profiles=[bluetooth.SERIAL_PORT_PROFILE])
            logger.info(f"Bluetooth dinleniyor: Kanal {port}")
            while self.running:
                client_sock, client_info = server_sock.accept()
                client_sock.close() 
        except Exception as e:
            logger.error(f"Bluetooth Error: {e}")

class UserManager:
    def __init__(self, db):
        self.db = db

    def register(self, username, password, name, surname, phone, email):
        if not CRYPTO_AVAILABLE:
            return False, "Kripto kütüphanesi eksik."
            
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem_priv = private_key.private_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8, encryption_algorithm=serialization.NoEncryption()).decode('utf-8')
        pem_pub = private_key.public_key().public_bytes(encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo).decode('utf-8')
        verification_code = str(random.randint(100000, 999999))
        
        conn = self.db.get_connection()
        try:
            conn.execute('INSERT INTO users (username, password, name, surname, phone, email, verification_code, wallet_private_key, wallet_public_key, balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 50)', 
                         (username, password, name, surname, phone, email, verification_code, pem_priv, pem_pub))
            conn.commit()
            print(f"--- DOĞRULAMA KODU: {verification_code} ---")
            return True, "Başarılı"
        except sqlite3.IntegrityError:
            return False, "Kullanıcı adı dolu"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def verify_user(self, username, code):
        conn = self.db.get_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and user['verification_code'] == code:
            conn = self.db.get_connection()
            conn.execute("UPDATE users SET is_verified = 1 WHERE username = ?", (username,))
            conn.commit()
            conn.close()
            return True
        return False

class StorageBlockchain:
    def __init__(self, db_manager):
        self.db = db_manager

    def upload_asset(self, user_pub_key, asset_type, name, content_data):
        conn = self.db.get_connection()
        try:
            size = len(content_data)
            cost = (size / (1024 * 1024)) * STORAGE_COST_PER_MB_MONTHLY
            
            cursor = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (user_pub_key,))
            row = cursor.fetchone()
            if not row or row[0] < cost:
                return False, "Yetersiz Bakiye"

            conn.execute("UPDATE users SET balance = balance - ? WHERE wallet_public_key = ?", (cost, user_pub_key))
            conn.execute('INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, last_payment_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)', 
                         (str(uuid4()), user_pub_key, asset_type, name, content_data, size, time.time(), time.time()))
            conn.commit()
            return True, "Başarılı"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
            
    def clone_asset(self, asset_id, new_owner_key):
        conn = self.db.get_connection()
        try:
            original = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
            if not original: return False, "Bulunamadı"
        finally:
            conn.close()
            
        return self.upload_asset(new_owner_key, original['type'], "Copy_" + original['name'], original['content'])

# --- BAŞLATMA ---
db = DatabaseManager(DB_FILE)
user_mgr = UserManager(db)
chain = StorageBlockchain(db)
mesh = MeshManager(db)

# --- WEB ARAYÜZÜ (Hata Önleyici Context Processor) ---
# Bu kısım 500 hatalarının çoğunu çözer. Her template render işleminde
# 'internet' ve 'peers' değişkenlerini otomatik olarak sayfaya gönderir.
@app.context_processor
def inject_common_variables():
    conn = db.get_connection()
    peers = conn.execute("SELECT * FROM mesh_peers WHERE last_seen > ?", (time.time() - 300,)).fetchall()
    conn.close()
    
    internet_status = False
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=0.5)
        internet_status = True
    except OSError:
        pass
        
    return dict(internet=internet_status, peers=peers)

LAYOUT = """
<!doctype html>
<html lang="tr">
<head>
    <title>GhostProtocol Node</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #222; color: #eee; padding: 20px; }
        .card { background: #333; padding: 15px; margin-bottom: 15px; border: 1px solid #444; border-radius: 5px; }
        a { color: #4dabf7; }
        input, button, select { width: 100%; padding: 10px; margin: 5px 0; }
        .online { color: #28a745; font-weight:bold; } .offline { color: #dc3545; font-weight:bold; }
    </style>
</head>
<body>
    <h1>👻 GhostProtocol ({{ request.host }})</h1>
    <div class="card">
        <p>Internet: <span class="{{ 'online' if internet else 'offline' }}">{{ 'ONLINE' if internet else 'OFFLINE' }}</span> | Peers: {{ peers|length }}</p>
        {% if session.get('username') %}
            User: <b>{{ session['username'] }}</b> | Balance: {{ session.get('balance', 0)|round(4) }}
            <br><a href="/dashboard">Dashboard</a> | <a href="/logout">Logout</a>
        {% else %}
            <a href="/login">Login</a> | <a href="/register">Register</a>
        {% endif %}
    </div>
    <div class="card">{% block content %}{% endblock %}</div>
</body>
</html>
"""

@app.route('/')
def home():
    try:
        conn = db.get_connection()
        assets = conn.execute("SELECT * FROM assets WHERE status = 'active' ORDER BY creation_time DESC LIMIT 10").fetchall()
        conn.close()
        return render_template_string(LAYOUT + """
        {% block content %}
            <h3>Son İçerikler</h3>
            {% for asset in assets %}
                <div style="border-bottom:1px solid #555; padding:5px;">
                    <b>{{ asset['name'] }}</b> ({{ asset['type'] }})
                    {% if session.get('username') %}
                        <form action="/clone_asset" method="post" style="display:inline;">
                            <input type="hidden" name="asset_id" value="{{ asset['asset_id'] }}">
                            <button type="submit" style="width:auto; padding:5px;">Kopyala</button>
                        </form>
                    {% endif %}
                </div>
            {% endfor %}
        {% endblock %}
        """, assets=assets)
    except Exception as e:
        return f"<h3>Sunucu Hatası (Home): {e}</h3>"

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        success, msg = user_mgr.register(request.form['username'], request.form['password'], request.form['name'], request.form['surname'], request.form['phone'], request.form['email'])
        if success:
            session['temp_username'] = request.form['username']
            return redirect(url_for('verify'))
        return f"Hata: {msg}"
    return render_template_string(LAYOUT + "{% block content %}<h3>Kayıt Ol</h3><form method='post'><input name='username' placeholder='Kullanıcı Adı'><input name='password' type='password' placeholder='Şifre'><input name='name' placeholder='Ad'><input name='surname' placeholder='Soyad'><input name='phone' placeholder='Tel'><input name='email' placeholder='Email'><button>Kaydol</button></form>{% endblock %}")

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if request.method == 'POST':
        if user_mgr.verify_user(session.get('temp_username', ''), request.form['code']):
            return redirect(url_for('login'))
        return "Hatalı Kod"
    return render_template_string(LAYOUT + "{% block content %}<h3>Doğrulama</h3><p>Terminaldeki kodu girin</p><form method='post'><input name='code' placeholder='Kod'><button>Doğrula</button></form>{% endblock %}")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = db.get_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (request.form['username'], request.form['password'])).fetchone()
        conn.close()
        if user:
            if user['is_verified'] == 0:
                session['temp_username'] = user['username']
                return redirect(url_for('verify'))
            session['username'] = user['username']
            session['pub_key'] = user['wallet_public_key']
            session['balance'] = user['balance']
            return redirect(url_for('dashboard'))
        return "Giriş Başarısız"
    return render_template_string(LAYOUT + "{% block content %}<h3>Giriş</h3><form method='post'><input name='username' placeholder='Kullanıcı Adı'><input name='password' type='password' placeholder='Şifre'><button>Giriş</button></form>{% endblock %}")

@app.route('/dashboard')
def dashboard():
    if not session.get('username'): return redirect('/login')
    conn = db.get_connection()
    assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ?", (session['pub_key'],)).fetchall()
    conn.close()
    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Panelim</h3>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <select name="type"><option value="image">Resim</option><option value="video">Video</option></select>
            <button>Yükle</button>
        </form>
        <h4>Dosyalarım</h4>
        <ul>{% for a in assets %}<li>{{ a['name'] }}</li>{% endfor %}</ul>
    {% endblock %}
    """, assets=assets)

@app.route('/upload', methods=['POST'])
def upload():
    if not session.get('username'): return redirect('/login')
    file = request.files['file']
    if file:
        data = base64.b64encode(file.read()).decode('utf-8')
        mime = "image/png" if request.form['type'] == 'image' else "video/mp4"
        content = f"data:{mime};base64,{data}"
        chain.upload_asset(session['pub_key'], request.form['type'], secure_filename(file.filename), content)
    return redirect(url_for('dashboard'))

@app.route('/clone_asset', methods=['POST'])
def clone_asset():
    if not session.get('username'): return redirect('/login')
    chain.clone_asset(request.form['asset_id'], session['pub_key'])
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    print("--- GHOST NODE BAŞLATILIYOR (SAFE MODE) ---")
    mesh.start()
    print(f"Erişim: http://{GHOST_HOST_IP}:{GHOST_PORT}")
    # debug=True hatanın tarayıcıda görünmesini sağlar
    app.run(host='0.0.0.0', port=GHOST_PORT, debug=True, use_reloader=False)