import os
import json
import cv2
import time
import math
import socket
import threading
import requests
import numpy as np
from flask import Flask, Response, jsonify, request, render_template_string
from ultralytics import YOLO

# =================================================================================
# PROJECT: Spatial AI Smart Room - Server with Auto-Shift & Calibration UI
# =================================================================================

ROOMS_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "rooms_config.json")

def get_local_ip():
    """Dynamically finds the laptop's actual IP address on Wi-Fi / Hotspot network"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

# --- 📱 CAMERA & ESP32 CONFIGURATION ---
import sys
CLASSROOM_VIDEO = os.path.join(os.path.dirname(__file__), "models", "Classroom Video", "EEE1_classroom.mp4")
DEFAULT_DEMO_VIDEO = os.path.join(os.path.dirname(__file__), "models", "Classroom Video", "test_demo_clip.mp4")

# Defaults to Classroom Video footage, otherwise test demo clip, otherwise webcam 0
if os.path.exists(CLASSROOM_VIDEO):
    CAMERA_SOURCE = CLASSROOM_VIDEO
elif os.path.exists(DEFAULT_DEMO_VIDEO):
    CAMERA_SOURCE = DEFAULT_DEMO_VIDEO
else:
    CAMERA_SOURCE = 0

for arg in sys.argv[1:]:
    if arg in ["--webcam", "-w", "0", "--cam"]:
        CAMERA_SOURCE = 0
        break
    elif arg.endswith((".mp4", ".avi", ".mov")) and os.path.exists(arg):
        CAMERA_SOURCE = os.path.abspath(arg)
        break
    elif arg.isdigit():
        CAMERA_SOURCE = int(arg)
        break

print(f"[AI SERVER] Active Camera/Video Source: {CAMERA_SOURCE}")
ESP32_IP = "http://192.168.43.125"

# --- 🎯 3D PERSPECTIVE GRID & MULTI-ROOM CONFIGURATION ---
DEFAULT_GRID_CONFIG = {
    "corners": [[340, 140], [1780, 190], [1880, 990], [220, 990]],
    "bend_pins": {
        "top": [1060, 165],
        "right": [1830, 590],
        "bottom": [1050, 990],
        "left": [280, 565]
    },
    "rows": 6,
    "cols": 6
}
GRID_CONFIG = dict(DEFAULT_GRID_CONFIG)

def clip_polygon_py(poly, xmin=0, ymin=0, xmax=1920, ymax=1080):
    """Sutherland-Hodgman Polygon Clipping against rectangular camera frame bounds"""
    def clip_edge(pts, inside_fn, intersect_fn):
        res = []
        if not pts:
            return res
        n = len(pts)
        for i in range(n):
            cur = pts[i]
            prev = pts[(i + n - 1) % n]
            cur_in = inside_fn(cur)
            prev_in = inside_fn(prev)
            if cur_in:
                if not prev_in:
                    res.append(intersect_fn(prev, cur))
                res.append(cur)
            elif prev_in:
                res.append(intersect_fn(prev, cur))
        return res

    out = [list(map(float, pt)) for pt in poly]
    # left
    out = clip_edge(out, lambda p: p[0] >= xmin,
                    lambda p1, p2: [float(xmin), p1[1] + (xmin - p1[0]) * (p2[1] - p1[1]) / (p2[0] - p1[0] or 1e-9)])
    # right
    out = clip_edge(out, lambda p: p[0] <= xmax,
                    lambda p1, p2: [float(xmax), p1[1] + (xmax - p1[0]) * (p2[1] - p1[1]) / (p2[0] - p1[0] or 1e-9)])
    # top
    out = clip_edge(out, lambda p: p[1] >= ymin,
                    lambda p1, p2: [p1[0] + (ymin - p1[1]) * (p2[0] - p1[0]) / (p2[1] - p1[1] or 1e-9), float(ymin)])
    # bottom
    out = clip_edge(out, lambda p: p[1] <= ymax,
                    lambda p1, p2: [p1[0] + (ymax - p1[1]) * (p2[0] - p1[0]) / (p2[1] - p1[1] or 1e-9), float(ymax)])

    return [[int(round(p[0])), int(round(p[1]))] for p in out]

def normalize_corners_py(corners):
    """Normalizes corners to [[x, y], [x, y], [x, y], [x, y]] whether passed as dicts or lists"""
    normalized = []
    if not corners:
        return list(DEFAULT_GRID_CONFIG["corners"])
    for c in corners:
        if isinstance(c, dict):
            normalized.append([int(round(float(c.get("x", 0)))), int(round(float(c.get("y", 0))))])
        elif isinstance(c, (list, tuple)) and len(c) >= 2:
            normalized.append([int(round(float(c[0]))), int(round(float(c[1])))])
    if len(normalized) != 4:
        return list(DEFAULT_GRID_CONFIG["corners"])
    return normalized

def normalize_bend_pins_py(bend_pins, corners):
    """Normalizes 4 edge bending pins (top, right, bottom, left) to native coordinate points"""
    mids = {
        "top": [int(round((corners[0][0] + corners[1][0]) / 2)), int(round((corners[0][1] + corners[1][1]) / 2))],
        "right": [int(round((corners[1][0] + corners[2][0]) / 2)), int(round((corners[1][1] + corners[2][1]) / 2))],
        "bottom": [int(round((corners[3][0] + corners[2][0]) / 2)), int(round((corners[3][1] + corners[2][1]) / 2))],
        "left": [int(round((corners[0][0] + corners[3][0]) / 2)), int(round((corners[0][1] + corners[3][1]) / 2))]
    }
    if not bend_pins or not isinstance(bend_pins, dict):
        return mids
    result = {}
    for edge in ["top", "right", "bottom", "left"]:
        pt = bend_pins.get(edge)
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            result[edge] = [int(round(float(pt[0]))), int(round(float(pt[1])))]
        elif isinstance(pt, dict) and "x" in pt and "y" in pt:
            result[edge] = [int(round(float(pt["x"]))), int(round(float(pt["y"])))]
        else:
            result[edge] = mids[edge]
    return result

def compute_grid_transform_py(corners):
    """Calculates 3D projective homography matrix evaluator in Python"""
    p0, p1, p2, p3 = corners
    x0, y0 = p0; x1, y1 = p1; x2, y2 = p2; x3, y3 = p3
    dx1 = x1 - x2; dx2 = x3 - x2; sx = x0 - x1 + x2 - x3
    dy1 = y1 - y2; dy2 = y3 - y2; sy = y0 - y1 + y2 - y3
    det = dx1 * dy2 - dy1 * dx2
    if abs(det) < 1e-7:
        return None
    g = (sx * dy2 - sy * dx2) / det
    h = (dx1 * sy - dy1 * sx) / det
    a = x1 - x0 + g * x1; b = x3 - x0 + h * x3; c = x0
    d = y1 - y0 + g * y1; e = y3 - y0 + h * y3; f = y0
    def transform(u, v):
        denom = g * u + h * v + 1.0
        return [int(round((a * u + b * v + c) / denom)), int(round((d * u + e * v + f) / denom))]
    return transform

def compute_all_cells_py(grid_cfg=None):
    """Computes all cell boundary polygons with homography and Coons patch edge bending"""
    cfg = grid_cfg if grid_cfg else GRID_CONFIG
    corners = normalize_corners_py(cfg.get("corners", DEFAULT_GRID_CONFIG["corners"]))
    rows = int(cfg.get("rows", 6))
    cols = int(cfg.get("cols", 6))
    tf = compute_grid_transform_py(corners)
    if not tf:
        return {}

    bends = normalize_bend_pins_py(cfg.get("bend_pins"), corners)
    mids = {
        "top": [(corners[0][0] + corners[1][0]) // 2, (corners[0][1] + corners[1][1]) // 2],
        "right": [(corners[1][0] + corners[2][0]) // 2, (corners[1][1] + corners[2][0]) // 2],
        "bottom": [(corners[3][0] + corners[2][0]) // 2, (corners[3][1] + corners[2][0]) // 2],
        "left": [(corners[0][0] + corners[3][0]) // 2, (corners[0][1] + corners[3][1]) // 2]
    }
    d_top_x = bends["top"][0] - mids["top"][0]
    d_top_y = bends["top"][1] - mids["top"][1]
    d_right_x = bends["right"][0] - mids["right"][0]
    d_right_y = bends["right"][1] - mids["right"][1]
    d_bot_x = bends["bottom"][0] - mids["bottom"][0]
    d_bot_y = bends["bottom"][1] - mids["bottom"][1]
    d_left_x = bends["left"][0] - mids["left"][0]
    d_left_y = bends["left"][1] - mids["left"][1]
    has_bends = any([d_top_x, d_top_y, d_right_x, d_right_y, d_bot_x, d_bot_y, d_left_x, d_left_y])

    def eval_pt(u, v):
        pt = tf(u, v)
        if not has_bends:
            return pt
        w_top = 4.0 * u * (1.0 - u) * (1.0 - v)
        w_bot = 4.0 * u * (1.0 - u) * v
        w_left = 4.0 * (1.0 - u) * v * (1.0 - v)
        w_right = 4.0 * u * v * (1.0 - v)
        dx = w_top * d_top_x + w_bot * d_bot_x + w_left * d_left_x + w_right * d_right_x
        dy = w_top * d_top_y + w_bot * d_bot_y + w_left * d_left_y + w_right * d_right_y
        return [int(round(pt[0] + dx)), int(round(pt[1] + dy))]

    cells = {}
    for r in range(rows):
        for c in range(cols):
            u0, u1 = c / cols, (c + 1) / cols
            v0, v1 = r / rows, (r + 1) / rows
            pTL = eval_pt(u0, v0); pTR = eval_pt(u1, v0); pBR = eval_pt(u1, v1); pBL = eval_pt(u0, v1)
            cid = f"R{r+1}-C{c+1}"
            cells[cid] = [pTL, pTR, pBR, pBL]
    return cells

def get_default_appliances_py(grid_cfg=None):
    """Generates clean initial room appliances"""
    cells = compute_all_cells_py(grid_cfg)
    b1_cells = [f"R{r}-C{c}" for r in [4, 5, 6] for c in range(1, 7)]
    b2_cells = [f"R{r}-C{c}" for r in [1, 2, 3] for c in range(1, 7)]

    def build_item(name, app_type, assigned, relay_ch):
        polys = [cells[cid] for cid in assigned if cid in cells]
        all_xs = [pt[0] for poly in polys for pt in poly] if polys else [960]
        all_ys = [pt[1] for poly in polys for pt in poly] if polys else [540]
        return {
            "name": name,
            "type": app_type,
            "roi": None,
            "assigned_cells": assigned,
            "cell_polygons": polys,
            "space_roi": [min(all_xs), min(all_ys), max(1, max(all_xs)-min(all_xs)), max(1, max(all_ys)-min(all_ys))],
            "zone_centroid": [int(np.mean(all_xs)), int(np.mean(all_ys))],
            "vision_state": "OFF",
            "control_state": False,
            "manual_override": "auto",
            "relay_channel": relay_ch
        }

    return {
        "block_1": build_item("Block 1 (Front Benches)", "fan", b1_cells, 1),
        "block_2": build_item("Block 2 (Back Benches)", "fan", b2_cells, 2)
    }

def recalculate_appliances_py():
    """Recalculates cell polygons and space_roi for all appliances using current GRID_CONFIG"""
    global APPLIANCES, GRID_CONFIG
    cells = compute_all_cells_py(GRID_CONFIG)
    if not cells:
        return
    for k, app in APPLIANCES.items():
        assigned = app.get("assigned_cells", [])
        if assigned:
            app["cell_polygons"] = [cells[cid] for cid in assigned if cid in cells]
            all_xs = [pt[0] for poly in app["cell_polygons"] for pt in poly] if app["cell_polygons"] else [960]
            all_ys = [pt[1] for poly in app["cell_polygons"] for pt in poly] if app["cell_polygons"] else [540]
            app["space_roi"] = [min(all_xs), min(all_ys), max(1, max(all_xs)-min(all_xs)), max(1, max(all_ys)-min(all_ys))]
            app["zone_centroid"] = [int(np.mean(all_xs)), int(np.mean(all_ys))]

# --- MULTI-ROOM CONFIGURATION STATE ---
ROOMS_DATA = {}
ACTIVE_ROOM_ID = "room_eee1"
ACTIVE_ROOM = {}
APPLIANCES = {}

def load_rooms_data():
    global ROOMS_DATA, ACTIVE_ROOM_ID, ACTIVE_ROOM, APPLIANCES, GRID_CONFIG
    if os.path.exists(ROOMS_CONFIG_FILE):
        try:
            with open(ROOMS_CONFIG_FILE, "r", encoding="utf-8") as f:
                ROOMS_DATA = json.load(f)
        except Exception as e:
            print(f"[CONFIG] Error loading {ROOMS_CONFIG_FILE}: {e}")
            ROOMS_DATA = {}

    if not ROOMS_DATA or "rooms" not in ROOMS_DATA or not ROOMS_DATA["rooms"]:
        ROOMS_DATA = {
            "active_room_id": "room_eee1",
            "rooms": {
                "room_eee1": {
                    "id": "room_eee1",
                    "name": "EEE Classroom 1",
                    "video_source": {"type": "file", "value": "models/Classroom Video/EEE1_classroom.mp4"},
                    "grid_config": dict(DEFAULT_GRID_CONFIG),
                    "appliances": get_default_appliances_py(DEFAULT_GRID_CONFIG)
                }
            },
            "recent_videos": [
                "models/Classroom Video/EEE1_classroom.mp4",
                "models/Classroom Video/test_demo_clip.mp4"
            ]
        }
        save_rooms_to_disk()

    ACTIVE_ROOM_ID = ROOMS_DATA.get("active_room_id")
    if not ACTIVE_ROOM_ID or ACTIVE_ROOM_ID not in ROOMS_DATA["rooms"]:
        ACTIVE_ROOM_ID = next(iter(ROOMS_DATA["rooms"].keys()))
        ROOMS_DATA["active_room_id"] = ACTIVE_ROOM_ID

    ACTIVE_ROOM = ROOMS_DATA["rooms"][ACTIVE_ROOM_ID]
    grid = ACTIVE_ROOM.get("grid_config", {})
    clean_corners = normalize_corners_py(grid.get("corners", DEFAULT_GRID_CONFIG["corners"]))
    GRID_CONFIG["corners"] = clean_corners
    GRID_CONFIG["bend_pins"] = normalize_bend_pins_py(grid.get("bend_pins"), clean_corners)
    GRID_CONFIG["rows"] = int(grid.get("rows", 6))
    GRID_CONFIG["cols"] = int(grid.get("cols", 6))

    raw_apps = ACTIVE_ROOM.get("appliances", {})
    APPLIANCES = {}
    for k, v in raw_apps.items():
        v["vision_state"] = "OFF"
        v["control_state"] = False
        if "manual_override" not in v:
            v["manual_override"] = "auto"
        if "relay_channel" not in v:
            v["relay_channel"] = 1
        if "cell_polygons" not in v:
            v["cell_polygons"] = []
        if "assigned_cells" not in v:
            v["assigned_cells"] = []
        APPLIANCES[k] = v

    recalculate_appliances_py()
    print(f"[CONFIG] Active Room: '{ACTIVE_ROOM.get('name')}' ({ACTIVE_ROOM_ID}) with {len(APPLIANCES)} appliances.")

def save_rooms_to_disk():
    global ROOMS_DATA, ACTIVE_ROOM_ID, ACTIVE_ROOM, APPLIANCES, GRID_CONFIG
    if not ROOMS_DATA:
        return
    ROOMS_DATA["active_room_id"] = ACTIVE_ROOM_ID
    if "rooms" not in ROOMS_DATA:
        ROOMS_DATA["rooms"] = {}

    if ACTIVE_ROOM_ID in ROOMS_DATA["rooms"]:
        clean_corners = normalize_corners_py(GRID_CONFIG.get("corners", DEFAULT_GRID_CONFIG["corners"]))
        clean_bend = normalize_bend_pins_py(GRID_CONFIG.get("bend_pins"), clean_corners)
        ROOMS_DATA["rooms"][ACTIVE_ROOM_ID]["grid_config"] = {
            "corners": clean_corners,
            "bend_pins": clean_bend,
            "rows": int(GRID_CONFIG.get("rows", 6)),
            "cols": int(GRID_CONFIG.get("cols", 6))
        }

        clean_apps = {}
        for k, v in APPLIANCES.items():
            clean_apps[k] = {
                "name": v.get("name", k),
                "type": v.get("type", "fan"),
                "roi": v.get("roi"),
                "assigned_cells": v.get("assigned_cells", []),
                "cell_polygons": v.get("cell_polygons", []),
                "space_roi": v.get("space_roi", [0, 0, 0, 0]),
                "zone_centroid": v.get("zone_centroid", [960, 540]),
                "manual_override": v.get("manual_override", "auto"),
                "relay_channel": v.get("relay_channel", 1)
            }
        ROOMS_DATA["rooms"][ACTIVE_ROOM_ID]["appliances"] = clean_apps

    try:
        with open(ROOMS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(ROOMS_DATA, f, indent=2)
        print(f"[CONFIG] Saved multi-room state to {ROOMS_CONFIG_FILE}")
    except Exception as e:
        print(f"[CONFIG] Error saving to {ROOMS_CONFIG_FILE}: {e}")

def switch_active_room(room_id):
    global ACTIVE_ROOM_ID, ACTIVE_ROOM, GRID_CONFIG, APPLIANCES, ROOMS_DATA
    if room_id not in ROOMS_DATA.get("rooms", {}):
        return False
    ACTIVE_ROOM_ID = room_id
    ROOMS_DATA["active_room_id"] = room_id
    ACTIVE_ROOM = ROOMS_DATA["rooms"][room_id]

    grid = ACTIVE_ROOM.get("grid_config", {})
    clean_corners = normalize_corners_py(grid.get("corners", DEFAULT_GRID_CONFIG["corners"]))
    GRID_CONFIG["corners"] = clean_corners
    GRID_CONFIG["bend_pins"] = normalize_bend_pins_py(grid.get("bend_pins"), clean_corners)
    GRID_CONFIG["rows"] = int(grid.get("rows", 6))
    GRID_CONFIG["cols"] = int(grid.get("cols", 6))

    raw_apps = ACTIVE_ROOM.get("appliances", {})
    APPLIANCES = {}
    for k, v in raw_apps.items():
        v["vision_state"] = "OFF"
        v["control_state"] = False
        if "manual_override" not in v:
            v["manual_override"] = "auto"
        if "relay_channel" not in v:
            v["relay_channel"] = 1
        APPLIANCES[k] = v

    recalculate_appliances_py()
    save_rooms_to_disk()
    return True

load_rooms_data()

# --- GLOBAL THREADING STATE ---
latest_frame = None
raw_camera_frame = None
prev_gray_frame = None
ref_gray_32f = None
camera_shift_x = 0
camera_shift_y = 0
lock = threading.Lock()
PROXIMITY_RADIUS = 280
SCAN_INTERVAL_SEC = 0.0
last_scan_time = 0
last_esp_send_time = 0
humans_detected_count = 0
remaining_time_global = 0.0
AI_TRACKING_ACTIVE = True
pending_camera_switch = None

# --- INITIALIZE FLASK SERVER ---
app = Flask(__name__)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
@app.route("/dashboard")
@app.route("/dashboard.html")
def serve_index_html():
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="text/html")
    return "Error: index.html not found", 404

# --- 🎯 INTERACTIVE VISUAL CALIBRATION PAGE ---
CALIBRATION_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>3D Room Perspective Depth Grid & Space Calibration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .crosshair-cur { cursor: crosshair; }
        .canvas-container { position: relative; display: inline-block; user-select: none; }
        .pin-badge { pointer-events: none; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-3 md:p-6 font-sans">
    <div class="max-w-7xl mx-auto space-y-4">
        <!-- HEADER -->
        <header class="flex flex-col md:flex-row justify-between items-start md:items-center pb-4 border-b border-slate-800 gap-4">
            <div>
                <h1 class="text-xl md:text-2xl font-bold text-sky-400 flex items-center gap-2">
                    <span>📐</span> 3D Classroom Depth Perspective Grid & Space Calibration
                </h1>
                <p class="text-xs md:text-sm text-slate-400 mt-1">
                    Calibrated for Classroom CCTV &bull; Select exact desk grid cells for each Fan 🌀 or Light 💡!
                </p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
                <span id="calib-room-badge" class="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-sky-950 text-sky-300 border border-sky-700 flex items-center gap-1.5 shadow">
                    <span>🏫</span> <span id="calib-room-name">EEE Classroom 1</span>
                </span>
                <select id="clone-room-dropdown" onchange="cloneGridFromOtherRoom(this.value)" class="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-slate-900 border border-slate-700 text-slate-300 hover:text-white cursor-pointer focus:outline-none shadow">
                    <option value="">📋 Clone Grid From Another Room...</option>
                </select>
                <span id="sync-status-badge" class="px-2.5 py-1.5 rounded-lg text-xs font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700 flex items-center gap-1.5 shadow">
                    <span>🟢</span> Live Synced
                </span>
                <button onclick="saveAllToBackend(true)" class="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 shadow-lg shadow-emerald-900/40">
                    <span>💾</span> Save & Apply
                </button>
                <button onclick="resetCameraShift()" class="px-3 py-2 bg-amber-600 hover:bg-amber-500 rounded-lg text-xs font-semibold transition">
                    🔄 Reset Auto-Shift
                </button>
                <a href="/" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5">
                    <span>🏠</span> Back to Dashboard
                </a>
            </div>
        </header>

        <!-- MAIN LAYOUT -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- CANVAS AREA (2 COLS) -->
            <div class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl space-y-3">
                <div class="flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="text-xs uppercase tracking-wider font-bold text-slate-400">Classroom CCTV View</span>
                        <span id="active-mode-badge" class="px-2.5 py-0.5 rounded text-[11px] font-bold bg-sky-950 text-sky-300 border border-sky-700">
                            Mode: Click Desk Cells to Select
                        </span>
                    </div>
                    <span id="shift-indicator" class="text-xs font-mono text-emerald-400 bg-emerald-950/60 px-2.5 py-1 rounded border border-emerald-800">
                        Camera Shift: (0px, 0px)
                    </span>
                </div>

                <div class="flex items-center justify-between text-xs px-1">
                    <span class="text-slate-400 flex items-center gap-1.5 font-medium">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <span>Boundary Clipping: <b class="text-emerald-300">AUTO-CLIPPING ACTIVE (1920×1080)</b></span>
                    </span>
                    <span class="text-slate-500 italic text-[11px]">Yellow pins can be dragged outside the camera boundary</span>
                </div>

                <!-- 🔍 VIDEO SIZE & DYNAMIC FRAMING CONTROLS -->
                <div class="bg-slate-950 p-2.5 rounded-xl border border-sky-800/80 space-y-2 text-xs shadow-md">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <div class="flex items-center gap-2">
                            <span class="font-bold text-sky-300 flex items-center gap-1.5">
                                <span>🔍</span> Video Size (Scale & Extend):
                            </span>
                            <button type="button" onclick="adjustVideoScale(-0.1)" title="Shrink Video (-10%)" class="w-6 h-6 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold transition text-xs">➖</button>
                            <input id="video-scale-slider" type="range" min="50" max="220" value="100" step="5" oninput="onVideoScaleSlider(this.value)" class="w-24 accent-sky-400 cursor-pointer">
                            <button type="button" onclick="adjustVideoScale(0.1)" title="Extend Video (+10%)" class="w-6 h-6 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold transition text-xs">➕</button>
                            <span id="video-scale-badge" class="font-mono text-emerald-400 font-bold px-2 py-0.5 bg-slate-900 border border-slate-700 rounded text-[11px] min-w-[95px] text-center">100% (1920×1080)</span>
                        </div>

                        <!-- Quick Presets -->
                        <div class="flex flex-wrap items-center gap-1.5">
                            <span class="text-slate-400 text-[11px] font-medium">Presets:</span>
                            <button type="button" onclick="setVideoScale(0.75)" class="px-2 py-1 bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700 rounded text-[11px] font-semibold transition">
                                75% Small
                            </button>
                            <button type="button" onclick="setVideoScale(1.0)" class="px-2 py-1 bg-sky-950 hover:bg-sky-900 text-sky-300 border border-sky-600 rounded text-[11px] font-semibold transition">
                                100% Normal
                            </button>
                            <button type="button" onclick="setVideoScale(1.25)" class="px-2 py-1 bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-500 rounded text-[11px] font-semibold transition">
                                🚀 125% Extend
                            </button>
                            <button type="button" onclick="setVideoScale(1.5)" class="px-2 py-1 bg-purple-950 hover:bg-purple-900 text-purple-300 border border-purple-500 rounded text-[11px] font-semibold transition">
                                150% Wide
                            </button>
                            <button type="button" onclick="setVideoScale(1.8)" class="px-2 py-1 bg-amber-950 hover:bg-amber-900 text-amber-300 border border-amber-500 rounded text-[11px] font-semibold transition">
                                180% Max
                            </button>
                        </div>
                    </div>

                    <div class="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-slate-800/80 text-[11px]">
                        <!-- Stretch Controls -->
                        <div class="flex items-center gap-1.5">
                            <span class="text-slate-400 font-medium">Fine Stretch:</span>
                            <button type="button" onclick="nudgeVideoStretch('width', 0.05)" title="Extend Video Width" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded font-mono">↔️ W+5%</button>
                            <button type="button" onclick="nudgeVideoStretch('width', -0.05)" title="Shrink Video Width" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded font-mono">↔️ W-5%</button>
                            <button type="button" onclick="nudgeVideoStretch('height', 0.05)" title="Extend Video Height" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded font-mono">↕️ H+5%</button>
                            <button type="button" onclick="nudgeVideoStretch('height', -0.05)" title="Shrink Video Height" class="px-1.5 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded font-mono">↕️ H-5%</button>
                        </div>

                        <!-- Pan Navigation & Reset -->
                        <div class="flex items-center gap-1.5">
                            <span class="text-slate-400 font-medium">Pan:</span>
                            <button type="button" onclick="panVideo(-35, 0)" title="Pan Left" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-slate-200 rounded">◀</button>
                            <button type="button" onclick="panVideo(0, -35)" title="Pan Up" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-slate-200 rounded">▲</button>
                            <button type="button" onclick="panVideo(0, 35)" title="Pan Down" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-slate-200 rounded">▼</button>
                            <button type="button" onclick="panVideo(35, 0)" title="Pan Right" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-slate-200 rounded">▶</button>
                            <button type="button" onclick="resetVideoTransform()" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-amber-300 border border-slate-600 rounded font-semibold transition">
                                🔄 Reset View
                            </button>
                        </div>

                        <!-- Helpful Mouse Shortcut Tip -->
                        <div class="text-slate-500 italic text-[10px]">
                            💡 Mouse Wheel: Zoom &bull; Right-Click / Middle-Click Drag: Pan view
                        </div>
                    </div>
                </div>

                <div class="canvas-container overflow-hidden rounded-xl border border-slate-700 w-full flex justify-center bg-slate-950 p-1">
                    <canvas id="calib-canvas" class="crosshair-cur max-w-full h-auto shadow-inner rounded-lg"></canvas>
                </div>

                <!-- 3D PERSPECTIVE GRID CONTROLS BAR -->
                <div class="bg-slate-950 p-3 rounded-xl border border-slate-800 space-y-2 text-xs">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <span class="font-bold text-slate-300 flex items-center gap-1.5">
                            <span>📐</span> Grid Presets & Adjustments:
                        </span>
                        <div class="flex items-center gap-2">
                            <!-- Rows adjustment -->
                            <div class="flex items-center bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 gap-1.5">
                                <span class="text-slate-400 font-medium text-[11px]">Rows:</span>
                                <button onclick="changeRows(-1)" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold">-</button>
                                <span id="grid-rows-val" class="font-mono text-sky-400 font-bold px-1">5</span>
                                <button onclick="changeRows(1)" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold">+</button>
                            </div>
                            <!-- Cols adjustment -->
                            <div class="flex items-center bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 gap-1.5">
                                <span class="text-slate-400 font-medium text-[11px]">Cols:</span>
                                <button onclick="changeCols(-1)" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold">-</button>
                                <span id="grid-cols-val" class="font-mono text-sky-400 font-bold px-1">4</span>
                                <button onclick="changeCols(1)" class="w-5 h-5 flex items-center justify-center bg-slate-800 hover:bg-slate-700 text-white rounded font-bold">+</button>
                            </div>
                        </div>
                    </div>

                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
                        <button onclick="applyPreset('desks_aligned')" class="py-2 px-2 bg-emerald-950 hover:bg-emerald-900 border border-emerald-500 text-emerald-300 font-bold rounded-lg text-[11px] flex items-center justify-center gap-1 transition shadow-sm">
                            <span>⭐</span> Auto-Align Desks (5×4)
                        </button>
                        <button onclick="applyPreset('desks_extended')" class="py-2 px-2 bg-sky-950 hover:bg-sky-900 border border-sky-600 text-sky-300 font-bold rounded-lg text-[11px] flex items-center justify-center gap-1 transition">
                            <span>🚀</span> Extend Beyond Frame
                        </button>
                        <button id="btn-toggle-bend-pins" onclick="toggleBendPins()" class="py-2 px-2 bg-purple-950 hover:bg-purple-900 border border-purple-500 text-purple-300 font-bold rounded-lg text-[11px] flex items-center justify-center gap-1 transition">
                            <span>🧲</span> 8 Pins (Curved): ON
                        </button>
                        <button id="btn-toggle-pins" onclick="toggleCornerPins()" class="py-2 px-2 bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 font-bold rounded-lg text-[11px] flex items-center justify-center gap-1 transition">
                            <span>📌</span> Pins: ON
                        </button>
                    </div>

                    <!-- Quick Nudge Bar for Plane Extension & Opacity Slider -->
                    <div class="bg-slate-900/90 p-2 rounded-lg border border-slate-800 flex flex-wrap items-center justify-between gap-1.5 pt-2">
                        <div class="flex items-center gap-2">
                            <span class="text-[11px] font-semibold text-slate-300 flex items-center gap-1">
                                <span>✂️</span> Extend / Nudge:
                            </span>
                            <button type="button" onclick="nudgeBottom(40)" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 rounded text-[11px] font-medium transition cursor-pointer">
                                ⬇️ Bottom +40px
                            </button>
                            <button type="button" onclick="nudgeBottom(-40)" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 rounded text-[11px] font-medium transition cursor-pointer">
                                ⬆️ Bottom -40px
                            </button>
                            <button type="button" onclick="nudgeSides(40)" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 rounded text-[11px] font-medium transition cursor-pointer">
                                ↔️ Sides +40px
                            </button>
                        </div>
                        <div class="flex flex-wrap items-center gap-2">
                            <!-- Opacity Slider -->
                            <div class="flex items-center bg-slate-950 border border-slate-700 rounded-lg px-2 py-1 gap-1.5">
                                <span class="text-slate-400 font-medium text-[11px]">Opacity:</span>
                                <input id="grid-opacity-slider" type="range" min="5" max="35" value="12" step="1" oninput="setGridOpacity(this.value)" class="w-16 accent-sky-400 cursor-pointer">
                                <span id="grid-opacity-badge" class="font-mono text-sky-400 font-bold text-[11px]">12%</span>
                            </div>
                            <button type="button" onclick="resetBendPins()" class="px-2 py-1 bg-purple-950 hover:bg-purple-900 text-purple-200 border border-purple-600 rounded text-[11px] font-semibold transition cursor-pointer" title="Straighten all bent edges">
                                🔄 Straighten Bends
                            </button>
                            <button type="button" onclick="resetPinsToFrame()" class="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-amber-300 border border-slate-600 rounded text-[11px] font-medium transition cursor-pointer">
                                🎯 Snap Inside
                            </button>
                        </div>
                    </div>
                </div>

                <!-- VISUAL LEGEND -->
                <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px] bg-slate-950/80 p-2 rounded-xl border border-slate-800">
                    <div class="flex items-center gap-1.5 text-sky-400">
                        <span class="w-3 h-3 rounded-sm border border-sky-400 bg-sky-500/20"></span>
                        <span>🌀 Fan Space Cells</span>
                    </div>
                    <div class="flex items-center gap-1.5 text-amber-400">
                        <span class="w-3 h-3 rounded-sm border border-amber-400 bg-amber-500/20"></span>
                        <span>💡 Light Space Cells</span>
                    </div>
                    <div class="flex items-center gap-1.5 text-yellow-300">
                        <span class="w-3 h-3 rounded-full border-2 border-yellow-400 bg-yellow-400/40"></span>
                        <span>🟡 4 Corner Pins</span>
                    </div>
                    <div class="flex items-center gap-1.5 text-purple-300">
                        <span class="w-3 h-3 rotate-45 border-2 border-purple-400 bg-purple-400/40 inline-block"></span>
                        <span>🔷 4 Bending Diamond Pins</span>
                    </div>
                </div>
            </div>

            <!-- RIGHT CONTROL PANEL -->
            <div class="space-y-4">
                <!-- APPLIANCE EDITOR CARD -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl space-y-4">
                    <div class="flex justify-between items-center pb-2 border-b border-slate-800">
                        <h3 class="text-base font-bold text-white flex items-center gap-2">
                            <span>✏️</span> Active Appliance / Zone
                        </h3>
                        <span id="active-cells-count" class="text-xs font-mono font-bold px-2 py-0.5 rounded bg-sky-950 text-sky-400 border border-sky-800">
                            0 Cells Selected
                        </span>
                    </div>

                    <!-- SELECT APPLIANCE -->
                    <div>
                        <label class="text-xs text-slate-400">Select Appliance to Configure:</label>
                        <select id="select-active-appliance" onchange="onSelectApplianceChange()" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs mt-1 font-semibold focus:outline-none focus:border-sky-500">
                            <!-- Populated by JS -->
                        </select>
                    </div>

                    <div>
                        <label class="text-xs text-slate-400">Appliance / Zone Name:</label>
                        <input id="prop-name" type="text" oninput="onPropNameChange()" placeholder="e.g. Block 1 (Front Benches)" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs focus:outline-none focus:border-sky-500 mt-1">
                    </div>

                    <div>
                        <label class="text-xs text-slate-400">Control Target Type:</label>
                        <div class="grid grid-cols-2 gap-2 mt-1">
                            <button type="button" id="btn-type-fan" onclick="setType('fan')" class="py-2 px-3 rounded-lg border border-sky-500 bg-sky-950/60 text-sky-300 font-semibold text-xs flex items-center justify-center gap-1.5">
                                <span>🌀</span> Ceiling Fan
                            </button>
                            <button type="button" id="btn-type-light" onclick="setType('light')" class="py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold text-xs flex items-center justify-center gap-1.5">
                                <span>💡</span> Tube Light
                            </button>
                        </div>
                    </div>

                    <!-- 📍 PHYSICAL CEILING MARKER (OPTIONAL) -->
                    <div class="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                        <div class="flex items-center justify-between">
                            <label class="text-xs font-semibold text-slate-300 flex items-center gap-2 cursor-pointer select-none">
                                <input type="checkbox" id="check-enable-ceiling" onchange="toggleCeilingOption()" class="rounded border-slate-700 bg-slate-900 text-sky-500 focus:ring-0">
                                <span>📍 Physical Ceiling Marker</span>
                            </label>
                            <span id="ceiling-marker-badge" class="text-[10px] text-slate-500 font-mono">Optional (Off)</span>
                        </div>
                        <p class="text-[11px] text-slate-400 leading-tight">
                            Camera frame-la fan/light ceiling theriyalana ithe <b class="text-slate-300">off</b> laiye vekkalam. Students desk-la vanthale automate aagum!
                        </p>
                        <div id="ceiling-marker-controls" class="hidden pt-1 space-y-1.5">
                            <button type="button" id="btn-ceiling-marker" onclick="toggleCeilingMarkerMode()" class="w-full py-1.5 px-2 text-xs bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition">
                                <span>🎯</span> Click on Camera to Place Ceiling Box
                            </button>
                            <button type="button" onclick="clearCeilingMarker()" class="w-full py-1 text-[11px] text-slate-400 hover:text-red-400 text-center">
                                Remove Ceiling Marker
                            </button>
                        </div>
                    </div>

                    <!-- QUICK BATCH CELL SELECTION BUTTONS -->
                    <div class="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-bold text-slate-300">Quick Column / Row Shortcuts:</span>
                            <button type="button" onclick="selectAllCells()" class="text-sky-400 hover:text-sky-300 text-[11px] font-semibold">Select All</button>
                        </div>
                        <div id="batch-column-buttons" class="grid grid-cols-4 gap-1.5">
                            <!-- Populated dynamically based on cols count -->
                        </div>
                        <div class="grid grid-cols-3 gap-1.5 pt-1">
                            <button type="button" onclick="quickSelectRows([0, 1])" class="py-1 px-1 text-[11px] bg-slate-900 hover:bg-slate-800 rounded border border-slate-700 text-slate-300">Back (R1-R2)</button>
                            <button type="button" onclick="quickSelectRows([2])" class="py-1 px-1 text-[11px] bg-slate-900 hover:bg-slate-800 rounded border border-slate-700 text-slate-300">Mid (R3)</button>
                            <button type="button" onclick="quickSelectRows([3, 4])" class="py-1 px-1 text-[11px] bg-slate-900 hover:bg-slate-800 rounded border border-slate-700 text-slate-300">Front (R4-R5)</button>
                        </div>
                        <button type="button" onclick="clearActiveCells()" class="w-full py-1 text-[11px] text-red-400 hover:text-red-300 text-center">Clear Cells for This Appliance</button>
                    </div>

                    <!-- ACTION BUTTONS -->
                    <div class="grid grid-cols-2 gap-2 pt-1">
                        <button onclick="addNewAppliancePrompt()" class="py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1">
                            <span>➕</span> Add New Appliance
                        </button>
                        <button onclick="deleteActiveAppliance()" class="py-2 bg-red-950/80 hover:bg-red-900 text-red-400 border border-red-800/80 rounded-lg text-xs font-bold transition">
                            🗑️ Delete Appliance
                        </button>
                    </div>
                </div>

                <!-- CONFIGURED APPLIANCES OVERVIEW -->
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl max-h-[340px] flex flex-col">
                    <div class="flex justify-between items-center mb-2 pb-2 border-b border-slate-800 text-xs">
                        <span class="font-bold text-slate-400 uppercase">Configured Appliances (<span id="appliance-count">0</span>)</span>
                        <button onclick="clearAllAppliances()" class="text-red-400 hover:text-red-300">Clear All</button>
                    </div>
                    
                    <div id="appliances-list" class="space-y-2 overflow-y-auto flex-1 pr-1 text-xs">
                        <!-- Populated by JS -->
                    </div>

                    <button onclick="saveAllToBackend()" class="w-full mt-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-bold transition shadow-lg shadow-emerald-900/30 flex items-center justify-center gap-1.5">
                        <span>💾</span> Save 3D Calibration Permanently
                    </button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const canvas = document.getElementById('calib-canvas');
        const ctx = canvas.getContext('2d');
        const img = new Image();

        // High-precision classroom perspective presets
        const PRESETS = {
            "desks_aligned": {
                name: "Classroom Desks (Auto-Aligned to Benches)",
                corners: [
                    { x: 340, y: 140, label: "P1: Back-Left Desk" },
                    { x: 1780, y: 190, label: "P2: Back-Right Desk" },
                    { x: 1880, y: 990, label: "P3: Front-Right Desk" },
                    { x: 220, y: 990, label: "P4: Front-Left Desk" }
                ],
                bend_pins: {
                    top: { x: 1060, y: 165 },
                    right: { x: 1830, y: 590 },
                    bottom: { x: 1050, y: 990 },
                    left: { x: 280, y: 565 }
                },
                rows: 5,
                cols: 4
            },
            "desks_extended": {
                name: "Extended Beyond Frame (Bottom & Sides)",
                corners: [
                    { x: 220, y: 140, label: "P1: Back Window Desk" },
                    { x: 1840, y: 160, label: "P2: Back Right Desk" },
                    { x: 1980, y: 1160, label: "P3: Front Right (Extended)" },
                    { x: -30, y: 1160, label: "P4: Front Left (Extended)" }
                ],
                bend_pins: {
                    top: { x: 1030, y: 150 },
                    right: { x: 1910, y: 660 },
                    bottom: { x: 975, y: 1160 },
                    left: { x: 95, y: 650 }
                },
                rows: 5,
                cols: 4
            },
            "full_room": {
                name: "Full Room (Wall to Wall)",
                corners: [
                    { x: 80, y: 120, label: "P1: Far Window Wall" },
                    { x: 1880, y: 130, label: "P2: Far Blackboard Wall" },
                    { x: 1910, y: 1070, label: "P3: Near Door Wall" },
                    { x: 20, y: 1070, label: "P4: Near Window Wall" }
                ],
                rows: 5,
                cols: 4
            }
        };

        function normalizeCorner(c, fallbackLabel) {
            if (Array.isArray(c) && c.length >= 2) {
                return { x: Math.round(Number(c[0])), y: Math.round(Number(c[1])), label: fallbackLabel || "Corner Pin" };
            }
            if (c && typeof c === 'object') {
                return {
                    x: Math.round(Number(c.x !== undefined ? c.x : (c[0] || 0))),
                    y: Math.round(Number(c.y !== undefined ? c.y : (c[1] || 0))),
                    label: c.label || fallbackLabel || "Corner Pin"
                };
            }
            return { x: 0, y: 0, label: fallbackLabel || "Corner Pin" };
        }

        function getStraightMidpoints(corners) {
            const c = corners.map(pt => normalizeCorner(pt));
            return {
                top: { x: Math.round((c[0].x + c[1].x) / 2), y: Math.round((c[0].y + c[1].y) / 2) },
                right: { x: Math.round((c[1].x + c[2].x) / 2), y: Math.round((c[1].y + c[2].y) / 2) },
                bottom: { x: Math.round((c[3].x + c[2].x) / 2), y: Math.round((c[3].y + c[2].y) / 2) },
                left: { x: Math.round((c[0].x + c[3].x) / 2), y: Math.round((c[0].y + c[3].y) / 2) }
            };
        }

        let gridConfig = {
            corners: JSON.parse(JSON.stringify(PRESETS["desks_aligned"].corners)),
            bend_pins: JSON.parse(JSON.stringify(PRESETS["desks_aligned"].bend_pins)),
            rows: 5,
            cols: 4
        };

        function ensureBendPins() {
            if (!gridConfig.bend_pins) gridConfig.bend_pins = {};
            const mids = getStraightMidpoints(gridConfig.corners);
            ['top', 'right', 'bottom', 'left'].forEach(edge => {
                const cur = gridConfig.bend_pins[edge];
                if (cur && Array.isArray(cur) && cur.length >= 2) {
                    gridConfig.bend_pins[edge] = { x: Math.round(Number(cur[0])), y: Math.round(Number(cur[1])) };
                } else if (cur && typeof cur === 'object' && cur.x !== undefined && cur.y !== undefined) {
                    gridConfig.bend_pins[edge] = { x: Math.round(Number(cur.x)), y: Math.round(Number(cur.y)) };
                } else {
                    gridConfig.bend_pins[edge] = { x: mids[edge].x, y: mids[edge].y };
                }
            });
        }

        let appliances = {};
        let activeKey = null;
        let showCornerPins = true;
        let showBendPins = true;
        let draggingPinIdx = -1;
        let draggedPinType = null;
        let draggedPinKey = null;
        let dragStartCornerPos = null;
        let hoveredCell = null;
        let ceilingMarkerMode = false;
        let gridOpacity = 0.12; // Transparent overlay (12% default)

        // Subtle, transparent color palette for appliances
        const COLOR_PALETTE = [
            { border: '#38bdf8', fillRgb: '56, 189, 248', badge: 'bg-sky-500 text-white' },
            { border: '#f59e0b', fillRgb: '245, 158, 11', badge: 'bg-amber-500 text-white' },
            { border: '#10b981', fillRgb: '16, 185, 129', badge: 'bg-emerald-500 text-white' },
            { border: '#a855f7', fillRgb: '168, 85, 247', badge: 'bg-purple-500 text-white' },
            { border: '#ec4899', fillRgb: '236, 72, 153', badge: 'bg-pink-500 text-white' },
            { border: '#06b6d4', fillRgb: '6, 182, 212', badge: 'bg-cyan-500 text-white' }
        ];

        function getApplianceColor(index) {
            return COLOR_PALETTE[index % COLOR_PALETTE.length];
        }

        function setGridOpacity(val) {
            gridOpacity = Math.max(0.04, Math.min(0.40, parseFloat(val) / 100));
            const badge = document.getElementById('grid-opacity-badge');
            if (badge) badge.innerText = `${Math.round(gridOpacity * 100)}%`;
            redrawCanvas();
        }

        // =====================================================================
        // 📐 PROJECTIVE HOMOGRAPHY (3D Perspective Interpolator)
        // =====================================================================
        function getPerspectiveTransform(p0, p1, p2, p3) {
            const x0 = Number(p0.x), y0 = Number(p0.y);
            const x1 = Number(p1.x), y1 = Number(p1.y);
            const x2 = Number(p2.x), y2 = Number(p2.y);
            const x3 = Number(p3.x), y3 = Number(p3.y);

            const dx1 = x1 - x2;
            const dx2 = x3 - x2;
            const sx = x0 - x1 + x2 - x3;
            const dy1 = y1 - y2;
            const dy2 = y3 - y2;
            const sy = y0 - y1 + y2 - y3;

            const det = dx1 * dy2 - dy1 * dx2;
            if (Math.abs(det) < 1e-7) return null;

            const g = (sx * dy2 - sy * dx2) / det;
            const h = (dx1 * sy - dy1 * sx) / det;
            const a = x1 - x0 + g * x1;
            const b = x3 - x0 + h * x3;
            const c = x0;
            const d = y1 - y0 + g * y1;
            const e = y3 - y0 + h * y3;
            const f = y0;

            return function(u, v) {
                const denom = g * u + h * v + 1.0;
                return {
                    x: Math.round((a * u + b * v + c) / denom),
                    y: Math.round((d * u + e * v + f) / denom)
                };
            };
        }

        // =====================================================================
        // ✂️ SUTHERLAND-HODGMAN POLYGON CLIPPER (Auto-clips plane to frame)
        // =====================================================================
        function clipPolygonToRect(poly, xmin, ymin, xmax, ymax) {
            if (!poly || poly.length < 3) return [];

            function clipEdge(pts, insideFn, intersectFn) {
                const res = [];
                const n = pts.length;
                if (n === 0) return res;
                for (let i = 0; i < n; i++) {
                    const cur = pts[i];
                    const prev = pts[(i + n - 1) % n];
                    const curIn = insideFn(cur);
                    const prevIn = insideFn(prev);

                    if (curIn) {
                        if (!prevIn) {
                            res.push(intersectFn(prev, cur));
                        }
                        res.push({ x: Math.round(cur.x), y: Math.round(cur.y) });
                    } else if (prevIn) {
                        res.push(intersectFn(prev, cur));
                    }
                }
                return res;
            }

            let out = poly.map(p => ({ x: Number(p.x !== undefined ? p.x : p[0]), y: Number(p.y !== undefined ? p.y : p[1]) }));

            // 1. Left (x >= xmin)
            out = clipEdge(out, (p) => p.x >= xmin, (p1, p2) => {
                const dx = (p2.x - p1.x) || 1e-6;
                const t = (xmin - p1.x) / dx;
                return { x: xmin, y: Math.round(p1.y + t * (p2.y - p1.y)) };
            });

            // 2. Right (x <= xmax)
            out = clipEdge(out, (p) => p.x <= xmax, (p1, p2) => {
                const dx = (p2.x - p1.x) || 1e-6;
                const t = (xmax - p1.x) / dx;
                return { x: xmax, y: Math.round(p1.y + t * (p2.y - p1.y)) };
            });

            // 3. Top (y >= ymin)
            out = clipEdge(out, (p) => p.y >= ymin, (p1, p2) => {
                const dy = (p2.y - p1.y) || 1e-6;
                const t = (ymin - p1.y) / dy;
                return { x: Math.round(p1.x + t * (p2.x - p1.x)), y: ymin };
            });

            // 4. Bottom (y <= ymax)
            out = clipEdge(out, (p) => p.y <= ymax, (p1, p2) => {
                const dy = (p2.y - p1.y) || 1e-6;
                const t = (ymax - p1.y) / dy;
                return { x: Math.round(p1.x + t * (p2.x - p1.x)), y: ymax };
            });

            return out;
        }

        function computeGridCells() {
            ensureBendPins();
            const c = gridConfig.corners.map((pt, i) => normalizeCorner(pt, `P${i+1}`));
            const transform = getPerspectiveTransform(c[0], c[1], c[2], c[3]);
            if (!transform) return [];

            const mids = getStraightMidpoints(c);
            const dTopX = (gridConfig.bend_pins.top ? gridConfig.bend_pins.top.x : mids.top.x) - mids.top.x;
            const dTopY = (gridConfig.bend_pins.top ? gridConfig.bend_pins.top.y : mids.top.y) - mids.top.y;

            const dRightX = (gridConfig.bend_pins.right ? gridConfig.bend_pins.right.x : mids.right.x) - mids.right.x;
            const dRightY = (gridConfig.bend_pins.right ? gridConfig.bend_pins.right.y : mids.right.y) - mids.right.y;

            const dBotX = (gridConfig.bend_pins.bottom ? gridConfig.bend_pins.bottom.x : mids.bottom.x) - mids.bottom.x;
            const dBotY = (gridConfig.bend_pins.bottom ? gridConfig.bend_pins.bottom.y : mids.bottom.y) - mids.bottom.y;

            const dLeftX = (gridConfig.bend_pins.left ? gridConfig.bend_pins.left.x : mids.left.x) - mids.left.x;
            const dLeftY = (gridConfig.bend_pins.left ? gridConfig.bend_pins.left.y : mids.left.y) - mids.left.y;

            const hasBends = (dTopX !== 0 || dTopY !== 0 || dRightX !== 0 || dRightY !== 0 ||
                              dBotX !== 0 || dBotY !== 0 || dLeftX !== 0 || dLeftY !== 0);

            function evalPoint(u, v) {
                const p = transform(u, v);
                if (!hasBends) return p;

                // Coons Patch / Quadratic Bezier displacement along 4 edges
                const wTop = 4.0 * u * (1.0 - u) * (1.0 - v);
                const wBot = 4.0 * u * (1.0 - u) * v;
                const wLeft = 4.0 * (1.0 - u) * v * (1.0 - v);
                const wRight = 4.0 * u * v * (1.0 - v);

                const dx = wTop * dTopX + wBot * dBotX + wLeft * dLeftX + wRight * dRightX;
                const dy = wTop * dTopY + wBot * dBotY + wLeft * dLeftY + wRight * dRightY;

                return {
                    x: Math.round(p.x + dx),
                    y: Math.round(p.y + dy)
                };
            }

            const cells = [];
            const rows = gridConfig.rows;
            const cols = gridConfig.cols;
            const imgW = img.naturalWidth || 1920;
            const imgH = img.naturalHeight || 1080;

            for (let r = 0; r < rows; r++) {
                for (let col = 0; col < cols; col++) {
                    const u0 = col / cols, u1 = (col + 1) / cols;
                    const v0 = r / rows, v1 = (r + 1) / rows;

                    const pTL = evalPoint(u0, v0);
                    const pTR = evalPoint(u1, v0);
                    const pBR = evalPoint(u1, v1);
                    const pBL = evalPoint(u0, v1);

                    const unclippedPoly = [pTL, pTR, pBR, pBL];
                    // Automatically cut off / clip polygon precisely at camera frame boundaries!
                    const clippedPoly = clipPolygonToRect(unclippedPoly, 0, 0, imgW, imgH);

                    let cx = 0, cy = 0;
                    if (clippedPoly.length >= 3) {
                        clippedPoly.forEach(pt => { cx += pt.x; cy += pt.y; });
                        cx = Math.round(cx / clippedPoly.length);
                        cy = Math.round(cy / clippedPoly.length);
                    } else {
                        cx = Math.round((pTL.x + pTR.x + pBR.x + pBL.x) / 4);
                        cy = Math.round((pTL.y + pTR.y + pBR.y + pBL.y) / 4);
                    }

                    const id = `R${r+1}-C${col+1}`;

                    cells.push({
                        id: id,
                        row: r,
                        col: col,
                        unclippedPoly: unclippedPoly,
                        poly: clippedPoly.length >= 3 ? clippedPoly : unclippedPoly,
                        hasVisiblePortion: clippedPoly.length >= 3,
                        center: { x: cx, y: cy }
                    });
                }
            }
            return cells;
        }

        function pointInPoly(pt, poly) {
            let inside = false;
            for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                const xi = poly[i].x, yi = poly[i].y;
                const xj = poly[j].x, yj = poly[j].y;
                const intersect = ((yi > pt.y) !== (yj > pt.y)) &&
                    (pt.x < (xj - xi) * (pt.y - yi) / (yj - yi) + xi);
                if (intersect) inside = !inside;
            }
            return inside;
        }

        // =====================================================================
        // 🎨 CANVAS RENDERING & DYNAMIC VIDEO RESIZING
        // =====================================================================
        function refreshFrame() {
            img.src = '/video_feed?' + new Date().getTime();
        }

        const BASE_PAD_X = 140;
        const BASE_PAD_Y = 120;

        // Video transform states: scale, pan, dragging
        let videoScaleX = 1.0;
        let videoScaleY = 1.0;
        let videoPanX = 0;
        let videoPanY = 0;
        let isPanning = false;
        let panStartX = 0;
        let panStartY = 0;
        let panInitialX = 0;
        let panInitialY = 0;
        let mouseMovedDistance = 0;
        let mouseDownClientPos = { x: 0, y: 0 };

        function getVideoTransform() {
            const imgW = img.naturalWidth || 1920;
            const imgH = img.naturalHeight || 1080;
            const drawnW = Math.round(imgW * videoScaleX);
            const drawnH = Math.round(imgH * videoScaleY);
            const originX = Math.round((canvas.width - drawnW) / 2) + videoPanX;
            const originY = Math.round((canvas.height - drawnH) / 2) + videoPanY;
            return {
                imgW,
                imgH,
                drawnW,
                drawnH,
                originX,
                originY,
                scaleX: videoScaleX,
                scaleY: videoScaleY
            };
        }

        function toCanvas(pt, vt) {
            return {
                x: vt.originX + pt.x * vt.scaleX,
                y: vt.originY + pt.y * vt.scaleY
            };
        }

        function toNative(canvasPt, vt) {
            return {
                x: Math.round((canvasPt.x - vt.originX) / vt.scaleX),
                y: Math.round((canvasPt.y - vt.originY) / vt.scaleY)
            };
        }

        function syncCanvasDimensions() {
            const imgW = img.naturalWidth || 1920;
            const imgH = img.naturalHeight || 1080;
            const drawnW = Math.round(imgW * videoScaleX);
            const drawnH = Math.round(imgH * videoScaleY);
            const targetW = Math.max(2200, drawnW + 2 * BASE_PAD_X);
            const targetH = Math.max(1320, drawnH + 2 * BASE_PAD_Y);
            if (canvas.width !== targetW || canvas.height !== targetH) {
                canvas.width = targetW;
                canvas.height = targetH;
            }
        }

        img.onload = () => {
            syncCanvasDimensions();
            redrawCanvas();
        };

        function setVideoScale(val) {
            val = Math.max(0.4, Math.min(2.5, val));
            videoScaleX = val;
            videoScaleY = val;
            updateVideoScaleUI();
            syncCanvasDimensions();
            redrawCanvas();
        }

        function adjustVideoScale(delta) {
            setVideoScale(videoScaleX + delta);
        }

        function onVideoScaleSlider(val) {
            setVideoScale(parseFloat(val) / 100);
        }

        function nudgeVideoStretch(axis, delta) {
            if (axis === 'width') {
                videoScaleX = Math.max(0.4, Math.min(2.5, videoScaleX + delta));
            } else {
                videoScaleY = Math.max(0.4, Math.min(2.5, videoScaleY + delta));
            }
            updateVideoScaleUI();
            syncCanvasDimensions();
            redrawCanvas();
        }

        function panVideo(dx, dy) {
            videoPanX += dx;
            videoPanY += dy;
            redrawCanvas();
        }

        function resetVideoTransform() {
            videoScaleX = 1.0;
            videoScaleY = 1.0;
            videoPanX = 0;
            videoPanY = 0;
            updateVideoScaleUI();
            syncCanvasDimensions();
            redrawCanvas();
        }

        function updateVideoScaleUI() {
            const pct = Math.round(videoScaleX * 100);
            const slider = document.getElementById('video-scale-slider');
            if (slider) slider.value = pct;
            const badge = document.getElementById('video-scale-badge');
            if (badge) {
                const vt = getVideoTransform();
                badge.innerText = `${pct}% (${vt.drawnW}×${vt.drawnH})`;
            }
        }

        function redrawCanvas() {
            const vt = getVideoTransform();

            // Fill canvas with extended background
            ctx.fillStyle = '#060a12';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            // Subtle pattern in padding margins outside the drawn video
            ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
            for (let x = 0; x < canvas.width; x += 36) {
                for (let y = 0; y < canvas.height; y += 36) {
                    if (x < vt.originX || x > vt.originX + vt.drawnW || y < vt.originY || y > vt.originY + vt.drawnH) {
                        ctx.fillRect(x + 16, y + 16, 2, 2);
                    }
                }
            }

            // Draw video frame with dynamic size
            ctx.drawImage(img, vt.originX, vt.originY, vt.drawnW, vt.drawnH);

            // Draw frame boundary outline (Cyan)
            ctx.strokeStyle = '#0284c7';
            ctx.lineWidth = 2.5;
            ctx.strokeRect(vt.originX, vt.originY, vt.drawnW, vt.drawnH);

            // Badge text on frame boundary
            ctx.fillStyle = '#38bdf8';
            ctx.font = 'bold 11px sans-serif';
            ctx.fillText(`📷 Camera Video Frame (${vt.drawnW} × ${vt.drawnH}) — Scale: ${Math.round(vt.scaleX * 100)}% | Auto-Clipped at Edges`, vt.originX + 12, vt.originY - 8);

            const cells = computeGridCells();

            // 1. Draw Grid Cells & Appliance Assignment Fills
            cells.forEach(cell => {
                const isHovered = (hoveredCell && hoveredCell.id === cell.id);
                
                let ownerKey = null;
                let ownerApp = null;
                let ownerIdx = 0;
                let idx = 0;
                for (const [k, app] of Object.entries(appliances)) {
                    if (app.assigned_cells && app.assigned_cells.includes(cell.id)) {
                        ownerKey = k;
                        ownerApp = app;
                        ownerIdx = idx;
                        break;
                    }
                    idx++;
                }

                // If cell extends outside frame, draw faint dashed outline in outer margin
                const isPartiallyOutside = cell.unclippedPoly.some(p => p.x < 0 || p.x > vt.imgW || p.y < 0 || p.y > vt.imgH);
                if (isPartiallyOutside) {
                    ctx.beginPath();
                    cell.unclippedPoly.forEach((p, i) => {
                        const cp = toCanvas(p, vt);
                        if (i === 0) ctx.moveTo(cp.x, cp.y);
                        else ctx.lineTo(cp.x, cp.y);
                    });
                    ctx.closePath();
                    ctx.strokeStyle = 'rgba(56, 189, 248, 0.2)';
                    ctx.setLineDash([4, 4]);
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    ctx.setLineDash([]);
                }

                // Draw CLIPPED cell polygon inside the camera frame
                if (cell.hasVisiblePortion) {
                    ctx.beginPath();
                    cell.poly.forEach((p, i) => {
                        const cp = toCanvas(p, vt);
                        if (i === 0) ctx.moveTo(cp.x, cp.y);
                        else ctx.lineTo(cp.x, cp.y);
                    });
                    ctx.closePath();

                    if (ownerApp) {
                        const color = getApplianceColor(ownerIdx);
                        const alpha = (ownerKey === activeKey) ? gridOpacity : (gridOpacity * 0.45);
                        ctx.fillStyle = `rgba(${color.fillRgb}, ${alpha})`;
                        ctx.fill();
                        ctx.strokeStyle = color.border;
                        ctx.lineWidth = (ownerKey === activeKey) ? 1.5 : 1.0;
                        ctx.stroke();
                    } else if (isHovered) {
                        ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
                        ctx.fill();
                        ctx.strokeStyle = '#ffffff';
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                    } else {
                        ctx.strokeStyle = 'rgba(56, 189, 248, 0.25)';
                        ctx.lineWidth = 0.8;
                        ctx.stroke();
                    }

                    // Cell Label badge inside visible frame
                    ctx.font = 'bold 11px sans-serif';
                    const cCenter = toCanvas(cell.center, vt);
                    const lx = cCenter.x;
                    const ly = cCenter.y;
                    if (ownerApp) {
                        ctx.fillStyle = '#ffffff';
                        const icon = (ownerApp.type === 'fan' ? '🌀' : '💡');
                        ctx.fillText(`${cell.id} ${icon}`, lx - 22, ly + 4);
                    } else {
                        ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
                        ctx.fillText(cell.id, lx - 16, ly + 4);
                    }
                }
            });

            // 2. Draw Ceiling Markers & Connecting 3D Beams ONLY IF ROI IS SET AND NON-EMPTY
            let appIndex = 0;
            for (const [key, app] of Object.entries(appliances)) {
                const color = getApplianceColor(appIndex);
                if (app.roi && Array.isArray(app.roi) && app.roi.length === 4 && (app.roi[2] > 0 && app.roi[3] > 0)) {
                    const [x, y, w, h] = app.roi;
                    const isSelected = (key === activeKey);

                    const mx = vt.originX + x * vt.scaleX;
                    const my = vt.originY + y * vt.scaleY;
                    const mw = w * vt.scaleX;
                    const mh = h * vt.scaleY;

                    ctx.strokeStyle = isSelected ? '#22c55e' : color.border;
                    ctx.lineWidth = isSelected ? 3 : 2;
                    ctx.strokeRect(mx, my, mw, mh);

                    ctx.fillStyle = isSelected ? '#22c55e' : color.border;
                    ctx.font = 'bold 12px sans-serif';
                    ctx.fillText(`${app.type === 'fan' ? '🌀' : '💡'} ${app.name} (Ceiling)`, mx + 4, (my - 6 > 15 ? my - 6 : my + 16));

                    if (app.zone_centroid) {
                        ctx.strokeStyle = isSelected ? 'rgba(34, 197, 94, 0.7)' : 'rgba(255, 255, 255, 0.35)';
                        ctx.lineWidth = 1.5;
                        ctx.setLineDash([5, 5]);
                        ctx.beginPath();
                        ctx.moveTo(mx + Math.floor(mw / 2), my + Math.floor(mh / 2));
                        const zc = toCanvas({ x: app.zone_centroid[0], y: app.zone_centroid[1] }, vt);
                        ctx.lineTo(zc.x, zc.y);
                        ctx.stroke();
                        ctx.setLineDash([]);
                    }
                }
                appIndex++;
            }

            // 3. Draw Perspective Boundary Pins (4 Corners + 4 Bending Diamond Pins)
            if (showCornerPins) {
                ensureBendPins();
                const cornerLabels = [
                    "P1: Back-Left",
                    "P2: Back-Right",
                    "P3: Front-Right",
                    "P4: Front-Left"
                ];

                // A. Draw 4 Corner Circular Pins
                gridConfig.corners.forEach((rawCorner, idx) => {
                    const corner = normalizeCorner(rawCorner, cornerLabels[idx]);
                    const isDragging = (draggingPinIdx === idx && draggedPinType === 'corner');
                    const isOutside = (corner.x < 0 || corner.x > vt.imgW || corner.y < 0 || corner.y > vt.imgH);

                    const cp = toCanvas(corner, vt);
                    const cx = cp.x;
                    const cy = cp.y;

                    // Connector line from pin to boundary if outside
                    if (isOutside) {
                        const clampedNative = {
                            x: Math.max(0, Math.min(vt.imgW, corner.x)),
                            y: Math.max(0, Math.min(vt.imgH, corner.y))
                        };
                        const clampedPt = toCanvas(clampedNative, vt);
                        ctx.beginPath();
                        ctx.moveTo(cx, cy);
                        ctx.lineTo(clampedPt.x, clampedPt.y);
                        ctx.strokeStyle = '#f43f5e';
                        ctx.lineWidth = 1.5;
                        ctx.setLineDash([3, 3]);
                        ctx.stroke();
                        ctx.setLineDash([]);
                    }

                    // Outer circular glowing ring
                    ctx.beginPath();
                    ctx.arc(cx, cy, isDragging ? 13 : 9, 0, Math.PI * 2);
                    ctx.fillStyle = isDragging ? '#f43f5e' : (isOutside ? '#fb923c' : '#f59e0b');
                    ctx.fill();
                    ctx.lineWidth = 2.5;
                    ctx.strokeStyle = '#ffffff';
                    ctx.stroke();

                    // Pin Label Badge
                    let labelText = `${cornerLabels[idx]} (${corner.x}, ${corner.y})`;
                    if (isOutside) labelText += " [Extended]";
                    ctx.font = 'bold 10px sans-serif';
                    const textWidth = ctx.measureText(labelText).width + 12;

                    ctx.fillStyle = '#0f172a';
                    ctx.fillRect(cx + 12, cy - 10, textWidth, 18);
                    ctx.strokeStyle = isOutside ? '#fb923c' : '#f59e0b';
                    ctx.lineWidth = 1;
                    ctx.strokeRect(cx + 12, cy - 10, textWidth, 18);
                    ctx.fillStyle = isOutside ? '#fed7aa' : '#fef08a';
                    ctx.fillText(labelText, cx + 16, cy + 3);
                });

                // B. Draw 4 Bending Diamond Pins (top, right, bottom, left)
                if (showBendPins) {
                    const mids = getStraightMidpoints(gridConfig.corners);
                    const bendList = [
                        { key: 'top', idx: 4, name: 'B_top', label: 'Top Bend', pin: gridConfig.bend_pins.top, mid: mids.top },
                        { key: 'right', idx: 5, name: 'B_right', label: 'Right Bend', pin: gridConfig.bend_pins.right, mid: mids.right },
                        { key: 'bottom', idx: 6, name: 'B_bot', label: 'Bottom Bend', pin: gridConfig.bend_pins.bottom, mid: mids.bottom },
                        { key: 'left', idx: 7, name: 'B_left', label: 'Left Bend', pin: gridConfig.bend_pins.left, mid: mids.left }
                    ];

                    bendList.forEach(b => {
                        const isDragging = (draggingPinIdx === b.idx && draggedPinType === 'bend');
                        const bp = toCanvas(b.pin, vt);
                        const mp = toCanvas(b.mid, vt);

                        // Faint dashed line from straight midpoint to bend pin if bent
                        const distFromMid = Math.hypot(b.pin.x - b.mid.x, b.pin.y - b.mid.y);
                        if (distFromMid > 4) {
                            ctx.beginPath();
                            ctx.moveTo(mp.x, mp.y);
                            ctx.lineTo(bp.x, bp.y);
                            ctx.strokeStyle = '#c084fc';
                            ctx.lineWidth = 1.5;
                            ctx.setLineDash([3, 3]);
                            ctx.stroke();
                            ctx.setLineDash([]);
                        }

                        // Diamond Pin shape
                        const r = isDragging ? 13 : 9;
                        ctx.beginPath();
                        ctx.moveTo(bp.x, bp.y - r);
                        ctx.lineTo(bp.x + r, bp.y);
                        ctx.lineTo(bp.x, bp.y + r);
                        ctx.lineTo(bp.x - r, bp.y);
                        ctx.closePath();
                        ctx.fillStyle = isDragging ? '#f43f5e' : (distFromMid > 4 ? '#a855f7' : '#06b6d4');
                        ctx.fill();
                        ctx.strokeStyle = '#ffffff';
                        ctx.lineWidth = 2.5;
                        ctx.stroke();

                        // Label
                        ctx.font = 'bold 10px sans-serif';
                        const text = `${b.name} (${b.pin.x}, ${b.pin.y})`;
                        const tw = ctx.measureText(text).width + 10;
                        ctx.fillStyle = '#0f172a';
                        ctx.fillRect(bp.x + 12, bp.y - 10, tw, 18);
                        ctx.strokeStyle = '#a855f7';
                        ctx.lineWidth = 1;
                        ctx.strokeRect(bp.x + 12, bp.y - 10, tw, 18);
                        ctx.fillStyle = '#e9d5ff';
                        ctx.fillText(text, bp.x + 16, bp.y + 3);
                    });
                }
            }
        }

        // =====================================================================
        // 🎯 HIGH-PRECISION SCREEN-SPACE PIN HIT DETECTION & POINTER INTERACTIONS
        // =====================================================================
        function getScreenCoordinates(nativePt, vt) {
            const cp = toCanvas(nativePt, vt);
            const rect = canvas.getBoundingClientRect();
            return {
                x: rect.left + (cp.x / canvas.width) * rect.width,
                y: rect.top + (cp.y / canvas.height) * rect.height
            };
        }

        function getPinHit(clientX, clientY) {
            if (!showCornerPins || ceilingMarkerMode) return null;
            const vt = getVideoTransform();
            const HIT_RADIUS = 34; // Generous 34 CSS pixels for effortless grabbing on desktop & mobile

            let bestHit = null;
            let minDistance = Infinity;

            // 1. Check 4 Corner Pins
            gridConfig.corners.forEach((rawCorner, idx) => {
                const corner = normalizeCorner(rawCorner);
                const screenPt = getScreenCoordinates(corner, vt);
                const dist = Math.hypot(clientX - screenPt.x, clientY - screenPt.y);
                if (dist <= HIT_RADIUS && dist < minDistance) {
                    minDistance = dist;
                    bestHit = {
                        type: 'corner',
                        idx: idx,
                        key: null,
                        pin: corner,
                        dist: dist
                    };
                }
            });

            // 2. Check 4 Bending Diamond Pins
            if (showBendPins) {
                ensureBendPins();
                const bendKeys = [
                    { idx: 4, key: 'top' },
                    { idx: 5, key: 'right' },
                    { idx: 6, key: 'bottom' },
                    { idx: 7, key: 'left' }
                ];
                bendKeys.forEach(b => {
                    const pin = gridConfig.bend_pins[b.key];
                    if (!pin) return;
                    const screenPt = getScreenCoordinates(pin, vt);
                    const dist = Math.hypot(clientX - screenPt.x, clientY - screenPt.y);
                    if (dist <= HIT_RADIUS && dist < minDistance) {
                        minDistance = dist;
                        bestHit = {
                            type: 'bend',
                            idx: b.idx,
                            key: b.key,
                            pin: pin,
                            dist: dist
                        };
                    }
                });
            }

            return bestHit;
        }

        function getNativeFromClient(clientX, clientY) {
            const rect = canvas.getBoundingClientRect();
            const scaleFactorX = canvas.width / rect.width;
            const scaleFactorY = canvas.height / rect.height;
            const canvasPxX = (clientX - rect.left) * scaleFactorX;
            const canvasPxY = (clientY - rect.top) * scaleFactorY;
            const vt = getVideoTransform();
            return {
                native: toNative({ x: canvasPxX, y: canvasPxY }, vt),
                canvasX: canvasPxX,
                canvasY: canvasPxY
            };
        }

        let didJustDragPin = false;

        function handlePointerDown(clientX, clientY, button) {
            mouseDownClientPos = { x: clientX, y: clientY };
            mouseMovedDistance = 0;

            // Right-click or middle-click: Pan canvas
            if (button === 1 || button === 2) {
                isPanning = true;
                panStartX = clientX;
                panStartY = clientY;
                panInitialX = videoPanX;
                panInitialY = videoPanY;
                canvas.style.cursor = 'grabbing';
                return;
            }

            // Left-click or touch: Test pin hit
            const hit = getPinHit(clientX, clientY);
            if (hit) {
                draggingPinIdx = hit.idx;
                draggedPinType = hit.type;
                draggedPinKey = hit.key;
                dragStartCornerPos = { x: hit.pin.x, y: hit.pin.y };
                canvas.style.cursor = 'grabbing';
                redrawCanvas();
                return;
            }
        }

        function handlePointerMove(clientX, clientY) {
            mouseMovedDistance += Math.hypot(clientX - mouseDownClientPos.x, clientY - mouseDownClientPos.y);

            // Pan canvas
            if (isPanning) {
                const dx = clientX - panStartX;
                const dy = clientY - panStartY;
                videoPanX = panInitialX + dx;
                videoPanY = panInitialY + dy;
                redrawCanvas();
                return;
            }

            const { native: pt } = getNativeFromClient(clientX, clientY);

            // Drag pin
            if (draggingPinIdx >= 0) {
                if (draggedPinType === 'corner') {
                    const dx = pt.x - dragStartCornerPos.x;
                    const dy = pt.y - dragStartCornerPos.y;
                    dragStartCornerPos = { x: pt.x, y: pt.y };

                    ensureBendPins();
                    if (draggingPinIdx === 0) { // Top-Left
                        gridConfig.bend_pins.top.x += Math.round(dx / 2);
                        gridConfig.bend_pins.top.y += Math.round(dy / 2);
                        gridConfig.bend_pins.left.x += Math.round(dx / 2);
                        gridConfig.bend_pins.left.y += Math.round(dy / 2);
                    } else if (draggingPinIdx === 1) { // Top-Right
                        gridConfig.bend_pins.top.x += Math.round(dx / 2);
                        gridConfig.bend_pins.top.y += Math.round(dy / 2);
                        gridConfig.bend_pins.right.x += Math.round(dx / 2);
                        gridConfig.bend_pins.right.y += Math.round(dy / 2);
                    } else if (draggingPinIdx === 2) { // Bottom-Right
                        gridConfig.bend_pins.bottom.x += Math.round(dx / 2);
                        gridConfig.bend_pins.bottom.y += Math.round(dy / 2);
                        gridConfig.bend_pins.right.x += Math.round(dx / 2);
                        gridConfig.bend_pins.right.y += Math.round(dy / 2);
                    } else if (draggingPinIdx === 3) { // Bottom-Left
                        gridConfig.bend_pins.bottom.x += Math.round(dx / 2);
                        gridConfig.bend_pins.bottom.y += Math.round(dy / 2);
                        gridConfig.bend_pins.left.x += Math.round(dx / 2);
                        gridConfig.bend_pins.left.y += Math.round(dy / 2);
                    }

                    gridConfig.corners[draggingPinIdx] = {
                        x: pt.x,
                        y: pt.y,
                        label: gridConfig.corners[draggingPinIdx].label || `P${draggingPinIdx+1}`
                    };
                } else if (draggedPinType === 'bend') {
                    ensureBendPins();
                    gridConfig.bend_pins[draggedPinKey] = { x: pt.x, y: pt.y };
                }

                recalculateAllAppliancePolygons();
                redrawCanvas();
                return;
            }

            // Hover indicator cursor & cell hover
            const hit = getPinHit(clientX, clientY);
            if (hit) {
                canvas.style.cursor = 'grab';
            } else {
                canvas.style.cursor = 'crosshair';
            }

            const cells = computeGridCells();
            let found = null;
            for (const cell of cells) {
                if (pointInPoly(pt, cell.poly) || pointInPoly(pt, cell.unclippedPoly)) {
                    found = cell;
                    break;
                }
            }
            if (hoveredCell !== found) {
                hoveredCell = found;
                redrawCanvas();
            }
        }

        function handlePointerUp() {
            if (isPanning) {
                isPanning = false;
                canvas.style.cursor = 'crosshair';
            }
            if (draggingPinIdx >= 0) {
                draggingPinIdx = -1;
                draggedPinType = null;
                draggedPinKey = null;
                canvas.style.cursor = 'crosshair';
                recalculateAllAppliancePolygons();
                redrawCanvas();

                didJustDragPin = true;
                setTimeout(() => { didJustDragPin = false; }, 250);

                // 🔥 AUTO-SAVE IMMEDIATELY SO CALIBRATION PERSISTS!
                saveAllToBackend(false);
            }
        }

        // --- BIND MOUSE & TOUCH LISTENERS ---
        canvas.addEventListener('mousedown', (e) => {
            handlePointerDown(e.clientX, e.clientY, e.button);
        });
        window.addEventListener('mousemove', (e) => {
            handlePointerMove(e.clientX, e.clientY);
        });
        window.addEventListener('mouseup', () => {
            handlePointerUp();
        });

        // Mobile touch drag support
        canvas.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                const t = e.touches[0];
                handlePointerDown(t.clientX, t.clientY, 0);
                if (draggingPinIdx >= 0) {
                    e.preventDefault();
                }
            }
        }, { passive: false });

        window.addEventListener('touchmove', (e) => {
            if (draggingPinIdx >= 0 && e.touches.length === 1) {
                const t = e.touches[0];
                handlePointerMove(t.clientX, t.clientY);
                e.preventDefault();
            }
        }, { passive: false });

        window.addEventListener('touchend', () => {
            if (draggingPinIdx >= 0) {
                handlePointerUp();
            }
        });
        window.addEventListener('touchcancel', () => {
            if (draggingPinIdx >= 0) {
                handlePointerUp();
            }
        });

        canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
        });

        canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY < 0 ? 0.05 : -0.05;
            adjustVideoScale(delta);
        }, { passive: false });

        canvas.addEventListener('click', (e) => {
            if (didJustDragPin || mouseMovedDistance > 12) return;
            const hit = getPinHit(e.clientX, e.clientY);
            if (hit) return; // Don't toggle cells when clicking a pin!

            const { native: pt } = getNativeFromClient(e.clientX, e.clientY);

            // 1. Ceiling Marker Placement Mode
            if (ceilingMarkerMode) {
                if (!activeKey || !appliances[activeKey]) return;
                const w = appliances[activeKey].type === 'fan' ? 180 : 240;
                const h = appliances[activeKey].type === 'fan' ? 180 : 50;
                appliances[activeKey].roi = [
                    Math.max(0, pt.x - Math.floor(w / 2)),
                    Math.max(0, pt.y - Math.floor(h / 2)),
                    w,
                    h
                ];
                ceilingMarkerMode = false;
                document.getElementById('btn-ceiling-marker').className = "w-full py-1.5 px-2 text-xs bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition";
                document.getElementById('active-mode-badge').innerText = "Mode: Click Desk Cells to Select";
                updateActiveApplianceUI();
                redrawCanvas();
                saveAllToBackend(false);
                return;
            }

            // 2. Desk Cell Selection Mode
            const cells = computeGridCells();
            for (const cell of cells) {
                if (pointInPoly(pt, cell.poly) || pointInPoly(pt, cell.unclippedPoly)) {
                    toggleCellForActiveAppliance(cell.id);
                    break;
                }
            }
        });

        // =====================================================================
        // 🔄 APPLIANCE & CELL MANAGEMENT
        // =====================================================================
        function toggleCellForActiveAppliance(cellId) {
            if (!activeKey) {
                addNewAppliancePrompt();
                if (!activeKey) return;
            }

            const app = appliances[activeKey];
            if (!app.assigned_cells) app.assigned_cells = [];

            // Remove from other appliances
            for (const [k, other] of Object.entries(appliances)) {
                if (k !== activeKey && other.assigned_cells) {
                    other.assigned_cells = other.assigned_cells.filter(id => id !== cellId);
                }
            }

            if (app.assigned_cells.includes(cellId)) {
                app.assigned_cells = app.assigned_cells.filter(id => id !== cellId);
            } else {
                app.assigned_cells.push(cellId);
            }

            recalculateAllAppliancePolygons();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function recalculateAllAppliancePolygons() {
            const cells = computeGridCells();
            const cellMap = {};
            cells.forEach(c => cellMap[c.id] = c);

            for (const [k, app] of Object.entries(appliances)) {
                const assigned = app.assigned_cells || [];
                app.cell_polygons = [];
                let sumX = 0, sumY = 0, ptCount = 0;

                assigned.forEach(cId => {
                    if (cellMap[cId]) {
                        const poly = cellMap[cId].poly.map(p => [p.x, p.y]);
                        app.cell_polygons.push(poly);
                        poly.forEach(pt => {
                            sumX += pt[0];
                            sumY += pt[1];
                            ptCount++;
                        });
                    }
                });

                if (ptCount > 0) {
                    app.zone_centroid = [Math.round(sumX / ptCount), Math.round(sumY / ptCount)];
                } else if (app.roi) {
                    app.zone_centroid = [app.roi[0] + Math.floor(app.roi[2]/2), app.roi[1] + app.roi[3] + 200];
                } else {
                    app.zone_centroid = [960, 540];
                }
            }
        }

        function setType(type) {
            if (!activeKey || !appliances[activeKey]) return;
            appliances[activeKey].type = type;
            const fanBtn = document.getElementById('btn-type-fan');
            const lightBtn = document.getElementById('btn-type-light');
            if (type === 'fan') {
                fanBtn.className = "py-2 px-3 rounded-lg border border-sky-500 bg-sky-950/60 text-sky-300 font-semibold text-xs flex items-center justify-center gap-1.5";
                lightBtn.className = "py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold text-xs flex items-center justify-center gap-1.5";
            } else {
                lightBtn.className = "py-2 px-3 rounded-lg border border-amber-500 bg-amber-950/60 text-amber-300 font-semibold text-xs flex items-center justify-center gap-1.5";
                fanBtn.className = "py-2 px-3 rounded-lg border border-slate-700 bg-slate-950 text-slate-400 font-semibold text-xs flex items-center justify-center gap-1.5";
            }
            renderList();
            redrawCanvas();
        }

        function onPropNameChange() {
            if (!activeKey || !appliances[activeKey]) return;
            appliances[activeKey].name = document.getElementById('prop-name').value;
            syncApplianceDropdown();
            renderList();
        }

        // --- OPTIONAL CEILING MARKER HANDLING ---
        function toggleCeilingOption() {
            if (!activeKey || !appliances[activeKey]) return;
            const enabled = document.getElementById('check-enable-ceiling').checked;
            const controls = document.getElementById('ceiling-marker-controls');
            const badge = document.getElementById('ceiling-marker-badge');

            if (enabled) {
                controls.classList.remove('hidden');
                badge.innerText = appliances[activeKey].roi ? `Set: [${appliances[activeKey].roi[0]}, ${appliances[activeKey].roi[1]}]` : "Not Placed Yet";
            } else {
                controls.classList.add('hidden');
                appliances[activeKey].roi = null;
                badge.innerText = "Optional (Off)";
                ceilingMarkerMode = false;
                document.getElementById('active-mode-badge').innerText = "Mode: Click Desk Cells to Select";
                redrawCanvas();
            }
        }

        function toggleCeilingMarkerMode() {
            ceilingMarkerMode = !ceilingMarkerMode;
            const btn = document.getElementById('btn-ceiling-marker');
            const badge = document.getElementById('active-mode-badge');
            if (ceilingMarkerMode) {
                btn.className = "w-full py-1.5 px-2 text-xs bg-emerald-600 text-white rounded-lg font-bold flex items-center justify-center gap-1.5 animate-pulse";
                badge.innerText = "Mode: Click Camera to Place Ceiling Box";
            } else {
                btn.className = "w-full py-1.5 px-2 text-xs bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 rounded-lg font-semibold flex items-center justify-center gap-1.5 transition";
                badge.innerText = "Mode: Click Desk Cells to Select";
            }
        }

        function clearCeilingMarker() {
            if (!activeKey || !appliances[activeKey]) return;
            appliances[activeKey].roi = null;
            document.getElementById('check-enable-ceiling').checked = false;
            document.getElementById('ceiling-marker-controls').classList.add('hidden');
            document.getElementById('ceiling-marker-badge').innerText = "Optional (Off)";
            ceilingMarkerMode = false;
            document.getElementById('active-mode-badge').innerText = "Mode: Click Desk Cells to Select";
            redrawCanvas();
        }

        // --- BATCH SELECTIONS & GRID SIZING ---
        function changeRows(delta) {
            gridConfig.rows = Math.max(1, Math.min(10, gridConfig.rows + delta));
            document.getElementById('grid-rows-val').innerText = gridConfig.rows;
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function changeCols(delta) {
            gridConfig.cols = Math.max(1, Math.min(8, gridConfig.cols + delta));
            document.getElementById('grid-cols-val').innerText = gridConfig.cols;
            updateBatchButtons();
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function applyPreset(presetKey) {
            const p = PRESETS[presetKey];
            if (!p) return;
            gridConfig.corners = JSON.parse(JSON.stringify(p.corners));
            if (p.bend_pins) {
                gridConfig.bend_pins = JSON.parse(JSON.stringify(p.bend_pins));
            } else {
                resetBendPins();
            }
            gridConfig.rows = p.rows;
            gridConfig.cols = p.cols;
            document.getElementById('grid-rows-val').innerText = gridConfig.rows;
            document.getElementById('grid-cols-val').innerText = gridConfig.cols;
            updateBatchButtons();
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function toggleCornerPins() {
            showCornerPins = !showCornerPins;
            const btn = document.getElementById('btn-toggle-pins');
            if (btn) btn.innerHTML = `<span>📌</span> Pins: ${showCornerPins ? 'ON' : 'OFF'}`;
            redrawCanvas();
        }

        function toggleBendPins() {
            showBendPins = !showBendPins;
            const btn = document.getElementById('btn-toggle-bend-pins');
            if (btn) btn.innerHTML = `<span>🧲</span> 8 Pins (Curved): ${showBendPins ? 'ON' : 'OFF'}`;
            redrawCanvas();
        }

        function resetBendPins() {
            const mids = getStraightMidpoints(gridConfig.corners);
            gridConfig.bend_pins = {
                top: { x: mids.top.x, y: mids.top.y },
                right: { x: mids.right.x, y: mids.right.y },
                bottom: { x: mids.bottom.x, y: mids.bottom.y },
                left: { x: mids.left.x, y: mids.left.y }
            };
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function nudgeBottom(delta) {
            // P3 is Front-Right (idx 2), P4 is Front-Left (idx 3)
            gridConfig.corners[2].y += delta;
            gridConfig.corners[3].y += delta;
            ensureBendPins();
            gridConfig.bend_pins.bottom.y += delta;
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function nudgeSides(delta) {
            // P4 is Front-Left (idx 3) -> expand left (-delta), P3 is Front-Right (idx 2) -> expand right (+delta)
            gridConfig.corners[3].x -= delta;
            gridConfig.corners[2].x += delta;
            ensureBendPins();
            gridConfig.bend_pins.left.x -= Math.round(delta / 2);
            gridConfig.bend_pins.right.x += Math.round(delta / 2);
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function resetPinsToFrame() {
            const imgW = img.naturalWidth || 1920;
            const imgH = img.naturalHeight || 1080;
            gridConfig.corners.forEach(c => {
                c.x = Math.max(20, Math.min(imgW - 20, c.x));
                c.y = Math.max(20, Math.min(imgH - 20, c.y));
            });
            recalculateAllAppliancePolygons();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function updateBatchButtons() {
            const container = document.getElementById('batch-column-buttons');
            container.innerHTML = '';
            const cols = gridConfig.cols;
            for (let c = 0; c < cols; c++) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = "py-1 px-1 text-[11px] bg-slate-900 hover:bg-slate-800 rounded border border-slate-700 text-slate-300";
                btn.innerText = `Col ${c+1}`;
                btn.onclick = () => quickSelectColumn(c);
                container.appendChild(btn);
            }
        }

        function quickSelectColumn(colIdx) {
            if (!activeKey || !appliances[activeKey]) return;
            const cells = computeGridCells();
            cells.filter(c => c.col === colIdx).forEach(c => {
                if (!appliances[activeKey].assigned_cells.includes(c.id)) {
                    appliances[activeKey].assigned_cells.push(c.id);
                }
            });
            recalculateAllAppliancePolygons();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function quickSelectRows(rowIndices) {
            if (!activeKey || !appliances[activeKey]) return;
            const cells = computeGridCells();
            cells.filter(c => rowIndices.includes(c.row)).forEach(c => {
                if (!appliances[activeKey].assigned_cells.includes(c.id)) {
                    appliances[activeKey].assigned_cells.push(c.id);
                }
            });
            recalculateAllAppliancePolygons();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function selectAllCells() {
            if (!activeKey || !appliances[activeKey]) return;
            const cells = computeGridCells();
            appliances[activeKey].assigned_cells = cells.map(c => c.id);
            recalculateAllAppliancePolygons();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function clearActiveCells() {
            if (!activeKey || !appliances[activeKey]) return;
            appliances[activeKey].assigned_cells = [];
            recalculateAllAppliancePolygons();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
            saveAllToBackend(false);
        }

        function addNewAppliancePrompt() {
            const count = Object.keys(appliances).length + 1;
            const name = prompt("Enter Appliance or Space Name:", `Block ${count}`);
            if (!name) return;

            const isLight = name.toLowerCase().includes("light") || name.toLowerCase().includes("tube");
            const type = isLight ? "light" : "fan";
            const key = `app_${Date.now()}`;

            appliances[key] = {
                name: name,
                type: type,
                roi: null, // STRICTLY OPTIONAL - NO DEFAULT CEILING BOX
                assigned_cells: [],
                cell_polygons: [],
                zone_centroid: [960, 600]
            };

            activeKey = key;
            syncApplianceDropdown();
            updateActiveApplianceUI();
            renderList();
            redrawCanvas();
        }

        function deleteActiveAppliance() {
            if (!activeKey) return;
            if (confirm(`Delete ${appliances[activeKey].name}?`)) {
                delete appliances[activeKey];
                const keys = Object.keys(appliances);
                activeKey = keys.length > 0 ? keys[0] : null;
                syncApplianceDropdown();
                updateActiveApplianceUI();
                renderList();
                redrawCanvas();
            }
        }

        function clearAllAppliances() {
            if (confirm("Clear all appliances and their assigned grid cells?")) {
                appliances = {};
                activeKey = null;
                syncApplianceDropdown();
                updateActiveApplianceUI();
                renderList();
                redrawCanvas();
                saveAllToBackend(false);
            }
        }

        function onSelectApplianceChange() {
            const sel = document.getElementById('select-active-appliance');
            activeKey = sel.value;
            updateActiveApplianceUI();
            redrawCanvas();
        }

        function syncApplianceDropdown() {
            const sel = document.getElementById('select-active-appliance');
            sel.innerHTML = '';
            for (const [k, app] of Object.entries(appliances)) {
                const opt = document.createElement('option');
                opt.value = k;
                opt.innerText = `${app.type === 'fan' ? '🌀' : '💡'} ${app.name}`;
                if (k === activeKey) opt.selected = true;
                sel.appendChild(opt);
            }
        }

        function updateActiveApplianceUI() {
            if (!activeKey || !appliances[activeKey]) {
                document.getElementById('prop-name').value = '';
                document.getElementById('active-cells-count').innerText = '0 Cells Selected';
                document.getElementById('check-enable-ceiling').checked = false;
                document.getElementById('ceiling-marker-controls').classList.add('hidden');
                document.getElementById('ceiling-marker-badge').innerText = 'Optional (Off)';
                return;
            }

            const app = appliances[activeKey];
            document.getElementById('prop-name').value = app.name;
            setType(app.type);

            const count = (app.assigned_cells || []).length;
            document.getElementById('active-cells-count').innerText = `${count} Cells (${(app.assigned_cells || []).join(', ') || 'None'})`;

            const hasRoi = (app.roi && Array.isArray(app.roi) && app.roi.length === 4 && (app.roi[2] > 0));
            document.getElementById('check-enable-ceiling').checked = Boolean(hasRoi);
            const controls = document.getElementById('ceiling-marker-controls');
            const badge = document.getElementById('ceiling-marker-badge');

            if (hasRoi) {
                controls.classList.remove('hidden');
                badge.innerText = `[${app.roi[0]}, ${app.roi[1]}]`;
            } else {
                controls.classList.add('hidden');
                badge.innerText = "Optional (Off)";
            }
        }

        function renderList() {
            const list = document.getElementById('appliances-list');
            list.innerHTML = '';
            document.getElementById('appliance-count').innerText = Object.keys(appliances).length;

            let idx = 0;
            for (const [key, item] of Object.entries(appliances)) {
                const color = getApplianceColor(idx);
                const cellsStr = (item.assigned_cells || []).join(', ') || 'No cells assigned';

                const el = document.createElement('div');
                el.className = `p-2.5 rounded-lg bg-slate-950 border transition cursor-pointer ${key === activeKey ? 'border-sky-500 shadow-md' : 'border-slate-800 hover:border-slate-700'}`;
                el.onclick = () => {
                    activeKey = key;
                    syncApplianceDropdown();
                    updateActiveApplianceUI();
                    redrawCanvas();
                };

                el.innerHTML = `
                    <div class="flex justify-between items-center">
                        <div class="font-bold text-white flex items-center gap-1.5">
                            <span>${item.type === 'fan' ? '🌀' : '💡'}</span> ${item.name}
                        </div>
                        <span class="text-[10px] font-bold px-2 py-0.5 rounded text-white" style="background:${color.border}">
                            ${(item.assigned_cells || []).length} Cells
                        </span>
                    </div>
                    <div class="text-[10px] text-slate-400 font-mono mt-1 truncate">
                        Cells: <span class="text-sky-300 font-semibold">${cellsStr}</span>
                    </div>
                `;
                list.appendChild(el);
                idx++;
            }
        }

        // =====================================================================
        // 💾 BACKEND COMMUNICATION
        // =====================================================================
        function parseCoord(p, fallback) {
            if (!p) return fallback;
            if (Array.isArray(p) && p.length >= 2) return { x: Math.round(Number(p[0])), y: Math.round(Number(p[1])) };
            if (typeof p === 'object' && p.x !== undefined && p.y !== undefined) return { x: Math.round(Number(p.x)), y: Math.round(Number(p.y)) };
            return fallback;
        }

        function loadFromBackend() {
            fetch('/api/appliances')
                .then(r => r.json())
                .then(data => {
                    appliances = data.appliances || {};
                    if (data.grid_config) {
                        gridConfig.rows = data.grid_config.rows || 5;
                        gridConfig.cols = data.grid_config.cols || 4;
                        if (data.grid_config.corners && data.grid_config.corners.length === 4) {
                            gridConfig.corners = data.grid_config.corners.map((c, i) => normalizeCorner(c, `P${i+1}`));
                        }
                        const mids = getStraightMidpoints(gridConfig.corners);
                        if (data.grid_config.bend_pins) {
                            gridConfig.bend_pins = {
                                top: parseCoord(data.grid_config.bend_pins.top, mids.top),
                                right: parseCoord(data.grid_config.bend_pins.right, mids.right),
                                bottom: parseCoord(data.grid_config.bend_pins.bottom, mids.bottom),
                                left: parseCoord(data.grid_config.bend_pins.left, mids.left)
                            };
                        } else {
                            ensureBendPins();
                        }
                    }

                    document.getElementById('grid-rows-val').innerText = gridConfig.rows;
                    document.getElementById('grid-cols-val').innerText = gridConfig.cols;
                    updateBatchButtons();

                    const keys = Object.keys(appliances);
                    activeKey = keys.length > 0 ? keys[0] : null;

                    syncApplianceDropdown();
                    updateActiveApplianceUI();
                    recalculateAllAppliancePolygons();
                    renderList();
                    redrawCanvas();
                    populateRoomsInCalibration();
                });
        }

        function cloneGridFromOtherRoom(srcId) {
            if (!srcId) return;
            if (!confirm(`Are you sure you want to copy the 3D perspective depth grid from this room? This will replace your current room's grid coordinates.`)) {
                document.getElementById('clone-room-dropdown').value = '';
                return;
            }
            fetch('/api/rooms/clone_grid', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source_id: srcId })
            })
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    showToast("🎉 3D Grid cloned from room successfully!");
                    loadFromBackend();
                } else {
                    showToast("Error cloning grid: " + d.error, true);
                }
            })
            .catch(e => showToast("Clone request failed: " + e, true));
        }

        function populateRoomsInCalibration() {
            fetch('/api/rooms')
                .then(r => r.json())
                .then(d => {
                    const badge = document.getElementById('calib-room-name');
                    if (badge && d.current_room) badge.innerText = d.current_room.name;
                    const select = document.getElementById('clone-room-dropdown');
                    if (select && d.rooms) {
                        select.innerHTML = '<option value="">📋 Clone Grid From Another Room...</option>';
                        d.rooms.forEach(r => {
                            if (r.id !== d.active_room_id) {
                                const opt = document.createElement('option');
                                opt.value = r.id;
                                opt.innerText = `Clone from: ${r.name} (${r.appliance_count} appliances)`;
                                select.appendChild(opt);
                            }
                        });
                    }
                }).catch(() => {});
        }

        function saveAllToBackend(showAlert = true) {
            recalculateAllAppliancePolygons();
            ensureBendPins();

            const badge = document.getElementById('sync-status-badge');
            if (badge) {
                badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-400 animate-ping"></span> 🟡 Saving...`;
                badge.className = "px-2.5 py-1.5 rounded-lg text-xs font-bold bg-amber-950/80 text-amber-300 border border-amber-700 flex items-center gap-1.5 shadow transition-all";
            }

            // Prepare clean data for backend
            const cleanCorners = gridConfig.corners.map(c => {
                const norm = normalizeCorner(c);
                return [norm.x, norm.y];
            });

            const cleanBend = {
                top: [gridConfig.bend_pins.top.x, gridConfig.bend_pins.top.y],
                right: [gridConfig.bend_pins.right.x, gridConfig.bend_pins.right.y],
                bottom: [gridConfig.bend_pins.bottom.x, gridConfig.bend_pins.bottom.y],
                left: [gridConfig.bend_pins.left.x, gridConfig.bend_pins.left.y]
            };

            fetch('/api/save_appliances', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    appliances: appliances,
                    grid_config: {
                        corners: cleanCorners,
                        bend_pins: cleanBend,
                        rows: gridConfig.rows,
                        cols: gridConfig.cols
                    }
                })
            })
            .then(r => r.json())
            .then(res => {
                if (badge) {
                    badge.innerHTML = `<span>🟢</span> Live Synced`;
                    badge.className = "px-2.5 py-1.5 rounded-lg text-xs font-bold bg-emerald-950/80 text-emerald-300 border border-emerald-700 flex items-center gap-1.5 shadow transition-all duration-300";
                }
                showToast("🎉 Calibration saved & synced live!");
                if (showAlert) {
                    // feedback shown via toast
                }
            })
            .catch(e => {
                if (badge) {
                    badge.innerHTML = `<span>🔴</span> Save Failed`;
                    badge.className = "px-2.5 py-1.5 rounded-lg text-xs font-bold bg-rose-950/80 text-rose-300 border border-rose-700 flex items-center gap-1.5 shadow";
                }
                showToast("Error saving calibration: " + e, true);
            });
        }

        function showToast(msg, isError = false) {
            let container = document.getElementById('toast-container');
            if (!container) {
                container = document.createElement('div');
                container.id = 'toast-container';
                container.className = 'fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none';
                document.body.appendChild(container);
            }
            const toast = document.createElement('div');
            toast.className = `px-4 py-2.5 rounded-xl text-xs font-semibold shadow-2xl transition-all duration-300 transform translate-y-2 opacity-0 flex items-center gap-2 ${isError ? 'bg-rose-900 border border-rose-600 text-rose-100' : 'bg-slate-900 border border-emerald-500 text-emerald-200'}`;
            toast.innerHTML = `<span>${isError ? '⚠️' : '✅'}</span> <span>${msg}</span>`;
            container.appendChild(toast);
            requestAnimationFrame(() => {
                toast.classList.remove('translate-y-2', 'opacity-0');
            });
            setTimeout(() => {
                toast.classList.add('opacity-0', 'translate-y-2');
                setTimeout(() => toast.remove(), 400);
            }, 2500);
        }

        function resetCameraShift() {
            fetch('/api/reset_shift', { method: 'POST' })
                .then(r => r.json())
                .then(d => alert("Camera reference reset to current view."));
        }

        setInterval(() => {
            fetch('/api/camera_shift')
                .then(r => r.json())
                .then(d => {
                    document.getElementById('shift-indicator').innerText = `Camera Shift: (${d.dx}px, ${d.dy}px)`;
                }).catch(() => {});
        }, 1000);

        setInterval(refreshFrame, 2000);
        updateBatchButtons();
        loadFromBackend();
        refreshFrame();
    </script>
</body>
</html>
"""

