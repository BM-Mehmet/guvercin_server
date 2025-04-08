from flask import Flask, jsonify, request
import redis

app = Flask(__name__)

# Redis bağlantısını kuruyoruz
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

# Kullanıcı adı var mı kontrolü
@app.route('/check_user', methods=['GET'])
def check_user():
    username = request.args.get('username')

    # 'users' set'ini alıyoruz
    all_users = redis_client.smembers('users')

    # Kullanıcı adıyla tam eşleşen bir kullanıcı var mı kontrol ediyoruz
    for user in all_users:
        if user.startswith(username + ":"):
            return jsonify({"message": "Kullanıcı mevcut", "exists": True}), 200

    return jsonify({"message": "Kullanıcı bulunamadı", "exists": False}), 404

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5003)

