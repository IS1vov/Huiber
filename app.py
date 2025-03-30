from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import secrets

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(16)
socketio = SocketIO(app)

# Хранилище сообщений (в памяти)
messages = []


# Главная страница с чатом
@app.route("/")
def index():
    return render_template("index.html", messages=messages)


# Обработка нового сообщения
@socketio.on("send_message")
def handle_message(data):
    msg = {
        "id": secrets.token_hex(8),  # Уникальный ID для сообщения
        "text": data["message"],
        "username": data["username"],
    }
    messages.append(msg)
    emit("new_message", msg, broadcast=True)


# Обработка удаления сообщения
@socketio.on("delete_message")
def handle_delete(data):
    msg_id = data["id"]
    global messages
    messages = [msg for msg in messages if msg["id"] != msg_id]
    emit("message_deleted", {"id": msg_id}, broadcast=True)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
