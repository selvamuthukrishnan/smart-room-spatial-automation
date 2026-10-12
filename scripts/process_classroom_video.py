import cv2
import os

VIDEO_PATH = r"D:\Projects\Smart Home\models\Classroom Video\EEE1_classroom.mp4"
TRAIN_FRAMES_DIR = r"D:\Projects\Smart Home\dataset\train_frames"
DEMO_VIDEO_PATH = r"D:\Projects\Smart Home\models\Classroom Video\test_demo_clip.mp4"

def process_video():
    if not os.path.exists(VIDEO_PATH):
        print(f"[ERROR] Video not found at {VIDEO_PATH}")
        return

    os.makedirs(TRAIN_FRAMES_DIR, exist_ok=True)

    cap = cv2.VideoCapture(VIDEO_PATH)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"\n[INFO] Loaded Video: {VIDEO_PATH}")
    print(f"[INFO] Resolution: {width}x{height} | FPS: {fps} | Total Frames: {total_frames}")

    # Split:
    # 0 to 70% (~frame 0 to 5790, approx 0:00 to 3:51) -> Training frames
    # 70% to 100% (~frame 5791 to 8278, approx 3:52 to 5:31) -> Demo test video
    split_frame = int(total_frames * 0.70)
    
    # 1. Extract ~60 diverse training frames (1 frame every 90 frames = ~3.6 seconds)
    step = 90
    print(f"\n[STEP 1] Extracting Training Frames from 0:00 to 3:50 (Every {step} frames)...")
    
    frame_idx = 0
    saved_train_count = 0

    while frame_idx < split_frame:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            frame_name = os.path.join(TRAIN_FRAMES_DIR, f"train_frame_{saved_train_count:03d}.jpg")
            cv2.imwrite(frame_name, frame)
            saved_train_count += 1
            if saved_train_count % 10 == 0:
                print(f"  -> Extracted {saved_train_count} training frames...")

        frame_idx += 1

    print(f"[SUCCESS] Extracted {saved_train_count} training frames to: {TRAIN_FRAMES_DIR}")

    # 2. Save remaining 30% as Unseen Demo Test Video
    print(f"\n[STEP 2] Creating Unseen Live Demo Video Clip: {DEMO_VIDEO_PATH}...")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(DEMO_VIDEO_PATH, fourcc, fps, (width, height))

    test_frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
        test_frame_count += 1
        frame_idx += 1
        if test_frame_count % 500 == 0:
            print(f"  -> Written {test_frame_count} test frames to demo clip...")

    out.release()
    cap.release()

    test_duration_sec = test_frame_count / fps
    print(f"[SUCCESS] Demo test video created! ({test_frame_count} frames, {test_duration_sec:.1f} seconds)")
    print("\n" + "="*70)
    print(" ALL DONE!")
    print(f" [1] Training Frames: {TRAIN_FRAMES_DIR} ({saved_train_count} images)")
    print(f" [2] Unseen Test Clip: {DEMO_VIDEO_PATH} ({test_duration_sec:.1f}s)")
    print("="*70 + "\n")

if __name__ == "__main__":
    process_video()
