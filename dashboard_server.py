import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ==============================================================================
# SPATIAL AI SMART ROOM - CENTRAL DASHBOARD & BRIDGE SERVER
# ==============================================================================
# - Serves dashboard.html to any web browser
# - Stores the live state of all 10 workstation units (fans + lights)
# - Provides /api/status and /index for the ESP32 to retrieve data
# - Provides /api/update for the ML model (your friend's script) to update data
# ==============================================================================

PORT = 5000

# 10 Workstation Units State (True = ON/Occupied, False = OFF/Vacant)
STATE = {
    "units": [False] * 10,  # Index 0 = Unit 1, Index 1 = Unit 2, ..., Index 9 = Unit 10
    "fans": [False] * 10,
    "lights": [False] * 10
}

class DashboardHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        # 1. API Status endpoint (retrieved by ESP32 and Web Dashboard)
        if path in ["/api/status", "/status", "/index", "/api/index"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()

            # Active units count
            active_count = sum(1 for u in STATE["units"] if u)
            energy_saved = int(round((1.0 - (active_count / 10.0)) * 100))

            response_data = {
                "units": STATE["units"],
                "fans": STATE["fans"],
                "lights": STATE["lights"],
                "unit_1": STATE["units"][0],
                "unit_2": STATE["units"][1],
                "relay_1": STATE["units"][0],  # Relay 1 (Unit 1: Fan 1 + Light 1)
                "relay_2": STATE["units"][1],  # Relay 2 (Unit 2: Fan 2 + Light 2)
                "active_units": active_count,
                "energy_saved_percent": energy_saved
            }
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return

        # 2. API Update endpoint via GET query parameters
        # Example: /api/update?index=0&state=on OR /api/update?unit_1=on&unit_2=off
        if path == "/api/update":
            self._handle_params_update(params)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "State updated"}).encode("utf-8"))
            return

        # 3. Serve dashboard.html
        if path in ["/", "/dashboard", "/dashboard.html"]:
            dashboard_file = os.path.join(os.path.dirname(__file__), "dashboard.html")
            if os.path.exists(dashboard_file):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                with open(dashboard_file, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"dashboard.html not found")
            return

        # Fallback 404
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ["/api/update", "/update", "/control"]:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")

            try:
                data = json.loads(post_data)
                self._handle_json_update(data)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "units": STATE["units"]}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"JSON Error: {e}".encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def _handle_json_update(self, data):
        """Processes JSON updates from the friend's ML script"""
        # A. By full array: {"units": [1, 0, 0, ...]}
        if "units" in data and isinstance(data["units"], list):
            for i in range(min(10, len(data["units"]))):
                STATE["units"][i] = bool(data["units"][i])

        # B. By fans and lights arrays: {"fans": [...], "lights": [...]}
        if "fans" in data and isinstance(data["fans"], list):
            for i in range(min(10, len(data["fans"]))):
                STATE["fans"][i] = bool(data["fans"][i])
                if STATE["fans"][i]:
                    STATE["units"][i] = True

        if "lights" in data and isinstance(data["lights"], list):
            for i in range(min(10, len(data["lights"]))):
                STATE["lights"][i] = bool(data["lights"][i])
                if STATE["lights"][i]:
                    STATE["units"][i] = True

        # C. By single index: {"index": 0, "state": True} (0-indexed)
        if "index" in data:
            idx = int(data["index"])
            state = bool(data.get("state", data.get("val", data.get("status", True))))
            if 0 <= idx < 10:
                STATE["units"][idx] = state

        # D. By unit key: {"unit_1": true, "unit_2": false}
        for i in range(1, 11):
            key = f"unit_{i}"
            if key in data:
                STATE["units"][i - 1] = bool(data[key])

        print(f"[DASHBOARD UPDATE] Units Status: {[int(x) for x in STATE['units']]}")

    def _handle_params_update(self, params):
        """Processes GET query parameters: ?index=0&state=on"""
        if "index" in params:
            idx = int(params["index"][0])
            state = params.get("state", ["on"])[0] in ["on", "1", "true"]
            if 0 <= idx < 10:
                STATE["units"][idx] = state

        for i in range(1, 11):
            key = f"unit_{i}"
            if key in params:
                STATE["units"][i - 1] = params[key][0] in ["on", "1", "true"]

        print(f"[DASHBOARD UPDATE] Units Status: {[int(x) for x in STATE['units']]}")

    def log_message(self, format, *args):
        # Silence standard HTTP access logging to keep terminal clean
        return

def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"\n========================================================")
    print(f"  SPATIAL AI DIGITAL TWIN DASHBOARD SERVER STARTED")
    print(f"  Listening on: http://localhost:{PORT}")
    print(f"  ESP32 Status Endpoint: http://<YOUR_IP>:{PORT}/api/status")
    print(f"========================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Dashboard server stopped.")
        httpd.server_close()

if __name__ == "__main__":
    run_server()
