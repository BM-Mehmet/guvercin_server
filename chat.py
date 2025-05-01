import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import mysql.connector
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, messaging
import redis
from connectdb import get_connection

# Veritabanı bağlantısı
db_connection, cursor = get_connection()

# Redis bağlantısı
redis_client = redis.Redis(host="localhost", port=6379, db=0)

# Firebase Admin başlatılıyor
cred = credentials.Certificate("/home/ubuntu/guvercin/guvercin-b5d67-firebase-adminsdk-ieas1-28df47be95.json")
firebase_admin.initialize_app(cred)

# FastAPI uygulaması
app = FastAPI()

# Aktif WebSocket bağlantılarını tutar
active_connections = {}

# Bildirim gönderme fonksiyonu
def send_fcm_notification(receiver):
    try:
        fcm_token = redis_client.hget(f"user:{receiver}", "fcm_token")
        if fcm_token:
            notification = messaging.Message(
                notification=messaging.Notification(
                    title="Yeni bir mesajınız var!",
                ),
                token=fcm_token.decode()
            )
            response = messaging.send(notification)
            print(f"FCM bildirimi gönderildi: {response}")
        else:
            print(f"⚠️ {receiver} için FCM token bulunamadı.")
    except Exception as e:
        print(f"FCM bildirimi gönderilemedi: {e}")

# WebSocket mesajlaşma endpoint'i
@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    active_connections[username] = websocket

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            sender = message_data["sender"]
            receiver = message_data["receiver"]
            msg_type = message_data.get("type", "text")
            content = message_data.get("message", None)
            file_url = message_data.get("file_url", None)
            file_name = message_data.get("file_name", None)
            mime_type = message_data.get("mime_type", None)

            # Mesajı veritabanına kaydet
            cursor.execute("""
                INSERT INTO messages (sender, receiver, type, content, file_url, file_name, mime_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (sender, receiver, msg_type, content, file_url, file_name, mime_type))
            db_connection.commit()
            message_id = cursor.lastrowid

            # Gönderilecek veri
            message_data["message_id"] = message_id
            message_data["timestamp"] = int(time.time())
            message_data["status"] = "sent"

            json_message = json.dumps(message_data)

            # Alıcı aktifse mesajı gönder, değilse FCM bildirimi gönder
            receiver_ws = active_connections.get(receiver)

            if receiver_ws:
                try:
                    await receiver_ws.send_text(json_message)
                    cursor.execute("UPDATE messages SET delivered = TRUE WHERE id = %s", (message_id,))
                    db_connection.commit()
                except Exception as e:
                    print(f"WebSocket üzerinden mesaj gönderilemedi: {e}")
                    send_fcm_notification(receiver)
            else:
                send_fcm_notification(receiver)

    except WebSocketDisconnect:
        print(f"{username} bağlantısı kesildi.")
        active_connections.pop(username, None)

# Mesajları listeleyen endpoint
@app.get("/get_messages/{user1}/{user2}")
async def get_messages(user1: str, user2: str):
    cursor.execute("""
        SELECT * FROM messages
        WHERE ((sender = %s AND receiver = %s) OR (sender = %s AND receiver = %s))
        AND id NOT IN (
            SELECT message_id FROM deleted_messages WHERE user = %s
        )
        ORDER BY timestamp ASC
    """, (user1, user2, user2, user1, user1))
    messages = cursor.fetchall()
    for msg in messages:
        msg["timestamp"] = int(msg["timestamp"].timestamp())
    return messages

# Mesajı silen endpoint
@app.delete("/delete_message/{username}/{message_id}")
async def delete_message(username: str, message_id: int):
    cursor.execute("SELECT * FROM messages WHERE id = %s", (message_id,))
    result = cursor.fetchone()
    if not result:
        return {"status": "error", "message": "Mesaj bulunamadı"}

    cursor.execute("SELECT * FROM deleted_messages WHERE user = %s AND message_id = %s", (username, message_id))
    if cursor.fetchone():
        return {"status": "error", "message": "Mesaj zaten silinmiş"}

    cursor.execute("INSERT INTO deleted_messages (user, message_id) VALUES (%s, %s)", (username, message_id))
    db_connection.commit()
    return {"status": "success", "message": "Mesaj silindi"}

# Uygulama başlatma
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5004)

