import sys
import os
tempfile = __import__('tempfile')
import shutil
import socket
import threading
import pandas as pd
import webbrowser
import time

from flask import (
    Flask, request, render_template,
    redirect, url_for, send_file,
    jsonify, abort
)
from werkzeug.utils import secure_filename
from werkzeug.serving import make_server
from collections import defaultdict

# track last heartbeat timestamp
t_last_heartbeat = time.time()
server = None

# ─── Find an open port ─────────────────────────────────────────────────
def find_free_port(start=5050, end=5100):
    s = socket.socket()
    for p in range(start, end + 1):
        try:
            s.bind(("127.0.0.1", p))
            s.close()
            return p
        except OSError:
            continue
    raise RuntimeError(f"No free ports in {start}–{end}")

# ─── Locate templates/static ───────────────────────────────────────────
if getattr(sys, "frozen", False):
    base_dir = sys._MEIPASS
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

template_dir = os.path.join(base_dir, "templates")
static_dir = os.path.join(base_dir, "static")

app = Flask(
    __name__,
    template_folder=template_dir,
    static_folder=static_dir
)

# ─── Global state + temp image dir ────────────────────────────────────
UPLOAD_FOLDER = os.path.join(base_dir, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

temp_image_dir = tempfile.mkdtemp(prefix="pv_images_")
DEFAULT_EXCEL = "ProductGrid2025.xlsx"
current_excel_path = os.path.join(UPLOAD_FOLDER, DEFAULT_EXCEL)
current_excel_filename = DEFAULT_EXCEL if os.path.exists(current_excel_path) else "None selected"

all_products_data = []
all_attributes = []
all_distributions = []
all_filter_options = {}

# ─── Helpers ───────────────────────────────────────────────────────────
def get_filter_options(products, attributes):
    opts = defaultdict(set)
    for p in products:
        for attr in attributes:
            opts[attr].add(p["attributes"][attr])
    return {k: sorted(v) for k, v in opts.items()}

def find_image_relpath(pid: str) -> str | None:
    for root, _, files in os.walk(temp_image_dir):
        for fn in files:
            name, ext = os.path.splitext(fn.lower())
            if name == pid.lower() and ext in (".jpg", ".png"):
                rel = os.path.relpath(os.path.join(root, fn), temp_image_dir)
                return rel.replace(os.sep, "/")
    return None

def load_and_parse_excel(path: str):
    global all_products_data, all_attributes, all_distributions, all_filter_options

    if not path or not os.path.exists(path):
        all_products_data = []
        all_attributes = []
        all_distributions = []
        all_filter_options = {}
        return

    df = pd.read_excel(path)
    headers = df.columns.tolist()

    attributes = [h for h in headers if str(h).startswith("ATT")]
    distributions = [h for h in headers if str(h).startswith("DIST")]
    price_col = headers[-1] if "price" in headers[-1].lower() else None

    prods = []
    for idx, row in df.iterrows():
        pid = str(row.iloc[0]).strip()
        desc = str(row.iloc[1]).strip()
        price_str = f"{row[price_col]:.2f}" if price_col and not pd.isna(row[price_col]) else ""

        rel = find_image_relpath(pid)
        img_fn = rel or "notFound.png"

        attr_data = {a: str(row[a]).strip() for a in attributes}
        dist_data = {d: "X" in str(row[d]).upper() for d in distributions}

        prods.append({
            "original_index": idx,
            "image_filename": img_fn,
            "description": desc,
            "original_description": desc,
            "price": price_str,
            "original_price": price_str,
            "attributes": attr_data,
            "original_attributes": attr_data.copy(),
            "distribution": dist_data
        })

    all_products_data = prods
    all_attributes = attributes
    all_distributions = distributions
    all_filter_options = get_filter_options(prods, attributes)

# ─── Flask routes ─────────────────────────────────────────────────────
@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    global t_last_heartbeat
    t_last_heartbeat = time.time()
    return '', 204

# ─── Heartbeat monitor ─────────────────────────────────────────────────
def heartbeat_monitor():
    global t_last_heartbeat, server
    while True:
        time.sleep(10)
        elapsed = time.time() - t_last_heartbeat
        print(f"[monitor] {elapsed:.1f}s since last heartbeat")
        if elapsed > 70:
            print("[monitor] no heartbeat — shutting down")
            if server:
                server.shutdown()
            else:
                os._exit(0)
            break

@app.route("/", methods=["GET", "POST"])
def index():
    global current_excel_path, current_excel_filename
    if request.method == "POST":
        # Excel upload
        if "excel_file" in request.files:
            f = request.files["excel_file"]
            if f.filename:
                fn = secure_filename(f.filename)
                dest = os.path.join(UPLOAD_FOLDER, fn)
                f.save(dest)
                current_excel_path = dest
                current_excel_filename = fn
        # Images-folder upload
        for fs in request.files.getlist("image_files"):
            rel = fs.filename.replace("\\", "/")
            parts = [secure_filename(p) for p in rel.split("/")]
            out = os.path.join(temp_image_dir, *parts)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            fs.save(out)
        if current_excel_path:
            load_and_parse_excel(current_excel_path)
        return redirect(url_for("index"))
    if current_excel_path and not all_products_data:
        load_and_parse_excel(current_excel_path)
    return render_template(
        "grid.html",
        attributes=all_attributes,
        distributions=all_distributions,
        products=all_products_data,
        filter_options=all_filter_options,
        uploaded_filename=current_excel_filename
    )

@app.route("/user_images/<path:filename>")
def user_images(filename):
    safe = os.path.normpath(filename)
    temp_full = os.path.join(temp_image_dir, safe)
    if temp_full.startswith(temp_image_dir) and os.path.exists(temp_full):
        return send_file(temp_full)
    static_full = os.path.join(static_dir, "images", safe)
    if os.path.exists(static_full):
        return send_file(static_full)
    abort(404)

@app.route("/update_attributes", methods=["POST"])
def update_attributes():
    global all_products_data
    if not current_excel_path:
        return jsonify(success=False, message="No Excel"), 400
    changes = request.get_json() or []
    if not changes:
        return jsonify(success=False, message="No changes"), 400
    df = pd.read_excel(current_excel_path)
    cols = df.columns.tolist()
    desc_c = cols[1]
    price_c = cols[-1] if "price" in cols[-1].lower() else None
    for ch in changes:
        idx, attr, nv = ch["original_index"], ch["attribute"], ch["newValue"]
        if attr == "description":
            df.loc[idx, desc_c] = nv
        elif attr == "price" and price_c:
            df.loc[idx, price_c] = float(nv or 0)
        else:
            df.loc[idx, attr] = nv
    df.to_excel(current_excel_path, index=False)
    load_and_parse_excel(current_excel_path)
    return jsonify(success=True, message="Updated!")

@app.route("/download_current_grid")
def download_current_grid():
    if current_excel_path and os.path.exists(current_excel_path):
        return send_file(
            current_excel_path,
            as_attachment=True,
            download_name=current_excel_filename
        )
    return jsonify(success=False, message="No file")

@app.route("/shutdown", methods=["POST"])
def shutdown():
    print("🔌 Shutdown endpoint hit — shutting down server…", file=sys.stderr)
    if server:
        threading.Thread(target=server.shutdown).start()
    return "", 204

# ─── Bootstrap with make_server ────────────────────────────────────────
def run_server(port):
    global server
    server = make_server("127.0.0.1", port, app)
    server.serve_forever()

if __name__ == "__main__":
    # load default spreadsheet
    if current_excel_path:
        load_and_parse_excel(current_excel_path)
    try:
        port = find_free_port(5050, 5100)
    except RuntimeError as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
    url = f"http://127.0.0.1:{port}"
    # start Flask via make_server
    th = threading.Thread(target=lambda: run_server(port), daemon=True)
    th.start()
    # start heartbeat monitor
    monitor = threading.Thread(target=heartbeat_monitor, daemon=True)
    monitor.start()
    # open browser
    webbrowser.open(url)
    # wait until shutdown
    th.join()
    # cleanup
    shutil.rmtree(temp_image_dir, ignore_errors=True)
    sys.exit(0)
