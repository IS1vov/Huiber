from flask import Flask, render_template, request, send_from_directory, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import secrets
import os
from datetime import datetime, timezone  # Import timezone
import logging

app = Flask(__name__)
# IMPORTANT: Use a strong, persistent secret key for production
# Load from environment variable or config file if possible
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(24))
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # Limit upload size (e.g., 16MB)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# For production, consider using eventlet or gevent
# async_mode = None means it tries eventlet, then gevent, then Flask dev server
socketio = SocketIO(
    app, logger=True, engineio_logger=True, cors_allowed_origins="*"
)  # Allow all origins for simplicity, restrict in production


# --- Data Storage (In-memory, replace with DB for production) ---
messages = (
    []
)  # Store messages as dicts: {'id': '', 'text': '', 'username': '', 'image': '', 'timestamp': ''}
users = (
    {}
)  # Store user info: {'username': {'avatar': '', 'last_seen': datetime_obj, 'sid': ''}}


# --- Helper Functions ---
def get_user_info(username):
    return users.get(username)


def get_user_sid(username):
    user_info = users.get(username)
    return user_info["sid"] if user_info else None


def sanitize_input(text):
    """Basic sanitization (expand as needed)"""
    # Example: Limit length, remove potentially harmful tags (if allowing HTML)
    MAX_LEN = 1024
    return text[:MAX_LEN] if text else ""


def get_serializable_users():
    """Returns user data with ISO formatted timestamps"""
    # Make a copy to avoid modifying the original dict during iteration
    current_users = dict(users)
    return {
        u: {
            "avatar": info.get("avatar"),
            # Ensure last_seen is datetime before formatting
            "last_seen": (
                info["last_seen"].isoformat()
                if isinstance(info.get("last_seen"), datetime)
                else None
            ),
        }
        for u, info in current_users.items()
        if info  # Ensure info dict exists
    }


# --- Routes ---
@app.route("/")
def index():
    logger.info(f"Serving index.html for session: {session.get('username')}")
    # Pass current users data to the template initially
    # Template will primarily rely on socket events after load
    # Messages are now loaded via socket event
    return render_template(
        "index.html", users=get_serializable_users(), messages=[]
    )  # Start with empty messages


@app.route("/static/<path:filename>")
def serve_static(filename):
    # Route for explicitly serving static files if needed (Flask does this implicitly too)
    return send_from_directory("static", filename)


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        logger.warning("Upload attempt with no file part")
        return "No file part", 400
    file = request.files["file"]
    if file.filename == "":
        logger.warning("Upload attempt with no selected file")
        return "No selected file", 400

    if file:  # Add basic file type check if needed
        try:
            # Create a more robust filename
            _, ext = os.path.splitext(file.filename)
            # Allow only specific extensions (example)
            allowed_extensions = {".png", ".jpg", ".jpeg", ".gif"}
            if ext.lower() not in allowed_extensions:
                logger.warning(f"Upload attempt with disallowed extension: {ext}")
                return "File type not allowed", 400

            filename = secrets.token_hex(8) + ext
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            logger.info(f"File uploaded successfully: {filename}")
            return filename  # Return only the filename
        except Exception as e:
            logger.error(f"File upload failed: {e}", exc_info=True)
            return "Upload failed", 500

    return "Invalid file", 400


# --- SocketIO Event Handlers ---


@socketio.on("connect")
def handle_connect():
    sid = request.sid
    logger.info(f"Client connected: {sid}")
    # Don't associate user yet, wait for 'user_active'


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    disconnected_user = None
    # Find user by SID and remove them
    for username, info in list(users.items()):
        if info.get("sid") == sid:
            disconnected_user = username
            logger.info(f"Client disconnected: {username} ({sid})")
            # Don't delete immediately, maybe mark as offline first
            # Or just let last_seen handle it. For now, remove on disconnect.
            del users[username]
            break
    if disconnected_user:
        # Notify others about the user leaving
        emit("update_users", get_serializable_users(), broadcast=True)
    else:
        logger.info(f"Client disconnected (unknown user): {sid}")


