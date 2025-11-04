from flask import Flask, request, jsonify
from flask_cors import CORS
import socket
import threading
import sys

# --- Flask App Setup ---
app = Flask(__name__)
CORS(app)  # Cho phép yêu cầu từ trang HTML

# --- Các biến global cho socket client ---
client_socket = None
is_connected = False
receive_thread = None
message_lock = threading.Lock()
received_messages = []  # Danh sách lưu trữ message từ server

# --- Socket Handling Functions ---

def receive_loop():
    """
    Chạy trong luồng để tiếp tục nhận message từ server
    """
    global is_connected, client_socket, received_messages, message_lock
    
    while is_connected:
        try:
            client_socket.settimeout(1.0) 
            data = client_socket.recv(1024)
            
            if not data:
                print("[CLIENT] Server disconnected.")
                with message_lock:
                    received_messages.append("[SYSTEM] Server disconnected.")
                is_connected = False
                break
            
            message = data.decode('utf-8')
            print(f"[CLIENT] Received: {message}")
            with message_lock:
                received_messages.append(message)

        except socket.timeout:
            continue 
        except (socket.error, ConnectionResetError):
            if is_connected:
                print("[CLIENT] Connection lost.")
                with message_lock:
                    received_messages.append("[SYSTEM] Connection lost.")
            is_connected = False
            break
            
    is_connected = False
    if client_socket:
        client_socket.close()
    print("[CLIENT] Receive thread stopped.")

# --- Flask API Routes for the GUI ---

@app.route('/connect')
def connect_route():
    global client_socket, is_connected, receive_thread, received_messages, message_lock
    
    if is_connected:
        return "Already connected.", 400

    ip = request.args.get('ip')
    port_str = request.args.get('port')
    
    if not ip or not port_str:
        return "IP and Port are required.", 400
        
    try:
        port = int(port_str)
        with message_lock:
            received_messages = []
            
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((ip, port))
        
        is_connected = True
        receive_thread = threading.Thread(target=receive_loop, daemon=True)
        receive_thread.start()
        
        print(f"[CLIENT] Connected to server at {ip}:{port}")
        return f"✅ Connected to server at {ip}:{port}"
        
    except ConnectionRefusedError:
        print(f"[CLIENT] Connection refused for {ip}:{port}")
        return f"Error: Connection refused. Is the main server running?"
    except Exception as e:
        print(f"[CLIENT] Error connecting: {e}")
        return f"Error: {e}"

@app.route('/disconnect')
def disconnect_route():
    global client_socket, is_connected, receive_thread
    
    if not is_connected:
        return "Not connected.", 400
        
    try:
        is_connected = False
        if receive_thread:
            receive_thread.join(timeout=1.0)
        if client_socket:
            client_socket.close()
        print("[CLIENT] Disconnected.")
        return "Disconnected from server."
    except Exception as e:
        print(f"[CLIENT] Error during disconnect: {e}")
        return f"Error during disconnect: {e}"

@app.route('/send')
def send_route():
    global client_socket, is_connected
    
    message = request.args.get('message')
    if not message:
        return "Message is required.", 400
    if not is_connected or not client_socket:
        return "Error: Not connected to server.", 400
        
    try:
        client_socket.send(message.encode('utf-8'))
        print(f"[CLIENT] Sent: {message}")
        return f"Me: {message}"
    except socket.error as e:
        print(f"[CLIENT] Error sending message: {e}")
        is_connected = False
        return f"Error sending message: {e}", 500

@app.route('/get_messages')
def get_messages_route():
    global received_messages, message_lock, is_connected
    
    messages_to_send = []
    with message_lock:
        if not is_connected and not received_messages:
            return jsonify({"error": "Not connected."}), 400
        messages_to_send = received_messages[:]
        received_messages = []
        
    return jsonify(messages_to_send)

# --- Main Execution ---
if __name__ == "__main__":
    # Default to port 5001, but allow override from command line
    # Example: python client.py 5002
    if len(sys.argv) > 1:
        try:
            api_port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}. Using default 5001.")
            api_port = 5001
    else:
        api_port = 5001
    
    print(f"[CLIENT BRIDGE] Starting Flask API server on http://127.0.0.1:{api_port}")
    print("[CLIENT BRIDGE] This script acts as a bridge for the clientGUI.html file.")
    
    app.run(port=api_port, debug=True, use_reloader=False)
