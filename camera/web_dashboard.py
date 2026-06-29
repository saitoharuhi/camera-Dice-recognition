import os
import sys
import time
import cv2
import numpy as np
import threading
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

# Shared configuration (can be updated from Web UI)
config = {
    "threshold": 100,
    "min_size": 15,
    "max_size": 400,
    "invert": False
}
config_lock = threading.Lock()

# Shared state (updated by camera thread, read by FastAPI endpoints)
state = {
    "pip_count": 0,
    "fps": 0,
    "status_text": "カメラの起動を待っています...",
    "roll_history": [],
    "latest_frame": None
}
state_lock = threading.Lock()

# Stability variables for the camera loop
last_roll_value = 0
roll_stable_frames = 0
STABLE_FRAMES_REQUIRED = 12  # Number of stable frames to confirm a roll
roll_history = []

def camera_loop():
    global last_roll_value, roll_stable_frames, roll_history
    
    # Try opening cameras 0, 1, 2
    cap = None
    for device_id in [0, 1, 2]:
        print(f"[CAMERA] カメラデバイス ID {device_id} をオープン中...")
        cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(device_id)
            
        if cap.isOpened():
            print(f"[CAMERA] カメラデバイス ID {device_id} のオープンに成功しました。")
            break
        cap.release()
        cap = None
        
    if not cap:
        print("[ERROR] 利用可能なカメラが見つかりません。")
        with state_lock:
            state["status_text"] = "【エラー】カメラが見つかりません。"
        return

    # Set camera resolution (320x240 for processing speed)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    prev_time = time.time()
    fps_counter = 0
    fps = 0
    fps_update_interval = 0.5

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.03)
            continue
            
        # Get current config parameters safely
        with config_lock:
            threshold_val = config["threshold"]
            min_blob_size = config["min_size"]
            max_blob_size = config["max_size"]
            invert_threshold = config["invert"]

        # Grayscale & resize to 160x120 for processing efficiency
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_resized = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        
        # Binarize
        thresh_type = cv2.THRESH_BINARY if invert_threshold else cv2.THRESH_BINARY_INV
        _, binary = cv2.threshold(gray_resized, threshold_val, 255, thresh_type)
        
        # Connected Components
        num_labels, labels, stats_cc, centroids = cv2.connectedComponentsWithStats(binary)
        
        blobs = []
        for i in range(1, num_labels):
            area = int(stats_cc[i, cv2.CC_STAT_AREA])
            if min_blob_size <= area <= max_blob_size:
                w_b = int(stats_cc[i, cv2.CC_STAT_WIDTH])
                h_b = int(stats_cc[i, cv2.CC_STAT_HEIGHT])
                aspect_ratio = float(w_b) / float(h_b) if h_b > 0 else 0
                
                if 0.5 <= aspect_ratio <= 2.0:
                    x = int(stats_cc[i, cv2.CC_STAT_LEFT])
                    y = int(stats_cc[i, cv2.CC_STAT_TOP])
                    cx = int(centroids[i][0])
                    cy = int(centroids[i][1])
                    
                    blobs.append({
                        "cx": cx, "cy": cy,
                        "x1": x, "y1": y,
                        "x2": x + w_b - 1, "y2": y + h_b - 1,
                        "a": area
                    })
                    
        blobs = blobs[:50]
        pip_count = len(blobs)
        
        # Stability logic
        if pip_count == 0:
            roll_stable_frames = 0
            status_text = "さいころを写してください"
        else:
            status_text = "出目を解析中... (さいころを静止させてください)"
            if pip_count == last_roll_value:
                roll_stable_frames += 1
                if roll_stable_frames == STABLE_FRAMES_REQUIRED:
                    roll_history.insert(0, pip_count)
                    if len(roll_history) > 5:
                        roll_history.pop()
                    status_text = f"【確定】 出目: {pip_count} (履歴に追加しました)"
                elif roll_stable_frames > STABLE_FRAMES_REQUIRED:
                    status_text = f"【確定】 出目: {pip_count}"
            else:
                last_roll_value = pip_count
                roll_stable_frames = 0

        # Upscale for browser display (draw 4x coordinates on 640x480)
        raw_large = cv2.resize(gray_resized, (640, 480), interpolation=cv2.INTER_NEAREST)
        raw_color = cv2.cvtColor(raw_large, cv2.COLOR_GRAY2BGR)
        
        for index, blob in enumerate(blobs):
            x1, y1 = blob["x1"] * 4, blob["y1"] * 4
            x2, y2 = blob["x2"] * 4, blob["y2"] * 4
            cx, cy = blob["cx"] * 4, blob["cy"] * 4
            
            cv2.rectangle(raw_color, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.circle(raw_color, (cx, cy), 4, (0, 255, 0), -1)
            cv2.putText(raw_color, str(index + 1), (x1, max(20, y1 - 8)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
            
        binary_large = cv2.resize(binary, (640, 480), interpolation=cv2.INTER_NEAREST)
        binary_color = cv2.cvtColor(binary_large, cv2.COLOR_GRAY2BGR)
        
        # Combine side-by-side (Width: 1280, Height: 480)
        combined_large = cv2.hconcat([raw_color, binary_color])
        
        _, jpeg = cv2.imencode('.jpg', combined_large, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        
        # FPS Calculation
        fps_counter += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        if elapsed_time >= fps_update_interval:
            fps = int(fps_counter / elapsed_time)
            fps_counter = 0
            prev_time = curr_time

        # Update shared state
        with state_lock:
            state["pip_count"] = pip_count
            state["fps"] = fps
            state["status_text"] = status_text
            state["roll_history"] = list(roll_history)
            state["latest_frame"] = jpeg.tobytes()
            
        time.sleep(0.01)

# FastAPI application setup
app = FastAPI()

@app.get("/")
def get_dashboard():
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        index_path = os.path.join(script_dir, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content, status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>index.html が見つかりません</h1>", status_code=404)

# Video feed endpoint (MJPEG streaming)
def gen_frames():
    while True:
        with state_lock:
            frame_bytes = state["latest_frame"]
        if frame_bytes:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.05)  # ~20 FPS streaming to browser

@app.get("/video_feed")
def video_feed():
    return StreamingResponse(gen_frames(), media_type="multipart/x-mixed-replace; boundary=frame")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    # Send initial state and configs
    with state_lock:
        initial_state = {
            "pip_count": state["pip_count"],
            "fps": state["fps"],
            "status_text": state["status_text"],
            "roll_history": state["roll_history"],
        }
    with config_lock:
        initial_state["config"] = dict(config)
    
    try:
        await websocket.send_text(json.dumps(initial_state))
        
        async def send_updates():
            last_sent_state = {}
            while True:
                try:
                    with state_lock:
                        current_state = {
                            "pip_count": state["pip_count"],
                            "fps": state["fps"],
                            "status_text": state["status_text"],
                            "roll_history": state["roll_history"],
                        }
                    with config_lock:
                        current_state["config"] = dict(config)
                        
                    # Send only if changes occur, except FPS which changes rapidly
                    if (current_state["pip_count"] != last_sent_state.get("pip_count") or
                        current_state["status_text"] != last_sent_state.get("status_text") or
                        current_state["roll_history"] != last_sent_state.get("roll_history") or
                        current_state["fps"] != last_sent_state.get("fps")):
                        
                        await websocket.send_text(json.dumps(current_state))
                        last_sent_state = current_state
                        
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    break
                except Exception:
                    break

        update_task = asyncio.create_task(send_updates())
        
        while True:
            # Listen to configuration updates from the client
            data = await websocket.receive_text()
            params = json.loads(data)
            with config_lock:
                if "threshold" in params:
                    config["threshold"] = int(params["threshold"])
                if "min_size" in params:
                    config["min_size"] = int(params["min_size"])
                if "max_size" in params:
                    config["max_size"] = int(params["max_size"])
                if "invert" in params:
                    config["invert"] = bool(params["invert"])

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        update_task.cancel()
        manager.disconnect(websocket)

if __name__ == "__main__":
    # Start camera thread
    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()
    
    print("==================================================")
    print(" さいころ認識 Webダッシュボード (FastAPI版)")
    print("==================================================")
    print(" ブラウザで以下のURLを開いてください：")
    print("   http://localhost:8000")
    print("==================================================")
    print(" ※ 終了するには、このコンソールで 'Ctrl + C' を押してください。")
    print("==================================================")
    
    # Start web server
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
