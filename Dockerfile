FROM debian:bullseye-slim

# Dependencias necesarias
RUN apt-get update && apt-get install -y \
    wget unzip lib32gcc-s1 megatools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /terraria

# Descargar servidor oficial de Terraria
RUN wget https://terraria.org/system/dedicated_servers/archives/000/000/053/original/terraria-server-1449.zip \
    && unzip terraria-server-1449.zip -d /terraria \
    && rm terraria-server-1449.zip

# Copiar credenciales de MEGA (archivo megatools.conf)
COPY megatools.conf /root/.config/megatools/config

EXPOSE 7777

# Flujo de arranque:
# 1. Descargar mundo desde MEGA (si existe)
# 2. Ejecutar Terraria
# 3. Subir mundo actualizado a MEGA al terminar
CMD megaget --config /root/.config/megatools/config --path /terraria/MyWorld.wld /terraria/MyWorld.wld || true && \
    ./Linux/TerrariaServer.bin.x86_64 -port 7777 -world /terraria/MyWorld.wld -autocreate 1 && \
    megaupload --config /root/.config/megatools/config --path /terraria/MyWorld.wld /terraria/MyWorld.wld