import os
import logging
import asyncio
import json
import aiomqtt
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

token = os.environ["TB_TOKEN"]

logging.basicConfig(format='%(asctime)s - TelegramBot - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

estado_termostato = {
    "temperatura": 0.0,
    "humedad": 0.0,
    "setpoint": 0.0,
    "periodo": 0,
    "modo": "desconocido",
    "rele": 0
}

mqtt_client_global = None 
ESPERANDO_SETPOINT = 1 

async def mqtt_background_task():
    global mqtt_client_global, estado_termostato
    host = "mosquitto" 
    usr = os.environ.get("MQTT_USR")
    pwd = os.environ.get("MQTT_PASS")
    
    try:
        async with aiomqtt.Client(hostname=host, port=1883, username=usr, password=pwd) as client:
            mqtt_client_global = client
            await client.subscribe("28:cd:c1:05:57:12")
            logger.info("Bot conectado a Mosquitto")
            
            async for message in client.messages:
                tema = message.topic.value
                payload = message.payload.decode()
                
                if tema == "28:cd:c1:05:57:12":
                    try:
                        datos = json.loads(payload)
                        estado_termostato.update(datos)
                        logger.info(f"Cache actualizada: Temp {estado_termostato['temperatura']} C")
                    except json.JSONDecodeError:
                        logger.error("Recibido payload MQTT no valido.")
                        
    except aiomqtt.MqttError as e:
        logger.error(f"Error MQTT: {e}")

async def post_init(application: Application):
    asyncio.create_task(mqtt_background_task())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nombre = update.effective_user.first_name

    teclado = [
        ["Estado Actual", "Cambiar Modo"],
        ["Setpoint", "Control Rele"],
        ["Test Destello"]
    ]
    reply_markup = ReplyKeyboardMarkup(teclado, resize_keyboard=True)
    
    await update.message.reply_text(
        f"Hola {nombre}. Soy el bot de control de tu Termostato IoT.\nQue deseas hacer?",
        reply_markup=reply_markup
    )

async def manejar_teclado_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    
    if texto == "Estado Actual":
        estado_r = "PRENDIDO" if estado_termostato['rele'] == 1 else "APAGADO"
        msg = (
            f"*Temperatura:* {estado_termostato['temperatura']} C\n"
            f"*Humedad:* {estado_termostato['humedad']} %\n"
            f"*Setpoint:* {estado_termostato['setpoint']} C\n"
            f"*Modo:* {estado_termostato['modo'].capitalize()}\n"
            f"*Rele:* {estado_r}\n"
            f"*Periodo de envio:* {estado_termostato['periodo']} seg"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')

    elif texto == "Cambiar Modo":
        teclado_inline = [
            [InlineKeyboardButton("Automatico", callback_data="modo_automatico"),
             InlineKeyboardButton("Manual", callback_data="modo_manual")]
        ]
        reply_markup = InlineKeyboardMarkup(teclado_inline)
        await update.message.reply_text("Selecciona el modo de operacion:", reply_markup=reply_markup)

    elif texto == "Control Rele":
        if estado_termostato["modo"] == "automatico":
            await update.message.reply_text("El termostato esta en modo *Automatico*. Cambialo a Manual para usar esta funcion.", parse_mode='Markdown')
        else:
            teclado_inline = [
                [InlineKeyboardButton("Prender", callback_data="rele_1"),
                 InlineKeyboardButton("Apagar", callback_data="rele_0")]
            ]
            reply_markup = InlineKeyboardMarkup(teclado_inline)
            await update.message.reply_text("Control manual del rele:", reply_markup=reply_markup)
            
    elif texto == "Test Destello":
        if mqtt_client_global:
            await mqtt_client_global.publish("28:cd:c1:05:57:12/destello", payload="destello", qos=1)
            await update.message.reply_text("Orden de destello enviada a la placa.")
        else:
            await update.message.reply_text("Error: No hay conexion con el Broker MQTT.")

async def manejar_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    dato = query.data
    
    if dato.startswith("modo_"):
        nuevo_modo = dato.split("_")[1]
        if mqtt_client_global:
            await mqtt_client_global.publish("28:cd:c1:05:57:12/modo", payload=nuevo_modo, qos=1)
            await query.edit_message_text(f"Orden enviada: Modo cambiado a *{nuevo_modo}*.", parse_mode='Markdown')
            
    elif dato.startswith("rele_"):
        estado_rele = dato.split("_")[1]
        if mqtt_client_global:
            await mqtt_client_global.publish("28:cd:c1:05:57:12/rele", payload=estado_rele, qos=1)
            accion = "Prender" if estado_rele == "1" else "Apagar"
            await query.edit_message_text(f"Orden enviada: {accion} rele.")

async def pedir_setpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Setpoint":
        await update.message.reply_text("Por favor, escribi el nuevo valor de Setpoint (ejemplo: 24.5) o /cancelar para salir:")
        return ESPERANDO_SETPOINT
    return ConversationHandler.END

async def guardar_setpoint(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    try:
        nuevo_setpoint = float(texto.replace(",", ".")) 
        if nuevo_setpoint >= 0:
            if mqtt_client_global:
                await mqtt_client_global.publish("28:cd:c1:05:57:12/setpoint", payload=str(nuevo_setpoint), qos=1)
                await update.message.reply_text(f"Nuevo setpoint enviado: {nuevo_setpoint} C")
            return ConversationHandler.END
        else:
            await update.message.reply_text("El setpoint no puede ser negativo. Intenta con otro numero:")
            return ESPERANDO_SETPOINT
    except ValueError:
        await update.message.reply_text("Formato invalido. Ingresa un numero (ej: 25.5):")
        return ESPERANDO_SETPOINT

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operacion cancelada.")
    return ConversationHandler.END

if __name__ == '__main__':
    application = Application.builder().token(token).post_init(post_init).build()
    application.add_handler(CommandHandler('start', start))
    
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Setpoint$"), pedir_setpoint)],
        states={
            ESPERANDO_SETPOINT: [MessageHandler(filters.TEXT & ~filters.COMMAND, guardar_setpoint)],
        },
        fallbacks=[CommandHandler('cancelar', cancelar)]
    )
    application.add_handler(conv_handler)
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_teclado_principal))
    application.add_handler(CallbackQueryHandler(manejar_callbacks))
    
    logger.info("Bot iniciando...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
