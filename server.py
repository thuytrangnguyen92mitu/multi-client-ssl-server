from flask import Flask, request, jsonify
from flask_cors import CORS
import socket
import threading
import sys

# --- Cài Flask App  ---
app = Flask(__name__)
CORS(app)  # Allow all origins

# --- Biến Global cho socket Server ---
server_socket = None
server_thread = None
is_running = False
clients = []  # chưa danh sách các socket client đang kết nối
clients_lock = threading.Lock()  # khóa danh sách clients tránh xung đột khi nhiều luồng cùng truy cập danh sách
# --- Socket Server ---

def server_loop():
    """
    Vòng lặp chính của socket Server sẽ chạy trong luồng riêng
    Chấp nhận các kết nối từ clients mới và tạo ra luồng con riêng để xử lý từng client
    """
    global server_socket, is_running, clients
    try:
        # Lắng nghe các yêu cầu kết nối
        server_socket.listen(5)
        print(f"[SERVER] Listening on {server_socket.getsockname()}")
        is_running = True

        while is_running:
            try:
                # Cài đặt thời gian timeout() chứ không chặn 
                # Cho phép lặp để kiểm tra hàm is_running
                server_socket.settimeout(1.0)
                client_socket, client_address = server_socket.accept()
                
                # nếu Server mở và client request thì sẽ chaaos nhận kết nối
                print(f"[SERVER] Accepted connection from {client_address}")
                
                # Thêm client vào danh sách luồng an toàn
                with clients_lock:
                    clients.append(client_socket)
                
                # Bắt đầu 1 luồng mới cho client này
                client_thread = threading.Thread(
                    target=handle_client, 
                    args=(client_socket, client_address),
                    daemon=True # Đảm bảo luồng sẽ đóng khi mà chương trình thoát
                )
                client_thread.start()
                
            except socket.timeout:
                # Lặp lại để kiểm tra trạng thái kết nối
                continue
            except Exception as e:
                if is_running:
                    print(f"[SERVER] Error accepting connection: {e}")
        
        # --- Server Shutdown Cleanup ---
        print("[SERVER] Server loop stopping.")
        
    except Exception as e:
        if is_running: # Không báo lỗi khi tự động tắt
            print(f"[SERVER] Server loop error: {e}")
    finally:
        is_running = False
        # Đóng tất cả các clients đang kết nối
        with clients_lock:
            for client in clients:
                client.close()
            clients = []
        # Đóng server socket
        if server_socket:
            server_socket.close()
        server_socket = None
        print("[SERVER] Server has shut down.")

def handle_client(client_socket, client_address):
    """
    Cho mỗi client chạy 1 luồng riêng của nó
    Lắng nghe message và broadcast từ các client khác
    """
    global clients, clients_lock
    is_client_connected = True
    
    while is_client_connected and is_running:
        try:
            # Chừo dữ liệu từ client
            data = client_socket.recv(1024)
            if not data:
                # Client ngắt kết nối
                print(f"[SERVER] Client {client_address} disconnected.")
                is_client_connected = False
            else:
                message = data.decode('utf-8')
                print(f"[SERVER] Received from {client_address}: {message}")
                
                # Gửi message cho các client khác
                broadcast_message_from_client(f"{client_address}: {message}", client_socket)
                
        except (socket.error, ConnectionResetError):
            print(f"[SERVER] Connection lost to {client_address}.")
            is_client_connected = False
        except Exception as e:
            print(f"[SERVER] Error with client {client_address}: {e}")
            is_client_connected = False
    
    # --- Cleanup ---
    # Xóa client từ danh sách
    with clients_lock:
        if client_socket in clients:
            clients.remove(client_socket)
    client_socket.close()
    print(f"[SERVER] Cleaned up client {client_address}. Total clients: {len(clients)}")

def broadcast_message(message):
    """
    Gửi broadcast message từ server đến tất cả clients.
    Dùng định tuyến /broadcast Flask.
    """
    global clients, clients_lock
    print(f"[SERVER] Broadcasting: '{message}' to {len(clients)} clients.")
    with clients_lock:
        # Lặp bản sao của danh sách để phòng hờ có client bị ngắt kết nối
        # trong lúc broadcast có thể làm thay đổi danh sách
        for client in list(clients):
            try:
                client.send(message.encode('utf-8'))
            except socket.error as e:
                print(f"[SERVER] Error sending to {client.getpeername()}: {e}. Removing client.")
                client.close()
                if client in clients:
                    clients.remove(client)

# Hàm làm việc với client
def broadcast_message_from_client(message, sender_socket):
    """
    Broadcasts a message from one client to all *other* connected clients.
    """
    global clients, clients_lock
    print(f"[SERVER] Relaying: '{message}' to {len(clients) - 1} other clients.")
    with clients_lock:
        for client in list(clients):
            # Gửi đến tất cả clients trừ người gửi
            if client != sender_socket:
                try:
                    client.send(message.encode('utf-8'))
                except socket.error as e:
                    print(f"[SERVER] Error relaying to {client.getpeername()}: {e}. Removing client.")
                    client.close()
                    if client in clients:
                        clients.remove(client)


# --- Dùng Flask API cho GUI ---

@app.route('/get_info')
def get_info_route():
    port = request.args.get('port')
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname_ex(hostname)[-1][-1]
        return jsonify(ip=ip_address, port=port)
    except Exception as e:
        print(f"[API] Error in /get_info: {e}")
        return jsonify(error=str(e)), 500

@app.route('/start_server')
def start_server_route():
    global server_socket, server_thread, is_running
    
    if is_running:
        return "Server is already running.", 400
        
    ip = request.args.get('ip')
    port_str = request.args.get('port')
    
    if not ip or not port_str:
        return "IP and Port are required.", 400
        
    try:
        port = int(port_str)
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((ip, port))
        
        # Bắt đầu vòng lặp Server trong luồng mới
        server_thread = threading.Thread(target=server_loop, daemon=True)
        server_thread.start()
        
        return f"Server started at {ip}:{port}"
    except Exception as e:
        print(f"[API] Error in /start_server: {e}")
        return f"Error: {e}", 500

@app.route('/stop_server')
def stop_server_route():
    global server_socket, server_thread, is_running
    
    if not is_running:
        return "Server is not running.", 400
        
    try:
        is_running = False  # Tín hiệu luồng server để dừng
        
        # Đóng socket server để chặn lệnh accept()
        if server_socket:
            server_socket.close()
            
        # Chờ cho đến khi luồng server chặn xong
        if server_thread:
            server_thread.join(timeout=2.0)
            
        return "Server stopped."
    except Exception as e:
        print(f"[API] Error in /stop_server: {e}")
        return f"Error: {e}", 500

@app.route('/broadcast')
def broadcast_route():
    message = request.args.get('message')
    if not message:
        return "Message is required.", 400
        
    if not is_running:
        return "Server is not running.", 400
        
    broadcast_message(f"[SERVER BROADCAST] {message}")
    return f"Message sent to {len(clients)} client(s)."

# --- Main Execution ---
if __name__ == "__main__":
    print("[API] Starting Flask API server on http://127.0.0.1:5000")
    print("[API] This server controls the main socket server.")
    # Chạy Flask trong luồng chính
    app.run(port=5000)

