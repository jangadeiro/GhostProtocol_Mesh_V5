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
import traceback
import os
import requests
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for, Response
from uuid import uuid4
from werkzeug.utils import secure_filename

# --- LOGLAMA / LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GhostMesh")

# --- YAPILANDIRMA / CONFIGURATION ---
CLOUD_SERVER_IP = "http://46.101.219.46:5000" # Sizin Cloud Sunucunuz / Your Cloud Server
MINING_DIFFICULTY = 4
DB_FILE = os.path.join(os.getcwd(), "ghost_mesh.db")
MESH_PORT = 9999
GHOST_PORT = 5001 # Local node portu
DOMAIN_EXPIRY_SECONDS = 15552000 # 6 Ay / 6 Months
STORAGE_COST_PER_MB = 0.001
GHOST_BEACON_MSG = b"GHOST_PROTOCOL_NODE_HERE"

app = Flask(__name__)
app.secret_key = "mesh_secret"

# --- VERİTABANI YÖNETİCİSİ / DATABASE MANAGER ---
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_file, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            # Kullanıcılar / Users
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, wallet_public_key TEXT UNIQUE, balance REAL DEFAULT 0)''')
            # Varlıklar (Süre ve Gizlilik eklendi) / Assets (Expiry and Privacy added)
            cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, is_public INTEGER DEFAULT 1)''')
            # Bloklar / Blocks
            cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (block_index INTEGER PRIMARY KEY, timestamp REAL, proof INTEGER, previous_hash TEXT, block_hash TEXT)''')
            # Mesh Ağındaki Cihazlar / Mesh Peers
            cursor.execute('''CREATE TABLE IF NOT EXISTS mesh_peers (ip_address TEXT PRIMARY KEY, last_seen REAL, method TEXT)''')
            
            if cursor.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
                self.create_genesis_block(cursor)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.critical(f"DB Init Error: {e}")

    def create_genesis_block(self, cursor):
        genesis_hash = hashlib.sha256(json.dumps({'index': 1}, sort_keys=True).encode()).hexdigest()
        cursor.execute("INSERT INTO blocks (block_index, timestamp, proof, previous_hash, block_hash) VALUES (?, ?, ?, ?, ?)",
                       (1, time.time(), 1, '0', genesis_hash))

# --- SENKRONİZASYON YÖNETİCİSİ / SYNC MANAGER ---
class SyncManager:
    def __init__(self, db_manager):
        self.db = db_manager
        self.running = True

    def start_background_sync(self):
        # Arka planda periyodik olarak senkronizasyon dener / Periodically attempts sync in background
        thread = threading.Thread(target=self._sync_loop, daemon=True)
        thread.start()

    def _sync_loop(self):
        while self.running:
            self.sync_with_cloud()
            self.sync_with_mesh()
            time.sleep(30) # 30 saniyede bir dene / Try every 30 seconds

    def sync_with_cloud(self):
        # Bulut sunucusu ile senkronizasyon / Sync with Cloud Server
        try:
            logger.info("Bulut Sunucuya bağlanılıyor... / Connecting to Cloud Server...")
            response = requests.get(f"{CLOUD_SERVER_IP}/chain", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self._update_local_chain(data)
        except Exception as e:
            logger.warning(f"Bulut bağlantısı yok (Offline Mod) / No Cloud connection: {e}")

    def sync_with_mesh(self):
        # Yerel ağdaki (Mesh) diğer cihazlardan veri çek / Pull data from peers in local mesh
        conn = self.db.get_connection()
        peers = conn.execute("SELECT ip_address FROM mesh_peers WHERE last_seen > ?", (time.time() - 300,)).fetchall()
        conn.close()
        
        for peer in peers:
            try:
                # Peer IP'sine HTTP isteği at (WiFi Mesh)
                response = requests.get(f"{peer['ip_address']}/chain", timeout=2)
                if response.status_code == 200:
                    self._update_local_chain(response.json())
            except:
                pass

    def _update_local_chain(self, remote_data):
        # En Uzun Zincir Kuralı / Longest Chain Rule
        conn = self.db.get_connection()
        local_len = conn.execute("SELECT MAX(block_index) FROM blocks").fetchone()[0] or 0
        
        if remote_data['length'] > local_len:
            logger.info(f"Yeni zincir bulundu. Yerel: {local_len}, Uzak: {remote_data['length']}. Güncelleniyor...")
            
            # Veritabanını güncelle / Update Database
            # NOT: Gerçek bir blockchain'de bu işlem çok daha karmaşıktır (hash doğrulama vb.)
            # Burada simülasyon amaçlı direkt değiştiriyoruz.
            conn.execute("DELETE FROM blocks")
            conn.execute("DELETE FROM assets") # Varlıkları da eşitle / Sync assets too
            
            for b in remote_data['chain']:
                conn.execute("INSERT INTO blocks (block_index, timestamp, proof, previous_hash, block_hash) VALUES (?, ?, ?, ?, ?)",
                             (b['block_index'], b['timestamp'], b['proof'], b['previous_hash'], b['block_hash']))
            
            for a in remote_data['assets']:
                content = base64.b64decode(a['content'])
                conn.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (a['asset_id'], a['owner_pub_key'], a['type'], a['name'], content, a['storage_size'], a['creation_time'], a['expiry_time'], a['is_public']))
            
            conn.commit()
        conn.close()

# --- MESH AĞI (UDP/BLUETOOTH) / MESH NETWORK ---
class MeshNetwork:
    def __init__(self, db_manager):
        self.db = db_manager
        
    def start_discovery(self):
        # UDP Broadcast Başlat / Start UDP Broadcast
        threading.Thread(target=self._broadcast_presence, daemon=True).start()
        threading.Thread(target=self._listen_broadcast, daemon=True).start()

    def _broadcast_presence(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while True:
            try:
                # Kendi IP'mizi bulmaya çalış / Try to find own IP
                local_ip = socket.gethostbyname(socket.gethostname())
                msg = f"{GHOST_BEACON_MSG.decode()}|{GHOST_PORT}|{local_ip}".encode()
                sock.sendto(msg, ('<broadcast>', MESH_PORT))
                time.sleep(5)
            except:
                time.sleep(10)

    def _listen_broadcast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', MESH_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                decoded = data.decode().split('|')
                if decoded[0] == GHOST_BEACON_MSG.decode() and len(decoded) == 3:
                    peer_ip = decoded[2]
                    peer_port = decoded[1]
                    # Kendimizi eklemeyelim / Don't add self
                    if "127.0.0.1" not in peer_ip: 
                        self._add_peer(f"http://{peer_ip}:{peer_port}")
            except:
                pass

    def _add_peer(self, address):
        conn = self.db.get_connection()
        conn.execute("INSERT OR REPLACE INTO mesh_peers (ip_address, last_seen, method) VALUES (?, ?, ?)",
                     (address, time.time(), "WIFI"))
        conn.commit()
        conn.close()

# --- VARLIK YÖNETİMİ & ÜCRETLENDİRME / ASSET MANAGEMENT & FEES ---
class AssetManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def register_asset(self, owner_key, asset_type, name, content_bytes):
        # Varlık oluşturur (6 Ay süreli) / Creates asset (6 Months validity)
        size = len(content_bytes)
        creation_time = time.time()
        expiry_time = creation_time + DOMAIN_EXPIRY_SECONDS
        
        conn = self.db.get_connection()
        # Eğer bu isimde bir domain varsa ve süresi dolmamışsa hata ver
        # If domain exists and not expired, raise error
        existing = conn.execute("SELECT expiry_time FROM assets WHERE name = ? AND type = 'domain'", (name,)).fetchone()
        if existing and existing['expiry_time'] > time.time():
            conn.close()
            return False, "Domain alınmış ve süresi dolmamış. / Domain taken and not expired."

        conn.execute("INSERT OR REPLACE INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, is_public) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid4()), owner_key, asset_type, name, content_bytes, size, creation_time, expiry_time, 1))
        conn.commit()
        conn.close()
        return True, "Başarılı / Success"

    def clone_asset(self, asset_id, new_owner_key):
        # İçeriği kopyalar (Forking) / Clones content (Forking)
        conn = self.db.get_connection()
        original = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        
        if not original:
            conn.close()
            return False, "Varlık bulunamadı. / Asset not found."
            
        # Orijinal içeriği al, yeni bir kayıt oluştur. Yeni sahibi 'new_owner_key' olur.
        # Böylece orijinal silinse bile bu kopya yaşar.
        # Get original content, create new record. New owner is 'new_owner_key'.
        # Copy survives even if original is deleted.
        
        new_name = original['name'] if original['type'] != 'domain' else f"copy_{original['name']}"
        new_expiry = time.time() + DOMAIN_EXPIRY_SECONDS
        
        conn.execute("INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, is_public) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (str(uuid4()), new_owner_key, original['type'], new_name, original['content'], original['storage_size'], time.time(), new_expiry, 1))
        conn.commit()
        conn.close()
        return True, "Klonlandı / Cloned"

    def delete_asset(self, asset_id, owner_key):
        # Varlığı siler (Ücret ödemeyi durdurur) / Deletes asset (Stops fee payment)
        conn = self.db.get_connection()
        conn.execute("DELETE FROM assets WHERE asset_id = ? AND owner_pub_key = ?", (asset_id, owner_key))
        conn.commit()
        conn.close()
        return True

# --- UYGULAMA BAŞLATMA / APP INIT ---
db = DatabaseManager(DB_FILE)
sync = SyncManager(db)
mesh = MeshNetwork(db)
assets_mgr = AssetManager(db)

# Arka plan servislerini başlat / Start background services
sync.start_background_sync()
mesh.start_discovery()

# --- WEB ROTALARI / WEB ROUTES ---

# Global Template Değişkenleri
@app.context_processor
def inject_globals():
    try:
        conn = db.get_connection()
        peers = conn.execute("SELECT * FROM mesh_peers").fetchall()
        conn.close()
        # Basit internet kontrolü
        socket.create_connection(("8.8.8.8", 53), timeout=0.1)
        internet = True
    except:
        internet = False
        peers = []
    return dict(internet=internet, peers=peers)

# LAYOUT ve HTML Şablonları (Jinja2 hatalarına karşı temiz string)
LAYOUT = """
<!doctype html>
<html>
<head>
    <title>Ghost Mesh Node</title>
    <style>
        body { font-family: sans-serif; background: #222; color: #eee; padding: 20px; }
        .card { background: #333; padding: 15px; margin-bottom: 10px; border-radius: 5px; border: 1px solid #444; }
        .success { color: #4caf50; } .fail { color: #f44336; }
        a { color: #2196f3; text-decoration: none; }
        input, button { padding: 8px; margin: 5px 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border-bottom: 1px solid #555; padding: 8px; text-align: left; }
    </style>
</head>
<body>
    <h2>👻 GhostProtocol Mesh Node</h2>
    <div class="card">
        Durum: <span class="{{ 'success' if internet else 'fail' }}">{{ 'ONLINE (Cloud Sync)' if internet else 'OFFLINE (Mesh Only)' }}</span>
        | Peers: {{ peers|length }}
        <br>
        {% if session.get('username') %}
            Kullanıcı: <b>{{ session['username'] }}</b> | <a href="/dashboard">Panel</a> | <a href="/logout">Çıkış</a>
        {% else %}
            <a href="/login">Giriş</a> | <a href="/register">Kayıt</a>
        {% endif %}
    </div>
    {% block content %}{% endblock %}
</body>
</html>
"""

@app.route('/')
def home():
    # Ana Sayfa ve Arama / Home and Search
    return render_template_string(LAYOUT + """
    {% block content %}
    <div class="card">
        <h3>🔍 Ghost Arama / Search</h3>
        <form action="/search" method="get">
            <input name="q" placeholder="Domain (.ghost) veya İçerik..." style="width: 70%;">
            <button>Ara</button>
        </form>
    </div>
    {% endblock %}
    """)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    results = []
    if query:
        conn = db.get_connection()
        # Sadece süresi dolmamış domainleri ve içerikleri getir / Get only non-expired domains and content
        # expiry_time kontrolü burada yapılıyor
        now = time.time()
        results = conn.execute("SELECT * FROM assets WHERE name LIKE ? AND expiry_time > ?", (f'%{query}%', now)).fetchall()
        conn.close()
    
    return render_template_string(LAYOUT + """
    {% block content %}
    <h3>Sonuçlar / Results: {{ query }}</h3>
    {% for r in results %}
        <div class="card">
            <b>{{ r['name'] }}</b> ({{ r['type'] }})
            <br>Boyut: {{ (r['storage_size']/1024)|round(1) }} KB
            <br><a href="/view/{{ r['asset_id'] }}" target="_blank">Görüntüle / View</a>
            {% if session.get('username') %}
            | <form action="/clone" method="post" style="display:inline"><input type="hidden" name="id" value="{{ r['asset_id'] }}"><button>Kopyala / Clone</button></form>
            {% endif %}
        </div>
    {% endfor %}
    {% endblock %}
    """, results=results, query=query)

@app.route('/view/<asset_id>')
def view_asset(asset_id):
    conn = db.get_connection()
    asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    conn.close()
    
    if not asset: return "Bulunamadı / Not Found", 404
    
    # Süre kontrolü (Süresi dolmuşsa görüntüleme) / Expiry check
    if asset['expiry_time'] < time.time() and asset['type'] == 'domain':
        return "<h1>Domain Süresi Doldu / Domain Expired</h1><p>Bu içerik artık yayında değil.</p>", 403

    content = asset['content'] # BLOB
    
    if asset['type'] == 'domain':
        return content.decode('utf-8')
    else:
        return Response(content, mimetype="application/octet-stream")

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('username'): return redirect('/login')
    
    msg = ""
    # POST İşlemleri (Domain Kayıt, Silme, vb.)
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register_domain':
            name = request.form['name']
            data = request.form['data']
            success, msg = assets_mgr.register_asset(session['pub_key'], 'domain', name, data.encode('utf-8'))
        elif action == 'delete_asset':
            assets_mgr.delete_asset(request.form['id'], session['pub_key'])
            msg = "Varlık silindi / Asset deleted"

    # Verileri Çek
    conn = db.get_connection()
    my_assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ?", (session['pub_key'],)).fetchall()
    conn.close()
    
    # Varlık Listesi HTML'ini oluştur (Jinja2 hatasını önlemek için string birleştirme)
    assets_html = ""
    now = time.time()
    
    for a in my_assets:
        days_left = int((a['expiry_time'] - now) / 86400)
        status = "AKTİF" if days_left > 0 else "SÜRESİ DOLDU (Özel)"
        fee = round(a['storage_size'] / 1024 / 1024 * STORAGE_COST_PER_MB, 6)
        
        assets_html += f"""
        <tr>
            <td>{a['name']}</td>
            <td>{a['type']}</td>
            <td>{days_left} Gün</td>
            <td>{fee} GHOST/Ay</td>
            <td>{status}</td>
            <td>
                <form method="post" style="display:inline">
                    <input type="hidden" name="action" value="delete_asset">
                    <input type="hidden" name="id" value="{a['asset_id']}">
                    <button style="background:#f44336; color:white">Sil</button>
                </form>
            </td>
        </tr>
        """

    return render_template_string(LAYOUT + f"""
    {{% block content %}}
    <p style="color:red">{msg}</p>
    
    <div class="card">
        <h3>Yeni Domain Tescil (.ghost) - 6 Ay</h3>
        <form method="post">
            <input type="hidden" name="action" value="register_domain">
            <input name="name" placeholder="site.ghost" required>
            <br>
            <textarea name="data" rows="5" style="width:100%" placeholder="HTML İçeriği..."></textarea>
            <br><button>Tescil Et ve Yayınla</button>
        </form>
    </div>

    <div class="card">
        <h3>Varlıklarım & Alan Adlarım</h3>
        <table>
            <tr>
                <th>Ad</th>
                <th>Tip</th>
                <th>Kalan Süre</th>
                <th>Ücret</th>
                <th>Durum</th>
                <th>İşlem</th>
            </tr>
            {assets_html}
        </table>
    </div>
    {{% endblock %}}
    """)

@app.route('/clone', methods=['POST'])
def clone():
    if not session.get('username'): return redirect('/login')
    assets_mgr.clone_asset(request.form['id'], session['pub_key'])
    return redirect('/dashboard')

# --- AUTH (Basitleştirilmiş) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        conn = db.get_connection()
        # Demo: Şifre kontrolü yapmadan varsa girer, yoksa oluşturur (Basitlik için)
        user = conn.execute("SELECT * FROM users WHERE username = ?", (request.form['username'],)).fetchone()
        if not user:
            pub_key = str(uuid4()) # Demo anahtar
            conn.execute("INSERT INTO users (username, wallet_public_key) VALUES (?, ?)", (request.form['username'], pub_key))
            conn.commit()
            user = {'username': request.form['username'], 'wallet_public_key': pub_key}
        conn.close()
        session['username'] = user['username']
        session['pub_key'] = user['wallet_public_key']
        return redirect('/dashboard')
    return render_template_string(LAYOUT + """{% block content %}<form method='post'>Kullanıcı Adı: <input name='username'><button>Giriş</button></form>{% endblock %}""")

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/chain', methods=['GET'])
def chain_export():
    # Diğer mesh node'lar bizden veri çekerken burayı kullanır
    return jsonify(json.loads('{"chain": [], "length": 0}')) # Demo placeholder

if __name__ == '__main__':
    print(f"--- GHOST MESH NODE ({GHOST_PORT}) ---")
    app.run(host='0.0.0.0', port=GHOST_PORT, debug=True, use_reloader=False)
