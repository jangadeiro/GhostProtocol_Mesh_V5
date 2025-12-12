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
import logging
import requests
import traceback

# --- LOGLAMA / LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - GhostMeshNode - %(levelname)s - %(message)s')
logger = logging.getLogger("GhostMeshNode")

# --- YAPILANDIRMA / CONFIGURATION ---
MAX_SUPPLY = 100_000_000
STORAGE_COST_PER_MB_MONTHLY = 0.01
GRACE_PERIOD_SECONDS = 86400  # 24 Saat / 24 Hours
DB_FILE = "ghost_v5.db"

# Mesh Ayarları / Mesh Settings
MESH_PORT = 9999        # UDP Broadcast Portu / UDP Broadcast Port
GHOST_PORT = 5000       # HTTP API Portu / HTTP API Port
GHOST_BEACON_MSG = b"GHOST_PROTOCOL_NODE_HERE"
BLUETOOTH_UUID = "00001101-0000-1000-8000-00805F9B34FB" # GhostProtocol Özel ID / GhostProtocol Custom ID

app = Flask(__name__)
app.secret_key = "mesh_secret_key" # Session yönetimi için / For session management

# --- ÇOKLU DİL SÖZLÜĞÜ / MULTI-LANGUAGE DICTIONARY ---
LANGUAGES = {
    'tr': {
        'status_online': "ONLINE", 'status_offline': "OFFLINE", 'status_sync': "SENKRONİZE",
        'server': "Sunucu", 'mesh_active': "Mesh Aktif", 'mesh_status': "Durum", 
        'wallet_balance': "💰 Bakiye", 'wallet_address': "🔑 Cüzdan",
        'last_block': "Son Blok", 'peers': "Peer",
        'wifi': "WiFi", 'bluetooth': "Bluetooth", 'unknown': "Bilinmiyor",
        'server_sync_success': "✅ Sunucu ile senkronizasyon başarılı.",
        'server_sync_fail': "❌ Sunucuya erişilemiyor: ",
        'menu_select': "Menüden seçim yapın:",
        'menu_sync': "Zinciri Senkronize Et",
        'menu_mine': "Madencilik Yap",
        'menu_asset': "Varlık Yükle/Klonla (Web UI)",
        'menu_exit': "Çıkış",
        'enter_asset_id': "Klonlanacak Varlık ID'sini girin:",
        'enter_file_path': "Yüklenecek dosyanın yolunu girin:",
        'enter_asset_name': "Varlık Adını Girin (örn: domain.ghost):",
        'enter_asset_content': "Varlık İçeriğini Girin (HTML):",
        'asset_type_menu': "Yükleme Tipini Seçin:",
        'type_domain': "1. Domain (.ghost)",
        'type_image': "2. Görsel",
        'type_video': "3. Video",
        'type_audio': "4. Ses",
        'upload_success': "✅ Varlık başarıyla yüklendi/kaydedildi.",
        'upload_fail': "❌ Varlık yükleme/kayıt hatası: ",
        'clone_success': "✅ Varlık başarıyla klonlandı.",
        'clone_fail': "❌ Varlık klonlama hatası: ",
        'assets_title': "Varlıklar", # <--- Düzeltme: Eksik anahtar eklendi
    },
    'en': {
        'status_online': "ONLINE", 'status_offline': "OFFLINE", 'status_sync': "SYNCED",
        'server': "Server", 'mesh_active': "Mesh Active", 'mesh_status': "Status",
        'wallet_balance': "💰 Balance", 'wallet_address': "🔑 Wallet",
        'last_block': "Last Block", 'peers': "Peers",
        'wifi': "WiFi", 'bluetooth': "Bluetooth", 'unknown': "Unknown",
        'server_sync_success': "✅ Synchronization with server successful.",
        'server_sync_fail': "❌ Cannot reach server: ",
        'menu_select': "Select from the menu:",
        'menu_sync': "Synchronize Chain",
        'menu_mine': "Mine Block",
        'menu_asset': "Upload/Clone Asset (Web UI)",
        'menu_exit': "Exit",
        'enter_asset_id': "Enter Asset ID to clone:",
        'enter_file_path': "Enter path of file to upload:",
        'enter_asset_name': "Enter Asset Name (e.g., domain.ghost):",
        'enter_asset_content': "Enter Asset Content (HTML):",
        'asset_type_menu': "Select Upload Type:",
        'type_domain': "1. Domain (.ghost)",
        'type_image': "2. Image",
        'type_video': "3. Video",
        'type_audio': "4. Audio",
        'upload_success': "✅ Asset uploaded/registered successfully.",
        'upload_fail': "❌ Asset upload/registration failed: ",
        'clone_success': "✅ Asset cloned successfully.",
        'clone_fail': "❌ Asset cloning failed: ",
        'assets_title': "Assets", # <--- Düzeltme: Eksik anahtar eklendi
    }
}


