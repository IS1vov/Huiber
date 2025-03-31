from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO, emit
import os
import json
import eventlet
from pydub import AudioSegment

eventlet.monkey_patch()

app = Flask(__name__)
app.config["SECRET_KEY"] = "secret!"
socketio = SocketIO(app, async_mode="eventlet")

MESSAGES_FILE = "messages.json"
UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def load_messages():
    if os.path.exists(MESSAGES_FILE):
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_messages(messages):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False)


messages = load_messages()
users = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return "No file part", 400
    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400

    temp_path = os.path.join(app.config["UPLOAD_FOLDER"], f"temp_{file.filename}")
    file.save(temp_path)

    filename = file.filename
    if file.mimetype.startswith("audio/") or file.filename.endswith(".webm"):
        try:
            audio = AudioSegment.from_file(temp_path)
            filename = f"voice_{int(eventlet.time.time() * 1000)}.mp3"
            output_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            audio.export(output_path, format="mp3")
            os.remove(temp_path)
        except Exception as e:
            os.remove(temp_path)
            return f"Error converting audio: {str(e)}", 500
    elif file.mimetype.startswith("video/"):
        filename = f"video_{int(eventlet.time.time() * 1000)}.mp4"
        output_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        os.rename(temp_path, output_path)
    else:
        output_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        os.rename(temp_path, output_path)

    return filename


@socketio.on("user_active")
def handle_user_active(data):
    users[data["username"]] = {
        "avatar": data["avatar"],
        "last_seen": eventlet.time.time() * 1000,
    }
    emit("users_list", users, broadcast=True)


@socketio.on("get_users")
def send_users():
    emit("users_list", users)


@socketio.on("get_messages")
def send_messages():
    emit("initial_messages", {"messages": messages, "users": users})


@socketio.on("send_message")
def handle_message(data):
    msg = {
        "id": str(len(messages) + 1),
        "username": data["username"],
        "text": data.get("message"),
        "image": data.get("image"),
        "voice": data.get("voice"),
        "video": data.get("video"),
    }
    messages.append(msg)
    save_messages(messages)
    emit("new_message", msg, broadcast=True)


@socketio.on("edit_message")
def handle_edit_message(data):
    msg_id = data["id"]
    new_text = data["text"]
    for msg in messages:
        if (
            msg["id"] == msg_id
            and msg["username"] == data["username"]
            and "text" in msg
        ):
            msg["text"] = new_text
            save_messages(messages)
            emit("message_edited", {"id": msg_id, "text": new_text}, broadcast=True)
            break


@socketio.on("delete_message")
def delete_message(data):
    global messages
    messages = [
        msg
        for msg in messages
        if msg["id"] != data["id"] or msg["username"] != data["username"]
    ]
    save_messages(messages)
    emit("message_deleted", {"id": data["id"]}, broadcast=True)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)
