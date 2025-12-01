import hashlib
import json
import time
import sqlite3
import base64
import random
import socket
import threading
import sys
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for
from uuid import uuid4
from urllib.parse import urlparse
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from werkzeug.utils import secure_filename

# --- YAPILANDIRMA / CONFIGURATION ---
MAX_SUPPLY = 100_000_000
STORAGE_COST_PER_MB_MONTHLY = 0.001
GRACE_PERIOD_SECONDS = 86400  # 24 Saat / 24 Hours
DB_FILE = "ghost_v5.db"

# Mesh Ayarları / Mesh Settings
MESH_PORT = 9999        # UDP Broadcast Portu / UDP Broadcast Port
GHOST_PORT = 5000       # HTTP API Portu / HTTP API Port
GHOST_BEACON_MSG = b"GHOST_PROTOCOL_NODE_HERE"
BLUETOOTH_UUID = "00001101-0000-1000-8000-00805F9B34FB" # GhostProtocol Özel ID / GhostProtocol Custom ID

app = Flask(__name__)
app.secret_key = "mesh_secret_key" # Session yönetimi için / For session management

# --- VERİTABANI YÖNETİCİSİ / DATABASE MANAGER ---
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        # Flask multi-thread çalıştığı için her işlemde yeni bağlantı açılır
        # New connection is opened for each operation since Flask is multi-threaded
        conn = sqlite3.connect(self.db_file, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 1. KULLANICILAR (KYC/Kimlik) / USERS (KYC/Identity)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                name TEXT,
                surname TEXT,
                phone TEXT,
                email TEXT,
                is_verified INTEGER DEFAULT 0,
                verification_code TEXT,
                wallet_private_key TEXT,
                wallet_public_key TEXT UNIQUE,
                balance REAL DEFAULT 0
            )
        ''')

        # 2. BLOKLAR / BLOCKS
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blocks (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                proof INTEGER,
                previous_hash TEXT,
                block_hash TEXT
            )
        ''')

        # 3. İÇERİK VE DOMAIN (Varlıklar) / CONTENT AND DOMAIN (Assets)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                owner_pub_key TEXT,
                type TEXT,  -- 'domain', 'image', 'video', 'audio'
                name TEXT,
                content BLOB, -- Verinin kendisi / The data itself
                storage_size INTEGER,
                creation_time REAL,
                last_payment_time REAL,
                status TEXT DEFAULT 'active'
            )
        ''')

        # 4. MESH PEERS (Keşfedilen Cihazlar) / MESH PEERS (Discovered Devices)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mesh_peers (
                ip_address TEXT PRIMARY KEY,
                last_seen REAL,
                method TEXT -- 'WIFI' or 'BLUETOOTH'
            )
        ''')

        conn.commit()
        conn.close()

