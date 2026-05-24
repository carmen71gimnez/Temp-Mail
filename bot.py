import os
import requests
import random
import string
import logging
import threading
import re
import html
import io
import json
from bs4 import BeautifulSoup
from flask import Flask
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ==========================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==========================================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
API_KEY = os.getenv('TMAIL_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
BASE_URL = 'https://flawmail.site/api'

ESPERANDO_PERSONALIZADO, ESPERANDO_RECUPERAR = range(2)

# ==========================================
# SERVIDOR WEB FLASK (ANTISUSPENSIÓN 24/7)
# ==========================================
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@app.route('/')
def home():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sistema Temp Mail</title>
        <style>
            body { font-family: Arial, sans-serif; background-color: #ffffff; color: #212529; text-align: center; padding-top: 10vh; }
            .panel { display: inline-block; padding: 30px 50px; border: 1px solid #dee2e6; border-radius: 8px; background-color: #f8f9fa; }
            h2 { color: #0d6efd; margin-top: 0; }
            p { color: #6c757d; margin-bottom: 0; }
        </style>
    </head>
    <body>
        <div class="panel">
            <h2>✅ Servidor Activo 24/7</h2>
            <p>El bot de Telegram y la API de correos están operando correctamente.</p>
        </div>
    </body>
    </html>
    """
    return html_content

def servidor_web():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# FUNCIONES AUXILIARES (INSPECTOR DE CÓDIGO)
# ==========================================
def obtener_dominio():
    try:
        res = requests.get(f"{BASE_URL}/domains/{API_KEY}")
        if res.status_code == 200:
            return res.json()[0]
    except Exception as e:
        logging.error(f"Error obteniendo dominio: {e}")
    return None

def registrar_auditoria(id_telegram, usuario, accion, correo):
    if not WEBHOOK_URL: return
    payload = {
        "id_telegram": str(id_telegram),
        "usuario": f"@{usuario}" if usuario else "Privado",
        "accion": accion,
        "correo": correo
    }
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        logging.error(f"Error en auditoría: {e}")

def procesar_y_limpiar_html(html_crudo):
    """
    Convierte el código HTML crudo en un texto hermosamente formateado para Telegram.
    Mantiene negritas, formatea enlaces y organiza los espacios.
    """
    if not html_crudo: 
        return "Sin contenido legible."
    
    soup = BeautifulSoup(html_crudo, 'html.parser')
    
    # 1. Destruir código invisible y basura
    for elemento in soup(["script", "style", "head", "title", "meta", "noscript", "img", "svg"]):
        elemento.decompose()
        
    # 2. Escapar el texto original para evitar inyecciones que rompan Telegram
    for text_node in soup.find_all(string=True):
        safe_text = str(text_node).replace('<', '&lt;').replace('>', '&gt;')
        text_node.replace_with(safe_text)
        
    # 3. Formatear enlaces (Botones y Links) para que Telegram los muestre bonitos
    for a in soup.find_all('a', href=True):
        texto_enlace = a.get_text(strip=True)
        url = a['href']
        if url.startswith('http'):
            # Si el enlace es demasiado largo o no tiene texto, le ponemos uno genérico
            if not texto_enlace or "http" in texto_enlace or len(texto_enlace) > 40:
                texto_enlace = "Abrir Enlace"
            # Reemplazamos con HTML nativo que Telegram sí entiende
            a.replace_with(f'<a href="{url}">🔗 {texto_enlace}</a>')
            
    # 4. Formatear Negritas y Encabezados
    for h in soup.find_all(['h1', 'h2', 'h3']):
        texto = h.get_text(strip=True)
        if texto:
            h.replace_with(f"<b>{texto}</b>")
            
    for b in soup.find_all(['b', 'strong']):
        texto = b.get_text(strip=True)
        if texto:
            b.replace_with(f"<b>{texto}</b>")
            
    # 5. Listas con viñetas
    for li in soup.find_all('li'):
        texto = li.get_text(strip=True)
        if texto:
            li.replace_with(f"• {texto}")

    # 6. Extraer el texto preservando nuestras nuevas etiquetas (<a> y <b>)
    texto_sucio = soup.get_text(separator='\n')
    
    # 7. Limpiar CSS residual y entidades
    lineas_filtradas = []
    for linea in texto_sucio.split('\n'):
        l = linea.strip()
        if '{' in l or '}' in l or '@media' in l or 'margin:' in l or 'padding:' in l:
            continue
        if l:
            # Reemplazamos entidades web clásicas a texto real
            l = l.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
            lineas_filtradas.append(l)
            
    # 8. Unir las líneas aplicando un espaciado inteligente y profesional
    texto_final = ""
    for i, linea in enumerate(lineas_filtradas):
        texto_final += linea
        if i < len(lineas_filtradas) - 1:
            # Si ambas líneas son elementos de una lista, las dejamos juntas
            if lineas_filtradas[i+1].startswith('•') and linea.startswith('•'):
                texto_final += "\n"
            else:
                # Todo lo demás recibe doble espacio para mayor limpieza visual
                texto_final += "\n\n"
                
    return texto_final.strip()

# ==========================================
# INTERFAZ Y COMANDOS DEL BOT
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teclado = [
        [InlineKeyboardButton("🎲 Generar Aleatorio", callback_data='btn_aleatorio')],
        [InlineKeyboardButton("✍️ Crear Personalizado", callback_data='btn_personalizado')],
        [InlineKeyboardButton("♻️ Recuperar Correo", callback_data='btn_recuperar')]
    ]
    reply_markup = InlineKeyboardMarkup(teclado)
    texto = (
        "✉️ *Sistema de Correos Temporales*\n\n"
        "Bienvenido. Genera una bandeja de entrada temporal para proteger tu privacidad o verificar cuentas.\n\n"
        "Selecciona una opción del menú:"
    )
    
    context.user_data.clear()
    
    if update.message:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(texto, reply_markup=reply_markup, parse_mode='Markdown')
    return ConversationHandler.END

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    usuario = query.from_user

    if query.data == 'btn_aleatorio':
        dominio = obtener_dominio()
        if not dominio:
            await query.edit_message_text("❌ Error en el servidor. Intenta más tarde.")
            return ConversationHandler.END
            
        nombre_random = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        correo_final = f"{nombre_random}@{dominio}"
        
        requests.get(f"{BASE_URL}/email/{correo_final}/{API_KEY}")
        registrar_auditoria(usuario.id, usuario.username, "Aleatorio", correo_final)
        
        context.user_data['correo_actual'] = correo_final
        await mostrar_bandeja(update, context)
        return ConversationHandler.END

    elif query.data == 'btn_personalizado':
        await query.edit_message_text(
            "✍️ *Crear Correo Personalizado*\n\n"
            "Escribe el nombre que deseas usar (sin incluir el arroba).\n"
            "Ejemplo: `netflix2026`", 
            parse_mode='Markdown'
        )
        return ESPERANDO_PERSONALIZADO

    elif query.data == 'btn_recuperar':
        await query.edit_message_text(
            "♻️ *Recuperar Correo*\n\n"
            "Escribe la dirección de correo completa a la que deseas acceder nuevamente.\n"
            "Ejemplo: `prueba@flawmail.site`", 
            parse_mode='Markdown'
        )
        return ESPERANDO_RECUPERAR

async def procesar_personalizado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_usuario = update.message.text.strip().lower()
    dominio = obtener_dominio()
    correo_final = f"{texto_usuario}@{dominio}"
    
    requests.get(f"{BASE_URL}/email/{correo_final}/{API_KEY}")
    registrar_auditoria(update.message.from_user.id, update.message.from_user.username, "Personalizado", correo_final)
    
    context.user_data['correo_actual'] = correo_final
    class FakeUpdate:
        callback_query = None
        message = update.message
    await mostrar_bandeja(FakeUpdate(), context)
    return ConversationHandler.END

async def procesar_recuperar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correo_final = update.message.text.strip().lower()
    registrar_auditoria(update.message.from_user.id, update.message.from_user.username, "Recuperación", correo_final)
    
    context.user_data['correo_actual'] = correo_final
    class FakeUpdate:
        callback_query = None
        message = update.message
    await mostrar_bandeja(FakeUpdate(), context)
    return ConversationHandler.END

async def mostrar_bandeja(update, context: ContextTypes.DEFAULT_TYPE):
    correo = context.user_data.get('correo_actual')
    if not correo:
        return await start(update, context)

    ahora = datetime.now()
    ultimo_refresh = context.user_data.get('ultimo_refresh')
    if ultimo_refresh and (ahora - ultimo_refresh).total_seconds() < 5:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Espera unos segundos antes de actualizar de nuevo.", show_alert=True)
            return
    
    context.user_data['ultimo_refresh'] = ahora

    mensajes = []
    try:
        res = requests.get(f"{BASE_URL}/messages/{correo}/{API_KEY}")
        if res.status_code == 200:
            mensajes = res.json()
    except:
        pass

    texto = f"📭 *Tu Bandeja Activa:*\n`{correo}`\n\n"
    texto += "*Pulsa sobre el correo para copiarlo.*"

    teclado = [[InlineKeyboardButton("🔄 Actualizar Bandeja", callback_data='btn_actualizar')]]

    if not mensajes:
        texto += "\n\n_Sin mensajes nuevos..._"
    else:
        texto += f"\n\nTienes *{len(mensajes)}* mensaje(s):"
        context.user_data['mensajes_lista'] = mensajes
        for i, msg in enumerate(mensajes[:10]):
            remitente = msg.get('from', msg.get('sender', msg.get('sender_name', msg.get('fromName', 'Desconocido'))))
            asunto = msg.get('subject', 'Sin asunto')[:25]
            teclado.append([InlineKeyboardButton(f"📩 {remitente} - {asunto}...", callback_data=f'leer_{i}')])

    teclado.append([InlineKeyboardButton("🗑️ Desechar y Crear Nuevo", callback_data='btn_inicio')])
    reply_markup = InlineKeyboardMarkup(teclado)

    if update.callback_query:
        await update.callback_query.edit_message_text(texto, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.message:
        await update.message.reply_text(texto, reply_markup=reply_markup, parse_mode='Markdown')

async def bandeja_acciones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'btn_actualizar':
        await mostrar_bandeja(update, context)
    elif query.data == 'btn_inicio':
        await start(update, context)
    elif query.data.startswith('leer_'):
        indice = int(query.data.split('_')[1])
        mensajes = context.user_data.get('mensajes_lista', [])
        
        if indice < len(mensajes):
            msg = mensajes[indice]
            
            remitente = msg.get('from', msg.get('sender', msg.get('sender_name', msg.get('fromName', 'Desconocido'))))
            asunto = msg.get('subject', 'Sin asunto')
            fecha = msg.get('date', 'Fecha desconocida')
            
            html_descargado = msg.get('content') or msg.get('html') or msg.get('body') or msg.get('text') or "No se detectó contenido."
            
            # Texto elegantemente formateado
            texto_inspeccionado = procesar_y_limpiar_html(html_descargado)
            
            # DESTRUCCIÓN DEL CÓDIGO HTML DE LA MEMORIA
            del html_descargado 
            
            if len(texto_inspeccionado) > 3000:
                texto_inspeccionado = texto_inspeccionado[:3000] + "\n\n... [Mensaje extenso recortado por seguridad]"

            # Escapar la cabecera (evita errores si el asunto lleva un "<")
            remitente_seguro = html.escape(str(remitente)).replace('&amp;', '&')
            asunto_seguro = html.escape(str(asunto)).replace('&amp;', '&')
            fecha_segura = html.escape(str(fecha)).replace('&amp;', '&')

            texto_lectura = (
                f"👤 <b>De:</b> {remitente_seguro}\n"
                f"📌 <b>Asunto:</b> {asunto_seguro}\n"
                f"📅 <b>Fecha:</b> {fecha_segura}\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"{texto_inspeccionado}"
            )
            
            teclado = [[InlineKeyboardButton("🔙 Volver a la Bandeja", callback_data='btn_actualizar')]]
            # Utilizamos HTML nativo de Telegram para cargar nuestras etiquetas personalizadas
            await query.edit_message_text(texto_lectura, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='HTML')

async def comando_registros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEBHOOK_URL:
        await update.message.reply_text("La auditoría no está configurada.")
        return

    await update.message.reply_text("⏳ Consultando registros seguros...")
    
    try:
        res = requests.get(WEBHOOK_URL)
        if res.status_code == 200:
            datos = res.json()
            if not datos:
                await update.message.reply_text("📊 La base de datos está vacía.")
                return
            
            respuesta = "🛡️ *ÚLTIMOS MOVIMIENTOS EN EL SISTEMA*\n\n"
            for d in reversed(datos):
                respuesta += f"🕒 `{d['fecha']}`\n"
                respuesta += f"👤 {d['usuario']} | ⚡ {d['accion']}\n"
                respuesta += f"✉️ `{d['correo']}`\n\n"
            
            await update.message.reply_text(respuesta, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Error al conectar con Google Sheets.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error interno: {str(e)}")

# ==========================================
# MOTOR PRINCIPAL
# ==========================================
def main():
    hilo_web = threading.Thread(target=servidor_web, daemon=True)
    hilo_web.start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(menu_callback, pattern='^(btn_aleatorio|btn_personalizado|btn_recuperar)$')
        ],
        states={
            ESPERANDO_PERSONALIZADO: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_personalizado)],
            ESPERANDO_RECUPERAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_recuperar)]
        },
        fallbacks=[CommandHandler('start', start)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(bandeja_acciones, pattern='^(btn_actualizar|btn_inicio|leer_.*)$'))
    app.add_handler(CommandHandler('registrostech', comando_registros))

    app.run_polling()

if __name__ == '__main__':
    main()
