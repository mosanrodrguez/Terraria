FROM debian:bullseye-slim

# Dependencias necesarias
RUN apt-get update && apt-get install -y \
    wget unzip lib32gcc-s1 megatools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /terraria

# Descargar servidor oficial de Terraria (ejemplo versión 1433)
RUN wget https://terraria.org/api/download/pc-dedicated-server/terraria-server-1433.zip -O terraria-server.zip \
    && unzip terraria-server.zip -d /terraria \
    && rm terraria-server.zip

# Copiar credenciales de MEGA
COPY megatools.conf /root/.config/megatools/config

EXPOSE 7777

# Flujo de arranque:
# 1. Descargar mundo desde MEGA (si existe)
# 2. Ejecutar Terraria en background
# 3. Cada 30s: eliminar mundo en MEGA y subir el actual
CMD megaget --config /root/.config/megatools/config --path /terraria/MyWorld.wld /terraria/MyWorld.wld || true && \
    ./Linux/TerrariaServer.bin.x86_64 -port 7777 -world /terraria/MyWorld.wld -autocreate 1 & \
    while true; do \
        megarm --config /root/.config/megatools/config /terraria/MyWorld.wld || true; \
        megaupload --config /root/.config/megatools/config --path /terraria/MyWorld.wld /terraria/MyWorld.wld; \
        sleep 30; \
    done