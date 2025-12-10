import hashlib
import json
import time
import sqlite3
import base64
import random
import re
import logging
import os
import requests 
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for, Response
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from datetime import timedelta, datetime
from markupsafe import Markup 
from jinja2 import DictLoader, Template 

# --- LOGLAMA / LOGGING ---
# TR: Bilgi ve hata mesajları için loglama yapılandırması.
# EN: Logging configuration for info and error messages.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - GhostServer - %(levelname)s - %(message)s')
logger = logging.getLogger("GhostCloud")

# --- YAPILANDIRMA / CONFIGURATION ---
# TR: Ağ zorluk seviyesi (Hash'te bulunması gereken 0 sayısı)
# EN: Network difficulty level (Number of leading zeros required in the hash)
MINING_DIFFICULTY = 4
# TR: Başarılı madencilik için blok ödülü
# EN: Block reward for successful mining
BLOCK_REWARD = 10
DB_FILE = os.path.join(os.getcwd(), "ghost_cloud_v2.db") 
GHOST_PORT = 5000
DOMAIN_EXPIRY_SECONDS = 15552000  # 6 Ay / 6 Months

# TR: Varlık Ücretleri (YENİ GÜNCELLEMELER)
# EN: Asset Fees (NEW UPDATES)
STORAGE_COST_PER_MB = 0.01       # TR: Veri barındırma ücreti: MB başı 0.01 GHOST
DOMAIN_REGISTRATION_FEE = 1.0    # TR: 6 Aylık Domain Tescil Ücreti: 1.0 GHOST

# TR: Ağdaki diğer düğümler (Peer) listesi.
# EN: List of other peers in the network.
KNOWN_PEERS = []

app = Flask(__name__)
# TR: Flask oturumları için gizli anahtar
# EN: Secret key for Flask sessions
app.secret_key = 'cloud_super_secret_permanency_fix_2024_03_12_FINAL' 
app.permanent_session_lifetime = timedelta(days=7) 
app.config['SESSION_COOKIE_SECURE'] = False 
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' 

# --- ÇOKLU DİL SÖZLÜĞÜ / MULTI-LANGUAGE DICTIONARY ---
LANGUAGES = {
    'tr': {
        'title': "GhostProtocol Sunucusu", 'status_online': "ONLINE", 'status_offline': "OFFLINE",
        'server_status': "Sunucu Durumu", 'active_peers': "Aktif Peer",
        'dashboard_title': "Panel", 'mining_title': "Madencilik", 'logout': "Çıkış", 'login': "Giriş", 'register': "Kayıt", 'search': "Arama",
        'wallet_title': "💳 Cüzdanım", 'pubkey': "Genel Anahtar", 'balance': "Bakiye",
        'domain_title': "💾 .ghost Kayıt (Ücret: 1.0 GHOST / 6 Ay)", 'media_title': "🖼️ Varlık Yükle", 'asset_action': "İşlem", 
        'status_success': "Başarılı", 'status_failed': "Başarısız", 'mine_last_block': "Son Blok", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Kopyalandı!",
        'media_info': "Desteklenen: .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Yayınla", 
        'search_title': "🔍 Ghost Arama (İçerik & Domain)", 'edit': "Düzenle", 'delete': "Sil",
        'login_prompt': "Giriş Yap", 'username': "Kullanıcı Adı", 'password': "Şifre", 'submit': "Gönder",
        'asset_fee': "Ücret", 'asset_expires': "Süre Sonu", 'mine_success': "Blok Başarılı", 
        'mine_message': "Yeni blok bulundu: {{ block_hash }}. Ödül: {{ reward }} GHOST hesabınıza eklendi."
    },
    'en': {
        'title': "GhostProtocol Server", 'status_online': "ONLINE", 'status_offline': "OFFLINE",
        'server_status': "Server Status", 'active_peers': "Active Peers",
        'dashboard_title': "Dashboard", 'mining_title': "Mining", 'logout': "Logout", 'login': "Login", 'register': "Register", 'search': "Search",
        'wallet_title': "💳 My Wallet", 'pubkey': "Public Key", 'balance': "Balance",
        'domain_title': "💾 .ghost Registration (Fee: 1.0 GHOST / 6 Months)", 'media_title': "🖼️ Upload Asset", 'asset_action': "Action", 
        'status_success': "Success", 'status_failed': "Failed", 'mine_last_block': "Last Block", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Copied!",
        'media_info': "Supported: .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Publish", 
        'search_title': "🔍 Ghost Search (Content & Domain)", 'edit': "Edit", 'delete': "Delete",
        'login_prompt': "Login", 'username': "Username", 'password': "Password", 'submit': "Submit",
        'asset_fee': "Fee", 'asset_expires': "Expires", 'mine_success': "Block Success",
        'mine_message': "New block found: {{ block_hash }}. Reward: {{ reward }} GHOST added to your account."
    },
    # Diğer diller kısaltıldı, gerektiğinde genişletilebilir.
}

