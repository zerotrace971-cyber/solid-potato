import asyncio
import aio_pika
import json


CLOUDAMQP_URL = "amqps://ivndelvt:gs1Fmh81WXlTAvyYFMURyJmjFOHWWplf@warthog.lmq.cloudamqp.com/ivndelvt"


async def main():
  
    connection = await aio_pika.connect_robust(
        CLOUDAMQP_URL
    )

    channel = await connection.channel()

    queue = await channel.declare_queue(
        "security_events"
    )
    events = []
    with open("logs/events.jsonl", "r") as file:
        for line in file:
            line = line.strip()
            if line:
                events.append(json.loads(line))
        
    message = aio_pika.Message(
            body=json.dumps(events).encode()
        )    
    await channel.default_exchange.publish(
            message,
            routing_key=queue.name,
        )
    await connection.close()
    
    
    
    
asyncio.run(main())    