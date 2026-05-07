import asyncio
import ssl
import logging
import os
import aiomqtt

# 1. Configuración de logging (incluye el nombre de la tarea)
logging.basicConfig(
    format='%(asctime)s - %(taskName)s - %(levelname)s: %(message)s', 
    level=logging.INFO, 
    datefmt='%d/%m/%Y %H:%M:%S %z'
)

# --- CORRUTINAS DEL CONTADOR ---

async def incrementar_contador(estado):
    """Incrementa el contador cada 3 segundos."""
    while True:
        await asyncio.sleep(3)
        estado["contador"] += 1
        logging.info(f"Contador interno actualizado a: {estado['contador']}")

async def publicar_estado(client, estado):
    """Publica el estado del contador cada 5 segundos."""
    topico_pub = os.environ['TOPICOPUBLICAR']
    while True:
        await asyncio.sleep(5)
        mensaje = f"Valor del contador: {estado['contador']}"
        await client.publish(topico_pub, payload=mensaje)
        logging.info(f"Mensaje publicado en {topico_pub}: {mensaje}")

# --- CORRUTINAS DE LECTURA (PATRÓN ENRUTADOR) ---

async def atender_topico_1(message):
    """Corrutina dedicada exclusivamente a atender el primer tópico."""
    logging.info(f"Mensaje procesado en Tópico 1: {message.payload.decode('utf-8')}")

async def atender_topico_2(message):
    """Corrutina dedicada exclusivamente a atender el segundo tópico."""
    logging.info(f"Mensaje procesado en Tópico 2: {message.payload.decode('utf-8')}")

async def enrutador_mensajes(client):
    """Lee la tubería principal y distribuye a la corrutina correspondiente."""
    topico1 = os.environ['TOPICOSUB1']
    topico2 = os.environ['TOPICOSUB2']
    
    async for message in client.messages:
        # Se evalúa el tópico y se delega el mensaje creando una tarea independiente
        if message.topic.matches(topico1):
            asyncio.create_task(atender_topico_1(message), name="Task-Atendedor-1")
        elif message.topic.matches(topico2):
            asyncio.create_task(atender_topico_2(message), name="Task-Atendedor-2")

# --- ORQUESTACIÓN PRINCIPAL ---

async def main():
    # Estado compartido (sin variables globales)
    estado_compartido = {"contador": 0}

    # Configuración de comunicación cifrada (MQTTS)
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()

    # Creación de UN SOLO objeto client
    async with aiomqtt.Client(
        os.environ['SERVIDOR'],
        port=8883,
        tls_context=tls_context,
    ) as client:
        
        # Suscripción a los tópicos definidos en las variables de entorno
        await client.subscribe(os.environ['TOPICOSUB1'])
        await client.subscribe(os.environ['TOPICOSUB2'])

        # Lanzamiento de las corrutinas principales en paralelo
        async with asyncio.TaskGroup() as tg:
            tg.create_task(incrementar_contador(estado_compartido), name="Task-Contador")
            tg.create_task(publicar_estado(client, estado_compartido), name="Task-Publicador")
            tg.create_task(enrutador_mensajes(client), name="Task-Enrutador")

if __name__ == "__main__":
    # Captura de la excepción al detener el programa
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Programa detenido correctamente por el usuario (Ctrl-C).")