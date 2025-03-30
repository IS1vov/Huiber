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
socketio = SocketIO(app, logger=True, engineio_logger=True)

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
        users[username] = {
            "avatar": avatar,
            "last_seen": datetime.now(),
            "sid": request.sid,
        }
        users_serializable = {
            u: {"avatar": info["avatar"], "last_seen": info["last_seen"].isoformat()}
            for u, info in users.items()
        }
        emit("update_users", users_serializable, broadcast=True)


@socketio.on("disconnect")
def handle_disconnect():
    logger.info("Клиент отключился")
    for username, info in list(users.items()):
        if info["sid"] == request.sid:
            del users[username]
            break
    users_serializable = {
        u: {"avatar": info["avatar"], "last_seen": info["last_seen"].isoformat()}
        for u, info in users.items()
    }
    emit("update_users", users_serializable, broadcast=True)


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
    msg_id = data.get("id")
    username = data.get("username")
    global messages
    messages = [
        msg for msg in messages if msg["id"] != msg_id or msg["username"] != username
    ]
    emit("message_deleted", {"id": msg_id}, broadcast=True)


@socketio.on("get_users")
def handle_get_users(data):
    logger.info("Запрос списка пользователей")
    users_serializable = {
        u: {"avatar": info["avatar"], "last_seen": info["last_seen"].isoformat()}
        for u, info in users.items()
    }
    emit("users_list", users_serializable, room=request.sid)


@socketio.on("initiate_call")
def handle_initiate_call(data):
    logger.info(f"Инициирован звонок: {data}")
    caller = data.get("username")
    for username, info in users.items():
        if username != caller:
            emit("incoming_call", {"caller": caller}, room=info["sid"])


@socketio.on("offer")
def handle_offer(data):
    logger.info(f"Передача offer: {data}")
    target = data.get("target")
    if target in users:
        emit(
            "offer",
            {"offer": data["offer"], "caller": data["caller"]},
            room=users[target]["sid"],
        )


@socketio.on("answer")
def handle_answer(data):
    logger.info(f"Передача answer: {data}")
    caller = data.get("caller")
    if caller in users:
        emit(
            "answer",
            {"answer": data["answer"], "target": data["target"]},
            room=users[caller]["sid"],
        )


@socketio.on("ice_candidate")
def handle_ice_candidate(data):
    logger.info(f"Передача ICE candidate: {data}")
    target = data.get("target")
    if target in users:
        emit(
            "ice_candidate",
            {"candidate": data["candidate"], "caller": data["caller"]},
            room=users[target]["sid"],
        )


if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", 5001))
    logger.info(f"Запуск сервера на порту {port}")
    socketio.run(app, host="0.0.0.0", port=port)