@app.route("/calibrate")
def serve_calibrate():
    return render_template_string(CALIBRATION_HTML)

# --- 🏨 MULTI-ROOM PROFILE APIS ---
@app.route("/api/rooms", methods=["GET"])
def api_get_rooms():
    with lock:
        rooms_list = []
        for r_id, r in ROOMS_DATA.get("rooms", {}).items():
            rooms_list.append({
                "id": r_id,
                "name": r.get("name", r_id),
                "appliance_count": len(r.get("appliances", {}))
            })
        return jsonify({
            "active_room_id": ACTIVE_ROOM_ID,
            "rooms": rooms_list,
            "current_room": {
                "id": ACTIVE_ROOM_ID,
                "name": ACTIVE_ROOM.get("name", "Classroom"),
                "appliances": APPLIANCES,
                "grid_config": GRID_CONFIG
            }
        })

@app.route("/api/rooms/switch", methods=["POST"])
def api_room_switch():
    data = request.json or {}
    r_id = data.get("room_id")
    with lock:
        ok = switch_active_room(r_id)
    if ok:
        return jsonify({"success": True, "active_room_id": ACTIVE_ROOM_ID, "name": ACTIVE_ROOM.get("name")})
    return jsonify({"success": False, "error": "Room not found"}), 404

@app.route("/api/rooms/create", methods=["POST"])
def api_room_create():
    global ROOMS_DATA
    data = request.json or {}
    name = data.get("name", "").strip() or f"Room {len(ROOMS_DATA.get('rooms', {})) + 1}"
    new_id = f"room_{int(time.time())}"

    with lock:
        ROOMS_DATA.setdefault("rooms", {})[new_id] = {
            "id": new_id,
            "name": name,
            "video_source": {"type": "file", "value": "models/Classroom Video/EEE1_classroom.mp4"},
            "grid_config": dict(DEFAULT_GRID_CONFIG),
            "appliances": {}
        }
        switch_active_room(new_id)
    return jsonify({"success": True, "room_id": new_id, "name": name})

