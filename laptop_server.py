import socket
import json
import pickle
import numpy as np

# Configure server listener
HOST = '0.0.0.0' # Accepts connections from the phone in the same network
PORT = 9999

# Load the local laptop model safely
model_path = 'isl_alphabet_model_v2.pkl'
try:
    with open(model_path, 'rb') as f:
        model = pickle.load(f)
    print(f"[*] Successfully loaded local model: {model_path}")
except Exception as e:
    print(f"[!] Failed to load model. Ensure {model_path} is placed next to this script. Error: {e}")
    model = None

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(5)
print(f"[*] Server listening on {HOST}:{PORT}...")
print("[*] Turn on your BhashaSetu Android App to start receiving predictions.")

try:
    while True:
        client_socket, addr = server.accept()
        print(f"[*] Connection accepted from {addr}")
        try:
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    break
                
                # Process landmark frames received from Android client
                payload = json.loads(data)
                landmarks = np.array(payload.get('landmarks', []))
                
                if model and len(landmarks) > 0:
                    prediction = model.predict([landmarks])[0]
                    probabilities = model.predict_proba([landmarks])[0]
                    confidence = float(np.max(probabilities))
                    
                    # Reject predictions below confidence threshold (e.g., 70%)
                    if confidence < 0.70:
                        result = {"word": "Not recognized", "confidence": confidence}
                    else:
                        result = {"word": str(prediction), "confidence": confidence}
                else:
                    result = {"word": "Not recognized (Model Offline)", "confidence": 0.0}
                
                client_socket.send(json.dumps(result).encode('utf-8'))
        except Exception as e:
            print(f"[!] Session ended or error: {e}")
        finally:
            client_socket.close()
except KeyboardInterrupt:
    print("
[*] Server stopped.")
finally:
    server.close()
