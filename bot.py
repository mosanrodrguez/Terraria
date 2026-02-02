import logging
from datetime import datetime
import sqlite3
from math import radians, sin, cos, sqrt, atan2
import pytz

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    ConversationHandler,
    filters, 
    ContextTypes
)

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Estados de la conversación
(
    MAIN_MENU,
    CREAR_PERFIL,
    EDITAR_PREFERENCIAS_GENERO,
    EDITAR_PREFERENCIAS_EDAD_MIN,
    EDITAR_PREFERENCIAS_EDAD_MAX,
    EDITAR_PREFERENCIAS_DISTANCIA,
    OBTENER_UBICACION,
    LIKE_DISLIKE,
    SOLICITUDES,
    CONFIGURACION,
    EDITAR_PERFIL
) = range(11)

# Base de datos
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('dating_bot.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                nombre TEXT,
                edad INTEGER,
                genero TEXT,
                descripcion TEXT,
                foto TEXT,
                latitud REAL,
                longitud REAL,
                ultima_actividad TEXT,
                activo INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS preferencias (
                user_id INTEGER PRIMARY KEY,
                genero_preferido TEXT,
                edad_min INTEGER DEFAULT 13,
                edad_max INTEGER DEFAULT 99,
                distancia_max INTEGER DEFAULT 50,
                FOREIGN KEY (user_id) REFERENCES usuarios (user_id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS interacciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_from INTEGER,
                user_to INTEGER,
                tipo TEXT,
                fecha TEXT,
                FOREIGN KEY (user_from) REFERENCES usuarios (user_id),
                FOREIGN KEY (user_to) REFERENCES usuarios (user_id),
                UNIQUE(user_from, user_to)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1 INTEGER,
                user2 INTEGER,
                fecha TEXT,
                activo INTEGER DEFAULT 1,
                FOREIGN KEY (user1) REFERENCES usuarios (user_id),
                FOREIGN KEY (user2) REFERENCES usuarios (user_id),
                UNIQUE(user1, user2)
            )
        ''')
        
        self.conn.commit()
    
    def get_current_timestamp(self):
        return datetime.now(pytz.UTC).isoformat()
    
    # Métodos para usuarios
    def crear_usuario(self, user_id, username, nombre, edad, genero, descripcion=""):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO usuarios 
            (user_id, username, nombre, edad, genero, descripcion, ultima_actividad, activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, username, nombre, edad, genero, descripcion, self.get_current_timestamp()))
        self.conn.commit()
    
    def actualizar_ubicacion(self, user_id, latitud, longitud):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE usuarios 
            SET latitud = ?, longitud = ?, ultima_actividad = ?
            WHERE user_id = ?
        ''', (latitud, longitud, self.get_current_timestamp(), user_id))
        self.conn.commit()
    
    def obtener_usuario(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM usuarios WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    # Métodos para preferencias
    def crear_preferencias(self, user_id, genero_preferido="cualquiera", edad_min=13, edad_max=99, distancia_max=50):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO preferencias 
            (user_id, genero_preferido, edad_min, edad_max, distancia_max)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, genero_preferido, edad_min, edad_max, distancia_max))
        self.conn.commit()
    
    def obtener_preferencias(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM preferencias WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def actualizar_preferencia(self, user_id, campo, valor):
        cursor = self.conn.cursor()
        cursor.execute(f'UPDATE preferencias SET {campo} = ? WHERE user_id = ?', (valor, user_id))
        self.conn.commit()
    
    # Métodos para interacciones
    def registrar_interaccion(self, user_from, user_to, tipo):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO interacciones (user_from, user_to, tipo, fecha)
                VALUES (?, ?, ?, ?)
            ''', (user_from, user_to, tipo, self.get_current_timestamp()))
            self.conn.commit()
            
            if tipo == 'like':
                cursor.execute('''
                    SELECT 1 FROM interacciones 
                    WHERE user_from = ? AND user_to = ? AND tipo = 'like'
                ''', (user_to, user_from))
                if cursor.fetchone():
                    self.crear_match(user_from, user_to)
                    return True
            return False
        except Exception as e:
            logger.error(f"Error registrando interacción: {e}")
            return False
    
    def crear_match(self, user1, user2):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO matches (user1, user2, fecha)
                VALUES (?, ?, ?)
            ''', (min(user1, user2), max(user1, user2), self.get_current_timestamp()))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error creando match: {e}")
            return None
    
    def obtener_matches(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM matches 
            WHERE (user1 = ? OR user2 = ?) AND activo = 1
            ORDER BY fecha DESC
        ''', (user_id, user_id))
        return cursor.fetchall()
    
    # Método para encontrar perfiles compatibles
    def obtener_perfiles_compatibles(self, user_id, limit=20):
        usuario = self.obtener_usuario(user_id)
        preferencias = self.obtener_preferencias(user_id)
        
        if not usuario or not preferencias:
            return []
        
        cursor = self.conn.cursor()
        
        # Obtener IDs ya vistos
        cursor.execute('''
            SELECT DISTINCT user_to FROM interacciones WHERE user_from = ?
        ''', (user_id,))
        excluidos = [row[0] for row in cursor.fetchall()]
        excluidos.append(user_id)
        
        placeholders = ','.join(['?'] * len(excluidos))
        
        query = f'''
            SELECT u.*
            FROM usuarios u
            WHERE u.user_id NOT IN ({placeholders})
            AND u.activo = 1
            AND u.edad >= ? AND u.edad <= ?
            AND (? = 'cualquiera' OR u.genero = ?)
            AND u.latitud IS NOT NULL 
            AND u.longitud IS NOT NULL
            LIMIT ?
        '''
        
        params = [
            *excluidos,
            preferencias[2],  # edad_min
            preferencias[3],  # edad_max
            preferencias[1],  # genero_preferido
            preferencias[1],  # genero_preferido
            limit
        ]
        
        cursor.execute(query, params)
        return cursor.fetchall()

db = Database()

# Handlers principales
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    usuario = db.obtener_usuario(user_id)
    
    if usuario:
        await update.message.reply_text(
            f"👋 ¡Bienvenido de nuevo, {usuario[2]}!\n\n"
            "¿Qué te gustaría hacer hoy?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 Ver Perfiles", callback_data="ver_perfiles")],
                [InlineKeyboardButton("💌 Solicitudes", callback_data="solicitudes")],
                [InlineKeyboardButton("💬 Mis Chats", callback_data="mis_chats")],
                [InlineKeyboardButton("👤 Mi Perfil", callback_data="mi_perfil")],
                [InlineKeyboardButton("⚙️ Configuración", callback_data="configuracion")]
            ])
        )
    else:
        await update.message.reply_text(
            "👋 ¡Bienvenido al Bot de Citas! 🎯\n\n"
            "Vamos a crear tu perfil. ¿Cuál es tu nombre?"
        )
        return CREAR_PERFIL
    
    return MAIN_MENU

async def crear_perfil_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.message.text.strip()
    if len(nombre) < 2:
        await update.message.reply_text("Por favor, ingresa un nombre válido (mínimo 2 caracteres):")
        return CREAR_PERFIL
    
    context.user_data['nombre'] = nombre
    
    await update.message.reply_text(
        f"¡Genial, {nombre}! 👋\n\n"
        "Ahora, ¿cuántos años tienes?"
    )
    return CREAR_PERFIL

async def crear_perfil_edad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        edad_texto = update.message.text.strip()
        edad = int(edad_texto)
        
        if edad < 13:
            await update.message.reply_text("❌ Debes tener al menos 13 años para usar este bot. Por favor, ingresa tu edad real:")
            return CREAR_PERFIL
        
        if edad > 120:
            await update.message.reply_text("❌ Por favor, ingresa una edad válida (13-120):")
            return CREAR_PERFIL
        
        context.user_data['edad'] = edad
        
        keyboard = [
            [InlineKeyboardButton("Hombre 👨", callback_data="genero_hombre")],
            [InlineKeyboardButton("Mujer 👩", callback_data="genero_mujer")],
            [InlineKeyboardButton("Otro 🏳️‍🌈", callback_data="genero_otro")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"¡Perfecto! Tienes {edad} años.\n\n"
            "Ahora, ¿cuál es tu género?",
            reply_markup=reply_markup
        )
        return CREAR_PERFIL
    except ValueError:
        await update.message.reply_text("❌ Por favor, ingresa un número válido para la edad:")
        return CREAR_PERFIL

async def crear_perfil_genero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    genero = query.data.split("_")[1]
    context.user_data['genero'] = genero
    
    await query.edit_message_text(
        "¡Excelente! 🎉\n\n"
        "Ahora, comparte una breve descripción sobre ti:\n"
        "(Puedes hablar sobre tus intereses, hobbies, lo que buscas, etc.)\n\n"
        "Ejemplo: 'Me gusta el fútbol, leer y salir con amigos. Busco conocer gente nueva.'"
    )
    return CREAR_PERFIL

async def crear_perfil_descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    descripcion = update.message.text.strip()
    if len(descripcion) < 10:
        await update.message.reply_text("Por favor, escribe al menos 10 caracteres para tu descripción:")
        return CREAR_PERFIL
    
    if len(descripcion) > 500:
        descripcion = descripcion[:500] + "..."
    
    user = update.effective_user
    
    # Crear usuario en la base de datos
    db.crear_usuario(
        user_id=user.id,
        username=user.username,
        nombre=context.user_data['nombre'],
        edad=context.user_data['edad'],
        genero=context.user_data['genero'],
        descripcion=descripcion
    )
    
    # Crear preferencias por defecto (edad mínima 13 por defecto)
    db.crear_preferencias(user.id, edad_min=13)
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Configurar Preferencias", callback_data="config_preferencias")],
        [InlineKeyboardButton("📍 Compartir Ubicación", callback_data="compartir_ubicacion")]
    ]
    
    await update.message.reply_text(
        "🎉 ¡Perfil creado exitosamente! 🎉\n\n"
        "Para comenzar a ver perfiles, necesitas:\n"
        "1. ⚙️ Configurar tus preferencias\n"
        "2. 📍 Compartir tu ubicación\n\n"
        "¿Qué quieres hacer primero?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return MAIN_MENU

async def configurar_preferencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("Hombres 👨", callback_data="pref_genero_hombre")],
        [InlineKeyboardButton("Mujeres 👩", callback_data="pref_genero_mujer")],
        [InlineKeyboardButton("Todos 🏳️‍🌈", callback_data="pref_genero_cualquiera")]
    ]
    
    await query.edit_message_text(
        "⚙️ *Configuración de Preferencias*\n\n"
        "¿Qué género prefieres?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDITAR_PREFERENCIAS_GENERO

async def set_preferencia_genero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    genero_preferido = query.data.split("_")[2]
    user_id = query.from_user.id
    
    db.actualizar_preferencia(user_id, 'genero_preferido', genero_preferido)
    
    await query.edit_message_text(
        "¿Cuál es la *edad mínima* que prefieres? (Ej: 13)\n\n"
        "Nota: La edad mínima permitida es 13 años.",
        parse_mode='Markdown'
    )
    return EDITAR_PREFERENCIAS_EDAD_MIN

async def set_preferencia_edad_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        edad_min_texto = update.message.text.strip()
        edad_min = int(edad_min_texto)
        
        if edad_min < 13:
            await update.message.reply_text("❌ La edad mínima debe ser al menos 13 años. Por favor, ingresa un valor válido:")
            return EDITAR_PREFERENCIAS_EDAD_MIN
        
        if edad_min > 99:
            await update.message.reply_text("❌ Por favor, ingresa una edad válida (13-99):")
            return EDITAR_PREFERENCIAS_EDAD_MIN
        
        user_id = update.effective_user.id
        db.actualizar_preferencia(user_id, 'edad_min', edad_min)
        
        await update.message.reply_text(
            f"✅ Edad mínima establecida: {edad_min} años\n\n"
            "¿Cuál es la *edad máxima* que prefieres? (Ej: 30)",
            parse_mode='Markdown'
        )
        return EDITAR_PREFERENCIAS_EDAD_MAX
    except ValueError:
        await update.message.reply_text("❌ Por favor, ingresa un número válido:")
        return EDITAR_PREFERENCIAS_EDAD_MIN

async def set_preferencia_edad_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        edad_max_texto = update.message.text.strip()
        edad_max = int(edad_max_texto)
        
        user_id = update.effective_user.id
        preferencias = db.obtener_preferencias(user_id)
        
        if edad_max < 13:
            await update.message.reply_text("❌ La edad máxima debe ser al menos 13 años:")
            return EDITAR_PREFERENCIAS_EDAD_MAX
        
        if edad_max > 99:
            await update.message.reply_text("❌ Por favor, ingresa una edad válida (13-99):")
            return EDITAR_PREFERENCIAS_EDAD_MAX
        
        if edad_max < preferencias[2]:  # edad_min
            await update.message.reply_text(
                f"❌ La edad máxima ({edad_max}) debe ser mayor o igual a la mínima ({preferencias[2]}).\n"
                "Por favor, ingresa una edad mayor:"
            )
            return EDITAR_PREFERENCIAS_EDAD_MAX
        
        db.actualizar_preferencia(user_id, 'edad_max', edad_max)
        
        await update.message.reply_text(
            f"✅ Rango de edad establecido: {preferencias[2]}-{edad_max} años\n\n"
            "¿Hasta qué *distancia máxima* (en km) quieres buscar perfiles? (Ej: 50)\n\n"
            "Recomendación: 10-100 km",
            parse_mode='Markdown'
        )
        return EDITAR_PREFERENCIAS_DISTANCIA
    except ValueError:
        await update.message.reply_text("❌ Por favor, ingresa un número válido:")
        return EDITAR_PREFERENCIAS_EDAD_MAX

async def set_preferencia_distancia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        distancia_texto = update.message.text.strip()
        distancia = int(distancia_texto)
        
        if distancia < 1:
            await update.message.reply_text("❌ La distancia mínima es 1 km. Por favor, ingresa un valor válido:")
            return EDITAR_PREFERENCIAS_DISTANCIA
        
        if distancia > 1000:
            await update.message.reply_text("❌ La distancia máxima es 1000 km. Por favor, ingresa un valor menor:")
            return EDITAR_PREFERENCIAS_DISTANCIA
        
        user_id = update.effective_user.id
        db.actualizar_preferencia(user_id, 'distancia_max', distancia)
        
        keyboard = [[KeyboardButton("📍 Compartir ubicación", request_location=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        
        await update.message.reply_text(
            f"✅ Preferencias guardadas exitosamente!\n\n"
            "📍 *¡Último paso!*\n\n"
            "Para ver perfiles cercanos, necesitamos tu ubicación.\n"
            "Presiona el botón para compartirla:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return OBTENER_UBICACION
    except ValueError:
        await update.message.reply_text("❌ Por favor, ingresa un número válido para la distancia:")
        return EDITAR_PREFERENCIAS_DISTANCIA

async def obtener_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        location = update.message.location
        user_id = update.effective_user.id
        
        db.actualizar_ubicacion(user_id, location.latitude, location.longitude)
        
        keyboard = [
            [InlineKeyboardButton("👀 Ver Perfiles", callback_data="ver_perfiles")],
            [InlineKeyboardButton("👤 Mi Perfil", callback_data="mi_perfil")],
            [InlineKeyboardButton("⚙️ Configuración", callback_data="configuracion")]
        ]
        
        await update.message.reply_text(
            "✅ ¡Ubicación guardada exitosamente!\n\n"
            "🎯 *¡Todo listo!* Ahora puedes comenzar a ver perfiles cercanos.\n\n"
            "Selecciona una opción:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "❌ No se recibió la ubicación. Por favor, usa el botón para compartir tu ubicación."
        )
        return OBTENER_UBICACION

async def ver_perfiles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Verificar si tiene ubicación
    usuario = db.obtener_usuario(user_id)
    if not usuario or not usuario[7] or not usuario[8]:
        await query.edit_message_text(
            "📍 *Necesitas compartir tu ubicación primero*\n\n"
            "Para ver perfiles cercanos, debes compartir tu ubicación.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📍 Compartir Ubicación", callback_data="compartir_ubicacion")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
            ])
        )
        return MAIN_MENU
    
    perfiles = db.obtener_perfiles_compatibles(user_id, limit=1)
    
    if not perfiles:
        await query.edit_message_text(
            "😔 *No hay más perfiles disponibles*\n\n"
            "No encontramos más perfiles en tu área con tus preferencias actuales.\n\n"
            "Puedes intentar:\n"
            "• Ajustar tus preferencias\n"
            "• Ampliar la distancia de búsqueda\n"
            "• Volver más tarde",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Ajustar Preferencias", callback_data="config_preferencias")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
            ])
        )
        return MAIN_MENU
    
    perfil = perfiles[0]
    
    # Determinar emoji de género
    genero_emoji = "👤"
    if perfil[4] == "hombre":
        genero_emoji = "👨"
    elif perfil[4] == "mujer":
        genero_emoji = "👩"
    elif perfil[4] == "otro":
        genero_emoji = "🏳️‍🌈"
    
    mensaje = f"""
{genero_emoji} *{perfil[2]}*, {perfil[3]} años

*Sobre mí:*
{perfil[5] or 'No hay descripción disponible'}

📍 *Distancia:* Cerca de ti
"""
    
    keyboard = [
        [
            InlineKeyboardButton("❌ No", callback_data=f"dislike_{perfil[0]}"),
            InlineKeyboardButton("💖 Sí", callback_data=f"like_{perfil[0]}")
        ],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
    ]
    
    await query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    return LIKE_DISLIKE

async def procesar_like_dislike(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action, target_user_id = query.data.split("_")
    target_user_id = int(target_user_id)
    
    hay_match = db.registrar_interaccion(user_id, target_user_id, action)
    
    if action == 'like' and hay_match:
        usuario = db.obtener_usuario(user_id)
        target_usuario = db.obtener_usuario(target_user_id)
        
        # Mensaje para el usuario actual
        await query.edit_message_text(
            f"🎉 *¡MATCH!*\n\n"
            f"Has hecho match con *{target_usuario[2]}*!\n\n"
            f"Ahora pueden chatear desde '💬 Mis Chats' en el menú principal.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Mis Chats", callback_data="mis_chats")],
                [InlineKeyboardButton("👀 Ver más perfiles", callback_data="ver_perfiles")]
            ])
        )
        
        # Notificar al otro usuario
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"🎉 *¡NUEVO MATCH!*\n\n"
                     f"Has hecho match con *{usuario[2]}*!\n\n"
                     f"Puedes chatear desde '💬 Mis Chats' en el menú principal.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error notificando match: {e}")
        
        return MAIN_MENU
    
    # Mostrar siguiente perfil
    await ver_perfiles(update, context)
    return LIKE_DISLIKE

async def mostrar_solicitudes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    cursor = db.conn.cursor()
    cursor.execute('''
        SELECT i.*, u.nombre, u.edad, u.genero 
        FROM interacciones i
        JOIN usuarios u ON i.user_from = u.user_id
        WHERE i.user_to = ? 
        AND i.tipo = 'like'
        AND NOT EXISTS (
            SELECT 1 FROM matches 
            WHERE (user1 = ? AND user2 = i.user_from) 
            OR (user2 = ? AND user1 = i.user_from)
        )
        LIMIT 1
    ''', (user_id, user_id, user_id))
    
    solicitud = cursor.fetchone()
    
    if not solicitud:
        await query.edit_message_text(
            "📭 *No tienes solicitudes pendientes*\n\n"
            "Cuando alguien te dé 'Me gusta', aparecerá aquí.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 Ver Perfiles", callback_data="ver_perfiles")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
            ])
        )
        return MAIN_MENU
    
    # Determinar emoji de género
    genero_emoji = "👤"
    if solicitud[6] == "hombre":
        genero_emoji = "👨"
    elif solicitud[6] == "mujer":
        genero_emoji = "👩"
    elif solicitud[6] == "otro":
        genero_emoji = "🏳️‍🌈"
    
    mensaje = f"""
📩 *Nueva solicitud*

{genero_emoji} *{solicitud[4]}*, {solicitud[5]} años
💖 Te ha dado 'Me gusta'

¿Quieres aceptar y comenzar a chatear?
"""
    
    keyboard = [
        [
            InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_{solicitud[1]}"),
            InlineKeyboardButton("✅ Aceptar", callback_data=f"aceptar_{solicitud[1]}")
        ],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
    ]
    
    await query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    return SOLICITUDES

async def procesar_solicitud(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action, from_user_id = query.data.split("_")
    from_user_id = int(from_user_id)
    
    if action == 'aceptar':
        # Crear match
        match_id = db.crear_match(user_id, from_user_id)
        
        # Notificar al usuario que envió el like
        usuario = db.obtener_usuario(user_id)
        try:
            await context.bot.send_message(
                chat_id=from_user_id,
                text=f"🎉 *¡TU LIKE FUE CORRESPONDIDO!*\n\n"
                     f"*{usuario[2]}* ha aceptado tu solicitud.\n\n"
                     f"¡Ahora pueden chatear desde '💬 Mis Chats'!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error notificando aceptación: {e}")
        
        await query.edit_message_text(
            "✅ *Solicitud aceptada*\n\n"
            "¡Ahora pueden chatear! Visita '💬 Mis Chats' para comenzar.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Mis Chats", callback_data="mis_chats")],
                [InlineKeyboardButton("📭 Ver más solicitudes", callback_data="solicitudes")]
            ])
        )
    else:
        # Rechazar solicitud
        db.registrar_interaccion(user_id, from_user_id, 'dislike')
        await query.edit_message_text(
            "❌ *Solicitud rechazada*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📭 Ver más solicitudes", callback_data="solicitudes")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
            ])
        )
    
    return MAIN_MENU

async def mostrar_mis_chats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    matches = db.obtener_matches(user_id)
    
    if not matches:
        await query.edit_message_text(
            "💬 *No tienes chats activos*\n\n"
            "¡Interactúa con más perfiles para conseguir matches!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👀 Ver Perfiles", callback_data="ver_perfiles")],
                [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
            ])
        )
        return MAIN_MENU
    
    # Crear botones para cada match
    keyboard = []
    for match in matches:
        other_user_id = match[1] if match[1] != user_id else match[2]
        other_user = db.obtener_usuario(other_user_id)
        
        if other_user:
            keyboard.append([
                InlineKeyboardButton(
                    f"💬 {other_user[2]}",
                    callback_data=f"chat_{match[0]}"
                )
            ])
    
    keyboard.append([InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")])
    
    await query.edit_message_text(
        "💬 *Tus Chats Activos*\n\n"
        "Selecciona un chat para abrirlo:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return MAIN_MENU

async def mostrar_mi_perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    usuario = db.obtener_usuario(user_id)
    preferencias = db.obtener_preferencias(user_id)
    
    if not usuario:
        await query.edit_message_text("❌ Error al cargar tu perfil.")
        return MAIN_MENU
    
    # Determinar emoji de género
    genero_emoji = "👤"
    if usuario[4] == "hombre":
        genero_emoji = "👨"
    elif usuario[4] == "mujer":
        genero_emoji = "👩"
    elif usuario[4] == "otro":
        genero_emoji = "🏳️‍🌈"
    
    # Determinar estado de ubicación
    ubicacion_status = "✅ Configurada" if usuario[7] and usuario[8] else "❌ No configurada"
    
    mensaje = f"""
{genero_emoji} *Tu Perfil*

*Nombre:* {usuario[2]}
*Edad:* {usuario[3]} años
*Género:* {usuario[4].capitalize()}

*Descripción:*
{usuario[5] or 'Sin descripción'}

📍 *Ubicación:* {ubicacion_status}

*Tus Preferencias:*
• ⚧ Género: {preferencias[1].capitalize() if preferencias else 'Todos'}
• 🎂 Edad: {preferencias[2] if preferencias else '13'}-{preferencias[3] if preferencias else '99'} años
• 📏 Distancia: {preferencias[4] if preferencias else '50'} km
"""
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Configuración", callback_data="configuracion")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
    ]
    
    await query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    return MAIN_MENU

async def mostrar_configuracion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Editar Preferencias", callback_data="config_preferencias")],
        [InlineKeyboardButton("📍 Actualizar Ubicación", callback_data="compartir_ubicacion")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="menu_principal")]
    ]
    
    await query.edit_message_text(
        "⚙️ *Configuración*\n\n"
        "¿Qué te gustaría configurar?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CONFIGURACION

async def compartir_ubicacion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [[KeyboardButton("📍 Compartir ubicación", request_location=True)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    await query.message.reply_text(
        "📍 *Actualizar Ubicación*\n\n"
        "Presiona el botón para compartir tu ubicación actual:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return OBTENER_UBICACION

async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    usuario = db.obtener_usuario(user_id)
    
    if not usuario:
        await query.edit_message_text(
            "Parece que no tienes perfil. Usa /start para crear uno."
        )
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("👀 Ver Perfiles", callback_data="ver_perfiles")],
        [InlineKeyboardButton("💌 Solicitudes", callback_data="solicitudes")],
        [InlineKeyboardButton("💬 Mis Chats", callback_data="mis_chats")],
        [InlineKeyboardButton("👤 Mi Perfil", callback_data="mi_perfil")],
        [InlineKeyboardButton("⚙️ Configuración", callback_data="configuracion")]
    ]
    
    await query.edit_message_text(
        f"👋 *¡Hola, {usuario[2]}!*\n\n"
        "¿Qué te gustaría hacer hoy?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Operación cancelada. Usa /start para volver al menú principal.",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("/start")]], resize_keyboard=True)
    )
    return ConversationHandler.END

# Función principal
def main():
    # TU TOKEN DE BOT - ¡REEMPLAZADO!
    TOKEN = "8395240278:AAHABLB7_9e-bdgCmyPPoAO32GUw95K0kLE"
    
    # Crear aplicación
    application = Application.builder().token(TOKEN).build()
    
    # Conversación principal
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(ver_perfiles, pattern="^ver_perfiles$"),
                CallbackQueryHandler(mostrar_solicitudes, pattern="^solicitudes$"),
                CallbackQueryHandler(mostrar_mis_chats, pattern="^mis_chats$"),
                CallbackQueryHandler(mostrar_mi_perfil, pattern="^mi_perfil$"),
                CallbackQueryHandler(mostrar_configuracion, pattern="^configuracion$"),
                CallbackQueryHandler(menu_principal, pattern="^menu_principal$"),
                CallbackQueryHandler(configurar_preferencias, pattern="^config_preferencias$"),
                CallbackQueryHandler(compartir_ubicacion_menu, pattern="^compartir_ubicacion$"),
            ],
            CREAR_PERFIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, crear_perfil_nombre),
                MessageHandler(filters.TEXT & ~filters.COMMAND, crear_perfil_edad),
                CallbackQueryHandler(crear_perfil_genero, pattern="^genero_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, crear_perfil_descripcion),
            ],
            EDITAR_PREFERENCIAS_GENERO: [
                CallbackQueryHandler(set_preferencia_genero, pattern="^pref_genero_"),
            ],
            EDITAR_PREFERENCIAS_EDAD_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_preferencia_edad_min),
            ],
            EDITAR_PREFERENCIAS_EDAD_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_preferencia_edad_max),
            ],
            EDITAR_PREFERENCIAS_DISTANCIA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_preferencia_distancia),
            ],
            OBTENER_UBICACION: [
                MessageHandler(filters.LOCATION, obtener_ubicacion),
            ],
            LIKE_DISLIKE: [
                CallbackQueryHandler(procesar_like_dislike, pattern="^(like|dislike)_"),
                CallbackQueryHandler(menu_principal, pattern="^menu_principal$"),
            ],
            SOLICITUDES: [
                CallbackQueryHandler(procesar_solicitud, pattern="^(aceptar|rechazar)_"),
                CallbackQueryHandler(menu_principal, pattern="^menu_principal$"),
                CallbackQueryHandler(mostrar_solicitudes, pattern="^solicitudes$"),
            ],
            CONFIGURACION: [
                CallbackQueryHandler(menu_principal, pattern="^menu_principal$"),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )
    
    application.add_handler(conv_handler)
    
    # Añadir handler para manejar errores
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Error: {context.error}")
        if update and update.effective_chat:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Ocurrió un error. Por favor, usa /start para reiniciar."
                )
            except:
                pass
    
    application.add_error_handler(error_handler)
    
    # Iniciar bot
    print("🤖 Bot de citas iniciado...")
    print(f"✅ Token configurado: {TOKEN[:10]}...")
    print("📱 Busca tu bot en Telegram para comenzar!")
    
    application.run_polling()

if __name__ == '__main__':
    main()