# --- YARDIMCI FONKSİYONLAR / HELPERS ---
def extract_keywords(content_str):
    """
    TR: HTML etiketlerini temizler ve metinden anahtar kelimeleri ayıklar.
    EN: Cleans HTML tags and extracts keywords from the text.
    """
    try:
        text = re.sub(r'<(script|style).*?>.*?</\1>', '', content_str, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<.*?>', ' ', text)
        text = re.sub(r'[^a-zA-ZğüşıöçĞÜŞİÖÇ ]', ' ', text)
        words = text.lower().split()
        stop_words = {'ve', 'ile', 'the', 'and', 'for', 'this', 'bir', 'için', 'or', 'by'}
        keywords = set([w for w in words if len(w) > 2 and w not in stop_words])
        return ",".join(list(keywords)[:20])
    except:
        return ""

def calculate_asset_fee(size_bytes, asset_type):
    """
    TR: Varlık tipine göre doğru ücreti (GHOST cinsinden) hesaplar.
    EN: Calculates the correct fee (in GHOST) based on asset type.
    """
    if asset_type == 'domain':
        # TR: Domain tescilinde boyuttan bağımsız sabit ücret.
        # EN: Fixed fee for domain registration, regardless of size.
        return DOMAIN_REGISTRATION_FEE
    else:
        # TR: Diğer varlıklar için boyuta bağlı depolama ücreti (MB başına 0.01 GHOST).
        # EN: Size-dependent storage fee for other assets (0.01 GHOST per MB).
        return round((size_bytes / (1024 * 1024)) * STORAGE_COST_PER_MB, 4) # 4 ondalık hassasiyet

# --- VERİTABANI YÖNETİCİSİ / DATABASE MANAGER ---
class DatabaseManager:
    # TR: SQLite veritabanı işlemlerini yönetir. (Kod bu kısımda değişmedi)
    # EN: Manages SQLite database operations. (Code unchanged in this section)
    def __init__(self, db_file):
        self.db_file = db_file
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_file, check_same_thread=False, timeout=20) 
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, name TEXT, surname TEXT, wallet_public_key TEXT UNIQUE, balance REAL DEFAULT 50)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (block_index INTEGER PRIMARY KEY, timestamp REAL, previous_hash TEXT, block_hash TEXT, proof INTEGER, miner_key TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, keywords TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT, amount REAL, timestamp REAL, block_index INTEGER DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS mesh_peers (ip_address TEXT PRIMARY KEY, last_seen REAL)''')
        
        for table, column in [('assets', 'keywords'), ('blocks', 'miner_key'), ('assets', 'is_public')]:
            try:
                cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError:
                default = 'TEXT' if column == 'keywords' else 'INTEGER DEFAULT 1' if column == 'is_public' else 'TEXT'
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {default}")
                logger.warning(f"DB Update: '{column}' column added to {table} table.")
        
        if cursor.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
            self.create_genesis_block(cursor)
        conn.commit()
        conn.close()

    def create_genesis_block(self, cursor):
        genesis_hash = hashlib.sha256(b'GhostGenesis').hexdigest()
        cursor.execute("INSERT INTO blocks (block_index, timestamp, proof, previous_hash, block_hash, miner_key) VALUES (?, ?, ?, ?, ?, ?)",
                       (1, time.time(), 1, '0', genesis_hash, 'GhostProtocol_System'))

# --- ASSET MANAGER ---
class AssetManager:
    # TR: Varlık Kaydı ve Silme işlemlerini yönetir.
    # EN: Manages Asset Registration and Deletion.
    def __init__(self, db_manager):
        self.db = db_manager
        
    def register_asset(self, owner_key, asset_type, name, content, is_file=False):
        # TR: Yeni bir varlık kaydeder ve kullanıcı bakiyesinden ücret keser.
        # EN: Registers a new asset and deducts fee from user balance.
        keywords = ""
        if is_file:
            content.seek(0)
            content_bytes = content.read()
        else:
            content_bytes = content.encode('utf-8')
            if asset_type == 'domain':
                keywords = extract_keywords(content)
            
        size = len(content_bytes)
        # TR: Ücreti yeni fonksiyondan al
        # EN: Get the fee from the new function
        fee = calculate_asset_fee(size, asset_type)

        conn = self.db.get_connection()
        user_balance = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (owner_key,)).fetchone()['balance']
        
        if user_balance < fee:
             conn.close()
             return False, "Yetersiz bakiye. Tescil/Barındırma ücreti: {} GHOST".format(fee)
             
        try:
            conn.execute("INSERT OR REPLACE INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (str(uuid4()), owner_key, asset_type, name, content_bytes, size, time.time(), time.time() + DOMAIN_EXPIRY_SECONDS, keywords))
            # TR: Ücreti bakiyeden kes
            # EN: Deduct the fee from balance
            conn.execute("UPDATE users SET balance = balance - ? WHERE wallet_public_key = ?", (fee, owner_key))
            conn.commit()
            return True, f"Registered Successfully. Fee paid: {fee} GHOST"
        except Exception as e:
            logger.error(f"Asset registration failed: {e}")
            return False, str(e)

    def delete_asset(self, asset_id, owner_key):
        # TR: Varlığı siler ve kullanıcıya geri bildirimde bulunur. (Kod bu kısımda değişmedi)
        # EN: Deletes the asset and notifies the user. (Code unchanged in this section)
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM assets WHERE asset_id = ? AND owner_pub_key = ?", (asset_id, owner_key))
            conn.commit()
            if result.rowcount > 0:
                return True, "Asset deleted successfully."
            else:
                return False, "Asset not found or unauthorized."
        except Exception as e:
            logger.error(f"Asset deletion failed: {e}")
            return False, str(e)

# --- BLOK ZİNCİRİ YÖNETİCİSİ / BLOCKCHAIN MANAGER ---
# (Kod bu kısımda değişmedi)
class BlockchainManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_last_block(self):
        conn = self.db.get_connection()
        block = conn.execute("SELECT * FROM blocks ORDER BY block_index DESC LIMIT 1").fetchone()
        conn.close()
        return block

    def hash_block(self, index, timestamp, data, previous_hash, proof, miner_key):
        block_string = json.dumps({'index': index, 'timestamp': timestamp, 'data': data, 'previous_hash': previous_hash, 'proof': proof, 'miner': miner_key}, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def proof_of_work(self, last_proof):
        proof = 0
        while self.is_valid_proof(last_proof, proof) is False:
            proof += 1
        return proof

    def is_valid_proof(self, last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:MINING_DIFFICULTY] == '0' * MINING_DIFFICULTY

    def add_block(self, proof, previous_hash, miner_key):
        last_block = self.get_last_block()
        index = last_block['block_index'] + 1
        timestamp = time.time()
        data = [] 
        new_hash = self.hash_block(index, timestamp, data, previous_hash, proof, miner_key)
        
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT INTO blocks (block_index, timestamp, previous_hash, block_hash, proof, miner_key) VALUES (?, ?, ?, ?, ?, ?)",
                         (index, timestamp, previous_hash, new_hash, proof, miner_key))
            conn.execute("UPDATE users SET balance = balance + ? WHERE wallet_public_key = ?", (BLOCK_REWARD, miner_key))
            conn.commit()
            logger.info(f"Block {index} mined successfully by {miner_key}. Reward: {BLOCK_REWARD}")
            return new_hash
        except Exception as e:
            logger.error(f"Failed to add block: {e}")
            conn.close()
            return None

# --- MESH AĞI YÖNETİCİSİ / MESH NETWORK MANAGER ---
# (Kod bu kısımda değişmedi)
class MeshManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def register_peer(self, ip_address):
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT OR REPLACE INTO mesh_peers (ip_address, last_seen) VALUES (?, ?)",
                         (ip_address, time.time()))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Peer registration failed: {e}")
            conn.close()
            return False

    def get_active_peers(self, timeout_seconds=120):
        conn = self.db.get_connection()
        cutoff_time = time.time() - timeout_seconds
        count = conn.execute("SELECT COUNT(*) FROM mesh_peers WHERE last_seen > ?", (cutoff_time,)).fetchone()[0]
        conn.close()
        return count


# --- UYGULAMA BAŞLATMA / APP START ---
db = DatabaseManager(DB_FILE)
assets_mgr = AssetManager(db)
blockchain_mgr = BlockchainManager(db)
mesh_mgr = MeshManager(db)

# --- LAYOUT & UI (Ana Şablon) ---
LAYOUT = """
<!doctype html>
<html>
<head>
    <title>{{ lang['title'] }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #1a1a1a; color: #ddd; padding: 20px; }
        .card { background: #2a2a2a; padding: 15px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #333; }
        a { color: #00aaff; text-decoration: none; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { border: 1px solid #444; padding: 10px; text-align: left; font-size: 0.9em; }
        .action-button { background: #4caf50; color: #fff; border: none; padding: 10px; cursor: pointer; border-radius: 4px; }
        .delete-button { background: #f44336; color: #fff; border: none; padding: 8px; cursor: pointer; border-radius: 4px; font-size: 0.8em; }
        .hidden-textarea { position: fixed; top: -9999px; left: -9999px; }
        .search-form { display: flex; margin-bottom: 15px; }
        .search-form input[type="text"] { flex-grow: 1; padding: 10px; border: 1px solid #444; background: #333; color: #eee; border-radius: 4px 0 0 4px; }
        .search-form button { padding: 10px 15px; background: #555; color: white; border: none; border-radius: 0 4px 4px 0; cursor: pointer; }
        .login-form input { width: 95%; padding: 10px; margin: 5px 0; border: 1px solid #444; background: #333; color: #eee; border-radius: 4px; }
        .login-form button { width: 100%; }
        .success { color: #4caf50; }
        .error { color: #f44336; }
    </style>
    <script>
        function copyLink(link, btn) {
            let area = document.createElement("textarea");
            area.value = link; area.classList.add("hidden-textarea");
            document.body.appendChild(area);
            area.select(); document.execCommand('copy');
            document.body.removeChild(area);
            btn.innerText = "{{ lang['media_link_copy'] }}";
            setTimeout(() => { btn.innerText = "[Link]"; }, 1500);
            return false;
        }
    </script>
</head>
<body>
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <h2>👻 GhostProtocol</h2>
        <div class="lang">
            <a href="{{ url_for('set_lang', lang='tr') }}">TR🇹🇷</a> | 
            <a href="{{ url_for('set_lang', lang='en') }}">EN🇬🇧</a> | 
            <a href="{{ url_for('set_lang', lang='ru') }}">RU🇷🇺</a> | 
            <a href="{{ url_for('set_lang', lang='hy') }}">HY🇦🇲</a>
        </div>
    </div>
    
    {# TR: Arama Formu #}
    {# EN: Search Form #}
    <form class="search-form" action="{{ url_for('search_engine') }}" method="GET">
        <input type="text" name="q" placeholder="{{ lang['search_title'] }}..." required>
        <button type="submit">{{ lang['search'] }}</button>
    </form>
    
    <div class="card">
        {# TR: Sunucu ve Peer Durumu Bilgisi #}
        {# EN: Server and Peer Status Information #}
        📡 {{ lang['server_status'] }}: <span style="color:#4caf50;">{{ lang['status_online'] }}</span> | 
        🔗 {{ lang['active_peers'] }}: {{ active_peers_count }}
        <hr style="border-top: 1px solid #333; margin: 10px 0;">
        
        {% if session.get('username') %}
            👤 {{ session['username'] }} | 💰 {{ session.get('balance', 0)|round(4) }} GHOST
            <br>
            <a href="{{ url_for('dashboard') }}">{{ lang['dashboard_title'] }}</a> | 
            <a href="{{ url_for('mine') }}">{{ lang['mining_title'] }}</a> | 
            <a href="{{ url_for('logout') }}">{{ lang['logout'] }}</a>
        {% else %}
            <a href="{{ url_for('login') }}">{{ lang['login'] }}</a> | <a href="{{ url_for('register') }}">{{ lang['register'] }}</a>
        {% endif %}
    </div>
    {% if message %}<div class="card success">{{ message }}</div>{% endif %}
    {% if error %}<div class="card error">{{ error }}</div>{% endif %}
    {% block content %}{% endblock %}
</body>
</html>
"""

# --- DASHBOARD HTML ŞABLONU ---
DASHBOARD_UI = """
{% extends 'base.html' %}
{% block content %}
    <div class="card">
        {# TR: Başlık güncellendi #}
        {# EN: Title updated #}
        <h3>{{ lang['domain_title'] }}</h3>
        <form method="POST" action="{{ url_for('dashboard') }}">
            <input type="hidden" name="action" value="register_domain">
            <input type="text" name="name" placeholder="alanadi.ghost" required><br>
            <textarea name="data" placeholder="HTML İçeriği" style="width:98%; height:200px; margin-top:10px;" required></textarea><br>
            <button class="action-button" type="submit">{{ lang['register_btn'] }}</button>
        </form>
    </div>
    <div class="card">
        <h3>{{ lang['media_title'] }} (Barındırma Ücreti: {{ STORAGE_COST_PER_MB }} GHOST / MB)</h3>
        <p>{{ lang['media_info'] }}</p>
        <form method="POST" action="{{ url_for('dashboard') }}" enctype="multipart/form-data">
            <input type="hidden" name="action" value="upload_media">
            <input type="file" name="file" required><br>
            <button class="action-button" type="submit" style="margin-top:10px;">{{ lang['media_title'] }}</button>
        </form>
    </div>
    <div class="card">
        <h3>{{ lang['media_title'] }} ({{ assets|length }})</h3>
        <table>
            <tr>
                <th>{{ lang['asset_name'] }}</th>
                <th>{{ lang['asset_type'] }}</th>
                <th>{{ lang['asset_fee'] }}</th>
                <th>{{ lang['asset_expires'] }}</th>
                <th>{{ lang['asset_action'] }}</th>
                <th></th>
            </tr>
            {% for a in assets %}
            {% set asset_fee_calculated = calculate_asset_fee(a.storage_size, a.type)|round(4) %}
            {% set asset_relative_link = url_for('view_asset', asset_id=a.asset_id) %}
            {% set asset_external_link = url_for('view_asset', asset_id=a.asset_id, _external=True) %}
            <tr>
                <td>{{ a.name }} <br><span style="font-size: 0.7em;">ID: {{ a.asset_id[:8] }}...</span></td>
                <td>{{ a.type | upper }}</td>
                {# TR: Ücret gösterimi güncellendi #}
                {# EN: Fee display updated #}
                <td>{{ asset_fee_calculated }} GHOST</td> 
                <td>{{ datetime.fromtimestamp(a.expiry_time).strftime('%Y-%m-%d') }}</td>
                <td>
                    <a href="{{ asset_relative_link }}" target="_blank">Gör</a> 
                    | 
                    <a href="javascript:void(0);" onclick="return copyLink('{{ asset_external_link }}', this)">[Link]</a>
                </td>
                <td>
                    <a href="{{ url_for('edit_asset', asset_id=a.asset_id) }}">{{ lang['edit'] }}</a>
                    |
                    <form method="POST" style="display:inline;" onsubmit="return confirm('Bu varlığı silmek istediğinizden emin misiniz?');">
                        <input type="hidden" name="action" value="delete_asset">
                        <input type="hidden" name="asset_id" value="{{ a.asset_id }}">
                        <button type="submit" class="delete-button">{{ lang['delete'] }}</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>

{% endblock %}
"""

# --- LOGIN/REGISTER HTML ŞABLONU (Değişmedi) ---
LOGIN_UI = """
{% extends 'base.html' %}
{% block content %}
    <div class="card login-form">
        <h2>{{ lang['login_prompt'] }}</h2>
        <form method="POST" action="{{ url_for('handle_login') }}">
            <input type="text" name="username" placeholder="{{ lang['username'] }}" required>
            <input type="password" name="password" placeholder="{{ lang['password'] }}" required>
            <button class="action-button" type="submit">{{ lang['submit'] }}</button>
        </form>
        <p style="text-align:center; margin-top:10px;">{{ lang['register'] }} için <a href="{{ url_for('register') }}">buraya</a> tıkla.</p>
    </div>
{% endblock %}
"""
REGISTER_UI = """
{% extends 'base.html' %}
{% block content %}
    <div class="card login-form">
        <h2>{{ lang['register'] }}</h2>
        <form method="POST" action="{{ url_for('handle_register') }}">
            <input type="text" name="username" placeholder="{{ lang['username'] }}" required>
            <input type="password" name="password" placeholder="{{ lang['password'] }}" required>
            <input type="password" name="password_confirm" placeholder="{{ lang['password'] }} (Tekrar)" required>
            <button class="action-button" type="submit">{{ lang['submit'] }}</button>
        </form>
        <p style="text-align:center; margin-top:10px;">{{ lang['login'] }} için <a href="{{ url_for('login') }}">buraya</a> tıkla.</p>
    </div>
{% endblock %}
"""
# --- MINING HTML ŞABLONU (Değişmedi) ---
MINING_UI = """
{% extends 'base.html' %}
{% block content %}
    <div class="card">
        <h2>{{ lang['mining_title'] }}</h2>
        {% if new_hash %}
            <p class="success">🎉 {{ lang['mine_message'] | replace('{{ block_hash }}', new_hash[:12] + '...') | replace('{{ reward }}', BLOCK_REWARD) }}</p>
        {% else %}
            <p>Son blok: {{ last_block.block_index }} ({{ last_block.block_hash[:12] }}...)</p>
            <p>Zorluk: {{ MINING_DIFFICULTY }}</p>
            <p>Madencilik başlamak için butona tıklayın.</p>
        {% endif %}
        <form method="POST" action="{{ url_for('mine') }}">
            <button class="action-button" type="submit">Madenciliği Başlat / Yeniden Dene</button>
        </form>
    </div>
{% endblock %}
"""


# --- ROTALAR / ROUTES ---

@app.before_request
def update_peer_count():
    session['active_peers_count'] = mesh_mgr.get_active_peers(timeout_seconds=120)

@app.route('/')
def home():
    if session.get('username'): return redirect(url_for('dashboard'))
    L = LANGUAGES[session.get('lang', 'tr')]
    return render_template_string("{% extends 'base.html' %}{% block content %}<div class='card'>{{ lang['title'] }}'a Hoş Geldiniz. Lütfen giriş yapın.</div>{% endblock %}", lang=L, active_peers_count=session.get('active_peers_count'))

@app.route('/login', methods=['GET'])
def login():
    L = LANGUAGES[session.get('lang', 'tr')]
    return render_template_string(LOGIN_UI, lang=L, active_peers_count=session.get('active_peers_count'))

@app.route('/handle_login', methods=['POST'])
def handle_login():
    username = request.form['username']
    password = request.form['password']
    
    conn = db.get_connection()
    user = conn.execute("SELECT wallet_public_key, balance FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()

    if user:
        session['username'] = username
        session['pub_key'] = user['wallet_public_key']
        session['balance'] = user['balance']
    else:
        if username and password:
            pub_key = hashlib.sha256(username.encode()).hexdigest()[:20]
            try:
                conn.execute("INSERT INTO users (username, password, wallet_public_key, balance) VALUES (?, ?, ?, ?)", (username, password, pub_key, 50.00))
                conn.commit()
                session['username'] = username
                session['pub_key'] = pub_key
                session['balance'] = 50.00
            except sqlite3.IntegrityError:
                pass
    conn.close()

    if session.get('username'):
        return redirect(url_for('dashboard'))
    else:
        return redirect(url_for('login'))


@app.route('/logout') 
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST']) 
def register():
    L = LANGUAGES[session.get('lang', 'tr')]
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_confirm = request.form['password_confirm']

        if password != password_confirm:
            return render_template_string(REGISTER_UI, lang=L, error="Şifreler uyuşmuyor.", active_peers_count=session.get('active_peers_count'))
        
        pub_key = hashlib.sha256(username.encode()).hexdigest()[:20] 
        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO users (username, password, wallet_public_key, balance) VALUES (?, ?, ?, ?)", (username, password, pub_key, 50.00))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            return render_template_string(REGISTER_UI, lang=L, error="Kullanıcı adı zaten alınmış.", active_peers_count=session.get('active_peers_count'))

    return render_template_string(REGISTER_UI, lang=L, active_peers_count=session.get('active_peers_count'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    
    message = None
    error = None

    if request.method == 'POST':
        action = request.form.get('action')
        pub_key = session['pub_key']
        
        if action == 'register_domain':
            # TR: Domain kaydı
            success, res = assets_mgr.register_asset(pub_key, 'domain', request.form['name'], request.form['data'])
            if success: message = f"Domain kaydedildi: {request.form['name']}. ({res})"
            else: error = f"Hata: {res}"
            
        elif action == 'upload_media':
            # TR: Medya (Dosya) yükleme
            if 'file' in request.files:
                file = request.files['file']
                ext = file.filename.split('.')[-1].lower()
                asset_type = 'image' if ext in ['png', 'jpg', 'jpeg'] else 'file'
                if ext in ['css']: asset_type = 'css'
                elif ext in ['js']: asset_type = 'js'
                elif ext in ['woff', 'ttf', 'woff2']: asset_type = 'font'
                success, res = assets_mgr.register_asset(pub_key, asset_type, file.filename, file, is_file=True)
                if success: message = f"Varlık yüklendi: {file.filename}. ({res})"
                else: error = f"Hata: {res}"

        elif action == 'delete_asset':
            asset_id = request.form.get('asset_id')
            success, res = assets_mgr.delete_asset(asset_id, pub_key)
            if success: message = "Varlık başarıyla silindi."
            else: error = f"Silme Hatası: {res}"
            
    conn = db.get_connection()
    assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ? ORDER BY creation_time DESC", (session['pub_key'],)).fetchall()
    
    user_data = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (session['pub_key'],)).fetchone()
    if user_data:
        session['balance'] = user_data['balance']
    conn.close()
    
    return render_template_string(DASHBOARD_UI, 
        lang=L, 
        assets=assets, 
        now=time.time(), 
        datetime=datetime, 
        calculate_asset_fee=calculate_asset_fee, 
        message=message, 
        error=error,
        active_peers_count=session.get('active_peers_count'),
        STORAGE_COST_PER_MB=STORAGE_COST_PER_MB # Şablona ücret bilgisini ilet
    )

@app.route('/view_asset/<asset_id>')
def view_asset(asset_id):
    conn = db.get_connection()
    asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    conn.close()
    if not asset: return "404: Asset Not Found", 404

    mimes = {
        'css': 'text/css', 'js': 'application/javascript', 'domain': 'text/html',
        'font': 'font/woff2' if asset['name'].endswith('2') else 'font/woff',
        'image': 'image/png' 
    }
    return Response(asset['content'], mimetype=mimes.get(asset['type'], 'application/octet-stream'))

@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in LANGUAGES: session['lang'] = lang
    return redirect(request.referrer or '/')

@app.route('/mine', methods=['GET', 'POST'])
def mine():
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    
    last_block = blockchain_mgr.get_last_block()
    new_hash = None
    
    if request.method == 'POST':
        last_proof = last_block['proof']
        proof = blockchain_mgr.proof_of_work(last_proof) 
        new_hash = blockchain_mgr.add_block(proof, last_block['block_hash'], session['pub_key'])
        
        if new_hash:
            conn = db.get_connection()
            user_data = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (session['pub_key'],)).fetchone()
            if user_data:
                session['balance'] = user_data['balance']
            conn.close()

        last_block = blockchain_mgr.get_last_block()

    return render_template_string(MINING_UI, 
        lang=L, 
        last_block=last_block, 
        new_hash=new_hash, 
        MINING_DIFFICULTY=MINING_DIFFICULTY, 
        BLOCK_REWARD=BLOCK_REWARD,
        active_peers_count=session.get('active_peers_count')
    )

@app.route('/search')
def search_engine():
    query = request.args.get('q', '').lower()
    L = LANGUAGES[session.get('lang', 'tr')]
    conn = db.get_connection()
    
    results = conn.execute("SELECT * FROM assets WHERE type='domain' AND (name LIKE ? OR keywords LIKE ?)", (f'%{query}%', f'%{query}%')).fetchall()
    conn.close()
    
    html_output = f"<div class='card'><h3>{L['search_title']} - '{query}' ({len(results)} sonuç)</h3>"
    if results:
        html_output += "<table><tr><th>.ghost Domain</th><th>İçerik (İlk 100 Karakter)</th></tr>"
        for r in results:
            content_preview = r['content'][:100].decode('utf-8', 'ignore') if r['content'] else ""
            html_output += f"<tr><td><a href='{url_for('view_asset', asset_id=r['asset_id'])}' target='_blank'>{r['name']}</a></td><td>{content_preview}...</td></tr>"
        html_output += "</table>"
    else:
        html_output += "<p>Sonuç bulunamadı.</p>"
    html_output += "</div>"

    return render_template_string("{% extends 'base.html' %}{% block content %}" + html_output + "{% endblock %}", lang=L, active_peers_count=session.get('active_peers_count'))

@app.route('/edit_asset/<asset_id>')
def edit_asset(asset_id):
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    
    return render_template_string("{% extends 'base.html' %}{% block content %}<div class='card'><h2>{{ lang['edit'] }} Asset: {{ asset_id }}</h2><p>Düzenleme formu buraya gelecek.</p></div>{% endblock %}", lang=L, asset_id=asset_id, active_peers_count=session.get('active_peers_count'))

# --- MESH AĞI İLETİŞİM ROTASI (ghost_mesh_node.py ile Konuşma) ---
@app.route('/peer_update', methods=['POST'])
def peer_update():
    data = request.get_json()
    ip_address = request.remote_addr 
    if data and 'ip_address' in data:
         ip_address = data['ip_address'] 

    if ip_address:
        if mesh_mgr.register_peer(ip_address):
            return jsonify({'message': 'Peer updated successfully.'}), 200
        else:
            return jsonify({'error': 'Failed to update peer.'}), 500
    return jsonify({'error': 'Invalid data or no IP address detected'}), 400


# --- START ---
if __name__ == '__main__':
    # TR: Ana şablonu ve alt şablonları Jinja2 ortamına yükle
    app.jinja_env.loader = DictLoader({
        'base.html': LAYOUT, 
        'dashboard.html': DASHBOARD_UI,
        'login.html': LOGIN_UI, 
        'register.html': REGISTER_UI, 
        'mining.html': MINING_UI
    })
    app.run(host='0.0.0.0', port=GHOST_PORT, debug=True, use_reloader=False)
