from flask import Flask, request, jsonify
import redis
import uuid

app = Flask(__name__)

# Redis bağlantısı
redis_client = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)

@app.route('/register', methods=['POST'])
def register_user():
    try:
        # Gelen veriyi al
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        fcm_token = data.get('fcm')
        public_key = data.get('public_key')

        # Kullanıcı adı kontrolü
        if any(username in entry.split(':')[0] for entry in redis_client.smembers('users')):
            return jsonify({'error': 'Kullanıcı zaten mevcut.'}), 400

        # Benzersiz bir UUID oluştur
        user_id = str(uuid.uuid4())

        # Kullanıcı bilgilerini sakla
        user_data = {
            'username': username,
            'password': password,  # Şifre hashlenebilir
            'fcm_token': fcm_token,
            'public_key': public_key
        }

        # Redis'e kullanıcı ekle
        redis_client.sadd('users', f'{username}:{user_id}')  # username:user_id formatında sakla
        redis_client.hmset(f'user:{username}', user_data)   # Kullanıcı bilgilerini hash olarak sakla

        return jsonify({'message': 'Kullanıcı başarıyla kaydedildi.', 'user_id': user_id}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_user_id/<username>', methods=['GET'])
def get_user_id(username):
    try:
        # Kullanıcı adıyla ilişkili ID'yi bul
        for entry in redis_client.smembers('users'):
            stored_username, stored_user_id = entry.split(':')
            if stored_username == username:
                return jsonify({'user_id': stored_user_id}), 200

        return jsonify({'error': 'Kullanıcı bulunamadı.'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_username/<user_id>', methods=['GET'])
def get_username(user_id):
    try:
        # Kullanıcı ID'siyle ilişkili adı bul
        for entry in redis_client.smembers('users'):
            stored_username, stored_user_id = entry.split(':')
            if stored_user_id == user_id:
                return jsonify({'username': stored_username}), 200

        return jsonify({'error': 'Kullanıcı bulunamadı.'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