@socketio.on("user_active")
def handle_user_active(data):
    """Handles user joining, profile updates, and periodic pings."""
    sid = request.sid
    username = data.get("username")
    avatar = data.get("avatar")

    if not username:
        logger.warning(f"Received user_active event with no username from {sid}")
        return

    logger.info(f"User active event: {username} (Avatar: {avatar}, SID: {sid})")

    # Use timezone-aware datetime
    now = datetime.now(timezone.utc)
    needs_update_broadcast = False

    if username not in users:
        # New user joining
        logger.info(f"User '{username}' joining the chat.")
        users[username] = {"avatar": avatar, "last_seen": now, "sid": sid}
        needs_update_broadcast = True
        # Store username in session for server-side checks (like message deletion)
        session["username"] = username
    else:
        # Existing user update (ping or profile change)
        if users[username].get("sid") != sid:
            logger.info(
                f"User '{username}' reconnected with new SID: {sid} (Old: {users[username].get('sid')})"
            )
            # If user reconnects with a new SID, update it
            users[username]["sid"] = sid
            needs_update_broadcast = True  # Inform others they are back online

        if users[username].get("avatar") != avatar:
            logger.info(f"User '{username}' updated avatar.")
            users[username]["avatar"] = avatar
            needs_update_broadcast = True  # Inform others of avatar change

        # Always update last_seen on activity
        users[username]["last_seen"] = now

    if needs_update_broadcast:
        # Broadcast updated user list to everyone
        logger.info("Broadcasting user list update.")
        emit("update_users", get_serializable_users(), broadcast=True)


@socketio.on("get_messages")
def handle_get_messages():
    """Sends message history to the requesting client."""
    sid = request.sid
    logger.info(f"Sending initial messages ({len(messages)}) to {sid}")
    # Send messages along with the current user data for avatar lookup
    emit(
        "initial_messages",
        {"messages": messages, "users": get_serializable_users()},
        room=sid,
    )


@socketio.on("send_message")
def handle_message(data):
    sid = request.sid
    username = data.get("username")
    text = data.get("message", "")
    image = data.get("image")  # Filename from upload

    # Basic validation
    if not username or (not text and not image):
        logger.warning(f"Invalid message data received from {sid}: {data}")
        return
    # Check if sender is the logged-in user for this session (basic check)
    if session.get("username") != username:
        logger.warning(
            f"Message sender '{username}' does not match session user '{session.get('username')}' for SID {sid}"
        )
        # Decide how to handle: reject, log, etc. For now, allow but log.

    # Sanitize text input
    sanitized_text = sanitize_input(text)

    msg = {
        "id": secrets.token_hex(8),
        "text": sanitized_text,
        "username": username,
        "image": image,  # Store filename or None
        "timestamp": datetime.now(timezone.utc).isoformat(),  # Add timestamp
    }
    messages.append(msg)
    # Keep message history capped (optional)
    # MAX_MESSAGES = 100
    # if len(messages) > MAX_MESSAGES:
    #     messages.pop(0)

    logger.info(
        f"New message from {username}: '{sanitized_text[:30]}...' (Image: {image})"
    )

    # Get current avatar for the sending user to include in the broadcast
    sender_info = get_user_info(username)
    msg_broadcast = msg.copy()
    msg_broadcast["avatar"] = sender_info.get("avatar") if sender_info else None

    # Broadcast message to all connected clients
    emit("new_message", msg_broadcast, broadcast=True)

    # Update sender's last seen time as sending is activity
    if username in users:
        users[username]["last_seen"] = datetime.now(timezone.utc)
        # No need to broadcast user update just for last_seen unless desired


@socketio.on("delete_message")
def handle_delete(data):
    global messages
    sid = request.sid
    msg_id = data.get("id")
    requesting_user = data.get("username")  # Username sent from client

    logger.info(
        f"Delete request for msg ID {msg_id} by user {requesting_user} (SID: {sid})"
    )

    # --- Security Check ---
    # Verify the requestor is the owner of the message
    original_message = next((msg for msg in messages if msg["id"] == msg_id), None)

    if not original_message:
        logger.warning(f"Delete request failed: Message ID {msg_id} not found.")
        # Optionally inform the user: emit('delete_failed', {'reason': 'Message not found'}, room=sid)
        return

    # Check if the username requesting deletion matches the message owner
    if original_message["username"] != requesting_user:
        logger.warning(
            f"Delete request denied: User '{requesting_user}' tried to delete message owned by '{original_message['username']}'."
        )
        # Optionally inform the user: emit('delete_failed', {'reason': 'Permission denied'}, room=sid)
        return

    # --- Perform Deletion ---

    initial_length = len(messages)
    messages = [msg for msg in messages if msg["id"] != msg_id]

    if len(messages) < initial_length:
        logger.info(f"Message ID {msg_id} deleted successfully.")
        # Broadcast the deletion event to all clients
        emit("message_deleted", {"id": msg_id}, broadcast=True)
    else:
        # This case shouldn't happen if found earlier, but log just in case
        logger.error(
            f"Delete request failed: Message ID {msg_id} found but couldn't be removed."
        )


