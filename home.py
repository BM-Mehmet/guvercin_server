from flask import Flask, jsonify
import redis

app = Flask(__name__)

# Redis bağlantısı
r = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

@app.route('/chats/<username>', methods=['GET'])
def get_chats(username):
    """
    Kullanıcının mesajlaştığı diğer kişilerin listesini döner.
    """
    # Kullanıcı adı ile ID'yi al
    user_id = None
    for user in r.smembers("users"):
        stored_username, stored_user_id = user.split(":")
        if stored_username == username:
            user_id = stored_user_id
            break

    if not user_id:
        return jsonify({"message": "User not found"}), 404

    chats = set()  # Tekrarlı kullanıcıları engellemek için set kullanılıyor

    # Redis'teki sohbet anahtarlarını al
    chat_keys = r.keys(f"chat:{user_id}:*") + r.keys(f"chat:*:{user_id}")

    for key in chat_keys:
        parts = key.split(":")
        # 'chat:{user1}:{user2}' formatında key'den karşı tarafı bul
        other_user_id = parts[2] if parts[1] == user_id else parts[1]

        # Alıcı için kullanıcı adını al
        for user in r.smembers("users"):
            stored_username, stored_user_id = user.split(":")
            if stored_user_id == other_user_id and stored_username != username:
                chats.add(stored_username)
                break

    if not chats:
        return jsonify({"message": "No other users found"}), 404

    # Listeyi döndür
    return jsonify({"users": list(chats)}), 200

if __name__ == '__main__':
    # Sunucuyu 0.0.0.0 adresinde başlatıyoruz
    app.run(debug=True, host='0.0.0.0', port=5002)

