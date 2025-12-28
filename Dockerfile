FROM debian:bullseye-slim

RUN apt-get update && apt-get install -y \
    wget unzip lib32gcc-s1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /terraria

# Descargar servidor oficial de Terraria (ejemplo versión 1433)
RUN wget https://terraria.org/api/download/pc-dedicated-server/terraria-server-1433.zip -O terraria-server.zip \
    && unzip terraria-server.zip -d /terraria \
    && rm terraria-server.zip

EXPOSE 7777

# Arrancar servidor con mundo local
CMD /terraria/1433/Linux/TerrariaServer.bin.x86_64 -port 7777 -world /terraria/MyWorld.wld -autocreate 1