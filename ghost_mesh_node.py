import hashlib
import json
import time
import sqlite3
import base64
import random
import socket
import threading
import sys
import os
import requests
from uuid import uuid4
from datetime import timedelta
from typing import Optional, Tuple, Dict, Any, List

# --- CİHAZ ÖZELİNDE MESH/AĞ MODÜLLERİ (Mobil/Gömülü Cihazlar İçin) ---
# TR: Bluetooth ve WiFi modülleri için yer tutucular. 
# EN: Placeholders for Bluetooth and WiFi modules.
# TR: Gerçek uygulamada bu kısımlar pybluez, Bleak veya yerel WiFi API'leri ile değiştirilecektir.
# EN: In a real application, these parts would be replaced with pybluez, Bleak, or local WiFi APIs.
try:
    import bluetooth # Örn. pybluez
    BLUETOOTH_AVAILABLE = True
except ImportError:
    BLUETOOTH_AVAILABLE = False
    
try:
    # WiFi modülü yerine IP/Socket modülü kullanacağız.
    WIFI_AVAILABLE = True 
except Exception:
    WIFI_AVAILABLE = False

# --- LOGLAMA / LOGGING ---
# TR: Basit loglama (Flask kullanmadığımız için print veya logging modülü yeterli)
# EN: Simple logging (print or logging module is sufficient as we don't use Flask for UI)
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - GhostNode - %(levelname)s - %(message)s')
logger = logging.getLogger("GhostMeshNode")

# --- YAPILANDIRMA / CONFIGURATION (Sunucu ile Eşleşmeli) ---
NODE_ID = hashlib.sha256(socket.gethostname().encode()).hexdigest()[:10]
DB_FILE = os.path.join(os.getcwd(), f"ghost_node_{NODE_ID}.db") 

# TR: Merkezi Sunucu Adresi (Geliştirme ortamı için localhost, prodüksiyonda gerçek IP olmalı)
# EN: Central Server Address (localhost for dev, real IP for production)
GHOST_SERVER_URL = "http://127.0.0.1:5000" 

# TR: Varlık Ücretleri (ghost_server.py ile Eşleşmeli)
# EN: Asset Fees (Must match ghost_server.py)
STORAGE_COST_PER_MB = 0.01       # TR: Veri barındırma ücreti: MB başı 0.01 GHOST
DOMAIN_REGISTRATION_FEE = 1.0    # TR: 6 Aylık Domain Tescil Ücreti: 1.0 GHOST
DOMAIN_EXPIRY_SECONDS = 15552000 # 6 Ay

