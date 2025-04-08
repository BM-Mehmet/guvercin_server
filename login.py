from flask import Flask, request, jsonify
import redis
import jwt
import secrets
from datetime import datetime, timedelta, timezone

app = Flask(__name__)

# Redis bağlantısı
r = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)

# JWT için Secret Key
SECRET_KEY = secrets.token_hex(32)
print(f"SECRET_KEY: {SECRET_KEY}")

# Kullanıcı giriş endpoint'i
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    device_name = data.get('device')

    if not username or not password:
        return jsonify({'error': 'Kullanıcı adı ve şifre gereklidir!'}), 400

    # Redis'teki kullanıcıyı kontrol et
    user_key = f"user:{username}"
    stored_user = r.hgetall(user_key)

    if not stored_user:
        return jsonify({'error': 'Kullanıcı bulunamadı!'}), 404

    if stored_user.get('password') != password:
        return jsonify({'error': 'Kullanıcı adı veya şifre hatalı!'}), 401

    # JWT token oluştur
    token = jwt.encode(
        {
            'username': username,
            'device': device_name,
            'exp': datetime.now(timezone.utc) + timedelta(days=7)  # Token geçerlilik süresi: 7 gün
        },
        SECRET_KEY,
        algorithm='HS256'
    )

    # Redis'te oturumu sakla
    session_key = f"session:{username}"
    r.set(session_key, token)
    r.expire(session_key, 7 * 24 * 60 * 60)  # 7 gün TTL

    return jsonify({'message': 'Giriş başarılı!', 'token': token}), 201

# Oturum doğrulama endpoint'i
@app.route('/check-session', methods=['POST'])
def check_session():
    data = request.get_json()
    token = data.get('token')

    if not token:
        return jsonify({'error': 'Token eksik!'}), 400

    try:
        # Token doğrula
        decoded = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        username = decoded.get('username')

        # Redis'teki oturumu kontrol et
        session_key = f"session:{username}"
        stored_token = r.get(session_key)

        if not stored_token or stored_token != token:
            return jsonify({'valid': False, 'message': 'Oturum geçersiz!'}), 401

        return jsonify({'valid': True, 'message': 'Oturum geçerli!', 'username': username}), 200
    except jwt.ExpiredSignatureError:
        return jsonify({'valid': False, 'message': 'Token süresi dolmuş!'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'valid': False, 'message': 'Geçersiz token!'}), 401

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)

