# ClipClean — Automatic Video Processing Tool

ClipClean is a local, single-user application that lets you upload a video file, process it automatically, and download the result as a compatible MP4.

> **No paid services, no cloud required, no AI model downloads.**
> Everything runs on your computer.

---

## What ClipClean Does

- Accepts uploaded video files (MP4, MOV, MKV, WebM).
- Validates and analyses the video using FFprobe.
- Converts / normalises the video to a broadly compatible H.264 + AAC MP4.
- Uses stream-copy (fast, no quality loss) when the input is already in the target format.
- Optionally: trims a section, replaces audio, mutes an interval, or burns in subtitles.
- Provides a clean, modern web interface — upload → process → download.

## What ClipClean Does **Not** Do

- ❌ It is **not** a video editor — no timeline, no drag-and-drop clips.
- ❌ It does **not** guarantee copyright clearance or bypass Content ID.
- ❌ It does **not** download videos from YouTube or other platforms.
- ❌ It does **not** upload or publish anything automatically.
- ❌ It does **not** use techniques to evade copyright detection (mirroring, pitch shifting to hide matches, etc.).
- ❌ It does **not** require a paid API, subscription, or cloud service.

---

## Requirements

| Requirement | Details |
|---|---|
| **Python** | 3.10 or later (tested with 3.12) |
| **FFmpeg + FFprobe** | Must be installed and available on your system PATH |
| **OS** | Windows 10/11, Linux, macOS |
| **Browser** | Any modern browser (Chrome, Firefox, Edge, Safari) |
| **Disk space** | Enough for your video files (input + output) |

---

## Installation

### 1. Install Python

Download from [python.org/downloads](https://www.python.org/downloads/).
During installation on Windows, **check "Add Python to PATH"**.

### 2. Install FFmpeg

#### Windows
1. Go to <https://www.gyan.dev/ffmpeg/builds/>
2. Download **ffmpeg-release-essentials.zip**
3. Extract the ZIP to a folder, e.g. `C:\ffmpeg`
4. Add `C:\ffmpeg\bin` to your system PATH:
   - Press **Win + R**, type `sysdm.cpl`, press Enter
   - Click **Advanced** tab → **Environment Variables**
   - Under **System variables**, select **Path**, click **Edit**
   - Click **New** and type: `C:\ffmpeg\bin`
   - Click **OK** on all dialogs
5. Open a **new** terminal and verify:
   ```
   ffmpeg -version
   ffprobe -version
   ```

#### Linux (Ubuntu / Debian)
```bash
sudo apt update && sudo apt install ffmpeg
```

#### macOS (Homebrew)
```bash
brew install ffmpeg
```

### 3. Get ClipClean

Place the `clipclean` folder anywhere on your computer.

### 4. Start ClipClean

#### Windows
Double-click `run_windows.bat`, or open a terminal in the `clipclean` folder and run:
```
run_windows.bat
```

#### Linux / macOS
```bash
cd clipclean
chmod +x run.sh
./run.sh
```

#### Manual startup
```bash
cd clipclean
python -m venv .venv              # Create virtual environment (first time)

# Activate:
# Windows:   .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt    # Install dependencies
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 5. Open in browser

Navigate to **http://127.0.0.1:8000**

---

## How to Use

### Basic processing (Mode A)

1. Open ClipClean in your browser.
2. Check the **engine status** indicator — it should show green.
3. Drag a video onto the upload area, or click **Browse Files**.
4. Click **Process Video**.
5. Wait for processing to complete — you'll see real-time status updates.
6. Click **Download Processed Video**.

### Advanced options (Mode B)

Click **Advanced Options** to expand the optional editing form:

| Option | What it does |
|---|---|
| **Trim section** | Remove a segment between start and end timestamps |
| **Replace audio** | Swap the audio track with an uploaded audio file |
| **Mute interval** | Silence audio between start and end timestamps |
| **Add subtitles** | Burn SRT subtitles into the video |

> ⚠️ **Review your output before publishing.** Removing a segment changes context. ClipClean does not guarantee copyright clearance.

---

## Optional: AI Transcription

ClipClean can optionally use [Groq's](https://console.groq.com) free Whisper API for audio transcription. This is entirely optional.

1. Create a free account at <https://console.groq.com>
2. Generate an API key
3. Copy `.env.example` to `.env`
4. Add your key: `GROQ_API_KEY=gsk_your_key_here`
5. Restart ClipClean

Without an API key, the app works normally — AI features are simply disabled.

---

## Supported Formats

| Input | Output |
|---|---|
| MP4, MOV, MKV, WebM | MP4 (H.264 video + AAC audio) |

## Limits (configurable in `.env`)

| Limit | Default |
|---|---|
| Max upload size | 1 GB |
| Max video duration | 30 minutes |
| Max concurrent jobs | 2 |
| Job timeout | 1 hour |
| File cleanup age | 1 hour |

---

## Running Tests

```bash
cd clipclean

# Activate your virtual environment first, then:
python -m pytest tests/ -v

# Tests that require FFmpeg will be skipped automatically if it's not installed.
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "FFmpeg not available" | Install FFmpeg and ensure `ffmpeg` and `ffprobe` are on your PATH. Restart ClipClean. |
| "File too large" | Increase `MAX_UPLOAD_SIZE_MB` in your `.env` file. |
| "Video too long" | Increase `MAX_DURATION_SECONDS` in your `.env` file. |
| Port 8000 in use | Change `PORT` in `.env` or stop the other application using port 8000. |
| Processing stuck | Check the terminal for error messages. Restart ClipClean. |
| Import errors | Make sure you activated the virtual environment and ran `pip install -r requirements.txt`. |

---

## Privacy & Security

- ClipClean runs **locally** and binds to `127.0.0.1` by default — it is not accessible from other machines.
- Uploaded files are stored temporarily in the `data/` folder and cleaned up automatically after 1 hour.
- No data is sent to external services unless you configure the optional Groq AI integration.
- API keys are read from environment variables / `.env` and never exposed in the frontend.
- **Parsing untrusted media files carries inherent risk.** Only process files you trust.

---

## Copyright & Legal Notice

ClipClean is a video-processing tool for files you own or are authorised to edit.

- It does **not** guarantee that processed videos are free of copyrighted content.
- It does **not** bypass YouTube Content ID, Facebook Rights Manager, or any copyright-detection system.
- It does **not** certify copyright ownership.
- **You are responsible** for ensuring you have the right to process and publish any video.

---

## License

This project is provided as-is for personal and educational use.
