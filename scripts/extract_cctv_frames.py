import cv2
import os
import argparse

def extract_frames(video_path, output_dir="cctv_dataset_frames", frame_interval=30):
    """
    Extracts frames from a CCTV / Classroom video clip at regular intervals
    so they can be easily uploaded to Roboflow for quick annotation / fine-tuning.
    
    Usage:
        python extract_cctv_frames.py --video sample_cctv.mp4 --interval 25
    """
    if not os.path.exists(video_path):
        print(f"[ERROR] Video file not found: {video_path}")
        return

    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration_sec = total_frames / fps
    
    print(f"\n[INFO] Video: {video_path}")
    print(f"[INFO] Duration: {duration_sec:.1f}s ({total_frames} total frames at {fps:.1f} FPS)")
    print(f"[INFO] Extracting every {frame_interval}th frame (~1 frame every {frame_interval/fps:.2f}s)...\n")

    saved_count = 0
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            frame_filename = os.path.join(output_dir, f"cctv_frame_{saved_count:04d}.jpg")
            cv2.imwrite(frame_filename, frame)
            saved_count += 1
            if saved_count % 10 == 0:
                print(f"  -> Extracted {saved_count} frames...")

        frame_idx += 1

    cap.release()
    print(f"\n[SUCCESS] Extracted total {saved_count} frames into '{output_dir}/' folder!")
    print(f"[NEXT STEP] Upload these images to https://roboflow.com to annotate 'person' and export for YOLOv8!\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frames from CCTV / Classroom video for YOLO training")
    parser.add_argument("--video", type=str, default="sample_cctv.mp4", help="Path to input CCTV video file")
    parser.add_argument("--interval", type=int, default=30, help="Frame step interval (default: 30 = ~1 frame/sec)")
    parser.add_argument("--output", type=str, default="cctv_dataset_frames", help="Folder to save extracted frames")
    args = parser.parse_args()

    extract_frames(args.video, args.output, args.interval)
