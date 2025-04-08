from fastapi import FastAPI, HTTPException
import redis
import logging
import uvicorn

# FastAPI uygulamasını başlatma
app = FastAPI()

# Redis bağlantısı oluşturma
r = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# Logging yapılandırması
logging.basicConfig(level=logging.INFO)

@app.delete("/delete_user/{username}")
async def delete_user_account(username: str):
    """
    Kullanıcı adı ile ilişkili verileri siler
    """
    # Kullanıcının `users` setinde olup olmadığını kontrol et
    users = r.smembers("users")
    user_id = None

    for user in users:
        if user.startswith(f"{username}:"):
            user_id = user.split(":")[1]  # Kullanıcı ID'sini al
            break

    print(f"username: {username}")  # username yazdırma
    print(f"user_id: {user_id}")  # user_id yazdırma

    if not user_id:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    # Kullanıcıya ait session anahtarını sil
    session_key = f"session:{username}"
    r.delete(session_key)
    logging.info(f"Deleted session: {session_key}")

    # Kullanıcıyı 'users' kümesinden çıkar
    r.srem('users', f"{username}:{user_id}")

    # Kullanıcıya ait chat anahtarlarını sil (wildcard ile)
    cursor = 0
    while True:
        cursor, chat_keys = r.scan(cursor, match=f"chat:{user_id}:*")
        for chat_key in chat_keys:
            r.delete(chat_key)
            logging.info(f"Deleted chat key: {chat_key}")
        if cursor == 0:
            break

    # Kullanıcı bilgilerini de sil
    user_key = f"user:{username}"
    r.delete(user_key)
    logging.info(f"Deleted user key: {user_key}")

    return {"message": f"Hesap ve ilişkili veriler başarıyla silindi: {username}", "status": "success"}

# Uvicorn ile uygulamayı çalıştırma
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5005)

