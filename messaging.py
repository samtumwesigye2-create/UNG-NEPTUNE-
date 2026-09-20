"""NEPTUNE messaging backbone: Kafka-compatible event streams + RabbitMQ work queues.

Messaging is optional: NEPTUNE remains operational when brokers are unavailable.
PULSAR is the enterprise event backbone; NEXUS owns cross-system contracts.
"""
import json, os, uuid
from datetime import datetime, timezone
from typing import Any

KAFKA_BOOTSTRAP_SERVERS=os.getenv("KAFKA_BOOTSTRAP_SERVERS","")
KAFKA_SCHEMA_REGISTRY_URL=os.getenv("KAFKA_SCHEMA_REGISTRY_URL","")
RABBITMQ_URL=os.getenv("RABBITMQ_URL","")
NEXUS_BASE_URL=os.getenv("NEXUS_BASE_URL","")
PULSAR_BASE_URL=os.getenv("PULSAR_BASE_URL","")

TOPICS={
 "events":"neptune.events.v1",
 "tracks":"neptune.tracks.v1",
 "tasks":"neptune.tasks.v1",
 "readiness":"neptune.readiness.v1",
 "communications":"neptune.communications.v1",
 "audit":"neptune.audit.v1",
}
QUEUES={
 "workflow":"neptune.workflow.v1",
 "sync":"neptune.edge-sync.v1",
 "notifications":"neptune.notifications.v1",
}

def envelope(event_type:str,payload:dict[str,Any],classification:str="UNCLASSIFIED",releasability:str="INTERNAL")->dict[str,Any]:
    return {"schema":"ung.neptune.event","schema_version":"1.0.0","event_id":str(uuid.uuid4()),
      "event_type":event_type,"source":"UNG-NEPTUNE","occurred_at":datetime.now(timezone.utc).isoformat(),
      "classification":classification,"releasability":releasability,"payload":payload}

def status()->dict[str,Any]:
    return {"kafka":{"configured":bool(KAFKA_BOOTSTRAP_SERVERS),"schema_registry":bool(KAFKA_SCHEMA_REGISTRY_URL),"topics":TOPICS},
      "rabbitmq":{"configured":bool(RABBITMQ_URL),"queues":QUEUES},
      "integration":{"nexus":bool(NEXUS_BASE_URL),"pulsar":bool(PULSAR_BASE_URL)}}

async def publish_event(topic_key:str,event_type:str,payload:dict[str,Any],classification:str="UNCLASSIFIED",releasability:str="INTERNAL")->dict[str,Any]:
    msg=envelope(event_type,payload,classification,releasability)
    # Broker adapters are deliberately fail-soft so command functions do not depend on broker availability.
    if not KAFKA_BOOTSTRAP_SERVERS:
        return {"published":False,"reason":"kafka_not_configured","topic":TOPICS.get(topic_key,topic_key),"event":msg}
    try:
        from aiokafka import AIOKafkaProducer
        producer=AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
        await producer.start()
        try: await producer.send_and_wait(TOPICS.get(topic_key,topic_key),json.dumps(msg).encode())
        finally: await producer.stop()
        return {"published":True,"topic":TOPICS.get(topic_key,topic_key),"event_id":msg["event_id"]}
    except Exception as exc:
        return {"published":False,"reason":type(exc).__name__,"topic":TOPICS.get(topic_key,topic_key),"event_id":msg["event_id"]}

async def enqueue(queue_key:str,body:dict[str,Any])->dict[str,Any]:
    queue=QUEUES.get(queue_key,queue_key)
    if not RABBITMQ_URL: return {"queued":False,"reason":"rabbitmq_not_configured","queue":queue}
    try:
        import aio_pika
        conn=await aio_pika.connect_robust(RABBITMQ_URL)
        try:
            ch=await conn.channel(); q=await ch.declare_queue(queue,durable=True)
            await ch.default_exchange.publish(aio_pika.Message(body=json.dumps(body).encode(),delivery_mode=aio_pika.DeliveryMode.PERSISTENT),routing_key=q.name)
        finally: await conn.close()
        return {"queued":True,"queue":queue}
    except Exception as exc: return {"queued":False,"reason":type(exc).__name__,"queue":queue}
