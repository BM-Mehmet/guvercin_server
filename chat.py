import os
import json
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import uvicorn
import firebase_admin
from firebase_admin import credentials, messaging
import redis
from connectdb import get_connection

redis_client = redis.Redis(host="localhost", port=6379, db=0)

cred = credentials.Certificate("/home/gcloude/guvercin/guvercin-b5d67-firebase-adminsdk-ieas1-28df47be95.json")
firebase_admin.initialize_app(cred)

app = FastAPI()

active_connections: dict[str, WebSocket] = {}
USER_FILES_PATH = "/home/gcloude/download_file"
download_tokens: dict[str, str] = {}

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
            print(f"FCM bildirimi gonderildi: {response}")
        else:
            print(f"{receiver} icin FCM token bulunamadi.")
    except Exception as e:
        print(f"FCM bildirimi gonderilemedi: {e}")

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
    print(f"{username} baglandi.")

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
                    print(f"WebSocket mesaji gonderilemedi: {e}")
                    send_fcm_notification(receiver)
            else:
                send_fcm_notification(receiver)

            await websocket.send_text(json_message)

    except WebSocketDisconnect:
        print(f"🔌 {username} baglantisi kesildi.")
        active_connections.pop(username, None)

@app.websocket("/ws/{username}/seen")
async def websocket_seen(websocket: WebSocket, username: str):
    await websocket.accept()
    active_connections[username] = websocket
    print(f"👁 {username} seen guncelleyiciye baglandi.")

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
                    print(f"{ws_user} icin seen verisi gonderilemedi: {e}")

    except WebSocketDisconnect:
        print(f"👁🔌 {username} seen baglantisi kesildi.")
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
        raise HTTPException(status_code=404, detail="Dosya bilgisi bulunamadi.")

    file_path = result["file_url"]
    message_id = result["id"]

    if not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="Dosya fiziksel olarak mevcut degil.")

    def delete_message():
        try:
            conn2, cursor2 = get_connection()
            cursor2.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            conn2.commit()
            cursor2.close()
            conn2.close()
        except Exception as e:
            print("Veritabani silme hatasi:", e)

   #background_tasks.add_task(delete_message)

    return FileResponse(
        path=file_path,
        filename=os.path.basename(file_path),
        media_type="application/octet-stream"
    )
@app.delete("/delete_message/{message_id}")
def delete_message(message_id: int):
    # 1) Mesaj bilgisini al (fiziksel dosya yolu için)
    conn, cursor = get_connection()
    cursor.execute("SELECT file_url FROM messages WHERE id = %s", (message_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Mesaj bulunamadı.")
    
    file_path = row.get("file_url")
    
    # 2) Veritabanından mesaj kaydını sil
    cursor.execute("DELETE FROM messages WHERE id = %s", (message_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "success", "message": f"Mesaj {message_id} silindi."}

#background_tasks.add_task(delete_message)

@app.get("/get_messages/{user1}/{user2}")
async def get_messages(user1: str, user2: str):
    conn, cursor = get_connection()
    cursor.execute("""
        SELECT * FROM messages
        WHERE (sender = %s AND receiver = %s) OR (sender = %s AND receiver = %s)
        ORDER BY timestamp ASC
    """, (user1, user2, user2, user1))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    for row in rows:
        if "timestamp" in row and row["timestamp"]:
            row["timestamp"] = int(row["timestamp"].timestamp())
        if "seen_at" in row and row.get("seen_at"):
            row["seen_at"] = row["seen_at"].isoformat()

    return rows

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5004)

