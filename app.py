from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import secrets
import os
from datetime import datetime

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
app.config["UPLOAD_FOLDER"] = "static/uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
socketio = SocketIO(app)

# Хранилище сообщений и пользователей
messages = []
users = {}  # {username: {'avatar': str, 'last_seen': datetime}}


# Главная страница с чатом
@app.route("/")
def index():
    return render_template("index.html", messages=messages)


# Обработка загрузки файлов
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return "No file part", 400
    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400
    filename = secrets.token_hex(8) + "." + file.filename.split(".")[-1]
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


# Подключение пользователя
@socketio.on("connect")
def handle_connect():
    pass


# Отслеживание активности пользователя
@socketio.on("user_active")
def handle_user_active(data):
    username = data["username"]
    avatar = data.get("avatar")
    if username:
        users[username] = {"avatar": avatar, "last_seen": datetime.now()}
        emit("update_users", users, broadcast=True)


# Обработка отключения
@socketio.on("disconnect")
def handle_disconnect():
    pass


# Обработка нового сообщения
@socketio.on("send_message")
def handle_message(data):
    msg = {
        "id": secrets.token_hex(8),
        "text": data["message"],
        "username": data["username"],
        "image": data.get("image", None),
    }
    messages.append(msg)
    emit("new_message", msg, broadcast=True)


# Обработка удаления сообщения (только для админа)
@socketio.on("delete_message")
def handle_delete(data):
    if data.get("is_admin") and data.get("password") == "nadya":
        msg_id = data["id"]
        global messages
        messages = [msg for msg in messages if msg["id"] != msg_id]
        emit("message_deleted", {"id": msg_id}, broadcast=True)


# Запрос списка пользователей (для админа)
@socketio.on("get_users")
def handle_get_users(data):
    if data.get("is_admin") and data.get("password") == "nadya":
        emit("users_list", users, room=request.sid)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001)