# --- ÇOKLU DİL SÖZLÜĞÜ (Sunucu ile Eşleşmeli) ---
LANGUAGES = {
    'tr': {
        'node_name': "Ghost Node", 'search': "Arama", 'register': "Kaydet", 'wallet': "Cüzdan",
        'domain_title': f"💾 .ghost Kayıt (Ücret: {DOMAIN_REGISTRATION_FEE} GHOST / 6 Ay)",
        'media_title': f"🖼️ Varlık Yükle (Barındırma Ücreti: {STORAGE_COST_PER_MB} GHOST / MB)",
        'status_online': "ONLINE", 'status_offline': "OFFLINE", 'status_mesh_active': "Mesh Aktif",
        'asset_fee': "Ücret", 'asset_expires': "Süre Sonu", 'asset_type': "Tip",
        'no_pubkey': "Lütfen cüzdan genel anahtarınızı ayarlayın.",
        'balance': "Bakiye", 'not_enough_balance': "Yetersiz bakiye.",
        'menu_prompt': "Seçiminiz", 'exit': "Çıkış", 'sync': "Ağı Eşitle"
    },
    'en': {
        'node_name': "Ghost Node", 'search': "Search", 'register': "Register", 'wallet': "Wallet",
        'domain_title': f"💾 .ghost Registration (Fee: {DOMAIN_REGISTRATION_FEE} GHOST / 6 Months)",
        'media_title': f"🖼️ Upload Asset (Storage Fee: {STORAGE_COST_PER_MB} GHOST / MB)",
        'status_online': "ONLINE", 'status_offline': "OFFLINE", 'status_mesh_active': "Mesh Active",
        'asset_fee': "Fee", 'asset_expires': "Expires", 'asset_type': "Type",
        'no_pubkey': "Please set your wallet public key.",
        'balance': "Balance", 'not_enough_balance': "Insufficient balance.",
        'menu_prompt': "Your Choice", 'exit': "Exit", 'sync': "Sync Network"
    },
    'ru': {
        'node_name': "Узел Ghost", 'search': "Поиск", 'register': "Регистрация", 'wallet': "Кошелек",
        'domain_title': f"💾 Регистрация .ghost (Плата: {DOMAIN_REGISTRATION_FEE} GHOST / 6 Месяцев)",
        'media_title': f"🖼️ Загрузить Актив (Плата: {STORAGE_COST_PER_MB} GHOST / МБ)",
        'status_online': "ОНЛАЙН", 'status_offline': "ОФФЛАЙН", 'status_mesh_active': "Mesh Активен",
        'asset_fee': "Плата", 'asset_expires': "Срок", 'asset_type': "Тип",
        'no_pubkey': "Пожалуйста, настройте публичный ключ кошелька.",
        'balance': "Баланс", 'not_enough_balance': "Недостаточно средств.",
        'menu_prompt': "Ваш выбор", 'exit': "Выход", 'sync': "Синхронизация"
    },
    'hy': {
        'node_name': "Ghost Հանգույց", 'search': "Որոնում", 'register': "Գրանցվել", 'wallet': "Դրամապանակ",
        'domain_title': f"💾 .ghost Գրանցում (Վճար: {DOMAIN_REGISTRATION_FEE} GHOST / 6 Ամիս)",
        'media_title': f"🖼️ Բեռնել Ակտիվ (Վճար: {STORAGE_COST_PER_MB} GHOST / MB)",
        'status_online': "ԱՌՑԱՆՑ", 'status_offline': "ԱՆՑԱՆՑ", 'status_mesh_active': "Mesh Ակտիվ",
        'asset_fee': "Վճար", 'asset_expires': "Ժամկետը", 'asset_type': "Տեսակ",
        'no_pubkey': "Խնդրում ենք սահմանել ձեր դրամապանակի հանրային բանալին:",
        'balance': "Մնացորդ", 'not_enough_balance': "Անբավարար մնացորդ:",
        'menu_prompt': "Ընտրություն", 'exit': "Ելք", 'sync': "Սինխրոնիզացնել"
    }
}
DEFAULT_LANG = 'tr'

# --- YARDIMCI FONKSİYONLAR (Sunucu ile Eşleşmeli) ---

def extract_keywords(content_str):
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

def calculate_asset_fee(size_bytes: int, asset_type: str) -> float:
    if asset_type == 'domain':
        return DOMAIN_REGISTRATION_FEE
    else:
        return round((size_bytes / (1024 * 1024)) * STORAGE_COST_PER_MB, 5)

