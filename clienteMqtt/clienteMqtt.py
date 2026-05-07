import asyncio
import ssl
import logging
import os
import aiomqtt

logging.basicConfig(
    format='%(asctime)s - %(taskName)s - %(levelname)s: %(message)s', 
    level=logging.INFO, 
    datefmt='%d/%m/%Y %H:%M:%S %z'
)

async def incrementar_contador(estado):
    while True:
        await asyncio.sleep(3)
        estado["contador"] += 1
        logging.info(f"Contador interno actualizado a: {estado['contador']}")

async def publicar_estado(client, estado):
    topico_pub = os.environ['TOPICOPUBLICAR']
    while True:
        await asyncio.sleep(5)
        mensaje = f"Valor del contador: {estado['contador']}"
        await client.publish(topico_pub, payload=mensaje)
        logging.info(f"Mensaje publicado en {topico_pub}: {mensaje}")


async def atender_topico_1(message):
    logging.info(f"Mensaje procesado en Tópico 1: {message.payload.decode('utf-8')}")

async def atender_topico_2(message):
    logging.info(f"Mensaje procesado en Tópico 2: {message.payload.decode('utf-8')}")

async def enrutador_mensajes(client):
    topico1 = os.environ['TOPICOSUB1']
    topico2 = os.environ['TOPICOSUB2']
    
    async for message in client.messages:
        if message.topic.matches(topico1):
            asyncio.create_task(atender_topico_1(message), name="Task-Atendedor-1")
        elif message.topic.matches(topico2):
            asyncio.create_task(atender_topico_2(message), name="Task-Atendedor-2")

async def main():
    estado_compartido = {"contador": 0}
    tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls_context.verify_mode = ssl.CERT_REQUIRED
    tls_context.check_hostname = True
    tls_context.load_default_certs()

    async with aiomqtt.Client(
        os.environ['SERVIDOR'],
        port=8883,
        tls_context=tls_context,
    ) as client:
        
        # Suscripción a los tópicos
        await client.subscribe(os.environ['TOPICOSUB1'])
        await client.subscribe(os.environ['TOPICOSUB2'])

        # Corrutinas principales en paralelo
        async with asyncio.TaskGroup() as tg:
            tg.create_task(incrementar_contador(estado_compartido), name="Task-Contador")
            tg.create_task(publicar_estado(client, estado_compartido), name="Task-Publicador")
            tg.create_task(enrutador_mensajes(client), name="Task-Enrutador")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Programa detenido correctamente por el usuario (Ctrl-C).")