# 🎓 Guide: Training & Integrating a Custom Classroom CCTV AI Model

## 1. Why Online CCTV Footage is the Best Choice for College Projects
In real-world engineering projects:
- **Privacy & Security Policies:** Colleges never grant direct RTSP stream or admin access to institutional CCTV cameras due to privacy compliance (FERPA/GDPR) and IT firewall security.
- **Academic Standard:** Using public surveillance datasets, benchmark datasets, and simulated camera angles is the **standard industry & research methodology**.
- **Viva Defense Tip:** When examiners ask, explain:  
  *"Due to institutional privacy regulations, we trained and validated our spatial occupancy pipeline using public high-angle classroom surveillance datasets and transfer-learned YOLOv8 weights."* This sounds highly professional and technically sound!

---

## 2. Where to Get CCTV Footage & Datasets (100% Free)

### 🥇 Source A: Roboflow Universe (Easiest - Ready-Made Annotations!)
You don't even have to label images manually! Thousands of pre-annotated CCTV frames already exist.
1. Go to: [https://universe.roboflow.com/search?q=classroom+cctv](https://universe.roboflow.com/search?q=classroom+cctv)
2. Search queries:
   - `classroom cctv`
   - `classroom surveillance`
   - `students classroom detection`
   - `overhead person detection`
3. Click any top dataset -> Click **"Export Dataset"** -> Select **"YOLOv8"** -> Copy the download snippet or zip download.

---

### 🥈 Source B: YouTube Surveillance / Classroom CCTV Videos
1. Search on YouTube:
   - *"Classroom CCTV footage"*
   - *"Lecture hall surveillance camera view"*
   - *"College hall CCTV high angle"*
2. Download a 1 to 2 minute MP4 clip using any free tool.
3. Extract frames with our project script:
   ```bash
   python scripts/extract_cctv_frames.py --video sample_cctv.mp4 --interval 25
   ```
   *(This automatically extracts ~1 frame per second into `cctv_dataset_frames/`)*.
4. Upload those 50–100 images to [Roboflow.com](https://roboflow.com) (free) and draw boxes around students labeled as `person`.

---

## 3. Google Colab 10-Minute Training (Free T4 GPU)

Open a new notebook on [Google Colab](https://colab.research.google.com/):
1. **Menu:** *Runtime* -> *Change runtime type* -> Select **T4 GPU** -> Save.
2. In Cell 1, run:
```python
# 1. Install Ultralytics
!pip install -q ultralytics

# 2. Download or upload your dataset
# (If using Roboflow, paste the export curl/roboflow python snippet here)
```

3. In Cell 2, run training (Fine-tuning YOLOv8n backbone):
```python
from ultralytics import YOLO

# Load lightweight YOLOv8 Nano model (pretrained on COCO)
model = YOLO('yolov8n.pt')

# Train for 25 epochs (Takes only ~5 to 8 minutes on free Colab GPU!)
model.train(
    data='path_to_dataset/data.yaml',
    epochs=25,
    imgsz=640,
    batch=16,
    project='classroom_cctv',
    name='train_run'
)
```

4. Download the trained weights:
- Look in the Colab file tree: `classroom_cctv/train_run/weights/best.pt`.
- Right-click `best.pt` -> **Download** (~6.2 MB file).

---

## 4. Integrating the Custom Model into `spatial_server.py`

1. Move the downloaded `best.pt` into your project directory:
   ```
   d:\Projects\Smart Home\models\classroom_cctv_yolov8n.pt
   ```

2. Open `spatial_server.py` and change lines 609–611:
```python
# --- CUSTOM CLASSROOM CCTV MODEL ---
print("[AI SERVER] Loading Custom Classroom CCTV YOLOv8 Model...")
model = YOLO("models/classroom_cctv_yolov8n.pt")
```

3. That's it!
   - `yolov8n` runs at **~40–60 FPS on CPU** (much lighter and faster than `yolov8s-world.pt`).
   - The 10-second ECO scan will detect students accurately from high ceiling angles.
