from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
import redis
import uvicorn

app = FastAPI()

# Redis bağlantısı
r = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# CORS ayarları
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Aktif WebSocket bağlantılarını tutan sözlük
active_connections: Dict[str, WebSocket] = {}

@app.get("/chats/{username}")
async def get_chats(username: str):
    """
    Kullanıcının mesajlaştığı diğer kişilerin listesini döner.
    """
    user_id = None
    # Kullanıcı bilgilerini Redis'ten al
    for user in r.smembers("users"):
        stored_username, stored_user_id = user.split(":")
        if stored_username == username:
            user_id = stored_user_id
            break

    # Kullanıcı bulunamadıysa 404 dön
    if not user_id:
        return JSONResponse(status_code=404, content={"message": "User not found"})

    chats = set()
    # Redis'ten chat anahtarlarını al
    chat_keys = r.keys(f"chat:{user_id}:*") + r.keys(f"chat:*:{user_id}")
    
    for key in chat_keys:
        parts = key.split(":")
        other_user_id = parts[2] if parts[1] == user_id else parts[1]

        # Diğer kullanıcıyı bul ve listeye ekle
        for user in r.smembers("users"):
            stored_username, stored_user_id = user.split(":")
            if stored_user_id == other_user_id and stored_username != username:
                chats.add(stored_username)
                break

    # Eğer sohbet bulunmazsa 404 dön
    if not chats:
        return JSONResponse(status_code=404, content={"message": "No other users found"})

    return {"users": list(chats)}

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    """
    WebSocket bağlantısı kurar ve mesaj gönderimini sağlar.
    """
    await websocket.accept()
    active_connections[username] = websocket
    print(f"{username} joined.")

    try:
        while True:
            data = await websocket.receive_json()
            sender = data.get("sender")
            receiver = data.get("receiver")
            message = data.get("message")

            # Gönderilen mesajı alıcıya yönlendir
            print(f"{sender} -> {receiver}: {message}")

            if receiver in active_connections:
                await active_connections[receiver].send_json({
                    "sender": sender,
                    "receiver": receiver,
                    "message": message
                })

    except WebSocketDisconnect:
        print(f"{username} disconnected")
        active_connections.pop(username, None)

# Uvicorn ile uygulamayı başlat
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5002)

