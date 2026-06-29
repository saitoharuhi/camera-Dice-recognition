# Webカメラ さいころ認識システム (Web-Based Dice Recognition Dashboard)

Webカメラで撮影した映像からさいころの「目（ドット）」を画像解析技術によって検出し、リアルタイムでカウント・表示するシステムです。
FastAPIを用いてローカルウェブサーバーを立ち上げ、ブラウザから操作・確認できるモダンなダッシュボード形式で提供します。

---

## 主な機能

- **リアルタイムさいころ検出**: カメラ映像内の接続成分（Blob）の面積とアスペクト比を基に、さいころの目を瞬時に検出・カウントします。
- **モダンなWebダッシュボード**: グラスモフィズム（半透明）デザインを取り入れた、視認性の高いダークテーマのブラウザ画面で動作します。
- **パラメータのリアルタイム同期**: 
  - 二値化しきい値 (Threshold)
  - 目の最小面積 (Min Size)
  - 目の最大面積 (Max Size)
  - 白黒反転 (Invert)
  これらを画面上のスライダー・スイッチで操作すると、WebSocketを通じてPythonの解析パラメータに即座に反映されます。
- **出目判定の安定化 & 履歴記録**: 出目が一定時間（12フレーム以上）静止すると自動で確定判定を下し、直近5回分の出目履歴を画面下部に記録します。
- **サイド・バイ・サイド映像表示**: 検出点を重ねて描画したカラー映像（左）と、しきい値の適用具合を確認できる二値化（白黒）映像（右）を並べて表示し、パラメータ調整を支援します。

---

## 構成図

```mermaid
graph TD
    subgraph Python Backend (web_dashboard.py)
        Cap[Camera Capture] --> Proc[OpenCV Dice Detection]
        Settings[Shared Settings] --> Proc
        Proc --> Stream[MJPEG Stream /video_feed]
        Proc --> Stats[Stats & History State]
        WS[WebSocket Handler /ws] <--> Stats
        WS <--> Settings
    end
    subgraph Browser Frontend (index.html)
        UI[index.html UI]
        Img[Image tag] <-- /video_feed -- Stream
        WS_Client[JS WebSocket] <-- Stats -- WS
        WS_Client -- Slider Updates --> WS
    end
```

---

## 動作環境 & 必要ライブラリ

Python 3 がインストールされている必要があります。

### 必要な外部ライブラリ
以下のコマンドを実行してインストールしてください。
```bash
pip install opencv-python pillow fastapi uvicorn websockets numpy
```

---

## 使用方法

### 1. サーバーの起動
プロジェクトディレクトリ内で以下のコマンドを実行します。
```bash
python web_dashboard.py
```
起動に成功すると、自動的にカメラデバイスがオープンされ、サーバーのURLが表示されます。

### 2. ダッシュボードを開く
ブラウザを起動し、以下のURLにアクセスします。
> **[http://localhost:8000](http://localhost:8000)**

### 3. パラメータの調整
- 部屋の明るさやカメラの感度によって目が正しく認識されない場合は、画面上の「**2値化しきい値 (Threshold)**」スライダーを左右に動かして調整します（右側の二値化画像上で、さいころの目の部分だけが真っ白になるように調整するのがコツです）。
- さいころ以外のノイズを拾ってしまう場合は、**最小面積・最大面積**を調整してフィルタリングします。
- 黒地に白の目のさいころを使用する場合は、「**白黒反転 (Invert)**」をONにしてください。

### 4. サーバーの終了
起動しているターミナル（コマンドプロンプト等）で **`Ctrl + C`** キーを押すと、安全にカメラを解放して終了します。

---

## ファイル構成

- **`web_dashboard.py`**: OpenCVによる画像解析と、FastAPIによるWebサーバー、ストリーミング、WebSocket APIを統合したメインプログラム。
- **`index.html`**: HTML/CSS(CSS変数によるスタイリング)/JavaScriptを用いてブラウザ上に描画するユーザーインターフェース。
