import os
import sys
import time
import numpy as np

# OpenCV のインポート確認
try:
    import cv2
except ImportError:
    print("[ERROR] 'opencv-python' ライブラリがインストールされていません。")
    print("コマンドプロンプトやターミナルで以下を実行してください：")
    print("    pip install opencv-python")
    sys.exit(1)

# Pillow のインポート確認 (日本語描画用)
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERROR] 'pillow' ライブラリがインストールされていません。")
    print("コマンドプロンプトやターミナルで以下を実行してください：")
    print("    pip install pillow")
    sys.exit(1)

# コールバック関数 (トラックバー用)
def nothing(x):
    pass

# 出目履歴と安定化用変数
last_roll_value = 0
roll_stable_frames = 0
STABLE_FRAMES_REQUIRED = 12  # 確定に必要な安定フレーム数
roll_history = []            # 出目の履歴 (直近5件)

def main():
    global last_roll_value, roll_stable_frames, roll_history
    
    print("==================================================")
    print(" Webカメラ さいころ認識システム (大画面日本語 GUI版)")
    print("==================================================")
    print("  ※ ウィンドウ上で 'q' キーまたは 'ESC' を押すと終了します。")
    
    # 接続可能なカメラを順に探索 (DirectShow優先)
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
        print("[ERROR] 利用可能なカメラが見つかりません。USBウェブカメラの接続を確認してください。")
        sys.exit(1)

    # カメラの解像度とフォーマット設定 (軽量化のため320x240、高速化のためMJPG)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    # OpenCV ウィンドウの作成 (動的サイズ調整可能なように WINDOW_NORMAL に設定)
    window_name = "Dice Recognition Dashboard"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    # 初期ウィンドウサイズを 1280x840 にリサイズ
    cv2.resizeWindow(window_name, 1280, 840)
    
    # トラックバー (コントロール用スライダー) の作成 (日本語名)
    cv2.createTrackbar("Threshold", window_name, 100, 255, nothing)
    cv2.createTrackbar("Min Size", window_name, 15, 100, nothing)
    cv2.createTrackbar("Max Size", window_name, 400, 1000, nothing)
    cv2.createTrackbar("Invert", window_name, 0, 1, nothing)

    # Windowsの日本語フォントパスの解決
    font_path = "C:\\Windows\\Fonts\\meiryo.ttc"  # メイリオ
    if not os.path.exists(font_path):
        font_path = "C:\\Windows\\Fonts\\msgothic.ttc"  # MSゴシック
        
    try:
        font_large = ImageFont.truetype(font_path, 32)  # 下部ステータス用 (12 -> 32)
        font_small = ImageFont.truetype(font_path, 20)  # 画像内ラベル用 (10 -> 20)
    except IOError:
        # フォントが見つからない場合は標準フォントで代用
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # FPS計算用変数
    prev_time = time.time()
    fps = 0
    fps_counter = 0
    fps_update_interval = 0.5  # 0.5秒おきにFPSを更新

    print("[SYSTEM] 認識ダッシュボードを開始しました。")

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.1)
            continue
            
        # グレースケール変換 & 160x120 に縮小 (処理速度維持のためアルゴリズムはこの解像度で実行)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_resized = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        
        # トラックバーの現在値を取得
        threshold_val = cv2.getTrackbarPos("Threshold", window_name)
        min_blob_size = cv2.getTrackbarPos("Min Size", window_name)
        max_blob_size = cv2.getTrackbarPos("Max Size", window_name)
        invert_threshold = cv2.getTrackbarPos("Invert", window_name) == 1
        
        # 設定値の安全チェック
        min_blob_size = max(1, min_blob_size)
        max_blob_size = max(min_blob_size + 1, max_blob_size)
        
        # 2値化
        thresh_type = cv2.THRESH_BINARY if invert_threshold else cv2.THRESH_BINARY_INV
        _, binary = cv2.threshold(gray_resized, threshold_val, 255, thresh_type)
        
        # 接続成分 (Blob) の抽出
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
        
        blobs = []
        for i in range(1, num_labels):  # 0番目は背景なのでスキップ
            area = int(stats[i, cv2.CC_STAT_AREA])
            
            # 面積フィルタリング
            if min_blob_size <= area <= max_blob_size:
                w_b = int(stats[i, cv2.CC_STAT_WIDTH])
                h_b = int(stats[i, cv2.CC_STAT_HEIGHT])
                aspect_ratio = float(w_b) / float(h_b) if h_b > 0 else 0
                
                # アスペクト比フィルタ (0.5 〜 2.0)
                if 0.5 <= aspect_ratio <= 2.0:
                    x = int(stats[i, cv2.CC_STAT_LEFT])
                    y = int(stats[i, cv2.CC_STAT_TOP])
                    cx = int(centroids[i][0])
                    cy = int(centroids[i][1])
                    
                    blobs.append({
                        "cx": cx, "cy": cy,
                        "x1": x, "y1": y,
                        "x2": x + w_b - 1, "y2": y + h_b - 1,
                        "a": area
                    })
                    
        blobs = blobs[:50]  # 最大50個に制限
        pip_count = len(blobs)
        
        # --------------------------------------------------
        # 出目安定化ロジック (出目確定 & 履歴更新)
        # --------------------------------------------------
        if pip_count == 0:
            roll_stable_frames = 0
            status_text = "さいころを写してください"
        else:
            status_text = "出目を解析中... (さいころを静止させてください)"
            if pip_count == last_roll_value:
                roll_stable_frames += 1
                if roll_stable_frames == STABLE_FRAMES_REQUIRED:
                    # 確定：履歴に追加 (直近5件まで保持)
                    roll_history.insert(0, pip_count)
                    if len(roll_history) > 5:
                        roll_history.pop()
                    status_text = f"【確定】 出目: {pip_count} (履歴に追加しました)"
                elif roll_stable_frames > STABLE_FRAMES_REQUIRED:
                    status_text = f"【確定】 出目: {pip_count}"
            else:
                last_roll_value = pip_count
                roll_stable_frames = 0
                
        # --------------------------------------------------
        # 描画用画像の生成 (大画面表示向けに4倍にスケールアップ)
        # --------------------------------------------------
        # RAW画像を大画面向けに4倍拡大 (640x480)
        raw_large = cv2.resize(gray_resized, (640, 480), interpolation=cv2.INTER_NEAREST)
        raw_color = cv2.cvtColor(raw_large, cv2.COLOR_GRAY2BGR)
        
        # 検出枠や中心点を 4倍スケール上に描画して画質低下を防ぐ
        for index, blob in enumerate(blobs):
            # 座標を4倍にする
            x1 = blob["x1"] * 4
            y1 = blob["y1"] * 4
            x2 = blob["x2"] * 4
            y2 = blob["y2"] * 4
            cx = blob["cx"] * 4
            cy = blob["cy"] * 4
            
            # 赤枠 (少し太めの 2px)
            cv2.rectangle(raw_color, (x1, y1), (x2, y2), (0, 0, 255), 2)
            # 緑の中心点 (少し大きめの半径 4px)
            cv2.circle(raw_color, (cx, cy), 4, (0, 255, 0), -1)
            # インデックス番号 (太さ 2px)
            cv2.putText(raw_color, str(index + 1), (x1, max(20, y1 - 8)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
            
        # 2値化画像を大画面向けに4倍拡大 (640x480)
        binary_large = cv2.resize(binary, (640, 480), interpolation=cv2.INTER_NEAREST)
        binary_color = cv2.cvtColor(binary_large, cv2.COLOR_GRAY2BGR)
        
        # 2枚の画像を横に連結 (幅1280 x 高さ480)
        combined_large = cv2.hconcat([raw_color, binary_color])
        
        # 全体キャンバスの生成 (幅1280 x 高さ840: 下部に360pxの情報表示用黒余白を追加)
        canvas = np.zeros((840, 1280, 3), dtype=np.uint8)
        canvas[0:480, 0:1280] = combined_large
        
        # 境界線を描画
        cv2.line(canvas, (0, 480), (1280, 480), (80, 80, 80), 2)
        cv2.line(canvas, (640, 0), (640, 480), (80, 80, 80), 2)
        
        # FPS計測
        fps_counter += 1
        curr_time = time.time()
        elapsed_time = curr_time - prev_time
        if elapsed_time >= fps_update_interval:
            fps = int(fps_counter / elapsed_time)
            fps_counter = 0
            prev_time = curr_time
            
        # --------------------------------------------------
        # Pillow を使用した大画面向け日本語テキストの一括描画
        # --------------------------------------------------
        # BGR から RGB へ変換して PIL イメージを作成
        canvas_rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(canvas_rgb)
        draw = ImageDraw.Draw(pil_img)
        
        # ラベル描画 (画像内) - 黄色 (RGB: 255, 255, 0)
        draw.text((20, 15), "カメラ映像 (赤枠:検出点)", font=font_small, fill=(255, 255, 0))
        draw.text((660, 15), "2値化画像 (しきい値適用後)", font=font_small, fill=(255, 255, 0))
        
        # 下部エリアの情報表示
        start_y = 510
        line_spacing = 75
        white_color = (240, 240, 240)
        
        draw.text((40, start_y), f"動作速度 (FPS) : {fps}", font=font_large, fill=white_color)
        draw.text((40, start_y + line_spacing), f"現在の目の数   : {pip_count} 個", font=font_large, fill=white_color)
        
        # 安定状態に応じたテキストカラー (確定時は緑、それ以外は黄色)
        status_color = (0, 255, 0) if "【確定】" in status_text else (255, 255, 0)
        draw.text((40, start_y + line_spacing * 2), f"出目判定状況   : {status_text}", font=font_large, fill=status_color)
        
        history_str = ", ".join(map(str, roll_history)) if roll_history else "まだ履歴がありません"
        draw.text((40, start_y + line_spacing * 3), f"出目履歴(直近5回): {history_str}", font=font_large, fill=(0, 255, 255))
        
        # PIL から OpenCV (BGR) に戻す
        canvas = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        # ダッシュボードウィンドウの更新表示
        cv2.imshow(window_name, canvas)
        
        # キー入力受付 (q または ESC でループ終了)
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            print("[SYSTEM] 終了キーが押されました。プログラムを停止します。")
            break
            
    # カメラの解放とウィンドウの破棄
    cap.release()
    cv2.destroyAllWindows()
    print("[SYSTEM] カメラを解放し、すべてのウィンドウを閉じました。")

if __name__ == "__main__":
    main()
