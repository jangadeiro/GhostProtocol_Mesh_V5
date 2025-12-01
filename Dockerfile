# Temel İmaj: Debian tabanlı Slim sürüm (Alpine, PyBluez için sorun çıkarabilir)
FROM python:3.9-slim

# Çalışma dizini
WORKDIR /app

# Sistem bağımlılıklarını yükle (Bluetooth ve Derleme araçları için)
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libbluetooth-dev \
    && rm -rf /var/lib/apt/lists/*

# Python kütüphanelerini yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Uygulama kodunu kopyala
COPY ghost_mesh_node.py .

# Veri klasörü oluştur
RUN mkdir -p /app/data

# Portları aç (5000: Web/API, 9999: UDP Mesh Discovery)
EXPOSE 5000
EXPOSE 9999/udp

# Uygulamayı başlat
# Not: -u parametresi logların anlık olarak terminale düşmesini sağlar
ENTRYPOINT ["python", "-u", "ghost_mesh_node.py"]