@app.route("/api/rooms/rename", methods=["POST"])
def api_room_rename():
    data = request.json or {}
    r_id = data.get("room_id")
    name = data.get("name", "").strip()
    if not r_id or not name:
        return jsonify({"success": False, "error": "Invalid arguments"}), 400
    with lock:
        if r_id in ROOMS_DATA.get("rooms", {}):
            ROOMS_DATA["rooms"][r_id]["name"] = name
            if r_id == ACTIVE_ROOM_ID:
                ACTIVE_ROOM["name"] = name
            save_rooms_to_disk()
            return jsonify({"success": True, "name": name})
    return jsonify({"success": False, "error": "Room not found"}), 404

@app.route("/api/rooms/delete", methods=["POST"])
def api_room_delete():
    global ACTIVE_ROOM_ID, ROOMS_DATA
    data = request.json or {}
    r_id = data.get("room_id")
    with lock:
        rooms = ROOMS_DATA.get("rooms", {})
        if len(rooms) <= 1:
            return jsonify({"success": False, "error": "Cannot delete the only remaining room"}), 400
        if r_id in rooms:
            del rooms[r_id]
            if r_id == ACTIVE_ROOM_ID:
                new_active = next(iter(rooms.keys()))
                switch_active_room(new_active)
            else:
                save_rooms_to_disk()
            return jsonify({"success": True, "active_room_id": ACTIVE_ROOM_ID})
    return jsonify({"success": False, "error": "Room not found"}), 404

