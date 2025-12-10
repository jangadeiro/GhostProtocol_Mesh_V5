# GhostProtocol için temel Dockerfile
FROM python:3.10-slim

# Uygulamanın çalışacağı dizini ayarla
WORKDIR /app

# Gerekli paketleri yükle (requirements.txt dosyası var sayılır)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
# Hem server hem de mesh node dosyalarını kopyalamalıyız
COPY ghost_server.py .
COPY ghost_mesh_node.py .
COPY templates/ /app/templates/ # Eğer ayrı bir şablon dizini varsa

# Veritabanını kalıcı hale getirmek için /app dizini kalıcı bir birime (volume) bağlanmalıdır.
# Uygulama, Gunicorn ile başlatılacak
# Varsayılan CMD'yi aşağıda docker-compose'da belirteceğiz

# Server varsayılan portu 5000, Node varsayılan portu 5001'dir (docker-compose'da tanımlanmıştır)
EXPOSE 5000
EXPOSE 5001
