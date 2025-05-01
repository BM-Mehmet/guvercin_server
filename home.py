from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
from connectdb import get_connection
import uvicorn

app = FastAPI()

# CORS ayarları - Uygulamanın farklı alanlardan erişimine izin verir
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tüm domainlerden gelen taleplere izin verir
    allow_credentials=True,
    allow_methods=["*"],  # Tüm HTTP metodlarına izin verir
    allow_headers=["*"],  # Tüm header'lara izin verir
)

# Aktif WebSocket bağlantıları, her bir kullanıcıya WebSocket nesnesi
active_connections: Dict[str, WebSocket] = {}

@app.get("/chats/{username}")
async def get_chats(username: str):
    """
    Kullanıcının mesajlaştığı diğer kişilerin listesini döner.
    Bu API, kullanıcının gönderdiği veya aldığı mesajlara göre sohbet ettiği diğer kullanıcıları getirir.
    """
    try:
        # Veritabanı bağlantısı ve cursor
        db_connection, cursor = get_connection()

        # Kullanıcıya ait sohbetleri sorgula
        query = """
        SELECT DISTINCT
            CASE
                WHEN sender = %s THEN receiver
                WHEN receiver = %s THEN sender
            END AS other_user
        FROM messages
        WHERE (sender = %s OR receiver = %s)
        AND id NOT IN (
            SELECT message_id FROM deleted_messages WHERE user = %s
        )
        """
        # Parametreleri 4 kez aynı şekilde gönderiyoruz
        cursor.execute(query, (username, username, username, username, username))
        results = cursor.fetchall()

        if not results:
            return JSONResponse(status_code=404, content={"message": "Hiç sohbet yok."})

        # Kullanıcıların listesi döndürülür
        users = [row['other_user'] for row in results]
        print(f"Kullanıcılar: {users}")
        
        return {"users": users}

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

    finally:
        # Bağlantıyı ve cursor'u kapat
        cursor.close()
        db_connection.close()

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    """
    WebSocket bağlantısı kurar ve mesaj gönderimini sağlar.
    Bu API, kullanıcılar arasında anlık mesajlaşma işlemini WebSocket ile sağlar.
    """
    await websocket.accept()  # WebSocket bağlantısını kabul et
    active_connections[username] = websocket  # Bağlantıyı aktif bağlantılar listesine ekle
    print(f"{username} bağlandı.")

    try:
        while True:
            data = await websocket.receive_json()  # WebSocket'ten gelen veriyi JSON olarak al
            sender = data.get("sender")  # Gönderen kullanıcı adı
            receiver = data.get("receiver")  # Alıcı kullanıcı adı
            message = data.get("message")  # Gönderilen mesaj

            # Alıcı aktifse, mesajı alıcıya gönder
            if receiver in active_connections:
                await active_connections[receiver].send_json({
                    "type": "new_message",  # Mesaj türü
                    "from": sender,         # Gönderen kullanıcı
                    "message": message      # Mesaj içeriği
                })

    except WebSocketDisconnect:
        # Bağlantı koparsa, aktif bağlantılardan çıkar
        print(f"{username} bağlantısı koptu.")
        active_connections.pop(username, None)

# Uvicorn ile uygulamayı başlat
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5002)