@app.route("/api/rooms/clone_grid", methods=["POST"])
def api_room_clone_grid():
    global GRID_CONFIG, ACTIVE_ROOM
    data = request.json or {}
    src_id = data.get("source_id")
    target_id = data.get("target_id", ACTIVE_ROOM_ID)
    with lock:
        rooms = ROOMS_DATA.get("rooms", {})
        if src_id not in rooms:
            return jsonify({"success": False, "error": "Source room not found"}), 404
        src_grid = json.loads(json.dumps(rooms[src_id].get("grid_config", DEFAULT_GRID_CONFIG)))
        if target_id in rooms:
            rooms[target_id]["grid_config"] = src_grid
        if target_id == ACTIVE_ROOM_ID:
            clean_corners = normalize_corners_py(src_grid.get("corners", DEFAULT_GRID_CONFIG["corners"]))
            GRID_CONFIG = {
                "corners": clean_corners,
                "bend_pins": normalize_bend_pins_py(src_grid.get("bend_pins"), clean_corners),
                "rows": int(src_grid.get("rows", 6)),
                "cols": int(src_grid.get("cols", 6))
            }
            recalculate_appliances_py()
        save_rooms_to_disk()
    return jsonify({"success": True, "grid_config": GRID_CONFIG})

# --- 📹 VIDEO SOURCE APIS ---
@app.route("/api/video_source", methods=["GET"])
def api_get_video_source():
    with lock:
        recent = ROOMS_DATA.get("recent_videos", [])
        bundled = [
            {"name": "EEE Classroom 1 (Bundled)", "path": "models/Classroom Video/EEE1_classroom.mp4"},
            {"name": "Classroom Demo Clip", "path": "models/Classroom Video/test_demo_clip.mp4"}
        ]
        return jsonify({
            "current_source": str(CAMERA_SOURCE),
            "is_webcam": isinstance(CAMERA_SOURCE, int),
            "recent_videos": recent,
            "bundled_videos": bundled
        })

