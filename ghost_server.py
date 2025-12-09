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
logger = logging.getLogger("GhostCloud")

# --- YAPILANDIRMA / CONFIGURATION ---
MINING_DIFFICULTY = 4
BLOCK_REWARD = 10
DB_FILE = os.path.join(os.getcwd(), "ghost_cloud.db")
GHOST_PORT = 5000
DOMAIN_EXPIRY_SECONDS = 15552000  # 6 Ay (6 Months in seconds)
STORAGE_COST_PER_MB = 0.001       # MB başına ücret / Fee per MB

app = Flask(__name__)
app.secret_key = "cloud_super_secret"

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
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, wallet_public_key TEXT UNIQUE, balance REAL DEFAULT 0)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (block_index INTEGER PRIMARY KEY, timestamp REAL, proof INTEGER, previous_hash TEXT, block_hash TEXT)''')
            # expiry ve is_public alanları eklendi / Added expiry and is_public fields
            cursor.execute('''CREATE TABLE IF NOT EXISTS assets (asset_id TEXT PRIMARY KEY, owner_pub_key TEXT, type TEXT, name TEXT, content BLOB, storage_size INTEGER, creation_time REAL, expiry_time REAL, is_public INTEGER DEFAULT 1)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (tx_id TEXT PRIMARY KEY, sender TEXT, recipient TEXT, amount REAL, timestamp REAL)''')
            
            if cursor.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
                self.create_genesis_block(cursor)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.critical(f"DB Init Error: {e}")

    def create_genesis_block(self, cursor):
        genesis_hash = hashlib.sha256(json.dumps({'index': 1, 'timestamp': time.time()}, sort_keys=True).encode()).hexdigest()
        cursor.execute("INSERT INTO blocks (block_index, timestamp, proof, previous_hash, block_hash) VALUES (?, ?, ?, ?, ?)",
                       (1, time.time(), 1, '0', genesis_hash))

# --- BLOCKCHAIN MANTIĞI / BLOCKCHAIN LOGIC ---
class GhostChain:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_full_chain(self):
        # Tüm zinciri JSON formatında döndürür (Senkronizasyon için) / Returns full chain in JSON (For sync)
        conn = self.db.get_connection()
        blocks = [dict(row) for row in conn.execute("SELECT * FROM blocks ORDER BY block_index ASC").fetchall()]
        assets = [dict(row) for row in conn.execute("SELECT * FROM assets").fetchall()]
        conn.close()
        # BLOB verilerini string'e çevir / Convert BLOB to string for JSON serialization
        for a in assets:
            if isinstance(a['content'], bytes): a['content'] = base64.b64encode(a['content']).decode('utf-8')
        return {'chain': blocks, 'assets': assets, 'length': len(blocks)}

    def replace_chain(self, remote_chain_data):
        # Uzak zincir daha uzunsa yerel zinciri değiştir / Replace local chain if remote is longer
        # (Basitleştirilmiş Güven Modeli / Simplified Trust Model)
        local_len = self.db.get_connection().execute("SELECT MAX(block_index) FROM blocks").fetchone()[0] or 0
        if remote_chain_data['length'] > local_len:
            logger.info("Daha uzun zincir bulundu, güncelleniyor... / Longer chain found, updating...")
            conn = self.db.get_connection()
            # Tüm tabloları temizle ve yenilerini ekle / Wipe and replace
            conn.execute("DELETE FROM blocks")
            conn.execute("DELETE FROM assets")
            
            for b in remote_chain_data['chain']:
                conn.execute("INSERT INTO blocks (block_index, timestamp, proof, previous_hash, block_hash) VALUES (?, ?, ?, ?, ?)",
                             (b['block_index'], b['timestamp'], b['proof'], b['previous_hash'], b['block_hash']))
            
            for a in remote_chain_data['assets']:
                content = base64.b64decode(a['content'])
                conn.execute("INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (a['asset_id'], a['owner_pub_key'], a['type'], a['name'], content, a['storage_size'], a['creation_time'], a['expiry_time'], a['is_public']))
            conn.commit()
            conn.close()
            return True
        return False

# --- UYGULAMA BAŞLATMA / APP INIT ---
db = DatabaseManager(DB_FILE)
chain = GhostChain(db)

# --- API ENDPOINTS (SENKRONİZASYON İÇİN) ---
@app.route('/chain', methods=['GET'])
def full_chain():
    # Mesh node'larının veri çekmesi için endpoint / Endpoint for mesh nodes to pull data
    response = chain.get_full_chain()
    return jsonify(response), 200

@app.route('/sync', methods=['POST'])
def sync_chain():
    # Mesh node'larının veri göndermesi için (Opsiyonel) / Endpoint for mesh nodes to push data
    values = request.get_json()
    if not values: return "No data", 400
    chain.replace_chain(values)
    return "Synced", 200

# --- DASHBOARD & WEB UI (Özetlenmiş - Detaylar Mesh Node ile aynı mantıkta) ---
@app.route('/')
def home():
    return "<h1>GhostProtocol Cloud Server</h1><p>Bu, blok zincirinin ana omurgasıdır. Mesh düğümleri buraya bağlanarak senkronize olur.</p>"

if __name__ == '__main__':
    print("--- GHOST CLOUD SERVER ACTIVE ---")
    app.run(host='0.0.0.0', port=GHOST_PORT)
