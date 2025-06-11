import os
import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Body
from fastapi.responses import FileResponse
import uvicorn

import firebase_admin
from firebase_admin import credentials, messaging
import redis

from connectdb import get_connection  # Senin DB bağlantını getiren fonksiyon

# Redis ayarları
redis_client = redis.Redis(host="localhost", port=6379, db=0)

# Firebase admin başlatma
cred = credentials.Certificate("/home/gcloude/guvercin/guvercin-b5d67-firebase-adminsdk-ieas1-28df47be95.json")
firebase_admin.initialize_app(cred)

app = FastAPI()

active_connections: dict[str, WebSocket] = {}
USER_FILES_PATH = "/home/gcloude/download_file"
download_tokens: dict[str, str] = {}

@app.get("/public_key/{username}")
async def get_public_key(username: str):
    key = f"user:{username}"
    if not redis_client.exists(key):
        raise HTTPException(status_code=404, detail="User not found")
    public_key = redis_client.hget(key, "public_key")
    if public_key:
        return {"username": username, "public_key": public_key.decode()}
    else:
        raise HTTPException(status_code=404, detail="Public key not found")




def send_fcm_notification(receiver: str):
    try:
        fcm_token = redis_client.hget(f"user:{receiver}", "fcm_token")
        if fcm_token:
            message = messaging.Message(
                notification=messaging.Notification(
                    title="Yeni bir mesajınız var!",
                ),
                token=fcm_token.decode()
            )
            response = messaging.send(message)
            print(f"FCM bildirimi gönderildi: {response}")
        else:
            print(f"{receiver} için FCM token bulunamadı.")
    except Exception as e:
        print(f"FCM bildirimi gönderilemedi: {e}")

async def save_file(file: bytes, username: str, filename: str) -> str:
    user_folder = os.path.join(USER_FILES_PATH, username)
    os.makedirs(user_folder, exist_ok=True)
    file_path = os.path.join(user_folder, filename)
    with open(file_path, "wb") as f:
        f.write(file)

    token = str(uuid.uuid4())
    download_tokens[token] = file_path
    return token

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await websocket.accept()
    active_connections[username] = websocket
    print(f"{username} bağlandı.")

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            sender = message_data["sender"]
            receiver = message_data["receiver"]
            msg_type = message_data.get("type", "text")
            content = message_data.get("message")
            file_name = message_data.get("file_name")
            mime_type = message_data.get("mime_type")
            timestamp = datetime.now(timezone.utc)
            file_url = None

            if msg_type == "file" and file_name:
                file_bytes = await websocket.receive_bytes()
                download_token = await save_file(file_bytes, receiver, file_name)
                file_url = f"{USER_FILES_PATH}/{receiver}/{file_name}"

            conn, cursor = get_connection()
            cursor.execute("""
                INSERT INTO messages (sender, receiver, type, content, file_url, file_name, mime_type, timestamp, delivered, seen)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, FALSE)
            """, (sender, receiver, msg_type, content, file_url, file_name, mime_type, timestamp))
            conn.commit()
            message_id = cursor.lastrowid
            cursor.close()
            conn.close()

            message_data.update({
                "message_id": message_id,
                "timestamp": int(timestamp.timestamp()),
                "file_url": file_url,
                "status": "sent",
                "delivered": receiver in active_connections,
                "seen": False
            })

            json_message = json.dumps(message_data)
            receiver_ws = active_connections.get(receiver)

            if receiver_ws:
                try:
                    await receiver_ws.send_text(json_message)
                    conn, cursor = get_connection()
                    cursor.execute("UPDATE messages SET delivered = TRUE WHERE id = %s", (message_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                except Exception as e:
                    print(f"WebSocket mesajı gönderilemedi: {e}")
                    send_fcm_notification(receiver)
            else:
                send_fcm_notification(receiver)

            await websocket.send_text(json_message)

    except WebSocketDisconnect:
        print(f"🔌 {username} bağlantısı kesildi.")
        active_connections.pop(username, None)

@app.websocket("/ws/{username}/seen")
async def websocket_seen(websocket: WebSocket, username: str):
    await websocket.accept()
    active_connections[username] = websocket
    print(f"👁 {username} seen güncelleyiciye bağlandı.")

    try:
        while True:
            seen_data = await websocket.receive_text()
            seen_msg = json.loads(seen_data)

            message_id = seen_msg["message_id"]
            seen_status = seen_msg["seen"]

            conn, cursor = get_connection()
            cursor.execute("UPDATE messages SET seen = %s WHERE id = %s", (seen_status, message_id))
            conn.commit()
            cursor.close()
            conn.close()

            for ws_user, ws in active_connections.items():
                try:
                    await ws.send_text(seen_data)
                except Exception as e:
                    print(f"{ws_user} için seen verisi gönderilemedi: {e}")

    except WebSocketDisconnect:
        print(f"👁🔌 {username} seen bağlantısı kesildi.")
        active_connections.pop(username, None)

@app.get("/download_file/{username}/{file_name}")
def download_file(username: str, file_name: str, background_tasks: BackgroundTasks):
    conn, cursor = get_connection()
    cursor.execute("""
        SELECT id, file_url FROM messages
        WHERE receiver = %s AND file_name = %s
        ORDER BY id DESC LIMIT 1
    """, (username, file_name))
    result = cursor.fetchone()
    cursor.close()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="Dosya bilgisi bulunamadı.")

    file_path = result["file_url"]
    message_id = result["id"]

    if not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="Dosya fiziksel olarak mevcut değil.")

    def delete_message():
        try:
            conn2, cursor2 = get_connection()
            cursor2.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            conn2.commit()
            cursor2.close()
            conn2.close()
        except Exception as e:
            print("Veritabanı silme hatası:", e)

    # İstersen dosya indirildikten sonra mesaj silinebilir
    # background_tasks.add_task(delete_message)

    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="application/octet-stream"
    )

@app.post("/delete_message/{message_id}")
async def delete_message(message_id: int, payload: dict = Body(...)):
    username = payload.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="Kullanıcı adı gerekli.")

    conn, cursor = get_connection()
    cursor.execute(
        "SELECT 1 FROM deleted_messages WHERE message_id = %s AND user = %s",
        (message_id, username)
    )
    existing = cursor.fetchone()
    if existing:
        cursor.close()
        conn.close()
        return {"status": "already_deleted"}

    cursor.execute(
        "INSERT INTO deleted_messages (message_id, user) VALUES (%s, %s)",
        (message_id, username)
    )
    conn.commit()
    cursor.close()
    conn.close()

    return {"status": "deleted"}

@app.get("/get_messages/{user1}/{user2}")
async def get_messages(user1: str, user2: str):
    conn, cursor = get_connection()

    cursor.execute("""
        SELECT * FROM messages
        WHERE ((sender = %s AND receiver = %s)
               OR (sender = %s AND receiver = %s))
          AND id NOT IN (
              SELECT message_id FROM deleted_messages WHERE user = %s
          )
        ORDER BY timestamp
    """, (user1, user2, user2, user1, user1))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Zaman damgalarını uygun hale getir
    for row in rows:
        if "timestamp" in row and row["timestamp"]:
            row["timestamp"] = int(row["timestamp"].timestamp())
        if "seen_at" in row and row.get("seen_at"):
            row["seen_at"] = row["seen_at"].isoformat()

    return rows


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5004)