@app.route("/api/video_source/switch", methods=["POST"])
def api_switch_video_source():
    global pending_camera_switch, ROOMS_DATA
    data = request.json or {}
    src_type = data.get("type", "file")
    src_val = data.get("value")

    if src_val is None:
        return jsonify({"success": False, "error": "Missing source value"}), 400

    target = None
    if src_type == "webcam":
        try:
            target = int(src_val)
        except Exception:
            target = 0
    elif src_type == "phone":
        target = str(src_val).strip()
    else:  # file
        target_path = str(src_val).strip()
        if not os.path.isabs(target_path):
            abs_target = os.path.join(os.path.dirname(__file__), target_path)
            if os.path.exists(abs_target):
                target_path = abs_target
        if not os.path.exists(target_path):
            return jsonify({"success": False, "error": f"Video file not found: {target_path}"}), 404
        target = target_path

        # Add to recent videos
        recents = ROOMS_DATA.setdefault("recent_videos", [])
        rel_or_abs = str(src_val).strip()
        if rel_or_abs not in recents:
            recents.insert(0, rel_or_abs)
            if len(recents) > 10:
                recents.pop()
        save_rooms_to_disk()

    with lock:
        pending_camera_switch = target

    return jsonify({"success": True, "target": str(target)})

# --- 🤖 AI TRACKING CONTROLS ---
@app.route("/api/tracking/status", methods=["GET"])
def api_tracking_status():
    with lock:
        return jsonify({"active": AI_TRACKING_ACTIVE})

