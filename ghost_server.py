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
from flask import Flask, jsonify, request, render_template_string, session, redirect, url_for, Response, flash
from uuid import uuid4
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from datetime import timedelta, datetime
from markupsafe import Markup 
from jinja2 import DictLoader, Template 

# --- LOGLAMA / LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - GhostServer - %(levelname)s - %(message)s')
logger = logging.getLogger("GhostCloud")

# --- YAPILANDIRMA / CONFIGURATION ---
BASE_DIFFICULTY = 4 
TOTAL_SUPPLY = 100000000.0 
INITIAL_BLOCK_REWARD = 50.0 
HALVING_INTERVAL = 2000
DB_FILE = os.path.join(os.getcwd(), "ghost_cloud_v2.db") 
GHOST_PORT = 5000
DOMAIN_EXPIRY_SECONDS = 15552000 
STORAGE_COST_PER_MB = 0.01        
DOMAIN_REGISTRATION_FEE = 1.0     
INITIAL_USER_BALANCE = 50.0 
KNOWN_PEERS = []

app = Flask(__name__)
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
        'wallet_title': "💳 Cüzdanım", 'pubkey': "Public Key (Hash)", 'balance': "Bakiye",
        'domain_title': "💾 .ghost Kayıt", 'media_title': "🖼️ Varlık Yükle", 'asset_action': "İşlem", 
        'assets_title': "Kayıtlı Varlıklarım",
        'status_success': "Başarılı", 'status_failed': "Başarısız", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Kopyalandı!",
        'media_info': "Desteklenen: .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Yayınla", 
        'search_title': "🔍 Ghost Arama (İçerik & Domain)", 'edit': "Düzenle", 'delete': "Sil",
        'login_prompt': "Giriş Yap", 'username': "Kullanıcı Adı", 'password': "Şifre", 'submit': "Gönder",
        'asset_fee': "Ücret", 'asset_expires': "Süre Sonu", 'mine_success': "Blok Başarılı", 
        'mine_message': "Yeni blok bulundu: {{ block_hash }}. Ödül: {{ reward }} GHOST hesabınıza eklendi.",
        'mine_limit_error': "Günde sadece 1 kez madencilik yapabilirsiniz. Kalan süre:",
        'wallet_address': "Cüzdan Adresi (GHST)", 'last_transactions': "Son İşlemlerim", 
        'tx_id': "İşlem ID", 'tx_sender': "Gönderen", 'tx_recipient': "Alıcı", 'tx_amount': "Miktar", 'tx_timestamp': "Zaman",
        'no_transactions': "Henüz bir işlem yok.",
        'total_supply': "Toplam Arz", 'mined_supply': "Dolaşımdaki Arz", 'remaining_supply': "Kalan Arz",
        'mine_last_block': "Son Blok", 'mine_difficulty': "Zorluk", 'mine_reward': "Mevcut Ödül",
        'mine_next_halving': "Sonraki Yarılanma", 'domain_exists': "Bu .ghost adı zaten kayıtlı."
    },
    'en': {
        'title': "GhostProtocol Server", 'status_online': "ONLINE", 'status_offline': "OFFLINE",
        'server_status': "Server Status", 'active_peers': "Active Peers",
        'dashboard_title': "Dashboard", 'mining_title': "Mining", 'logout': "Logout", 'login': "Login", 'register': "Register", 'search': "Search",
        'wallet_title': "💳 My Wallet", 'pubkey': "Public Key (Hash)", 'balance': "Balance",
        'domain_title': "💾 .ghost Registration", 'media_title': "🖼️ Upload Asset", 'asset_action': "Action", 
        'assets_title': "My Registered Assets",
        'status_success': "Success", 'status_failed': "Failed", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Copied!",
        'media_info': "Supported: .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Publish", 
        'search_title': "🔍 Ghost Search (Content & Domain)", 'edit': "Edit", 'delete': "Delete",
        'login_prompt': "Login", 'username': "Username", 'password': "Password", 'submit': "Submit",
        'asset_fee': "Fee", 'asset_expires': "Expires", 'mine_success': "Block Success",
        'mine_message': "New block found: {{ block_hash }}. Reward: {{ reward }} GHOST added to your account.",
        'mine_limit_error': "You can only mine once per day. Time remaining:",
        'wallet_address': "Wallet Address (GHST)", 'last_transactions': "Last Transactions", 
        'tx_id': "Tx ID", 'tx_sender': "Sender", 'tx_recipient': "Recipient", 'tx_amount': "Amount", 'tx_timestamp': "Time",
        'no_transactions': "No transactions yet.",
        'total_supply': "Total Supply", 'mined_supply': "Circulating Supply", 'remaining_supply': "Remaining Supply",
        'mine_last_block': "Last Block", 'mine_difficulty': "Difficulty", 'mine_reward': "Current Reward",
        'mine_next_halving': "Next Halving", 'domain_exists': "This .ghost name is already registered."
    },
    'ru': {
        'title': "Сервер GhostProtocol", 'status_online': "ОНЛАЙН", 'status_offline': "ОФФЛАЙН",
        'server_status': "Статус Сервера", 'active_peers': "Активные Пиры",
        'dashboard_title': "Панель", 'mining_title': "Майнинг", 'logout': "Выход", 'login': "Вход", 'register': "Регистрация", 'search': "Поиск",
        'wallet_title': "💳 Мой Кошелек", 'pubkey': "Публичный Ключ (Хеш)", 'balance': "Баланс",
        'domain_title': "💾 Регистрация .ghost", 'media_title': "🖼️ Загрузить Актив", 'asset_action': "Действие", 
        'assets_title': "Мои зарегистрированные активы",
        'status_success': "Успех", 'status_failed': "Ошибка", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Скопировано!",
        'media_info': "Поддерживается: .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Опубликовать", 
        'search_title': "🔍 Ghost Поиск (Контент и Домен)", 'edit': "Редактировать", 'delete': "Удалить",
        'login_prompt': "Войти", 'username': "Имя пользователя", 'password': "Пароль", 'submit': "Отправить",
        'asset_fee': "Плата", 'asset_expires': "Срок", 'mine_success': "Блок Успешен", 
        'mine_message': "Найден новый блок: {{ block_hash }}. Награда: {{ reward }} GHOST добавлена на ваш счет.",
        'mine_limit_error': "Вы можете майнить только один раз в день. Оставшееся время:",
        'wallet_address': "Адрес Кошелька (GHST)", 'last_transactions': "Последние Транзакции", 
        'tx_id': "ID Транзакции", 'tx_sender': "Отправитель", 'tx_recipient': "Получатель", 'tx_amount': "Сумма", 'tx_timestamp': "Время",
        'no_transactions': "Пока нет транзакций.",
        'total_supply': "Общий Объем", 'mined_supply': "В Обращении", 'remaining_supply': "Оставшийся Объем",
        'mine_last_block': "Последний Блок", 'mine_difficulty': "Сложность", 'mine_reward': "Текущая Награда",
        'mine_next_halving': "Следующее Уполовинивание", 'domain_exists': "Это имя .ghost уже зарегистрировано."
    },
    'hy': {
        'title': "GhostProtocol Սերվեր", 'status_online': "ԱՌՑԱՆՑ", 'status_offline': "ԱՆՑԱՆՑ",
        'server_status': "Սերվերի Կարգավիճակը", 'active_peers': "Ակտիվ Փիրեր",
        'dashboard_title': "Վահանակ", 'mining_title': "Մայնինգ", 'logout': "Ելք", 'login': "Մուտք", 'register': "Գրանցվել", 'search': "Որոնում",
        'wallet_title': "💳 Իմ Դրամապանակը", 'pubkey': "Հանրային Բանալի (Հեշ)", 'balance': "Մնացորդ",
        'domain_title': "💾 .ghost Գրանցում", 'media_title': "🖼️ Բեռնել Ակտիվ", 'asset_action': "Գործողություն", 
        'assets_title': "Իմ Գրանցված Ակտիվները",
        'status_success': "Հաջող", 'status_failed': "Ձախողված", 
        'monthly_fee_unit': " GHOST", 'media_link_copy': "Պատճենվեց!",
        'media_info': "Աջակցվում է՝ .png, .jpg, .css, .js, .woff, .mp4, .mp3", 'register_btn': "Հրատարակել", 
        'search_title': "🔍 Ghost Որոնում (Բովանդակություն և Դոմեն)", 'edit': "Խմբագրել", 'delete': "Ջնջել",
        'login_prompt': "Մուտք գործել", 'username': "Օգտվողի անուն", 'password': "Գաղտնաբառ", 'submit': "Ուղարկել",
        'asset_fee': "Վճար", 'asset_expires': "Ժամկետը", 'mine_success': "Բլոկի Հաջողություն",
        'mine_message': "Գտնվեց նոր բլոկ: {{ block_hash }}: Պարգև՝ {{ reward }} GHOST ավելացվել է ձեր հաշվին:",
        'mine_limit_error': "Դուք կարող եք մայնինգ անել օրը միայն մեկ անգամ: Մնացած ժամանակը:",
        'wallet_address': "Դրամապանակի Հասցե (GHST)", 'last_transactions': "Վերջին Գործարքները", 
        'tx_id': "Գործարքի ID", 'tx_sender': "Ուղարկող", 'tx_recipient': "Ստացող", 'tx_amount': "Գումար", 'tx_timestamp': "Ժամանակ",
        'no_transactions': "Դեռ գործարքներ չկան։",
        'total_supply': "Ընդհանուր Մատակարարում", 'mined_supply': "Շրջանառվող Մատակարարում", 'remaining_supply': "Մնացորդային Մատակարարում",
        'mine_last_block': "Վերջին Բլոկ", 'mine_difficulty': "Բարդություն", 'mine_reward': "Ընթացիկ Պարգև",
        'mine_next_halving': "Հաջորդ Կիսում", 'domain_exists': "Այս .ghost անունն արդեն գրանցված է:"
    }
}

