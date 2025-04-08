import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import redis
import uvicorn

# Redis bağlantısı
r = redis.StrictRedis(host='localhost', port=6379, db=0)

# FastAPI uygulaması
app = FastAPI()

# Kullanıcıların aktif WebSocket bağlantılarını tutmak
active_connections = {}

# WebSocket bağlantısı kurma ve mesaj alma/gönderme
@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()

    # Aktif bağlantıyı kaydet
    active_connections[username] = websocket

    try:
        while True:
            data = await websocket.receive_text()  # Gelen veriyi al
            message_data = json.loads(data)

            sender = message_data["sender"]
            receiver = message_data["receiver"]
            message = message_data["message"]

            # Kullanıcı ID'lerini al
            sender_id = None
            receiver_id = None

            for user in r.smembers("users"):
                user_name, user_id = user.decode("utf-8").split(":")
                if user_name == sender:
                    sender_id = user_id
                elif user_name == receiver:
                    receiver_id = user_id

            if not sender_id or not receiver_id:
                continue  # Kullanıcılar bulunamadığında mesaj gönderme

            # Mesajı Redis'e kaydet
            message_data["timestamp"] = int(time.time())  # Zaman damgası ekle
            message_data["status"] = "sent"  # Mesajın durumu: "sent"
            message_json = json.dumps(message_data)

            # Sadece bir tarafın sohbet geçmişine ekle (gerekirse alıcıda da göstermek için)
            r.rpush(f"chat:{sender_id}:{receiver_id}", message_json)

            # Karşı tarafa mesajı ilet
            if receiver in active_connections:
                await active_connections[receiver].send_text(data)

    except WebSocketDisconnect:
        del active_connections[username]  # Bağlantı kesildiğinde bağlantıyı sil

# Mesajları alma işlemi
@app.get("/get_messages/{sender}/{receiver}")
async def get_messages(sender: str, receiver: str):
    # Kullanıcı ID'lerini al
    sender_id = None
    receiver_id = None

    for user in r.smembers("users"):
        user_name, user_id = user.decode("utf-8").split(":")
        if user_name == sender:
            sender_id = user_id
        elif user_name == receiver:
            receiver_id = user_id

    if not sender_id or not receiver_id:
        return {"error": "Kullanıcı ID'si bulunamadı"}, 404

    # Mesajları Redis'ten al
    messages_sender_to_receiver = r.lrange(f"chat:{sender_id}:{receiver_id}", 0, -1)
    messages_receiver_to_sender = r.lrange(f"chat:{receiver_id}:{sender_id}", 0, -1)

    # Mesajları birleştir ve zaman damgasına göre sırala
    all_messages = []
    all_messages.extend([json.loads(msg) for msg in messages_sender_to_receiver])
    all_messages.extend([json.loads(msg) for msg in messages_receiver_to_sender])

    all_messages.sort(key=lambda x: x['timestamp'])

    return all_messages

# Uvicorn ile uygulamayı başlat
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5004)