@app.route("/api/tracking/toggle", methods=["POST"])
def api_tracking_toggle():
    global AI_TRACKING_ACTIVE
    data = request.json or {}
    with lock:
        if "active" in data:
            AI_TRACKING_ACTIVE = bool(data["active"])
        else:
            AI_TRACKING_ACTIVE = not AI_TRACKING_ACTIVE
    return jsonify({"success": True, "active": AI_TRACKING_ACTIVE})

# --- 🔌 DYNAMIC APPLIANCES & SWITCHES APIS ---
@app.route("/api/appliances", methods=["GET"])
def api_get_appliances():
    with lock:
        return jsonify({
            "appliances": APPLIANCES,
            "grid_config": GRID_CONFIG,
            "active_room_id": ACTIVE_ROOM_ID,
            "active_room_name": ACTIVE_ROOM.get("name", "Classroom")
        })

@app.route("/api/save_appliances", methods=["POST"])
def api_save_appliances():
    global APPLIANCES, GRID_CONFIG
    data = request.json or {}
    new_appliances = data.get("appliances", {})
    new_grid = data.get("grid_config", None)
    with lock:
        if new_grid:
            clean_corners = normalize_corners_py(new_grid.get("corners", GRID_CONFIG.get("corners")))
            GRID_CONFIG["corners"] = clean_corners
            GRID_CONFIG["bend_pins"] = normalize_bend_pins_py(new_grid.get("bend_pins"), clean_corners)
            GRID_CONFIG["rows"] = int(new_grid.get("rows", GRID_CONFIG.get("rows", 6)))
            GRID_CONFIG["cols"] = int(new_grid.get("cols", GRID_CONFIG.get("cols", 6)))
        if new_appliances:
            for k, v in new_appliances.items():
                old_v = APPLIANCES.get(k, {})
                v["vision_state"] = old_v.get("vision_state", "OFF")
                v["control_state"] = old_v.get("control_state", False)
                v["manual_override"] = old_v.get("manual_override", "auto")
                v["relay_channel"] = old_v.get("relay_channel", 1)
            APPLIANCES = new_appliances
        recalculate_appliances_py()
        save_rooms_to_disk()
    return jsonify({"success": True, "appliances": APPLIANCES, "grid_config": GRID_CONFIG})