# --- MESH AĞ YÖNETİCİSİ / MESH NETWORK MANAGER ---
class MeshManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.running = True
        self.peers = {} 

    def start(self):
        # 1. Wi-Fi UDP Broadcast Dinleyici / Wi-Fi UDP Broadcast Listener
        threading.Thread(target=self.listen_udp_broadcast, daemon=True).start()
        # 2. Wi-Fi UDP Broadcast Yayıncı / Wi-Fi UDP Broadcast Publisher
        threading.Thread(target=self.broadcast_presence, daemon=True).start()
        # 3. Bluetooth Sunucu (Opsiyonel) / Bluetooth Server (Optional)
        threading.Thread(target=self.start_bluetooth_server, daemon=True).start()

    def register_peer(self, ip, method="WIFI"):
        """ Yeni bir cihaz bulunduğunda veritabanına kaydeder / Saves to database when a new device is found """
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT OR REPLACE INTO mesh_peers (ip_address, last_seen, method) VALUES (?, ?, ?)", 
                         (ip, time.time(), method))
            conn.commit()
            print(f"[{method}] Yeni Peer Bulundu / New Peer Found: {ip}")
        except Exception as e:
            print(e)
        finally:
            conn.close()

    # --- WI-FI (UDP BROADCAST) KATMANI / LAYER ---
    def broadcast_presence(self):
        """ Her 5 saniyede bir ağa 'Ben Buradayım' diye bağırır / Shouts 'I am here' to the network every 5 seconds """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        while self.running:
            try:
                # Mesaj: PROTOKOL_ADI | PORT / Message: PROTOCOL_NAME | PORT
                msg = f"{GHOST_BEACON_MSG.decode()}|{GHOST_PORT}".encode()
                sock.sendto(msg, ('<broadcast>', MESH_PORT))
                time.sleep(5)
            except Exception as e:
                print(f"Broadcast Hatası / Broadcast Error: {e}")
                time.sleep(10)

    def listen_udp_broadcast(self):
        """ Ağdaki diğer bağıranları dinler / Listens for others shouting in the network """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('', MESH_PORT))
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                decoded = data.decode().split('|')
                if decoded[0] == GHOST_BEACON_MSG.decode():
                    # Kendi IP'miz değilse ekle / Add if not our own IP
                    peer_ip = addr[0]
                    peer_port = decoded[1]
                    # Basitlik için kendi IP kontrolünü atlıyoruz / Skipping self-IP check for simplicity
                    full_address = f"http://{peer_ip}:{peer_port}"
                    self.register_peer(full_address, "WIFI")
            except Exception as e:
                print(f"UDP Dinleme Hatası / UDP Listening Error: {e}")

    # --- BLUETOOTH KATMANI / LAYER ---
    def start_bluetooth_server(self):
        """ Bluetooth RFCOMM Sunucusu / Bluetooth RFCOMM Server """
        try:
            import bluetooth # pybluez
            server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
            server_sock.bind(("", bluetooth.PORT_ANY))
            server_sock.listen(1)
            
            port = server_sock.getsockname()[1]
            
            bluetooth.advertise_service(server_sock, "GhostProtocolMesh",
                                        service_id=BLUETOOTH_UUID,
                                        service_classes=[BLUETOOTH_UUID, bluetooth.SERIAL_PORT_CLASS],
                                        profiles=[bluetooth.SERIAL_PORT_PROFILE])
            
            print(f"[BLUETOOTH] Dinleniyor... Kanal: {port} / Listening... Channel: {port}")
            
            while self.running:
                client_sock, client_info = server_sock.accept()
                print(f"[BLUETOOTH] Bağlantı / Connection: {client_info}")
                threading.Thread(target=self.handle_bt_client, args=(client_sock,), daemon=True).start()
                
        except ImportError:
            print("[BLUETOOTH] PyBluez yüklü değil, devre dışı. / PyBluez not installed, disabled.")
        except Exception as e:
            print(f"[BLUETOOTH] Başlatılamadı / Could not start: {e}")

    def handle_bt_client(self, sock):
        """ Bluetooth üzerinden gelen veri transferi / Data transfer via Bluetooth """
        try:
            # Basit Handshake: Blok uzunluğunu gönder / Simple Handshake: Send block length
            conn = self.db.get_connection()
            count = conn.execute("SELECT count(*) FROM blocks").fetchone()[0]
            conn.close()
            
            msg = f"HELLO_GHOST_CHAIN_LENGTH:{count}"
            sock.send(msg)
            sock.close()
        except:
            pass

# --- KULLANICI YÖNETİCİSİ / USER MANAGER ---
class UserManager:
    def __init__(self, db):
        self.db = db

    def register(self, username, password, name, surname, phone, email):
        # Yeni RSA Anahtar Çifti / New RSA Key Pair
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem_priv = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        
        pem_pub = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        verification_code = str(random.randint(100000, 999999))
        
        conn = self.db.get_connection()
        try:
            # Başlangıç bakiyesi 50 Coin / Initial balance 50 Coins
            conn.execute('''
                INSERT INTO users (username, password, name, surname, phone, email, verification_code, wallet_private_key, wallet_public_key, balance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 50) 
            ''', (username, password, name, surname, phone, email, verification_code, pem_priv, pem_pub))
            conn.commit()
            print(f"--- SİMÜLASYON / SIMULATION SMS/EMAIL ---")
            print(f"User: {name}, Code: {verification_code}")
            print(f"-----------------------------------------")
            return True, "Kayıt başarılı / Registration successful."
        except sqlite3.IntegrityError:
            return False, "Kullanıcı adı zaten var / Username already exists."
        finally:
            conn.close()

    def verify_user(self, username, code):
        conn = self.db.get_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        
        if user and user['verification_code'] == code:
            conn.execute("UPDATE users SET is_verified = 1 WHERE username = ?", (username,))
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    def update_contact(self, username, phone, email):
        conn = self.db.get_connection()
        # Yeniden doğrulama gerektirir / Requires re-verification
        new_code = str(random.randint(100000, 999999))
        conn.execute("UPDATE users SET phone = ?, email = ?, is_verified = 0, verification_code = ? WHERE username = ?",
                     (phone, email, new_code, username))
        conn.commit()
        conn.close()
        print(f"--- UPDATE CODE: {new_code} ---")
        return True