# --- VERİTABANI YÖNETİCİSİ / DATABASE MANAGER ---
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
        
        # Kullanıcılar
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT, pub_key TEXT, priv_key TEXT)''')
        
        # Varlıklar: owner_pub_key artık owner_node_ip'den ayrı
        cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, keywords TEXT)''')
        
        # Blockchain
        cursor.execute('''CREATE TABLE IF NOT EXISTS blockchain (index INTEGER PRIMARY KEY, timestamp REAL, transactions TEXT, proof INTEGER, previous_hash TEXT, hash TEXT, mined_by TEXT)''')
        
        # İşlemler
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT, amount REAL, timestamp REAL)''')
        
        # Peerler: Hem Mesh hem de ana sunucuları içerir
        cursor.execute('''CREATE TABLE IF NOT EXISTS peers (address TEXT PRIMARY KEY, type TEXT, last_seen REAL)''')
        
        # Genesis Blok Kontrolü ve Yaratma
        if cursor.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0] == 0:
            genesis_hash = hashlib.sha256("GenesisBlock_GhostProtocol_Mesh_v1".encode()).hexdigest()
            cursor.execute("INSERT INTO blockchain (index, timestamp, transactions, proof, previous_hash, hash, mined_by) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (1, time.time(), '[]', 1, '0', genesis_hash, 'GhostProtocol_System'))
        
        conn.commit()
        conn.close()

# --- BLOCKCHAIN YÖNETİCİSİ / BLOCKCHAIN MANAGER ---
class BlockchainManager:
    def __init__(self, db_manager):
        self.db = db_manager
        # ... (Diğer başlatma mantığı aynı kalır)

    def hash(self, block):
        block_string = json.dumps(dict(block), sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self, last_proof, difficulty=4):
        proof = 0
        while self.valid_proof(last_proof, proof, self.get_last_block()['previous_hash'], difficulty) is False:
            proof += 1
        return proof
    
    def valid_proof(self, last_proof, proof, previous_hash, difficulty):
        guess = f'{last_proof}{proof}{previous_hash}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:difficulty] == '0' * difficulty
        
    def get_last_block(self):
        conn = self.db.get_connection()
        last_block = conn.execute("SELECT * FROM blockchain ORDER BY index DESC LIMIT 1").fetchone()
        conn.close()
        return dict(last_block) if last_block else None

    def get_chain_length(self):
        conn = self.db.get_connection()
        length = conn.execute("SELECT COUNT(*) FROM blockchain").fetchone()[0]
        conn.close()
        return length

    def get_balance(self, pub_key):
        conn = self.db.get_connection()
        # Tüm işlemleri (gönderilenler ve alınanlar) topla
        sent = conn.execute("SELECT SUM(amount) FROM transactions WHERE sender = ?", (pub_key,)).fetchone()[0] or 0.0
        received = conn.execute("SELECT SUM(amount) FROM transactions WHERE recipient = ?", (pub_key,)).fetchone()[0] or 0.0
        
        # Varlık ücretleri (Gönderen = pub_key ise bakiye azalır)
        fee_transactions = conn.execute("SELECT amount FROM transactions WHERE sender = ? AND recipient = 'GhostProtocol_Fee_Wallet'", (pub_key,)).fetchall()
        asset_fees = sum([t['amount'] for t in fee_transactions]) if fee_transactions else 0.0
        
        conn.close()
        return received - sent - asset_fees

    def get_transactions(self, pub_key):
        conn = self.db.get_connection()
        transactions = conn.execute("SELECT * FROM transactions WHERE sender = ? OR recipient = ? ORDER BY timestamp DESC LIMIT 10", (pub_key, pub_key)).fetchall()
        conn.close()
        return [dict(t) for t in transactions]

    def mine_block(self, pub_key, difficulty=4, reward=10.0):
        # Basit madencilik mantığı (Hemen ödül gönderimi ile)
        last_block = self.get_last_block()
        if not last_block: return False
        
        last_proof = last_block['proof']
        proof = self.proof_of_work(last_proof, difficulty)
        
        previous_hash = self.hash(last_block)

        # Yeni blok oluştur
        new_block = {
            'index': last_block['index'] + 1,
            'timestamp': time.time(),
            'transactions': json.dumps([]),
            'proof': proof,
            'previous_hash': previous_hash,
            'hash': None, # Hash'i sonra hesaplayacağız
            'mined_by': pub_key
        }
        new_block['hash'] = self.hash(new_block)
        
        # Veritabanına kaydet
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT INTO blockchain (index, timestamp, transactions, proof, previous_hash, hash, mined_by) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (new_block['index'], new_block['timestamp'], new_block['transactions'], new_block['proof'], new_block['previous_hash'], new_block['hash'], new_block['mined_by']))
            
            # Madencilik ödülünü kaydet
            conn.execute("INSERT INTO transactions (tx_id, sender, recipient, amount, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (str(uuid4()), "GhostProtocol_Miner_System", pub_key, reward, time.time()))

            conn.commit()
            return new_block
        except Exception as e:
            logger.error(f"Blok kaydetme hatası: {e}")
            conn.close()
            return False
        finally:
            conn.close()

    def upload_asset(self, owner_key, asset_type, name, content):
        storage_size = len(content) if isinstance(content, bytes) else len(content.encode('utf-8', errors='ignore'))
        
        # Basit ücret hesaplama (Örnek)
        fee = round((storage_size / (1024 * 1024)) * STORAGE_COST_PER_MB_MONTHLY, 5)
        if asset_type == 'domain': fee = 1.0 # Domain için sabit ücret
        
        current_balance = self.get_balance(owner_key)

        if current_balance < fee:
            return False, f"Yetersiz bakiye ({fee:.4f} GHOST gerekli)."
        
        asset_id = str(uuid4())
        expiry_time = time.time() + (6 * 30 * 86400) # 6 Ay
        
        conn = self.db.get_connection()
        try:
            conn.execute("INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (asset_id, owner_key, asset_type, name, content, storage_size, time.time(), expiry_time, name))
            
            # İşlem kaydı (Ücret Kesintisi)
            conn.execute("INSERT INTO transactions (tx_id, sender, recipient, amount, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (str(uuid4()), owner_key, "GhostProtocol_Fee_Wallet", fee, time.time()))
            
            conn.commit()
            return True, f"Varlık başarıyla kaydedildi. Ücret: {fee:.4f} GHOST."
        except Exception as e:
            logger.error(f"Asset registration error: {e}")
            return False, f"Kayıt hatası: {e}"
        finally:
            conn.close()

    def get_user_assets(self, pub_key):
        conn = self.db.get_connection()
        assets = conn.execute("SELECT asset_id, type, name, storage_size, creation_time, expiry_time FROM assets WHERE owner_pub_key = ? ORDER BY creation_time DESC", (pub_key,)).fetchall()
        conn.close()
        return [dict(a) for a in assets]
        
    def clone_asset(self, asset_id, new_owner_key):
        conn = self.db.get_connection()
        original_asset = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        conn.close()
        
        if not original_asset:
            return False, "Varlık bulunamadı."

        original_asset = dict(original_asset)
        
        # Klonlama için ücret gerekebilir, burada basitlik için atlanmıştır.
        # Ücret mantığı burada uygulanmalıdır.
        
        new_asset_id = str(uuid4())
        # Klonlanan varlığın süresi aynı kalır veya yenilenir
        new_expiry_time = time.time() + (6 * 30 * 86400) 

        conn = self.db.get_connection()
        try:
            conn.execute("INSERT INTO assets (asset_id, owner_pub_key, type, name, content, storage_size, creation_time, expiry_time, keywords) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (new_asset_id, new_owner_key, original_asset['type'], f"CLONE-{original_asset['name']}", original_asset['content'], original_asset['storage_size'], time.time(), new_expiry_time, original_asset['keywords']))
            conn.commit()
            return True, f"Varlık başarıyla klonlandı: {new_asset_id}"
        except Exception as e:
            logger.error(f"Asset cloning error: {e}")
            return False, f"Klonlama hatası: {e}"
        finally:
            conn.close()

# --- MESH AĞI YÖNETİCİSİ / MESH NETWORK MANAGER ---
class MeshManager:
    # ... (MeshManager tanımı aynı kalır)

# ... (Kullanıcı Yönetimi, diğer sınıflar ve fonksiyonlar aynı kalır)

# --- USER MANAGER (Sadece Mesh Node'da gerekli olan minimum) ---
class UserManager:
    def __init__(self, db_manager):
        self.db = db_manager

    def login(self, username, password):
        conn = self.db.get_connection()
        user = conn.execute("SELECT pub_key, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and hashlib.sha256(password.encode()).hexdigest() == user['password_hash']:
            return user['pub_key']
        return None

    def register(self, username, password):
        conn = self.db.get_connection()
        try:
            # Anahtar Çifti Oluştur
            private_key, public_key = self.generate_key_pair()
            pub_key_hash = hashlib.sha256(public_key.encode()).hexdigest() # Cüzdan adresi
            
            # Kullanıcıyı kaydet
            conn.execute("INSERT INTO users (username, password_hash, pub_key, priv_key) VALUES (?, ?, ?, ?)",
                         (username, hashlib.sha256(password.encode()).hexdigest(), pub_key_hash, private_key))
            
            # Başlangıç bakiyesi ekle (Simülasyon)
            conn.execute("INSERT INTO transactions (tx_id, sender, recipient, amount, timestamp) VALUES (?, ?, ?, ?, ?)",
                         (str(uuid4()), "GhostProtocol_System", pub_key_hash, 50.0, time.time())) # 50 GHOST başlangıç
            
            conn.commit()
            return True, pub_key_hash
        except sqlite3.IntegrityError:
            return False, "Kullanıcı adı zaten mevcut."
        except Exception as e:
            logger.error(f"Kayıt hatası: {e}")
            return False, f"Bilinmeyen hata: {e}"
        finally:
            conn.close()

    def generate_key_pair(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        
        # PEM formatında kaydet
        pem_private = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

        pem_public = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        return pem_private, pem_public

# --- MESH AĞI YÖNETİCİSİ / MESH NETWORK MANAGER ---
class MeshManager:
    def __init__(self, node_address, db_manager, server_address):
        self.node_address = node_address
        self.db = db_manager
        self.server_address = server_address
        self.peers = set()
        self.is_connected = False
        self.is_syncing = False
        
        # UDP Broadcast
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.udp_socket.bind(('', MESH_PORT))

        # Peer keşif ve bakım döngüsü
        self.discovery_thread = threading.Thread(target=self._discovery_loop, daemon=True)
        self.maintenance_thread = threading.Thread(target=self._maintenance_loop, daemon=True)

    def _discovery_loop(self):
        while True:
            try:
                data, address = self.udp_socket.recvfrom(1024)
                if data == GHOST_BEACON_MSG and address[0] != self.node_address:
                    self.peers.add(f"http://{address[0]}:{GHOST_PORT}")
            except Exception as e:
                # Muhtemelen socket timeout veya başka bir hata.
                pass 
                
    def _maintenance_loop(self):
        while True:
            # 1. Ana Sunucu Durumunu Kontrol Et
            self.check_server_status()

            # 2. Peerlere Kendini Duyur
            self.announce_self()
            
            # 3. Kendi Zincirini Senkronize Et (Pasif Senkronizasyon)
            if self.is_connected and not self.is_syncing:
                 # Çok sık senkronizasyon yapmamak için bekle
                time.sleep(30)
                # self.sync_chain()
            
            time.sleep(60) # Her 60 saniyede bir kontrol et

    def announce_self(self):
        # UDP Broadcast ile kendini ağa duyur
        try:
            self.udp_socket.sendto(GHOST_BEACON_MSG, ('<broadcast>', MESH_PORT))
        except Exception as e:
            logger.error(f"UDP yayın hatası: {e}")

    def check_server_status(self):
        # Ana sunucuya ping at
        try:
            response = requests.post(f"{self.server_address}/peer_update", json={'ip_address': self.node_address}, timeout=5)
            if response.status_code == 200:
                self.is_connected = True
            else:
                self.is_connected = False
        except requests.RequestException:
            self.is_connected = False

    def sync_chain(self):
        # Ana sunucudan zinciri çekme ve çatışma çözme mantığı
        if not self.is_connected: return False

        self.is_syncing = True
        try:
            # Basit bir uzunluk kontrolü (Sunucunun /chain rotası olmalı)
            response = requests.get(f"{self.server_address}/chain", timeout=10)
            if response.status_code == 200:
                server_chain = response.json()
                server_length = len(server_chain)
                local_length = BlockchainManager(self.db).get_chain_length()
                
                if server_length > local_length:
                    # Zincirini değiştir
                    self.resolve_conflicts(server_chain)
                    logger.info("Zincir sunucu ile senkronize edildi.")
                    self.is_syncing = False
                    return True
        except requests.RequestException as e:
            logger.error(f"Senkronizasyon hatası: {e}")
        
        self.is_syncing = False
        return False
        
    def resolve_conflicts(self, new_chain):
        # Basit: Yeni zinciri veritabanına kaydet
        conn = self.db.get_connection()
        try:
            # Tüm eski blokları sil
            conn.execute("DELETE FROM blockchain")
            # Yeni blokları ekle
            for block in new_chain:
                conn.execute("INSERT INTO blockchain (index, timestamp, transactions, proof, previous_hash, hash, mined_by) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (block['index'], block['timestamp'], json.dumps(block['transactions']), block['proof'], block['previous_hash'], block['hash'], block['mined_by']))
            
            # Tüm eski işlemleri sil ve yeni zincirdeki işlemleri tekrar ekle (UTXO sistemi olmadığı için)
            conn.execute("DELETE FROM transactions")
            # İşlemleri yeniden ekleme mantığı burada olmalıdır (şimdilik atlandı)

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Zincir değiştirme hatası: {e}")
            return False
        finally:
            conn.close()


    def start(self):
        self.discovery_thread.start()
        self.maintenance_thread.start()

# --- MESH DÜĞÜMÜ SINIFI / MESH NODE CLASS ---

class GhostMeshNode:
    def __init__(self, server_address, lang_code='tr'):
        self.server_address = server_address
        self.db_mgr = DatabaseManager(DB_FILE)
        self.chain_mgr = BlockchainManager(self.db_mgr)
        self.user_mgr = UserManager(self.db_mgr)
        
        # Kendi IP adresini bulmaya çalış
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80)) # Google DNS'e bağlanarak yerel IP'yi al
            self.node_address = s.getsockname()[0]
            s.close()
        except:
            self.node_address = "127.0.0.1"
        
        self.mesh_mgr = MeshManager(self.node_address, self.db_mgr, self.server_address)
        self.set_language(lang_code)

    def set_language(self, lang_code):
        self.lang_code = lang_code
        self.L = LANGUAGES.get(lang_code, LANGUAGES['tr']) # Hata durumunda Türkçe varsayılan

    def get_user_pubkey(self):
        # Basit: Veritabanındaki ilk kullanıcıyı al
        conn = self.db_mgr.get_connection()
        user = conn.execute("SELECT pub_key FROM users LIMIT 1").fetchone()
        conn.close()
        return user['pub_key'] if user else None

    def display_status(self):
        L = self.L
        
        print("\n--- GhostProtocol Mesh Node Status ---")
        print(f"[{L['status_online'] if self.mesh_mgr.is_connected else L['status_offline']}] {L['server']}: {self.server_address}")
        
        # Ağ durumu
        try:
            # Şu an sadece WiFi/Kablolu durumu simülasyonu. Bluetooth entegrasyonu (RasPi) bekleniyor.
            mesh_type = L['wifi'] # Varsayılan WiFi/Kablolu
        except:
            mesh_type = L['unknown']
            
        print(f"[{L['mesh_active']}] {L['mesh_status']}: {mesh_type}")

        pub_key = self.get_user_pubkey()
        if pub_key:
            balance = self.chain_mgr.get_balance(pub_key)
            print(f"{L['wallet_balance']}: {balance:.4f} GHOST")
            print(f"{L['wallet_address']}: GHST{pub_key[:20]}") # İlk 20 karakteri göster
            
            # Varlıkları göster
            assets = self.chain_mgr.get_user_assets(pub_key)
            print(f"\n📂 {self.L['assets_title']} ({len(assets)}):") # <-- Hata burada oluşuyordu
            if assets:
                for asset in assets:
                    print(f"   [{asset['type'].upper()}] {asset['name']} (ID: {asset['asset_id'][:8]}...)")
            else:
                print(f"   Henüz {L['assets_title']} yok.")
        else:
            print("Kayıtlı kullanıcı yok. Lütfen Web Arayüzü'nden (Server) kayıt olun.")

        # Blok zinciri durumu
        last_block = self.chain_mgr.get_last_block()
        print(f"\n🔗 {L['last_block']}: {last_block['index']} (Hash: {last_block['hash'][:8]})")
        print(f"👥 {L['peers']}: {len(self.mesh_mgr.peers)} aktif peer keşfedildi.")

    def run(self):
        # Mesh Network Start
        self.mesh_mgr.start()
        
        while True:
            self.display_status()
            
            print(f"\n{self.L['menu_select']}")
            print(f"1. {self.L['menu_sync']}")
            print(f"2. {self.L['menu_mine']}")
            print(f"3. {self.L['menu_asset']}")
            print(f"4. {self.L['menu_exit']}")
            
            choice = input("> ")
            
            if choice == '1':
                print("Senkronize ediliyor...")
                if self.mesh_mgr.sync_chain():
                    print(self.L['server_sync_success'])
                else:
                    print(f"{self.L['server_sync_fail']} Senkronize edilemedi.")
            elif choice == '2':
                pub_key = self.get_user_pubkey()
                if pub_key:
                    print("Madencilik başlatılıyor (PoW)...")
                    try:
                        new_block = self.chain_mgr.mine_block(pub_key, difficulty=4, reward=10.0)
                        if new_block:
                            print(f"✅ Blok bulundu! Index: {new_block['index']}, Hash: {new_block['hash'][:8]}...")
                        else:
                            print("❌ Madencilik başarısız oldu (PoW bulunamadı veya zincir hatası).")
                    except Exception as e:
                         print(f"❌ Madencilik sırasında beklenmedik bir hata oluştu: {e}")
                else:
                    print("Madencilik için cüzdan adresi bulunamadı.")
            elif choice == '3':
                # Bu seçenek, normalde sadece web arayüzünden yapılmalıdır.
                print("Varlık işlemleri web arayüzü (Sunucu) üzerinden yapılmalıdır.")
            elif choice == '4':
                print("Kapatılıyor...")
                sys.exit(0)
            else:
                print("Geçersiz seçim.")
            
            time.sleep(2) # Kısa bekleme

# --- FLASK ROTALARI (Sadece Node'lar arası iletişim için) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Basit bir login arayüzü (Web UI'ya yönlendirme için)
    # ... (login rotası aynı kalır)
    pass
    
@app.route('/dashboard')
def dashboard():
    # Basit bir dashboard (Web UI'ya yönlendirme için)
    # ... (dashboard rotası aynı kalır)
    pass
    
@app.route('/upload_asset', methods=['POST'])
def upload_asset():
    # ... (upload_asset rotası aynı kalır)
    pass

@app.route('/clone_asset', methods=['POST'])
def clone_asset():
    # ... (clone_asset rotası aynı kalır)
    pass

@app.route('/logout')
def logout():
    # ... (logout rotası aynı kalır)
    pass

if __name__ == '__main__':
    # 1. Mesh Ağını Başlat / Start Mesh Network
    print("--- GhostProtocol Mesh Node Starting ---")
    
    # Server adresi yapılandırması (Ana sunucunun IP'si)
    main_server_address = os.environ.get('GHOST_SERVER_URL', 'http://127.0.0.1:5000')
    
    node = GhostMeshNode(main_server_address, lang_code='tr')
    node.run()
    
    # 2. Web Sunucusu Başlat (Peer İletişimi İçin)
    # app.run(host='0.0.0.0', port=GHOST_PORT)