@app.route("/api/appliances/add", methods=["POST"])
def api_appliance_add():
    global APPLIANCES
    data = request.json or {}
    name = data.get("name", "New Switch").strip()
    app_type = data.get("type", "fan")
    relay_ch = data.get("relay_channel", 1)
    assigned = data.get("assigned_cells", [])

    app_id = f"app_{int(time.time() * 1000)}"
    with lock:
        APPLIANCES[app_id] = {
            "name": name,
            "type": app_type,
            "roi": None,
            "assigned_cells": assigned,
            "cell_polygons": [],
            "space_roi": [0, 0, 0, 0],
            "zone_centroid": [960, 540],
            "vision_state": "OFF",
            "control_state": False,
            "manual_override": "auto",
            "relay_channel": int(relay_ch) if relay_ch else 1
        }
        recalculate_appliances_py()
        save_rooms_to_disk()
    return jsonify({"success": True, "id": app_id, "appliance": APPLIANCES[app_id]})

@app.route("/api/appliances/update", methods=["POST"])
def api_appliance_update():
    global APPLIANCES
    data = request.json or {}
    app_id = data.get("id")
    if not app_id or app_id not in APPLIANCES:
        return jsonify({"success": False, "error": "Appliance not found"}), 404

    with lock:
        app = APPLIANCES[app_id]
        if "name" in data: app["name"] = data["name"].strip()
        if "type" in data: app["type"] = data["type"]
        if "relay_channel" in data:
            ch = data["relay_channel"]
            app["relay_channel"] = int(ch) if ch else 1
        if "assigned_cells" in data:
            app["assigned_cells"] = data["assigned_cells"]
        recalculate_appliances_py()
        save_rooms_to_disk()
    return jsonify({"success": True, "appliance": APPLIANCES[app_id]})

@app.route("/api/appliances/delete", methods=["POST"])
def api_appliance_delete():
    global APPLIANCES
    data = request.json or {}
    app_id = data.get("id")
    with lock:
        if app_id in APPLIANCES:
            del APPLIANCES[app_id]
            recalculate_appliances_py()
            save_rooms_to_disk()
            return jsonify({"success": True})
    return jsonify({"success": False, "error": "Appliance not found"}), 404

@app.route("/api/appliances/override", methods=["POST"])
def api_appliance_override():
    global APPLIANCES
    data = request.json or {}
    app_id = data.get("id")
    mode = data.get("mode", "auto")  # "auto", "manual_on", "manual_off"
    with lock:
        if app_id in APPLIANCES:
            APPLIANCES[app_id]["manual_override"] = mode
            if mode == "manual_on":
                APPLIANCES[app_id]["control_state"] = True
                APPLIANCES[app_id]["vision_state"] = "MANUAL ON"
            elif mode == "manual_off":
                APPLIANCES[app_id]["control_state"] = False
                APPLIANCES[app_id]["vision_state"] = "MANUAL OFF"
            save_rooms_to_disk()
            return jsonify({"success": True, "mode": mode, "state": APPLIANCES[app_id]["control_state"]})
    return jsonify({"success": False, "error": "Appliance not found"}), 404

@app.route("/api/update", methods=["GET", "POST"])
@app.route("/api/toggle", methods=["POST"])
def api_toggle():
    global APPLIANCES
    with lock:
        if request.is_json:
            data = request.json
            if "appliance" in data:
                key = data["appliance"]
                if key in APPLIANCES:
                    cur = APPLIANCES[key].get("manual_override", "auto")
                    if cur == "auto":
                        new_state = not APPLIANCES[key]["control_state"]
                        APPLIANCES[key]["manual_override"] = "manual_on" if new_state else "manual_off"
                        APPLIANCES[key]["control_state"] = new_state
                    elif cur == "manual_on":
                        APPLIANCES[key]["manual_override"] = "manual_off"
                        APPLIANCES[key]["control_state"] = False
                    else:
                        APPLIANCES[key]["manual_override"] = "manual_on"
                        APPLIANCES[key]["control_state"] = True
                    save_rooms_to_disk()
    return jsonify({"success": True})

@app.route("/api/camera_shift")
def api_camera_shift():
    with lock:
        return jsonify({"dx": camera_shift_x, "dy": camera_shift_y})

@app.route("/api/reset_shift", methods=["POST"])
def api_reset_shift():
    global ref_gray_32f, camera_shift_x, camera_shift_y
    with lock:
        ref_gray_32f = None
        camera_shift_x = 0
        camera_shift_y = 0
    return jsonify({"success": True})