@socketio.on("get_users")
def handle_get_users():
    """Sends current user list to the requesting client."""
    sid = request.sid
    logger.info(f"Sending user list to {sid}")
    emit("users_list", get_serializable_users(), room=sid)


# --- WebRTC Signaling Handlers ---


@socketio.on("offer")
def handle_offer(data):
    """Forward WebRTC offer from caller to target."""
    caller = data.get("caller")
    target = data.get("target")
    offer_sdp = data.get("offer")

    if not all([caller, target, offer_sdp]):
        logger.warning(f"Invalid offer data received: {data}")
        return

    target_sid = get_user_sid(target)
    if target_sid:
        logger.info(f"Forwarding offer from {caller} to {target} ({target_sid})")
        # Send the offer *and* who it's from
        emit("offer", {"offer": offer_sdp, "sender": caller}, room=target_sid)
        # Also send the general incoming call notification if not done separately
        emit("incoming_call", {"caller": caller}, room=target_sid)
    else:
        logger.warning(f"Offer failed: Target user '{target}' not found or offline.")
        # Optionally notify caller: emit('call_failed', {'reason': 'User offline'}, room=request.sid)


@socketio.on("answer")
def handle_answer(data):
    """Forward WebRTC answer from callee back to original caller."""
    callee = data.get(
        "caller"
    )  # The one sending the answer is the 'caller' in this context
    original_caller = data.get(
        "target"
    )  # The one who initiated the call is the 'target' for the answer
    answer_sdp = data.get("answer")

    if not all([callee, original_caller, answer_sdp]):
        logger.warning(f"Invalid answer data received: {data}")
        return

    original_caller_sid = get_user_sid(original_caller)
    if original_caller_sid:
        logger.info(
            f"Forwarding answer from {callee} to {original_caller} ({original_caller_sid})"
        )
        # Send the answer *and* who it's from
        emit(
            "answer", {"answer": answer_sdp, "sender": callee}, room=original_caller_sid
        )
    else:
        logger.warning(
            f"Answer failed: Original caller '{original_caller}' not found or offline."
        )
        # Optionally notify callee: emit('call_failed', {'reason': 'Caller disconnected'}, room=request.sid)


@socketio.on("ice_candidate")
def handle_ice_candidate(data):
    """Forward WebRTC ICE candidates between peers."""
    sender = data.get("sender")
    target = data.get("target")
    candidate = data.get("candidate")

    if not all([sender, target, candidate]):
        logger.warning(f"Invalid ICE candidate data received: {data}")
        return

    target_sid = get_user_sid(target)
    if target_sid:
        # logger.debug(f"Forwarding ICE candidate from {sender} to {target} ({target_sid})") # Use debug for verbose logs
        # Send the candidate *and* who it's from
        emit(
            "ice_candidate", {"candidate": candidate, "sender": sender}, room=target_sid
        )
    else:
        # This can happen normally if one user disconnects during negotiation
        logger.warning(
            f"ICE candidate forwarding failed: Target user '{target}' not found or offline."
        )


# --- Main Execution ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))  # Use PORT env var if available
    # Use '0.0.0.0' to be accessible externally (e.g., in Docker or LAN)
    host = "0.0.0.0"
    logger.info(f"Starting Huiber server on {host}:{port}")
    # Set debug=False for production
    # Use the async_mode determined by SocketIO or specify ('threading', 'eventlet', 'gevent')
    socketio.run(
        app, host=host, port=port, debug=True, use_reloader=True
    )  # Debug=True enables reloader