# --- VERİTABANI YÖNETİCİSİ / DATABASE MANAGER ---
class DatabaseManager:
    # TR: SQLite veritabanı işlemlerini yönetir.
    # EN: Manages SQLite database operations.
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
        
        # TR: Kullanıcı konfigürasyonu (Cüzdan/Bakiye vb. için basit Key-Value)
        # EN: User configuration (Simple Key-Value for Wallet/Balance etc.)
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_config (key TEXT PRIMARY KEY, value TEXT)''')
        
        # TR: Düğümde kayıtlı varlıklar (Yerel Barındırma)
        # EN: Assets registered on the node (Local Hosting)
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, keywords TEXT)''')
        
        # TR: Varsayılan Bakiye ve Anahtar Kontrolü (Simülasyon için)
        # EN: Default Balance and Key Check (For simulation)
        cursor.execute("INSERT OR IGNORE INTO user_config (key, value) VALUES (?, ?)", ('balance', '50.0'))
        
        # Simüle edilmiş bir GHST adresi
        sim_hash = hashlib.sha256(NODE_ID.encode()).hexdigest()[:20]
        sim_address = f"GHST{sim_hash}"
        cursor.execute("INSERT OR IGNORE INTO user_config (key, value) VALUES (?, ?)", ('pub_key', sim_address))
        
        conn.commit()
        conn.close()

    def get_config(self, key):
        conn = self.get_connection()
        result = conn.execute("SELECT value FROM user_config WHERE key = ?", (key,)).fetchone()
        conn.close()
        return result['value'] if result else None

    def set_config(self, key, value):
        conn = self.get_connection()
        conn.execute("INSERT OR REPLACE INTO user_config (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
    
    def get_assets(self):
        conn = self.get_connection()
        assets = conn.execute("SELECT * FROM assets ORDER BY creation_time DESC").fetchall()
        conn.close()
        return assets

# --- MESH AĞI İLETİŞİM YÖNETİCİSİ / MESH NETWORK COMMS MANAGER ---
class MeshCommsManager:
    def __init__(self, db_manager: DatabaseManager, server_url: str):
        self.db = db_manager
        self.server_url = server_url
        self.node_ip = self._get_local_ip()

    def _get_local_ip(self) -> str:
        # TR: Yerel IP adresini bulmaya çalışır.
        # EN: Tries to find the local IP address.
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def send_to_server(self, endpoint: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # TR: Merkezi sunucuya veri gönderir (IP/HTTP)
        # EN: Sends data to the central server (IP/HTTP)
        url = f"{self.server_url}{endpoint}"
        try:
            response = requests.post(url, json=data, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Sessizce hata ver (Offline modu)
            return None

    def announce_presence(self):
        # TR: Merkezi sunucuya varlığını bildirir (Mesh Peer Update)
        # EN: Announces presence to the central server (Mesh Peer Update)
        data = {'ip_address': self.node_ip, 'node_id': NODE_ID}
        self.send_to_server('/peer_update', data)
        # logger.info(f"Node presence announced to server ({self.node_ip}).")
        
    # --- MESH (BT/WiFi) YEREL KEŞİF YER TUTUCULARI ---

    def discover_local_peers(self):
        # TR: Bluetooth ve WiFi üzerinden çevredeki cihazları keşfetme mantığı.
        # EN: Logic to discover nearby devices via Bluetooth and WiFi.
        pass # Simülasyon, log kalabalığı yapmamak için boş

# --- ASSET MANAGER (Yerel Cihaz İçin) ---
class NodeAssetManager:
    def __init__(self, db_manager: DatabaseManager, comms_manager: MeshCommsManager):
        self.db = db_manager
        self.comms = comms_manager

    def register_asset(self, asset_type: str, name: str, content: str | bytes, is_file: bool = False) -> Tuple[bool, str]:
        """
        TR: Varlığı yerel olarak kaydeder ve ücreti bakiyeden düşer.
        EN: Registers the asset locally and deducts the fee from the balance.
        """
        pub_key = self.db.get_config('pub_key')
        if not pub_key:
            return False, "Pubkey not set."

        if isinstance(content, str) and not is_file:
            content_bytes = content.encode('utf-8')
            keywords = extract_keywords(content) if asset_type == 'domain' else ""
        elif is_file:
            # content'in bytes olduğu varsayılır
            content_bytes = content
            keywords = ""
        else:
            content_bytes = content
            keywords = ""

        size = len(content_bytes)
        fee = calculate_asset_fee(size, asset_type)
        
        current_balance_str = self.db.get_config('balance')
        current_balance = float(current_balance_str) if current_balance_str else 0.0

        if current_balance < fee:
            # Basit dil kontrolü (hata mesajı için)
            return False, f"Yetersiz Bakiye ({fee:.4f} GHOST gerekli)"
        
        asset_id = str(uuid4())
        
        conn = self.db.get_connection()
        try:
            # 1. Yerel veritabanına kaydet
            conn.execute("INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (asset_id, pub_key, asset_type, name, content_bytes, size, time.time(), time.time() + DOMAIN_EXPIRY_SECONDS, keywords))
            
            # 2. Bakiyeyi güncelle
            new_balance = current_balance - fee
            self.db.set_config('balance', new_balance)
            
            # 3. Merkezi Sunucuya Bildirim (Opsiyonel - İleride eklenebilir)
            
            conn.commit()
            conn.close()
            return True, f"Başarılı. Ücret: {fee:.4f} GHOST. Yeni Bakiye: {new_balance:.4f}"
        except Exception as e:
            logger.error(f"Yerel varlık kaydı başarısız: {e}")
            conn.close()
            return False, str(e)

# --- TERMİNAL ARAYÜZÜ (CLI) ---
class GhostMeshNodeCLI:
    def __init__(self):
        self.db = DatabaseManager(DB_FILE)
        self.comms = MeshCommsManager(self.db, GHOST_SERVER_URL)
        self.asset_mgr = NodeAssetManager(self.db, self.comms)
        self.lang_code = DEFAULT_LANG
        self.L = LANGUAGES[self.lang_code]

    def clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_header(self):
        self.clear_screen()
        print(f"========================================")
        print(f"   👻 GHOST PROTOCOL MESH NODE (CLI)   ")
        print(f"   ID: {NODE_ID} | IP: {self.comms.node_ip}")
        print(f"========================================\n")

    def select_language(self):
        print("1. Türkçe\n2. English\n3. Русский\n4. Հայերեն")
        choice = input("Language / Dil: ")
        if choice == '1': self.lang_code = 'tr'
        elif choice == '2': self.lang_code = 'en'
        elif choice == '3': self.lang_code = 'ru'
        elif choice == '4': self.lang_code = 'hy'
        self.L = LANGUAGES.get(self.lang_code, LANGUAGES['tr'])

    def run(self):
        self.select_language()
        
        # Başlangıçta sunucuya bildirim
        self.comms.announce_presence()

        while True:
            self.print_header()
            self.display_status()
            
            print(f"\n--- {self.L['menu_prompt']} ---")
            print(f"1. {self.L['register']} (.ghost Domain)")
            print(f"2. {self.L['register']} (Media/File)")
            print(f"3. {self.L['search']}")
            print(f"4. {self.L['sync']}")
            print(f"5. {self.L['exit']}")
            
            choice = input("> ")
            
            if choice == '1':
                self.register_domain_ui()
            elif choice == '2':
                self.register_media_ui()
            elif choice == '3':
                self.search_ui()
            elif choice == '4':
                print(f"\n{self.L['sync']}...")
                self.comms.announce_presence()
                time.sleep(1)
            elif choice == '5':
                print("Bye!")
                break

    def display_status(self):
        pub_key = self.db.get_config('pub_key')
        balance = self.db.get_config('balance')
        assets = self.db.get_assets()
        
        # Sunucu durumunu kontrol et (Basit ping)
        server_status = self.L['status_online'] if self.comms.send_to_server('/', {}) is None else self.L['status_online'] # Basit hack, None dönmüyorsa online varsay
        mesh_status = self.L['status_mesh_active'] if (BLUETOOTH_AVAILABLE or WIFI_AVAILABLE) else self.L['status_offline']

        print(f"[{self.L['status_online']}] Server: {GHOST_SERVER_URL}")
        print(f"[{mesh_status}] Mesh: {'BT' if BLUETOOTH_AVAILABLE else ''} {'WiFi' if WIFI_AVAILABLE else ''}")
        print(f"💰 {self.L['balance']}: {float(balance):.4f} GHOST")
        print(f"🔑 {self.L['wallet']}: {pub_key}")
        print(f"\n📂 {self.L['assets_title']} ({len(assets)}):")
        
        for a in assets[:5]:
            fee = calculate_asset_fee(a['storage_size'], a['type'])
            print(f" - [{a['type'].upper()}] {a['name']} ({fee:.4f} GHOST)")
        if len(assets) > 5: print(" ...")

    def register_domain_ui(self):
        print(f"\n--- {self.L['domain_title']} ---")
        name = input("Domain (.ghost): ")
        if not name.endswith(".ghost"): name += ".ghost"
        
        print("(Enter to skip content for now)")
        content = input("HTML Content: ")
        
        success, msg = self.asset_mgr.register_asset('domain', name, content)
        print(f"\n>> {msg}")
        input("Press Enter...")

    def register_media_ui(self):
        print(f"\n--- {self.L['media_title']} ---")
        path = input("File Path: ")
        
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    content = f.read()
                name = os.path.basename(path)
                
                # Basit tip tahmini
                ext = name.split('.')[-1].lower()
                atype = 'image' if ext in ['png','jpg'] else 'file'
                if ext in ['css']: atype = 'css'
                elif ext in ['js']: atype = 'js'
                
                success, msg = self.asset_mgr.register_asset(atype, name, content, is_file=True)
                print(f"\n>> {msg}")
            except Exception as e:
                print(f"\n>> Error: {e}")
        else:
            print("\n>> File not found.")
        input("Press Enter...")

    def search_ui(self):
        print(f"\n--- {self.L['search']} ---")
        q = input("Query: ")
        
        # Yerel Arama
        local_res = [a for a in self.db.get_assets() if q in a['name'] or (a['keywords'] and q in a['keywords'])]
        print(f"Local Results: {len(local_res)}")
        for r in local_res: print(f" - {r['name']}")
        
        input("Press Enter...")

if __name__ == '__main__':
    node = GhostMeshNodeCLI()
    try:
        node.run()
    except KeyboardInterrupt:
        print("\nKapatılıyor...")