def generate_video_stream():
    """Live MJPEG video streaming for dashboard & calibration"""
    while True:
        with lock:
            if latest_frame is None:
                time.sleep(0.04)
                continue
            ret, buffer = cv2.imencode(".jpg", latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret:
                time.sleep(0.04)
                continue
            frame_bytes = buffer.tobytes()

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
        time.sleep(0.04)

@app.route("/video_feed")
def video_feed():
    return Response(generate_video_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/status")
@app.route("/status")
def api_status():
    """Unified API consumed by index.html and ESP32"""
    with lock:
        app_list = list(APPLIANCES.values())
        active_apps = sum(1 for a in app_list if a.get("control_state", False))
        total_apps = max(len(app_list), 1)
        energy_saved = int(round((1.0 - (active_apps / total_apps)) * 100)) if total_apps > 0 else 100

        # Hardware relays (Relay 1: any app with channel 1 ON; Relay 2: any app with channel 2 ON)
        relay_1 = any(a.get("control_state", False) for a in app_list if a.get("relay_channel") == 1)
        relay_2 = any(a.get("control_state", False) for a in app_list if a.get("relay_channel") == 2)

        # Fallback if no relay_channel is set
        if not any(a.get("relay_channel") in [1, 2] for a in app_list):
            if len(app_list) >= 1: relay_1 = app_list[0].get("control_state", False)
            if len(app_list) >= 2: relay_2 = app_list[1].get("control_state", False)

        return jsonify({
            "tracking_active": AI_TRACKING_ACTIVE,
            "active_room_id": ACTIVE_ROOM_ID,
            "active_room_name": ACTIVE_ROOM.get("name", "Classroom"),
            "appliances": APPLIANCES,
            "active_appliances_count": active_apps,
            "total_appliances_count": len(app_list),
            "energy_saved_percent": energy_saved,
            "humans_detected": humans_detected_count,
            "relay_1": relay_1,
            "relay_2": relay_2,
            "esp32_ip": ESP32_IP,
            "local_ip": LOCAL_IP,
            "wifi_url": f"http://{LOCAL_IP}:5000",
            "camera_source": str(CAMERA_SOURCE),
            "camera_shift": {"dx": camera_shift_x, "dy": camera_shift_y},
            "grid_config": GRID_CONFIG
        })

def start_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# Start web server thread
flask_thread = threading.Thread(target=start_flask, daemon=True)
flask_thread.start()

def auto_launch_dashboard():
    """Automatically launches the Digital Twin dashboard in the default browser"""
    time.sleep(1.2)
    try:
        import webbrowser
        webbrowser.open("http://localhost:5000")
        print(f"[AI SERVER] 🌐 Automatically opened Digital Twin Dashboard: http://localhost:5000")
    except Exception as e:
        print(f"[AI SERVER] Note: Browser auto-launch ({e})")

threading.Thread(target=auto_launch_dashboard, daemon=True).start()

# --- VISION ON / OFF DETECTION ENGINES ---
def detect_fan_spinning(curr_gray, prev_gray, roi):
    x, y, w, h = roi
    fh, fw = curr_gray.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop_curr = curr_gray[y1:y2, x1:x2]
    crop_prev = prev_gray[y1:y2, x1:x2]

    diff = cv2.absdiff(crop_curr, crop_prev)
    _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    motion_score = np.mean(thresh)

    return "ON (SPINNING)" if motion_score > 3.5 else "OFF (STILL)"

def detect_light_illuminated(frame, roi):
    x, y, w, h = roi
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + w), min(fh, y + h)

    if x2 <= x1 or y2 <= y1:
        return "OFF"

    crop = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    mean_val = np.mean(gray)
    bright_percentile = np.percentile(gray, 90)

    if mean_val > 175 or bright_percentile > 230:
        return "ON (GLOWING)"
    else:
        return "OFF (DARK)"

def send_esp32_hardware(relay1, relay2):
    try:
        url = f"{ESP32_IP}/control?light={'on' if relay1 else 'off'}&fan={'on' if relay2 else 'off'}"
        requests.get(url, timeout=0.8)
    except Exception:
        pass

# --- MAIN AI COMPUTER VISION LOOP ---
print("\n" + "="*70)
print(" 🚀 SPATIAL AI SMART ROOM - DIGITAL TWIN SERVER ACTIVE")
print("="*70)
print(f" 💻 Local Dashboard:       http://localhost:5000")
print(f" 🎯 Appliance Calibration: http://localhost:5000/calibrate")
print(f" 📱 Same Wi-Fi Mobile:     http://{LOCAL_IP}:5000")
print(f" 🌐 Target ESP32 Hardware: {ESP32_IP}")
print("-" * 70)
print(f" 📶 CONNECT PHONE / TABLET TO SAME WI-FI & OPEN:")
print(f"    👉 http://{LOCAL_IP}:5000")
print(f"    👉 http://{LOCAL_IP}:5000/calibrate")
print(" 🌐 Automatically launching dashboard in your browser...")
print("="*70 + "\n")

MODEL_24MB_PATH = os.path.join(os.path.dirname(__file__), "models", "classroom_cctv_yolov8s_world.pt")
MODEL_6MB_PATH = os.path.join(os.path.dirname(__file__), "models", "classroom_cctv_yolov8n.pt")

if os.path.exists(MODEL_24MB_PATH):
    print(f"[AI SERVER] Loading High-Accuracy 24MB Fine-Tuned Model ({MODEL_24MB_PATH})...")
    model = YOLO(MODEL_24MB_PATH)
elif os.path.exists(MODEL_6MB_PATH):
    print(f"[AI SERVER] Loading 6MB Fine-Tuned Classroom Model ({MODEL_6MB_PATH})...")
    model = YOLO(MODEL_6MB_PATH)
else:
    print("[AI SERVER] Loading YOLO-World fallback...")
    model = YOLO("yolov8s-world.pt")
    model.set_classes(["person", "ceiling fan", "tube light", "lamp", "fluorescent light"])

cap = cv2.VideoCapture(CAMERA_SOURCE)
if not cap.isOpened():
    if os.path.exists(CLASSROOM_VIDEO):
        print(f"[AI SERVER] Warning: Could not open {CAMERA_SOURCE}. Falling back to classroom video: {CLASSROOM_VIDEO}")
        CAMERA_SOURCE = CLASSROOM_VIDEO
        cap = cv2.VideoCapture(CAMERA_SOURCE)
    elif os.path.exists(DEFAULT_DEMO_VIDEO):
        print(f"[AI SERVER] Warning: Could not open {CAMERA_SOURCE}. Falling back to demo video: {DEFAULT_DEMO_VIDEO}")
        CAMERA_SOURCE = DEFAULT_DEMO_VIDEO
        cap = cv2.VideoCapture(CAMERA_SOURCE)

window_name = "Spatial AI Smart Classroom Vision Monitor"
cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
cv2.resizeWindow(window_name, 960, 540)
try:
    cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
except Exception:
    pass

frame_idx = 0
while True:
    # 0. Thread-safe camera / video source switching
    with lock:
        if pending_camera_switch is not None:
            new_target = pending_camera_switch
            pending_camera_switch = None
            try:
                print(f"[AI SERVER] Switching video source to: {new_target}")
                new_cap = cv2.VideoCapture(new_target)
                if new_cap.isOpened():
                    cap.release()
                    cap = new_cap
                    CAMERA_SOURCE = new_target
                    ref_gray_32f = None
                    prev_gray_frame = None
                    print(f"[AI SERVER] Successfully connected to new source: {CAMERA_SOURCE}")
                else:
                    print(f"[AI SERVER] Warning: Failed to open new source: {new_target}")
            except Exception as e:
                print(f"[AI SERVER] Error switching camera source: {e}")

    ret, frame = cap.read()
    if not ret or frame is None:
        if isinstance(CAMERA_SOURCE, str) and os.path.exists(CAMERA_SOURCE):
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            time.sleep(0.05)
            continue
        time.sleep(0.1)
        continue

    frame_idx += 1
    fh, fw = frame.shape[:2]
    curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    curr_gray_32f = np.float32(curr_gray)

    # =========================================================================
    # 🔄 AUTO-SHIFT DETECTION
    # =========================================================================
    if ref_gray_32f is None:
        ref_gray_32f = curr_gray_32f.copy()
    else:
        try:
            shift, response = cv2.phaseCorrelate(ref_gray_32f, curr_gray_32f)
            if response > 0.45 and (abs(shift[0]) < fw / 3 and abs(shift[1]) < fh / 3):
                camera_shift_x = int(round(-shift[0]))
                camera_shift_y = int(round(-shift[1]))
        except Exception:
            pass

    if prev_gray_frame is None:
        prev_gray_frame = curr_gray.copy()

    detected_humans = []
    current_human_boxes = []

    # =========================================================================
    # 🤖 AI TRACKING vs PAUSED MODE
    # =========================================================================
    if AI_TRACKING_ACTIVE:
        results = model(frame, verbose=False)[0]
        for box in results.boxes:
            cls_id = int(box.cls[0])
            label = results.names[cls_id].lower() if cls_id in results.names else ""
            conf = float(box.conf[0])
            if ("person" in label or cls_id == 0) and conf > 0.28:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                hx, hy = int((x1 + x2) / 2), int(y2)
                detected_humans.append((hx, hy))
                current_human_boxes.append((x1, y1, x2, y2, conf))

        with lock:
            humans_detected_count = len(detected_humans)
            active_count = 0
            for i, (key, item) in enumerate(APPLIANCES.items()):
                override = item.get("manual_override", "auto")
                if override == "manual_on":
                    item["control_state"] = True
                    item["vision_state"] = "MANUAL ON"
                    active_count += 1
                    continue
                elif override == "manual_off":
                    item["control_state"] = False
                    item["vision_state"] = "MANUAL OFF"
                    continue

                occupied = False
                cell_polys = item.get("cell_polygons", [])

                if cell_polys:
                    for poly_pts in cell_polys:
                        poly_np = np.array(poly_pts, dtype=np.int32)
                        poly_np[:, 0] += camera_shift_x
                        poly_np[:, 1] += camera_shift_y

                        # 1. Test student feet coordinates
                        for (hx, hy) in detected_humans:
                            if cv2.pointPolygonTest(poly_np, (float(hx), float(hy)), False) >= 0:
                                occupied = True
                                break
                        if occupied:
                            break

                        # 2. Test student center or bounding box overlap
                        for (x1, y1, x2, y2, _) in current_human_boxes:
                            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                            if cv2.pointPolygonTest(poly_np, (float(cx), float(cy)), False) >= 0:
                                occupied = True
                                break
                            min_px = int(np.min(poly_np[:, 0]))
                            max_px = int(np.max(poly_np[:, 0]))
                            min_py = int(np.min(poly_np[:, 1]))
                            max_py = int(np.max(poly_np[:, 1]))
                            if not (x2 < min_px or x1 > max_px or y2 < min_py or y1 > max_py):
                                occupied = True
                                break
                        if occupied:
                            break
                elif item.get("space_roi"):
                    sx = item["space_roi"][0] + camera_shift_x
                    sy = item["space_roi"][1] + camera_shift_y
                    sw = item["space_roi"][2]
                    sh = item["space_roi"][3]
                    for (hx, hy) in detected_humans:
                        if (sx <= hx <= sx + sw) and (sy <= hy <= sy + sh):
                            occupied = True
                            break
                else:
                    zx = item["zone_centroid"][0] + camera_shift_x
                    zy = item["zone_centroid"][1] + camera_shift_y
                    for (hx, hy) in detected_humans:
                        if math.hypot(hx - zx, hy - zy) < PROXIMITY_RADIUS:
                            occupied = True
                            break

                item["control_state"] = occupied
                item["vision_state"] = "ACTIVE (OCCUPIED)" if occupied else "IDLE (VACANT)"
                if occupied:
                    active_count += 1
    else:
        # AI Tracking PAUSED: Save GPU/CPU inference, handle manual overrides
        with lock:
            humans_detected_count = 0
            active_count = 0
            for key, item in APPLIANCES.items():
                override = item.get("manual_override", "auto")
                if override == "manual_on":
                    item["control_state"] = True
                    item["vision_state"] = "MANUAL ON"
                    active_count += 1
                elif override == "manual_off":
                    item["control_state"] = False
                    item["vision_state"] = "MANUAL OFF"
                else:
                    item["control_state"] = False
                    item["vision_state"] = "PAUSED"

    prev_gray_frame = curr_gray.copy()

    # Dispatch to ESP32 hardware relays (every 1.2s)
    current_time = time.time()
    if current_time - last_esp_send_time >= 1.2:
        last_esp_send_time = current_time
        with lock:
            app_list = list(APPLIANCES.values())
            r1 = any(a.get("control_state", False) for a in app_list if a.get("relay_channel") == 1)
            r2 = any(a.get("control_state", False) for a in app_list if a.get("relay_channel") == 2)
            if not any(a.get("relay_channel") in [1, 2] for a in app_list):
                if len(app_list) >= 1: r1 = app_list[0].get("control_state", False)
                if len(app_list) >= 2: r2 = app_list[1].get("control_state", False)
        send_esp32_hardware(r1, r2)

    # 4. Render Visual Overlays on Video Feed
    with lock:
        overlay = frame.copy()

        # A. Draw Room Ground Perspective Grid Outline
        if "corners" in GRID_CONFIG:
            raw_corners = [[pt[0] + camera_shift_x, pt[1] + camera_shift_y] for pt in GRID_CONFIG["corners"]]
            clipped_g = clip_polygon_py(raw_corners, 0, 0, fw, fh)
            if len(clipped_g) >= 3:
                cv2.polylines(overlay, [np.array(clipped_g, dtype=np.int32)], isClosed=True, color=(120, 100, 60), thickness=2)

        # B. Draw Each Appliance's 3D Perspective Cell Polygons
        for key, item in APPLIANCES.items():
            cell_polys = item.get("cell_polygons", [])
            is_occupied = item.get("control_state", False)
            is_fan = (item.get("type") == "fan")

            if cell_polys:
                if is_occupied:
                    fill_color = (160, 200, 30) if is_fan else (20, 180, 240)  # BGR
                    border_color = (200, 240, 50) if is_fan else (50, 210, 255)
                    thick = 1
                else:
                    fill_color = (40, 60, 15) if is_fan else (10, 40, 60)
                    border_color = (80, 110, 30) if is_fan else (20, 80, 110)
                    thick = 1

                for poly_pts in cell_polys:
                    shifted_poly = [[pt[0] + camera_shift_x, pt[1] + camera_shift_y] for pt in poly_pts]
                    clipped_poly = clip_polygon_py(shifted_poly, 0, 0, fw, fh)
                    if len(clipped_poly) >= 3:
                        poly_np = np.array(clipped_poly, dtype=np.int32)
                        cv2.fillPoly(overlay, [poly_np], fill_color)
                        cv2.polylines(frame, [poly_np], isClosed=True, color=border_color, thickness=thick)

                # Centroid tag
                first_poly = np.array(cell_polys[0], dtype=np.int32)
                cx = int(np.mean(first_poly[:, 0])) + camera_shift_x
                cy = int(np.mean(first_poly[:, 1])) + camera_shift_y
                status_tag = f"[{'ACTIVE' if is_occupied else 'IDLE'}] {item['name']}"
                cv2.putText(frame, status_tag, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.40, border_color, 1)

        # Alpha blend overlay with frame (12% opacity for grid and polygons)
        cv2.addWeighted(overlay, 0.12, frame, 0.88, 0, frame)

        # C. Draw Student Bounding Boxes (if tracking active)
        if AI_TRACKING_ACTIVE:
            for (x1, y1, x2, y2, conf) in current_human_boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 120, 0), 2)
                label_text = f"Student {int(conf*100)}%"
                (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
                cv2.rectangle(frame, (x1, max(0, y1 - th - 6)), (x1 + tw + 6, y1), (255, 120, 0), -1)
                cv2.putText(frame, label_text, (x1 + 3, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                hx, hy = int((x1 + x2) / 2), int(y2)
                cv2.circle(frame, (hx, hy), 6, (0, 0, 255), -1)

        # Top Status Banner on Video Frame
        banner_bg = (20, 20, 30)
        cv2.rectangle(frame, (10, 10), (760, 50), banner_bg, -1)
        room_name = ACTIVE_ROOM.get("name", "Classroom")
        if AI_TRACKING_ACTIVE:
            status_text = f"[{room_name}] AI Live | Students: {humans_detected_count} | Active: {active_count} | Shift: ({camera_shift_x},{camera_shift_y})px"
            cv2.putText(frame, status_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 2)
        else:
            status_text = f"[{room_name}] PAUSED - AI Tracking Inactive | Video Monitor Live"
            cv2.putText(frame, status_text, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 165, 255), 2)

        # Store latest frame for live web stream
        latest_frame = frame.copy()

    try:
        cv2.imshow(window_name, frame)
    except Exception as e:
        pass

    key = cv2.waitKey(10) & 0xFF
    if key in [ord('q'), ord('Q'), 27]:
        break

cap.release()
cv2.destroyAllWindows()
print("[SHUTDOWN] System exited successfully.")