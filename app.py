from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import secrets
import os
from datetime import datetime
import logging

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
app.config["UPLOAD_FOLDER"] = "static/uploads"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
socketio = SocketIO(app, logger=True, engineio_logger=True)  # Включаем логи SocketIO

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

messages = []
users = {}


@app.route("/")
def index():
    logger.info("Запрос главной страницы")
    return render_template("index.html", messages=messages)


@app.route("/upload", methods=["POST"])
def upload_file():
    logger.info("Запрос на загрузку файла")
    if "file" not in request.files:
        return "No file part", 400
    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400
    filename = secrets.token_hex(8) + "." + file.filename.split(".")[-1]
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


@socketio.on("connect")
def handle_connect():
    logger.info("Клиент подключился")


@socketio.on("user_active")
def handle_user_active(data):
    logger.info(f"User active: {data}")
    username = data.get("username")
    avatar = data.get("avatar")
    if username:
        users[username] = {"avatar": avatar, "last_seen": datetime.now()}
        users_serializable = {
            u: {"avatar": info["avatar"], "last_seen": info["last_seen"].isoformat()}
            for u, info in users.items()
        }
        emit("update_users", users_serializable, broadcast=True)


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("Клиент отключился")


@socketio.on("send_message")
def handle_message(data):
    logger.info(f"Новое сообщение: {data}")
    msg = {
        "id": secrets.token_hex(8),
        "text": data.get("message", ""),
        "username": data.get("username", ""),
        "image": data.get("image"),
    }
    messages.append(msg)
    emit("new_message", msg, broadcast=True)


@socketio.on("delete_message")
def handle_delete(data):
    logger.info(f"Запрос на удаление: {data}")
    if data.get("is_admin") and data.get("password") == "nadya":
        msg_id = data["id"]
        global messages
        messages = [msg for msg in messages if msg["id"] != msg_id]
        emit("message_deleted", {"id": msg_id}, broadcast=True)


@socketio.on("get_users")
def handle_get_users(data):
    logger.info(f"Запрос списка пользователей: {data}")
    if data.get("is_admin") and data.get("password") == "nadya":
        users_serializable = {
            u: {"avatar": info["avatar"], "last_seen": info["last_seen"].isoformat()}
            for u, info in users.items()
        }
        emit("users_list", users_serializable, room=request.sid)


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", 5001))
    logger.info(f"Запуск сервера на порту {port}")
    socketio.run(app, host="0.0.0.0", port=port)