# --- BLOK ZİNCİRİ VE DEPOLAMA / BLOCKCHAIN & STORAGE ---
class StorageBlockchain:
    def __init__(self, db_manager):
        self.db = db_manager

    def calculate_rent(self, size_bytes):
        """ 1 MB = 0.001 Ghost/Ay (Month) """
        size_mb = size_bytes / (1024 * 1024)
        monthly_cost = size_mb * STORAGE_COST_PER_MB_MONTHLY
        return monthly_cost

    def upload_asset(self, user_pub_key, asset_type, name, content_data):
        """ Veriyi kaydeder ve ücreti keser / Saves data and deducts fee """
        conn = self.db.get_connection()
        
        if isinstance(content_data, str):
            size = len(content_data.encode('utf-8'))
        else:
            size = len(content_data)

        cost = self.calculate_rent(size)
        
        # Bakiye Kontrolü / Balance Check
        cursor = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (user_pub_key,))
        balance = cursor.fetchone()[0]

        if balance < cost:
            conn.close()
            return False, "Yetersiz Bakiye / Insufficient Balance"

        conn.execute("UPDATE users SET balance = balance - ? WHERE wallet_public_key = ?", (cost, user_pub_key))
        
        asset_id = str(uuid4())
        conn.execute('''
            INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, last_payment_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (asset_id, user_pub_key, asset_type, name, content_data, size, time.time(), time.time()))
        
        conn.commit()
        conn.close()
        return True, asset_id

    def check_asset_status(self, asset_id):
        """ Kira kontrolü / Rent check """
        conn = self.db.get_connection()
        asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        
        if not asset: return "not_found"
        
        current_time = time.time()
        time_diff = current_time - asset['last_payment_time']
        month_seconds = 30 * 24 * 60 * 60
        
        if time_diff > month_seconds:
            # Ödeme zamanı / Payment time
            cost = self.calculate_rent(asset['storage_size'])
            user = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (asset['owner_pub_key'],)).fetchone()
            
            if user['balance'] >= cost:
                conn.execute("UPDATE users SET balance = balance - ? WHERE wallet_public_key = ?", (cost, asset['owner_pub_key']))
                conn.execute("UPDATE assets SET last_payment_time = ? WHERE asset_id = ?", (current_time, asset_id))
                conn.commit()
                return "active"
            else:
                # Grace Period Kontrolü / Grace Period Check
                grace_end = asset['last_payment_time'] + month_seconds + GRACE_PERIOD_SECONDS
                if current_time > grace_end:
                    conn.execute("UPDATE assets SET status = 'suspended' WHERE asset_id = ?", (asset_id,))
                    conn.commit()
                    return "suspended"
                else:
                    return "grace_period"
        
        return asset['status']

    def clone_asset(self, original_asset_id, new_owner_pub_key):
        """ İçerik Kopyalama / Content Cloning """
        conn = self.db.get_connection()
        original = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (original_asset_id,)).fetchone()
        
        if not original:
            return False, "Dosya bulunamadı / File not found"

        return self.upload_asset(
            user_pub_key=new_owner_pub_key,
            asset_type=original['type'],
            name="Copy_" + original['name'],
            content_data=original['content']
        )

# --- UYGULAMA BAŞLATMA / APP INITIALIZATION ---
db = DatabaseManager(DB_FILE)
user_mgr = UserManager(db)
chain = StorageBlockchain(db)
mesh = MeshManager(db)

# --- WEB ARAYÜZÜ / WEB INTERFACE ---
LAYOUT = """
<!doctype html>
<html lang="tr">
<head>
    <title>GhostProtocol Mesh Node</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #222; color: #eee; margin: 0; padding: 20px; }
        .card { background: #333; padding: 15px; margin-bottom: 15px; border-radius: 5px; border: 1px solid #444; }
        .status-badge { display:inline-block; padding: 5px 10px; border-radius: 10px; font-size: 0.8em; }
        .online { background: #28a745; color: white; }
        .offline { background: #dc3545; color: white; }
        a { color: #4dabf7; text-decoration: none; }
        input, button, select { width: 100%; padding: 10px; margin: 5px 0; box-sizing: border-box; }
        button { background: #007bff; color: white; border: none; cursor: pointer; }
    </style>
</head>
<body>
    <h1>👻 GhostProtocol Mesh</h1>
    
    <div class="card">
        <h3>🔗 Ağ Durumu / Network Status</h3>
        <p>İnternet: <span class="status-badge {{ 'online' if internet else 'offline' }}">{{ 'ONLINE' if internet else 'OFFLINE' }}</span></p>
        <p>Mesh Mode: <span class="status-badge online">ACTIVE (WiFi/BT)</span></p>
        <p>Peers: {{ peers|length }}</p>
        <ul>
            {% for peer in peers %}
                <li>📡 {{ peer['ip_address'] }} <small>({{ peer['method'] }})</small></li>
            {% endfor %}
        </ul>
        <a href="/sync_mesh" style="color:yellow;">[Sync Mesh]</a>
    </div>

    <div class="navbar">
        {% if session.get('username') %}
            <span>User: {{ session['username'] }} ({{ session['balance']|round(4) }} GHOST)</span>
            | <a href="/dashboard">Dashboard</a> | <a href="/logout">Logout</a>
        {% else %}
            <a href="/login">Login</a> | <a href="/register">Register</a>
        {% endif %}
    </div>

    <div class="card">
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

def check_internet():
    # Google DNS'e ping atarak interneti test et / Test internet by pinging Google DNS
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return True
    except OSError:
        return False

@app.route('/')
def home():
    conn = db.get_connection()
    peers = conn.execute("SELECT * FROM mesh_peers WHERE last_seen > ?", (time.time() - 300,)).fetchall()
    
    # Halka açık içerikler / Public assets
    public_assets = conn.execute("SELECT * FROM assets WHERE type != 'domain' AND status = 'active' ORDER BY creation_time DESC LIMIT 5").fetchall()
    conn.close()
    
    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Son İçerikler / Latest Content</h3>
        {% for asset in assets %}
            <div style="border-bottom:1px solid #555; padding:10px;">
                <strong>{{ asset['name'] }}</strong> ({{ asset['type'] }})
                <br>
                {% if asset['type'] == 'image' %}
                    <img src="{{ asset['content'] }}" style="max-width:100px;">
                {% endif %}
                {% if session.get('username') %}
                    <form action="/clone_asset" method="post">
                        <input type="hidden" name="asset_id" value="{{ asset['asset_id'] }}">
                        <button type="submit" style="background:#28a745; width:auto;">Copy/Clone</button>
                    </form>
                {% endif %}
            </div>
        {% endfor %}
    {% endblock %}
    """, internet=check_internet(), peers=peers, assets=public_assets)

@app.route('/sync_mesh')
def sync_mesh():
    """ Manuel olarak Mesh üzerindeki cihazlardan veri çeker / Manually pulls data from devices on Mesh """
    # Demo amaçlı basit senkronizasyon simülasyonu / Simple sync simulation for demo
    return redirect('/')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        success, msg = user_mgr.register(
            request.form['username'], request.form['password'],
            request.form['name'], request.form['surname'],
            request.form['phone'], request.form['email']
        )
        if success:
            session['temp_username'] = request.form['username']
            return redirect(url_for('verify'))
        return f"Error: {msg}"
    
    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Register</h3>
        <form method="post">
            <input type="text" name="name" placeholder="Name" required>
            <input type="text" name="surname" placeholder="Surname" required>
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <input type="tel" name="phone" placeholder="Phone" required>
            <input type="email" name="email" placeholder="Email" required>
            <button type="submit">Sign Up</button>
        </form>
    {% endblock %}
    """, internet=check_internet(), peers=[])

@app.route('/verify', methods=['GET', 'POST'])
def verify():
    if request.method == 'POST':
        username = session.get('temp_username') or request.form['username']
        if user_mgr.verify_user(username, request.form['code']):
            return redirect(url_for('login'))
        return "Invalid Code!"
        
    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Verification</h3>
        <p>Check terminal for code.</p>
        <form method="post">
            <input type="text" name="username" placeholder="Username" value="{{session.get('temp_username', '')}}">
            <input type="text" name="code" placeholder="6-Digit Code">
            <button type="submit">Verify</button>
        </form>
    {% endblock %}
    """, internet=check_internet(), peers=[])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = db.get_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", 
                            (request.form['username'], request.form['password'])).fetchone()
        conn.close()
        
        if user:
            if user['is_verified'] == 0:
                session['temp_username'] = user['username']
                return redirect(url_for('verify'))
            
            session['username'] = user['username']
            session['pub_key'] = user['wallet_public_key']
            session['balance'] = user['balance']
            return redirect(url_for('dashboard'))
        return "Login Failed."

    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Login</h3>
        <form method="post">
            <input type="text" name="username" placeholder="Username">
            <input type="password" name="password" placeholder="Password">
            <button type="submit">Login</button>
        </form>
    {% endblock %}
    """, internet=check_internet(), peers=[])

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('username'): return redirect('/login')
    
    conn = db.get_connection()
    assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ?", (session['pub_key'],)).fetchall()
    conn.close()

    return render_template_string(LAYOUT + """
    {% block content %}
        <h3>Dashboard</h3>
        <p><strong>Upload Asset (Cost: 0.001 GHOST/MB)</strong></p>
        <form action="/upload" method="post" enctype="multipart/form-data">
            <input type="file" name="file" required>
            <select name="type">
                <option value="image">Image</option>
                <option value="audio">Audio</option>
                <option value="video">Video</option>
            </select>
            <button type="submit">Upload</button>
        </form>
        
        <h4>My Assets</h4>
        <ul>
        {% for asset in assets %}
            <li>{{ asset['name'] }} ({{ asset['status'] }})</li>
        {% endfor %}
        </ul>
    {% endblock %}
    """, internet=check_internet(), peers=[], assets=assets)

@app.route('/upload', methods=['POST'])
def upload():
    if not session.get('username'): return redirect('/login')
    
    file = request.files['file']
    ftype = request.form['type']
    
    if file:
        file_data = file.read()
        b64_str = base64.b64encode(file_data).decode('utf-8')
        mime_type = "image/png"
        if ftype == 'video': mime_type = 'video/mp4'
        elif ftype == 'audio': mime_type = 'audio/mpeg'
        
        final_content = f"data:{mime_type};base64,{b64_str}"
        
        success, msg = chain.upload_asset(session['pub_key'], ftype, secure_filename(file.filename), final_content)
        
        if success:
            return redirect(url_for('dashboard'))
        else:
            return f"Error: {msg}"
    return "No file."

@app.route('/clone_asset', methods=['POST'])
def clone_asset():
    if not session.get('username'): return redirect('/login')
    success, msg = chain.clone_asset(request.form['asset_id'], session['pub_key'])
    return redirect(url_for('dashboard')) if success else f"Error: {msg}"

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    # 1. Mesh Ağını Başlat / Start Mesh Network
    print("--- GhostProtocol Mesh Node Starting ---")
    mesh.start()
    
    # 2. Web Sunucusunu Başlat / Start Web Server
    print(f"--- Web UI: http://0.0.0.0:{GHOST_PORT} ---")
    # use_reloader=False, thread çakışmasını önlemek için / to prevent thread conflict
    app.run(host='0.0.0.0', port=GHOST_PORT, debug=False, use_reloader=False)