# --- YARDIMCI FONKSİYONLAR / HELPERS ---
def generate_user_keys(username):
    original_hash = hashlib.sha256(username.encode()).hexdigest()[:20]
    ghst_address = f"GHST{original_hash}" 
    return original_hash, ghst_address

def generate_qr_code_link(ghst_address):
    return f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={ghst_address}"

def extract_keywords(content_str):
    if not content_str: return ""
    try:
        text = re.sub(r'<(script|style).*?>.*?</\1>', '', content_str, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<.*?>', ' ', text)
        text = re.sub(r'[^a-zA-ZğüşıöçĞÜŞİÖÇ ]', ' ', text)
        words = text.lower().split()
        stop_words = {'ve', 'ile', 'the', 'and', 'for', 'this', 'bir', 'için', 'or', 'by', 'bu', 'da', 'de', 'mi'}
        keywords = set([w for w in words if len(w) > 2 and w not in stop_words])
        return ",".join(list(keywords)[:20])
    except:
        return ""

def calculate_asset_fee(size_bytes, asset_type):
    if asset_type == 'domain':
        return DOMAIN_REGISTRATION_FEE
    else:
        return round((size_bytes / (1024 * 1024)) * STORAGE_COST_PER_MB, 5)

def calculate_difficulty(active_peer_count):
    increase = active_peer_count // 5
    return BASE_DIFFICULTY + increase

# --- VERİTABANI VE YÖNETİCİLER ---
class DatabaseManager:
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
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, name TEXT, surname TEXT, wallet_public_key TEXT UNIQUE, balance REAL DEFAULT 50, last_mined REAL DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (block_index INTEGER PRIMARY KEY, timestamp REAL, previous_hash TEXT, block_hash TEXT, proof INTEGER, miner_key TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, keywords TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT, amount REAL, timestamp REAL, block_index INTEGER DEFAULT 0)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS mesh_peers (ip_address TEXT PRIMARY KEY, last_seen REAL)''')
        
        # Sütun Kontrolleri
        try: cursor.execute("SELECT last_mined FROM users LIMIT 1")
        except sqlite3.OperationalError: cursor.execute("ALTER TABLE users ADD COLUMN last_mined REAL DEFAULT 0")

        for table, column in [('assets', 'keywords'), ('blocks', 'miner_key')]:
            try: cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
            except sqlite3.OperationalError: cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")

        if cursor.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
            self.create_genesis_block(cursor)
        conn.commit()
        conn.close()

    def create_genesis_block(self, cursor):
        genesis_hash = hashlib.sha256(b'GhostGenesis').hexdigest()
        cursor.execute("INSERT INTO blocks (block_index, timestamp, previous_hash, block_hash, proof, miner_key) VALUES (?, ?, ?, ?, ?, ?)",
                       (1, time.time(), '0', genesis_hash, 1, 'GhostProtocol_System'))

class AssetManager:
    def __init__(self, db_manager):
        self.db = db_manager
        
    def register_asset(self, owner_key, asset_type, name, content, is_file=False):
        keywords = ""
        name = name.lower()
        conn = self.db.get_connection()

        if asset_type == 'domain':
             if conn.execute("SELECT 1 FROM assets WHERE type = 'domain' AND name = ?", (name,)).fetchone():
                conn.close()
                return False, LANGUAGES[session.get('lang', 'tr')]['domain_exists']

        if is_file:
            content_bytes = content.read()
            content.seek(0) 
        else:
            # İçerik boş gelebilir (Domain tescilinde)
            if not content:
                content = "<html><body><h1>Yapım Aşamasında</h1></body></html>"
            content_bytes = content.encode('utf-8')
            if asset_type == 'domain':
                keywords = extract_keywords(content)
            
        size = len(content_bytes)
        fee = calculate_asset_fee(size, asset_type)

        user_balance_row = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (owner_key,)).fetchone()
        
        if not user_balance_row or user_balance_row['balance'] < fee:
             conn.close()
             return False, f"Yetersiz bakiye. Gerekli: {fee:.5f} GHOST"

        try:
            conn.execute("INSERT OR REPLACE INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (str(uuid4()), owner_key, asset_type, name, content_bytes, size, time.time(), time.time() + DOMAIN_EXPIRY_SECONDS, keywords))
            conn.execute("UPDATE users SET balance = balance - ? WHERE wallet_public_key = ?", (fee, owner_key))
            
            tx_id = str(uuid4())
            conn.execute("INSERT INTO transactions (tx_id, sender, recipient, amount, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (tx_id, owner_key, "Asset_Fee_Collector", fee, time.time()))

            conn.commit()
            return True, f"Başarılı. Ücret: {fee:.5f} GHOST"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_asset_by_id(self, asset_id):
        conn = self.db.get_connection()
        asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        conn.close()
        return asset
        
    def get_assets_by_owner(self, owner_key):
        conn = self.db.get_connection()
        assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ? ORDER BY creation_time DESC", (owner_key,)).fetchall()
        conn.close()
        return assets
    
    def get_domain_by_name(self, name):
        conn = self.db.get_connection()
        asset = conn.execute("SELECT * FROM assets WHERE type = 'domain' AND name = ?", (name.lower(),)).fetchone()
        conn.close()
        return asset

    def delete_asset(self, asset_id, owner_key):
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            result = cursor.execute("DELETE FROM assets WHERE asset_id = ? AND owner_pub_key = ?", (asset_id, owner_key))
            conn.commit()
            return (True, "Varlık silindi.") if result.rowcount > 0 else (False, "Bulunamadı.")
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
            
    def update_asset_content(self, asset_id, owner_key, new_content):
        conn = self.db.get_connection()
        try:
            asset = conn.execute("SELECT * FROM assets WHERE asset_id = ? AND owner_pub_key = ?", (asset_id, owner_key)).fetchone()
            if not asset: return False, "Yetkisiz işlem."
            
            new_content_bytes = new_content.encode('utf-8')
            new_size = len(new_content_bytes)
            keywords = extract_keywords(new_content) if asset['type'] == 'domain' else ""
                
            conn.execute("UPDATE assets SET content = ?, storage_size = ?, keywords = ? WHERE asset_id = ?",
                         (new_content_bytes, new_size, keywords, asset_id))
            conn.commit()
            return True, "Güncellendi."
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
            
    def search_assets(self, query):
        conn = self.db.get_connection()
        search_terms = f"%{query.lower()}%"
        assets = conn.execute("SELECT * FROM assets WHERE name LIKE ? OR keywords LIKE ?", (search_terms, search_terms)).fetchall()
        conn.close()
        return assets

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

    def proof_of_work(self, last_proof, difficulty):
        proof = 0
        while self.is_valid_proof(last_proof, proof, difficulty) is False:
            proof += 1
        return proof

    def is_valid_proof(self, last_proof, proof, difficulty):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:difficulty] == '0' * difficulty
    
    def get_current_mined_supply(self):
        conn = self.db.get_connection()
        total = conn.execute("SELECT SUM(amount) FROM transactions WHERE sender = 'GhostProtocol_System'").fetchone()[0] or 0.0
        initial = conn.execute("SELECT COUNT(id) FROM users").fetchone()[0] * INITIAL_USER_BALANCE
        conn.close()
        return total + initial

    def calculate_block_reward(self, current_block_index):
        halvings = current_block_index // HALVING_INTERVAL
        reward = INITIAL_BLOCK_REWARD / (2**halvings)
        current_supply = self.get_current_mined_supply()
        if current_supply + reward > TOTAL_SUPPLY:
            reward = max(0.0, TOTAL_SUPPLY - current_supply)
        return round(reward, 4)

    def new_block(self, proof, miner_key, data=""):
        last_block = self.get_last_block()
        index = last_block['block_index'] + 1
        timestamp = time.time()
        reward = self.calculate_block_reward(index)
        previous_hash = last_block['block_hash']
        block_hash = self.hash_block(index, timestamp, data, previous_hash, proof, miner_key)

        conn = self.db.get_connection()
        try:
            conn.execute("INSERT INTO blocks (block_index, timestamp, previous_hash, block_hash, proof, miner_key) VALUES (?, ?, ?, ?, ?, ?)",
                         (index, timestamp, previous_hash, block_hash, proof, miner_key))
            if reward > 0:
                conn.execute("UPDATE users SET balance = balance + ? WHERE wallet_public_key = ?", (reward, miner_key))
                tx_id = str(uuid4())
                conn.execute("INSERT INTO transactions (tx_id, sender, recipient, amount, timestamp, block_index) VALUES (?, ?, ?, ?, ?, ?)",
                             (tx_id, "GhostProtocol_System", miner_key, reward, time.time(), index))
            conn.commit()
            return {'block_hash': block_hash, 'reward': reward}
        except Exception:
            conn.close()
            return None
        finally:
            conn.close()

class MeshManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def register_peer(self, ip_address):
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT OR REPLACE INTO mesh_peers (ip_address, last_seen) VALUES (?, ?)", (ip_address, time.time()))
            conn.commit()
            return True
        except: return False
        finally: conn.close()

    def get_active_peers(self, timeout_seconds=120):
        conn = self.db.get_connection()
        count = conn.execute("SELECT COUNT(*) FROM mesh_peers WHERE last_seen > ?", (time.time() - timeout_seconds,)).fetchone()[0]
        conn.close()
        return count

class TransactionManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_last_transactions(self, pub_key, limit=10):
        conn = self.db.get_connection()
        transactions = conn.execute("SELECT * FROM transactions WHERE sender = ? OR recipient = ? ORDER BY timestamp DESC LIMIT ?", (pub_key, pub_key, limit)).fetchall()
        conn.close()
        return transactions

# --- INIT ---
db = DatabaseManager(DB_FILE)
assets_mgr = AssetManager(db)
blockchain_mgr = BlockchainManager(db)
mesh_mgr = MeshManager(db)
tx_mgr = TransactionManager(db)

# --- HTML TEMPLATES ---

LAYOUT = r"""
<!DOCTYPE html>
<html>
<head>
<title>{{ lang['title'] }}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style> 
body { font-family: sans-serif; background: #1a1a1a; color: #ddd; padding: 20px; } 
.card { background: #2a2a2a; padding: 15px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #333; } 
a { color: #00aaff; text-decoration: none; } 
a:hover { text-decoration: underline; }
.header-bar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; border-bottom: 2px solid #333; padding-bottom: 10px; }
.header-bar h2 { margin: 0; }
.menu a { margin-left: 15px; color: #ccc; }
.menu a:hover { color: #fff; }
.action-button { background-color: #4caf50; color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; transition: background-color 0.3s; }
.action-button:hover { background-color: #45a049; }
.login-form input[type="text"], .login-form input[type="password"], .login-form input[type="number"], .login-form input[type="url"], .login-form textarea { width: 100%; padding: 10px; margin: 5px 0 10px 0; display: inline-block; border: 1px solid #555; border-radius: 4px; box-sizing: border-box; background-color: #333; color: #ddd; }
.status-message { padding: 10px; margin-bottom: 10px; border-radius: 5px; font-weight: bold; }
.status-success { background-color: #4CAF50; color: white; }
.status-error { background-color: #f44336; color: white; }
table { border-collapse: collapse; width: 100%; font-size: 0.9em; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid #333; }
th { background-color: #3a3a3a; }
.content-section { margin-top: 15px; }
.lang-switch a { margin-left: 5px; color: #888; }
.supply-info p { margin: 5px 0; font-size: 0.9em; }
</style>
<script>
    function copyLink(btn, link) {
        let area = document.createElement('textarea');
        area.value = link;
        document.body.appendChild(area);
        area.select();
        document.execCommand('copy');
        document.body.removeChild(area);
        let originalText = btn.innerText;
        btn.innerText = "{{ lang['media_link_copy'] }}";
        setTimeout(() => { btn.innerText = originalText; }, 1500);
        return false;
    }
</script>
</head>
<body>
<div class="header-bar">
    <h2>👻 GhostProtocol</h2>
    <div class="lang-switch">
        <a href="{{ url_for('set_lang', lang='tr') }}">TR🇹🇷</a> | <a href="{{ url_for('set_lang', lang='en') }}">EN🇬🇧</a> | <a href="{{ url_for('set_lang', lang='ru') }}">RU🇷🇺</a> | <a href="{{ url_for('set_lang', lang='hy') }}">HY🇦🇲</a>
    </div>
</div>
<div class="card">
    <div class="supply-info">
        <p><strong>{{ lang['total_supply'] }}:</strong> {{ TOTAL_SUPPLY | int | thousands }} GHOST</p>
        <p><strong>{{ lang['mined_supply'] }}:</strong> {{ current_mined_supply | round(4) | thousands }} GHOST</p>
        <p><strong>{{ lang['remaining_supply'] }}:</strong> <span style="color: {% if remaining_supply > 0 %}#4caf50{% else %}#f44336{% endif %}; font-weight: bold;">{{ remaining_supply | round(4) | thousands }} GHOST</span></p>
    </div>
    <hr style="border-top: 1px solid #333; margin: 10px 0;">
    📡 {{ lang['server_status'] }}: <span style="color:#4caf50;">{{ lang['status_online'] }}</span> | 🔗 {{ lang['active_peers'] }}: {{ active_peers_count }}
</div>
<div class="card menu">
    <a href="{{ url_for('dashboard') }}">{{ lang['dashboard_title'] }}</a>
    <a href="{{ url_for('mining') }}">{{ lang['mining_title'] }}</a>
    <a href="{{ url_for('search_content') }}">{{ lang['search'] }}</a>
    {% if session.get('username') %}
        <a href="{{ url_for('logout') }}">{{ lang['logout'] }}</a>
    {% else %}
        <a href="{{ url_for('login') }}">{{ lang['login'] }}</a>
        <a href="{{ url_for('register') }}">{{ lang['register'] }}</a>
    {% endif %}
</div>
{% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
        {% for category, message in messages %}
            <div class="status-message status-{{ category }}">{{ message | safe }}</div>
        {% endfor %}
    {% endif %}
{% endwith %}
<div class="content-section">
{% block content %}{% endblock %}
</div>
</body>
</html>
"""

DASHBOARD_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card">
    <h3>{{ lang['wallet_title'] }}</h3>
    <p><strong>{{ lang['wallet_address'] }}:</strong> {{ user_ghst_address }} <img src="{{ qr_code_link }}" style="vertical-align: middle; margin-left: 10px; width: 75px; height: 75px;"></p>
    <p><strong>{{ lang['pubkey'] }}:</strong> {{ user_pub_key_hash }}</p>
    <p><strong>{{ lang['balance'] }}:</strong> <span style="font-size: 1.5em; color: #ffeb3b;">{{ session.get('balance', 0) | round(4) | thousands }} GHOST</span></p>
</div>

<div style="display: flex; gap: 12px;">
    <div class="card" style="flex: 1;">
        <h3>{{ lang['domain_title'] }}</h3>
        <p><strong>Ücret:</strong> {{ DOMAIN_REGISTRATION_FEE }} GHOST (Sabit)</p>
        <p><strong>Süre:</strong> 6 Ay</p>
        <form method="POST" action="{{ url_for('dashboard') }}">
            <input type="hidden" name="action" value="register_domain">
            <input type="text" name="domain_name" placeholder="Domain Adı (ornek.ghost)" required pattern="[a-zA-Z0-9.-]+\.ghost$"><br>
            {# İçerik alanı kaldırıldı, kayıt için zorunlu değil #}
            <button class="action-button" type="submit">{{ lang['register_btn'] }}</button>
        </form>
    </div>
    <div class="card" style="flex: 1;">
        <h3>{{ lang['media_title'] }}</h3>
        <p style="font-size:0.9em; color:#aaa;">{{ lang['media_info'] }}</p>
        <p><strong>Barındırma:</strong> {{ STORAGE_COST_PER_MB }} GHOST / MB</p>
        <form method="POST" action="{{ url_for('dashboard') }}" enctype="multipart/form-data">
            <input type="hidden" name="action" value="upload_media">
            <input type="file" name="file" required><br>
            <button class="action-button" type="submit" style="margin-top:10px;">{{ lang['media_title'] }}</button>
        </form>
    </div>
</div>

<div class="card">
    <h3>{{ lang['assets_title'] }}</h3>
    <table style="width:100%">
        <tr>
            <th>Ad</th> <th>Tip</th> <th>{{ lang['asset_fee'] }}</th> <th>{{ lang['asset_expires'] }}</th> <th>{{ lang['asset_action'] }}</th> <th></th>
        </tr>
        {% for a in assets %}
        {% set asset_fee_calculated = calculate_asset_fee(a.storage_size, a.type)|round(4) %}
        {% set asset_relative_link = url_for('view_asset', asset_id=a.asset_id) %}
        {% set asset_external_link = url_for('view_asset', asset_id=a.asset_id, _external=True) %}
        <tr>
            <td>{{ a.name }} <br><span style="font-size: 0.7em;">ID: {{ a.asset_id[:8] }}...</span></td>
            <td>{{ a.type | upper }}</td>
            <td>{{ asset_fee_calculated }}{{ lang['monthly_fee_unit'] }}</td>
            <td>{{ datetime.fromtimestamp(a.expiry_time).strftime('%Y-%m-%d') }}</td>
            <td>
                <a href="{{ asset_relative_link }}" target="_blank">Gör</a> 
                | 
                <a href="javascript:void(0);" onclick="return copyLink(this, '{{ asset_external_link }}');">Link</a>
                
                {# DÜZENLEME BUTONU: Sadece metin tabanlı veya domainler için #}
                {% if a.type == 'domain' or a.type in ['css', 'js', 'file'] %}
                    | <a href="{{ url_for('edit_asset', asset_id=a.asset_id) }}" style="color:#f1c40f;">{{ lang['edit'] }}</a>
                {% endif %}
            </td>
            <td>
                <form method="POST" style="display: inline-block;">
                    <input type="hidden" name="action" value="delete_asset">
                    <input type="hidden" name="asset_id" value="{{ a.asset_id }}">
                    <button class="action-button" type="submit" style="background-color: #f44336; padding: 5px 8px;">{{ lang['delete'] }}</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </table>
</div>

<div class="card">
    <h3>{{ lang['last_transactions'] }}</h3>
    <table style="width:100%">
        <tr>
            <th>{{ lang['tx_id'] }}</th> <th>{{ lang['tx_sender'] }}</th> <th>{{ lang['tx_recipient'] }}</th> <th>{{ lang['tx_amount'] }}</th> <th>{{ lang['tx_timestamp'] }}</th>
        </tr>
        {% for tx in transactions %}
        <tr>
            <td>{{ tx.tx_id[:8] }}...</td>
            <td style="color: {% if tx.sender == user_ghst_address %}#f44336{% else %}#4caf50{% endif %};">{{ tx.sender[:4] }}...{{ tx.sender[-4:] }}</td>
            <td style="color: {% if tx.recipient == user_ghst_address %}#4caf50{% else %}#f44336{% endif %};">{{ tx.recipient[:4] }}...{{ tx.recipient[-4:] }}</td>
            <td>{{ tx.amount | round(4) }} GHOST</td>
            <td>{{ datetime.fromtimestamp(tx.timestamp).strftime('%Y-%m-%d %H:%M') }}</td>
        </tr>
        {% else %}
        <tr><td colspan="5">{{ lang['no_transactions'] }}</td></tr>
        {% endfor %}
    </table>
</div>
{% endblock %}
"""

LOGIN_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card login-form">
    <h3>{{ lang['login_prompt'] }}</h3>
    <form method="POST" action="{{ url_for('handle_login') }}">
        <input type="text" name="username" placeholder="{{ lang['username'] }}" required><br>
        <input type="password" name="password" placeholder="{{ lang['password'] }}" required><br>
        <button class="action-button" type="submit">{{ lang['submit'] }}</button>
    </form>
    <p style="margin-top: 15px;"><a href="{{ url_for('register') }}">{{ lang['register'] }}</a></p>
</div>
{% endblock %}
"""

REGISTER_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card login-form">
    <h3>{{ lang['register'] }}</h3>
    <form method="POST">
        <input type="text" name="username" placeholder="{{ lang['username'] }}" required><br>
        <input type="password" name="password" placeholder="{{ lang['password'] }}" required><br>
        <input type="password" name="password_confirm" placeholder="Şifreyi Tekrarla" required><br>
        <button class="action-button" type="submit">{{ lang['submit'] }}</button>
    </form>
</div>
{% endblock %}
"""

MINING_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card">
    <h3>{{ lang['mining_title'] }}</h3>
    {% if message %}
        <div class="status-message status-success">{{ message | safe }}</div>
    {% endif %}
    {% if error %}
        <div class="status-message status-error">{{ error | safe }}</div>
    {% endif %}
    {% if last_block %}
    <p><strong>{{ lang['mine_last_block'] }}:</strong> Blok {{ last_block.block_index }} ({{ last_block.block_hash[:8] }}...)</p>
    <p><strong>{{ lang['mine_difficulty'] }}:</strong> {{ difficulty }}</p>
    <p><strong>{{ lang['mine_reward'] }}:</strong> <span style="font-size: 1.1em; color: {% if current_reward > 0 %}#ffeb3b{% else %}#f44336{% endif %}">{{ current_reward | round(4) }} GHOST</span></p>
    <p><strong>{{ lang['mine_next_halving'] }}:</strong> Blok {{ next_halving }} (Kalan: {{ next_halving - last_block.block_index }} Blok)</p>
    {% endif %}
    <hr style="border-top: 1px solid #333; margin: 10px 0;">
    {% if not can_mine %}
        <div class="status-message status-error">
            {{ lang['mine_limit_error'] }} {{ remaining_time }}
        </div>
        <button class="action-button" type="button" disabled style="opacity: 0.5;">Blok Madenciliği Yap</button>
    {% else %}
        <form method="POST">
            <button class="action-button" type="submit">Blok Madenciliği Yap</button>
        </form>
    {% endif %}
</div>
{% endblock %}
"""

SEARCH_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card">
    <h3>{{ lang['search_title'] }}</h3>
    <form method="GET">
        <input type="text" name="query" placeholder="Domain, anahtar kelime veya ID girin..." value="{{ query or '' }}" required><br>
        <button class="action-button" type="submit">{{ lang['search'] }}</button>
    </form>
</div>
{% if query and results %}
<div class="card">
    <h3>Arama Sonuçları ({{ results|length }})</h3>
    <table style="width:100%">
        <tr>
            <th>Ad</th><th>Tip</th><th>Sahibi</th><th>Anahtar Kelimeler</th><th>Link</th>
        </tr>
        {% for r in results %}
        <tr>
            <td>{{ r.name }}</td>
            <td>{{ r.type | upper }}</td>
            <td>{{ r.owner_pub_key[:4] }}...{{ r.owner_pub_key[-4:] }}</td>
            <td><span style="font-size: 0.8em;">{{ r.keywords or 'N/A' }}</span></td>
            <td><a href="{{ url_for('view_asset', asset_id=r.asset_id) }}" target="_blank">Görüntüle</a></td>
        </tr>
        {% endfor %}
    </table>
</div>
{% elif query and not results %}
<div class="card">
    <p>Aradığınız '{{ query }}' için sonuç bulunamadı.</p>
</div>
{% endif %}
{% endblock %}
"""

EDIT_ASSET_UI = r"""
{% extends 'base.html' %}
{% block content %}
<div class="card" style="max-width: 800px; margin: 40px auto;">
    <h3>{{ lang['edit'] }}: {{ asset.name }}</h3>
    {% if error %}
        <div class="status-message status-error">{{ error }}</div>
    {% endif %}
    {% if asset.type == 'domain' or asset.type in ['css', 'js', 'file'] %}
        <form method="POST">
            <div class="form-group">
                <label for="content">İçerik:</label>
                <textarea id="content" name="content" rows="20" style="width: 100%; font-family: monospace;">{{ asset_content }}</textarea>
            </div>
            <button type="submit" class="action-button">{{ lang['submit'] }}</button>
        </form>
    {% else %}
        <p>Bu dosya türü ({{ asset.type }}) web arayüzünden düzenlenemez.</p>
    {% endif %}
    <p style="margin-top: 15px;"><a href="{{ url_for('dashboard') }}">Geri Dön</a></p>
</div>
{% endblock %}
"""

# TR: Domain Görüntüleme Arayüzü (Şablon bloğu çakışmasını önlemek için ayrı template)
ASSET_VIEW_UI = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{ asset.name }} - GhostProtocol</title>
    <style>
        body { margin: 0; padding: 20px; font-family: sans-serif; line-height: 1.6; }
        .ghost-banner { background: #000; color: #0f0; padding: 10px; text-align: center; font-family: monospace; margin-bottom: 20px; }
        .ghost-content { border: 1px solid #ccc; padding: 20px; border-radius: 8px; background: #fff; color: #333; }
    </style>
</head>
<body>
    <div class="ghost-banner">
        Hosting on GhostProtocol Decentralized Web | <a href="{{ url_for('dashboard') }}" style="color: #0f0;">Dashboard</a>
    </div>
    <div class="ghost-content">
        {{ domain_html_content | safe }}
    </div>
</body>
</html>
"""

ASSET_DETAILS_UI = r"""
{% extends "base.html" %}
{% block content %}
    <div class="card">
        <h3>'{{ asset.name }}' Görüntüleniyor</h3>
        <p>Tip: {{ asset.type }} (İkili dosya). Bu içerik doğrudan tarayıcıda görüntülenemez. Lütfen dosyayı indirin.</p>
        <p><a href="{{ url_for('dashboard') }}">{{ L['dashboard_title'] }}</a></p>
    </div>
{% endblock %}
"""

# --- ROTLAR / ROUTES ---

@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route('/set_lang/<lang>')
def set_lang(lang):
    if lang in LANGUAGES:
        session['lang'] = lang
    return redirect(request.referrer or url_for('login'))

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET'])
def login():
    if session.get('username'): return redirect(url_for('dashboard'))
    L = LANGUAGES[session.get('lang', 'tr')]
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    active_peers_count = mesh_mgr.get_active_peers()
    return render_template_string(LOGIN_UI, lang=L, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/handle_login', methods=['POST'])
def handle_login():
    username = request.form['username']
    password = request.form['password']
    public_key_hash, ghst_address = generate_user_keys(username)
    conn = db.get_connection()
    user = conn.execute("SELECT wallet_public_key, balance FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
    if user:
        session['username'] = username
        session['balance'] = user['balance']
        session['pub_key'] = ghst_address
        session['pub_key_hash'] = public_key_hash
        conn.close()
        return redirect(url_for('dashboard'))
    else:
        if username and password:
            try:
                conn.execute("INSERT INTO users (username, password, wallet_public_key, balance) VALUES (?, ?, ?, ?)", (username, password, ghst_address, INITIAL_USER_BALANCE))
                conn.commit()
                session['username'] = username
                session['pub_key'] = ghst_address
                session['pub_key_hash'] = public_key_hash
                session['balance'] = INITIAL_USER_BALANCE
                conn.close()
                return redirect(url_for('dashboard'))
            except sqlite3.IntegrityError:
                pass
        conn.close()
        L = LANGUAGES[session.get('lang', 'tr')]
        current_mined_supply = blockchain_mgr.get_current_mined_supply()
        remaining_supply = TOTAL_SUPPLY - current_mined_supply
        active_peers_count = mesh_mgr.get_active_peers()
        return render_template_string(LOGIN_UI, lang=L, error="Kullanıcı adı veya şifre hatalı.", active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('username'): return redirect(url_for('dashboard'))
    L = LANGUAGES[session.get('lang', 'tr')]
    error = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        password_confirm = request.form['password_confirm']
        public_key_hash, ghst_address = generate_user_keys(username)
        if password != password_confirm:
            error = "Şifreler uyuşmuyor."
        else:
            conn = db.get_connection()
            try:
                conn.execute("INSERT INTO users (username, password, wallet_public_key, balance) VALUES (?, ?, ?, ?)", (username, password, ghst_address, INITIAL_USER_BALANCE))
                conn.commit()
                conn.close()
                session['username'] = username
                session['pub_key'] = ghst_address
                session['pub_key_hash'] = public_key_hash
                session['balance'] = INITIAL_USER_BALANCE
                return redirect(url_for('dashboard'))
            except sqlite3.IntegrityError:
                error = "Bu kullanıcı adı zaten alınmış."
            finally:
                conn.close()
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    active_peers_count = mesh_mgr.get_active_peers()
    return render_template_string(REGISTER_UI, lang=L, error=error, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    pub_key_ghst_address = session.get('pub_key')
    if not pub_key_ghst_address: return redirect(url_for('logout'))
    message = None
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'register_domain':
            domain_name = request.form['domain_name']
            content = "" 
            success, msg = assets_mgr.register_asset(pub_key_ghst_address, 'domain', domain_name, content)
            if success: message = msg
            else: error = msg
        elif action == 'upload_media':
            if 'file' in request.files:
                uploaded_file = request.files['file']
                if uploaded_file.filename != '':
                    name_lower = uploaded_file.filename.lower()
                    if name_lower.endswith(('.png', '.jpg', '.jpeg', '.gif')): asset_type = 'image'
                    elif name_lower.endswith(('.css')): asset_type = 'css'
                    elif name_lower.endswith(('.js')): asset_type = 'js'
                    elif name_lower.endswith(('.woff', '.ttf', '.woff2')): asset_type = 'font'
                    elif name_lower.endswith(('.mp4', '.webm')): asset_type = 'video'
                    elif name_lower.endswith(('.mp3', '.wav')): asset_type = 'audio'
                    else: asset_type = 'file'
                    success, msg = assets_mgr.register_asset(pub_key_ghst_address, asset_type, uploaded_file.filename, uploaded_file, is_file=True)
                    if success: message = msg
                    else: error = msg
                else: error = "Lütfen bir dosya seçin."
            else: error = "Dosya yüklenemedi."
        elif action == 'delete_asset':
            asset_id = request.form['asset_id']
            success, msg = assets_mgr.delete_asset(asset_id, pub_key_ghst_address)
            if success: message = msg
            else: error = msg
    conn = db.get_connection()
    assets = conn.execute("SELECT * FROM assets WHERE owner_pub_key = ? ORDER BY creation_time DESC", (pub_key_ghst_address,)).fetchall()
    user_data = conn.execute("SELECT balance FROM users WHERE wallet_public_key = ?", (pub_key_ghst_address,)).fetchone()
    if user_data: session['balance'] = user_data['balance']
    conn.close()
    transactions = tx_mgr.get_last_transactions(pub_key_ghst_address)
    qr_code_link = generate_qr_code_link(pub_key_ghst_address)
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    active_peers_count = mesh_mgr.get_active_peers()
    return render_template_string(DASHBOARD_UI, lang=L, assets=assets, transactions=transactions, user_ghst_address=pub_key_ghst_address, user_pub_key_hash=session.get('pub_key_hash', 'N/A'), qr_code_link=qr_code_link, error=error, message=message, DOMAIN_REGISTRATION_FEE=DOMAIN_REGISTRATION_FEE, STORAGE_COST_PER_MB=STORAGE_COST_PER_MB, calculate_asset_fee=calculate_asset_fee, datetime=datetime, url_for=url_for, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/mining', methods=['GET', 'POST'])
def mining():
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    pub_key_ghst_address = session['pub_key']
    conn = db.get_connection()
    user = conn.execute("SELECT last_mined FROM users WHERE wallet_public_key = ?", (pub_key_ghst_address,)).fetchone()
    last_mined_time = user['last_mined'] if user else 0
    conn.close()
    current_time = time.time()
    can_mine = (current_time - last_mined_time) >= 86400
    last_block = blockchain_mgr.get_last_block()
    current_block_index = last_block['block_index']
    active_peers = mesh_mgr.get_active_peers()
    difficulty = calculate_difficulty(active_peers)
    reward = blockchain_mgr.calculate_block_reward(current_block_index + 1)
    next_halving_block = ((current_block_index // HALVING_INTERVAL) + 1) * HALVING_INTERVAL
    new_hash = None
    error = None
    message = None
    if request.method == 'POST':
        if not can_mine:
            remaining_seconds = 86400 - (current_time - last_mined_time)
            remaining_time = str(timedelta(seconds=int(remaining_seconds)))
            error = f"{L['mine_limit_error']} {remaining_time}"
        elif reward == 0.0:
            error = "Madencilik ödülü 0'a ulaştı. Yeni GHOST coin basılamaz."
        else:
            last_proof = last_block['proof']
            proof = blockchain_mgr.proof_of_work(last_proof, difficulty)
            new_block = blockchain_mgr.new_block(proof, pub_key_ghst_address)
            new_hash = new_block['hash'] if new_block else None
            if new_hash:
                conn = db.get_connection()
                try:
                    conn.execute("UPDATE users SET last_mined = ? WHERE wallet_public_key = ?", (time.time(), pub_key_ghst_address))
                    conn.commit()
                except Exception as e:
                    logger.error(f"Error updating last_mined: {e}")
                finally:
                    conn.close()
                message = L['mine_success'] + f". {L['mine_message'].replace('{{ block_hash }}', new_hash[:8] + '...').replace('{{ reward }}', str(round(reward, 4)))}"
                last_block = blockchain_mgr.get_last_block()
            else:
                error = "Blok zincirine blok eklenirken hata."
    conn = db.get_connection()
    user = conn.execute("SELECT last_mined FROM users WHERE wallet_public_key = ?", (pub_key_ghst_address,)).fetchone()
    last_mined_time = user['last_mined'] if user else 0
    conn.close()
    current_time = time.time()
    can_mine = (current_time - last_mined_time) >= 86400
    remaining_seconds = max(0, 86400 - (current_time - last_mined_time))
    remaining_time = str(timedelta(seconds=int(remaining_seconds)))
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    return render_template_string(MINING_UI, lang=L, last_block=last_block, difficulty=difficulty, current_reward=reward, next_halving=next_halving_block, new_hash=new_hash, error=error, message=message, can_mine=can_mine, remaining_time=remaining_time, active_peers_count=active_peers, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/view/<asset_id>')
def view_asset(asset_id):
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    conn = db.get_connection()
    asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
    conn.close()
    if not asset: return f"Varlık bulunamadı. ({asset_id})", 404
    content_bytes = asset['content']
    name_lower = asset['name'].lower()
    active_peers_count = mesh_mgr.get_active_peers()
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    
    if asset['type'] == 'domain':
        try:
            clean_content = content_bytes.decode('utf-8', errors='ignore')
            clean_content = re.sub(r'<script.*?>.*?</script>', '', clean_content, flags=re.DOTALL | re.IGNORECASE)
            return render_template_string(ASSET_VIEW_UI, domain_html_content=clean_content, asset=dict(asset), url_for=url_for)
        except Exception as e:
            return f"Domain hatası: {e}", 500
            
    if asset['type'] in ['image', 'css', 'js', 'font', 'video', 'audio', 'file']:
        mime_type = 'application/octet-stream' 
        if name_lower.endswith(('.css')): mime_type = 'text/css'
        elif name_lower.endswith(('.js')): mime_type = 'application/javascript'
        elif name_lower.endswith(('.woff', '.ttf', '.woff2')): mime_type = 'font/woff' 
        elif name_lower.endswith(('.jpg', '.jpeg')): mime_type = 'image/jpeg'
        elif name_lower.endswith(('.png')): mime_type = 'image/png'
        elif name_lower.endswith(('.gif')): mime_type = 'image/gif'
        elif name_lower.endswith(('.mp4', '.webm')): mime_type = 'video/mp4'
        elif name_lower.endswith(('.mp3', '.wav')): mime_type = 'audio/mpeg'
        return Response(content_bytes, mimetype=mime_type, headers={'Content-Disposition': f'inline; filename="{asset["name"]}"'})

    return render_template_string(ASSET_DETAILS_UI, asset=dict(asset), L=L, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/search', methods=['GET'])
def search_content():
    L = LANGUAGES[session.get('lang', 'tr')]
    query = request.args.get('query', '').strip()
    results = []
    if query:
        results = assets_mgr.search_assets(query)
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    active_peers_count = mesh_mgr.get_active_peers()
    return render_template_string(SEARCH_UI, lang=L, query=query, results=results, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/edit_asset/<asset_id>', methods=['GET', 'POST'])
def edit_asset(asset_id):
    if not session.get('username'): return redirect(url_for('login'))
    L = LANGUAGES[session.get('lang', 'tr')]
    pub_key_ghst_address = session['pub_key']
    conn = db.get_connection()
    asset = conn.execute("SELECT * FROM assets WHERE asset_id = ? AND owner_pub_key = ?", (asset_id, pub_key_ghst_address)).fetchone()
    current_mined_supply = blockchain_mgr.get_current_mined_supply()
    remaining_supply = TOTAL_SUPPLY - current_mined_supply
    active_peers_count = mesh_mgr.get_active_peers()
    
    if not asset:
        conn.close()
        return redirect(url_for('dashboard'))
    try:
        asset_content = asset['content'].decode('utf-8', errors='ignore')
    except Exception:
        asset_content = ""
        
    error = None
    if request.method == 'POST':
        new_content = request.form['content']
        success, msg = assets_mgr.update_asset_content(asset_id, pub_key_ghst_address, new_content)
        if success:
             return redirect(url_for('dashboard'))
        else:
             error = msg
             
    conn.close()
    return render_template_string(EDIT_ASSET_UI, lang=L, asset=dict(asset), asset_content=asset_content, error=error, url_for=url_for, active_peers_count=active_peers_count, TOTAL_SUPPLY=TOTAL_SUPPLY, current_mined_supply=current_mined_supply, remaining_supply=remaining_supply)

@app.route('/peer_update', methods=['POST'])
def peer_update():
    data = request.get_json()
    ip_address = request.remote_addr 
    if data and 'ip_address' in data: ip_address = data['ip_address'] 
    if ip_address:
        if mesh_mgr.register_peer(ip_address): return jsonify({'message': 'Updated'}), 200
        else: return jsonify({'error': 'Failed'}), 500
    return jsonify({'error': 'Invalid'}), 400

if __name__ == '__main__':
    def format_thousands(value):
        try: return f"{float(value):,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except: return str(value)
    app.jinja_env.filters['thousands'] = format_thousands
    
    app.jinja_env.loader = DictLoader({
        'base.html': LAYOUT, 
        'dashboard.html': DASHBOARD_UI,
        'login.html': LOGIN_UI, 
        'register.html': REGISTER_UI, 
        'mining.html': MINING_UI,
        'search.html': SEARCH_UI,
        'asset_details.html': ASSET_DETAILS_UI,
        'edit_asset.html': EDIT_ASSET_UI
    })
    
    print("--- GHOST SERVER STARTED ---")
    app.run(host='0.0.0.0', port=GHOST_PORT, debug=True, threaded=True)
