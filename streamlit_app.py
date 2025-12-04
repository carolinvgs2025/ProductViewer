import streamlit as st
import pandas as pd
import os
import time # For performance troubleshooting
from collections import defaultdict
import base64
from io import BytesIO
from datetime import datetime
import uuid
from PIL import Image, ImageOps
import plotly.express as px

# This assumes your firestore_manager.py file is present and correct
from firestore_manager import (
    integrate_with_streamlit_app,
    get_or_create_user_id,
    save_current_project_to_cloud,
    load_project_summaries_from_cloud,
    ensure_project_loaded,
)

# Initialize Firebase
firestore_manager = integrate_with_streamlit_app()


# --- SESSION STATE INITIALIZATION ---
if "projects" not in st.session_state:
    st.session_state.projects = {}  # full project data (loaded on demand)
if "project_summaries" not in st.session_state:
    st.session_state.project_summaries = [] # lightweight list for home screen

# Load project summaries on startup
load_project_summaries_from_cloud()

# Page state
if 'current_project' not in st.session_state:
    st.session_state.current_project = None
if 'page' not in st.session_state:
    st.session_state.page = 'projects'


# --- PAGE CONFIG AND STYLING ---
st.set_page_config(
    page_title="Interactive Product Grid",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Hide Streamlit style elements
hide_streamlit_style = """
<style>
    /* 1. Hide the "Hamburger" menu (top right) */
    #MainMenu {
        visibility: hidden;
        display: none;
    }

    /* 2. Hide the "Deploy" button (top right) */
    .stDeployButton {
        visibility: hidden;
        display: none;
    }

    /* 3. Hide the footer */
    footer {
        visibility: hidden;
        display: none;
    }

    /* 4. SAFETY: Ensure the Header Bar itself is visible 
       (This holds the sidebar toggle > arrow) */
    header[data-testid="stHeader"] {
        visibility: visible !important;
        background: transparent !important;
    }

    /* 5. Explicitly target the sidebar toggle arrow to ensure it's seen */
    [data-testid="stSidebarCollapsedControl"] {
        visibility: visible;
        display: block;
        color: inherit;
    }

    /* 6. Fix content padding so title isn't cut off */
    .block-container {
        padding-top: 3rem !important;
    }

    /* 7. Custom styles for the MultiSelect (Scrollable + Small Tags) */
    .stMultiSelect div[data-baseweb="select"] > div:first-child {
        max-height: 100px; 
        overflow-y: auto;
    }
    .stMultiSelect [data-baseweb="tag"] span {
        font-size: 12px !important; 
    }
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Custom CSS
st.markdown("""
<style>
    .main > div {
        padding-top: 2rem;
    }
    .stSelectbox > div > div > select {
        background-color: white;
    }
    .product-card {
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 9px;
        margin: 5px;
        background-color: white;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .product-card img {
        image-rendering: -webkit-optimize-contrast;
        image-rendering: crisp-edges;
        max-width: 100%;
        height: auto;
        margin-bottom: 10px;
    }
    .changed-attribute {
        color: #B22222;
        font-weight: bold;
    }
    .project-card {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 20px;
        margin: 10px 0;
        background-color: white;
        box-shadow: 2px 2px 8px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
    }
    .project-card:hover {
        transform: translateY(-2px);
        box-shadow: 4px 4px 12px rgba(0,0,0,0.15);
    }
    .project-stats {
        color: #666;
        font-size: 0.9em;
    }
    .new-project-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 30px;
        border-radius: 15px;
        margin: 20px 0;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# --- IMAGE PROCESSING HELPERS ---
CARD_IMG_CSS_WIDTH = 200
CARD_IMG_CSS_HEIGHT = 220  # NEW: Fixed height for grid images
MODAL_IMG_CSS_WIDTH = 300
RETINA_FACTOR = 2


@st.cache_data(show_spinner=False)
def get_image_html_from_url(product_id: str, image_url: str, css_width: int):
    """Creates a simple <img> tag from a URL. Caches against the product_id."""
    if not image_url:
        # UPDATED: Use fixed height for placeholder
        return f'<div style="width: {css_width}px; height: {CARD_IMG_CSS_HEIGHT}px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; border-radius: 8px;">📷 No image</div>'
    
    # UPDATED: Fixed height with object-fit: contain
    return f'<img src="{image_url}" style="width: auto; max-width: {css_width}px; height: {CARD_IMG_CSS_HEIGHT}px; object-fit: contain; display: block; margin-left: auto; margin-right: auto;" alt="Product Image">'

@st.cache_data(show_spinner=False)
def _encode_png_uri(im: Image.Image) -> str:
    """Return a PNG data URI for a PIL image."""
    b = BytesIO()
    im.save(b, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode("ascii")

@st.cache_data(show_spinner=False)
def _resize_lanczos(img: Image.Image, target_w: int) -> Image.Image:
    """High-quality downscale while preserving aspect ratio."""
    if img.width <= target_w:
        return img.copy()
    r = target_w / img.width
    new_h = max(1, int(round(img.height * r)))
    return img.resize((target_w, new_h), Image.Resampling.LANCZOS)

@st.cache_data(show_spinner=False)
def build_img_srcset(image_bytes: bytes, css_width: int) -> str:
    """Return an <img> HTML string with srcset (1x/2x) as PNG data URIs."""
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    one_x = _resize_lanczos(img, css_width)
    two_x = _resize_lanczos(img, css_width * RETINA_FACTOR)
    uri_1x = _encode_png_uri(one_x)
    uri_2x = _encode_png_uri(two_x)
    
    # UPDATED: Fixed height with object-fit: contain
    return f"""
    <img
      src="{uri_1x}"
      srcset="{uri_1x} 1x, {uri_2x} {RETINA_FACTOR}x"
      style="width: auto; max-width: {css_width}px; height: {CARD_IMG_CSS_HEIGHT}px; object-fit: contain; display: block; margin-left: auto; margin-right: auto;"
      alt="Product Image"
    />
    """

@st.cache_data(show_spinner=False)
def get_cached_product_image_html(product_id: str, image_bytes: bytes, css_width: int):
    """Processes and caches the image HTML against the product_id."""
    if not image_bytes:
        # UPDATED: Use fixed height for placeholder
        return f'<div style="width: {css_width}px; height: {CARD_IMG_CSS_HEIGHT}px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; border-radius: 8px;">📷 No image</div>'
    return build_img_srcset(image_bytes, css_width)


# --- CORE DATA FUNCTIONS ---
def create_new_project(name, description=""):
    """Create a new project with an empty data structure."""
    project_id = str(uuid.uuid4())
    project = {
        'id': project_id,
        'name': name,
        'description': description,
        'created_date': datetime.now().isoformat(),
        'last_modified': datetime.now().isoformat(),
        'products_data': [],
        'attributes': [],
        'distributions': [],
        'filter_options': {},
        'pending_changes': {},
        'uploaded_images': {},
        'excel_filename': None
    }
    st.session_state.projects[project_id] = project
    return project_id

def update_project_timestamp(project_id):
    """Update the last modified timestamp for a project."""
    if project_id in st.session_state.projects:
        st.session_state.projects[project_id]['last_modified'] = datetime.now().isoformat()

def sanitize_attr(attr):
    """Sanitize attribute names for use as keys."""
    return attr.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace('+', 'plus').replace(':', '')

def get_filter_options(products, attributes):
    """Generate filter options from products data."""
    opts = defaultdict(set)
    for p in products:
        for attr in attributes:
            opts[attr].add(p["attributes"][attr])
    return {k: sorted(v) for k, v in opts.items()}

def find_image_for_product(product_id, uploaded_images):
    """Find matching image for a product ID."""
    for filename, file_data in uploaded_images.items():
        name_part = os.path.splitext(filename)[0].lower()
        if name_part == str(product_id).lower():
            return file_data
    return None

def create_image_lookup(uploaded_images: dict) -> dict:
    """
    Creates a dictionary for instant image lookups.
    Key: product_id (lowercase string), Value: image_bytes.
    This is much faster than looping.
    """
    return {
        os.path.splitext(filename)[0].lower(): file_data
        for filename, file_data in uploaded_images.items()
    }

def load_and_parse_excel(uploaded_file, image_url_mappings):
    """
    More robustly parse an uploaded Excel file and return structured data,
    mapping products to their IMAGE URLs instead of raw bytes.
    """
    if uploaded_file is None:
        return [], [], [], {}

    # --- OPTIMIZATION: Create the URL lookup dictionary ONCE ---
    # The keys are product IDs, and the values are the image URLs.
    url_lookup = {}
    for product_id, meta in image_url_mappings.items():
        if isinstance(meta, dict) and meta.get("public_url"):
            url_lookup[product_id.lower()] = meta["public_url"]
        elif isinstance(meta, str): # Legacy support
            url_lookup[product_id.lower()] = meta
    
    try:
        df = pd.read_excel(uploaded_file)
        df.columns = [str(c).strip() for c in df.columns]

        id_col = next((c for c in df.columns if 'product id' in c.lower()), None)
        desc_col = next((c for c in df.columns if 'description' in c.lower()), None)
        price_col = next((c for c in df.columns if 'price' in c.lower()), None)

        if not id_col or not desc_col:
            st.error("❌ Critical Error: Could not find 'Product ID' and 'Description' columns in the Excel file.")
            st.stop()
        
        attributes = [h for h in df.columns if h.startswith("ATT")]
        distributions = [h for h in df.columns if h.startswith("DIST")]
        
        products = []
        for idx, row in df.iterrows():
            
            # --- ROBUST ID HANDLING ---
            raw_id = row[id_col]
            # If Excel gave us a float like 123.0, convert to integer 123 first
            if isinstance(raw_id, float) and raw_id.is_integer():
                product_id = str(int(raw_id)).strip()
            else:
                product_id = str(raw_id).strip()
            
            # Double check for string ".0" suffix just in case
            if product_id.endswith(".0"):
                product_id = product_id[:-2]
            # --------------------------

            description = str(row[desc_col]).strip()
            
            try:
                price_val = float(row[price_col]) if price_col and not pd.isna(row[price_col]) else 0.0
                price_str = f"{price_val:.2f}"
            except (ValueError, TypeError):
                price_str = "0.00"
            
            # --- OPTIMIZATION: Use the fast dictionary lookup to get the URL ---
            image_url = url_lookup.get(product_id.lower())
            
            attr_data = {a: str(row[a]).strip() for a in attributes}
            dist_data = {d: "X" in str(row[d]).upper() for d in distributions}
            
            products.append({
                "original_index": idx, "product_id": product_id, 
                "image_data": None, # We no longer use raw bytes here
                "image_url": image_url, # We now use the URL
                "description": description, "original_description": description,
                "price": price_str, "original_price": price_str,
                "attributes": attr_data, "original_attributes": attr_data.copy(),
                "distribution": dist_data
            })
        
        filter_options = get_filter_options(products, attributes)
        return products, attributes, distributions, filter_options

    except Exception as e:
        st.error(f"❌ Failed to parse the Excel file. Please check its format. Error: {e}")
        return [], [], [], {}
        
        
def apply_filters(products, attribute_filters, distribution_filters, pending_changes=None, show_pending_only=False):
    """Apply filters to products and return filtered list."""
    if not products:
        return []

    filtered_products = products

    # --- NEW: Filter by Pending Changes ---
    if show_pending_only and pending_changes:
        # Normalize keys to strings to ensure we catch both int/str formats
        pending_keys = set(str(k) for k in pending_changes.keys())
        filtered_products = [
            p for p in filtered_products 
            if str(p["original_index"]) in pending_keys
        ]
    # --------------------------------------
    
    for attr, selected_values in attribute_filters.items():
        if selected_values and 'All' not in selected_values:
            filtered_products = [
                p for p in filtered_products if p["attributes"].get(attr, "") in selected_values
            ]

    if distribution_filters and 'All' not in distribution_filters:
        filtered_products = [
            p for p in filtered_products if any(
                p["distribution"].get(orig_dist, False)
                for dist in distribution_filters
                for orig_dist in p["distribution"] if orig_dist.replace('DIST ', '') == dist
            )
        ]
        
    return filtered_products

    
def create_download_excel(project):
    """Create Excel file, highlighting ONLY the most recently applied changes."""
    if not project['products_data']:
        return None
    
    attributes = project['attributes']
    distributions = project['distributions']
    headers = ["Product ID", "Description"] + attributes + distributions + ["Price"]
    
    data = []
    for product in project['products_data']:
        row = [product["product_id"], product["description"]]
        row.extend(product["attributes"].get(attr, "") for attr in attributes)
        row.extend("X" if product["distribution"].get(dist, False) else "" for dist in distributions)
        try:
            p_val = float(product["price"]) if product["price"] else 0.0
        except:
            p_val = 0.0
        row.append(p_val)
        data.append(row)
    
    df = pd.DataFrame(data, columns=headers)
    
    from openpyxl.styles import PatternFill
    output = BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
        workbook = writer.book
        ws = writer.sheets['Products']
        yellow_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
        
        # Retrieve the history of the last batch of applied changes
        last_applied = project.get('last_applied_changes', {})
        
        for i, product in enumerate(project['products_data']):
            excel_row = i + 2
            
            # Get changes for this specific product ID (handle int vs string keys)
            idx = product['original_index']
            changes = last_applied.get(idx) or last_applied.get(str(idx)) or {}
            
            # If this product wasn't in the last batch, skip it
            if not changes:
                continue

            # --- Check Description (Column 2) ---
            if 'description' in changes:
                ws.cell(row=excel_row, column=2).fill = yellow_fill
            
            # --- Check Attributes (Columns 3 to 3+len(attrs)) ---
            for j, attr in enumerate(attributes):
                if attr in changes:
                    col_idx = 3 + j
                    ws.cell(row=excel_row, column=col_idx).fill = yellow_fill
            
            # --- Check Price (Last Column) ---
            if 'price' in changes:
                price_col = len(headers)
                ws.cell(row=excel_row, column=price_col).fill = yellow_fill

    return output.getvalue()


# --- UI DISPLAY FUNCTIONS ---
def display_product_card(product, project, visible_attributes):
    """Display a single product card."""
    with st.container(border=True):
        
        image_html = get_image_html_from_url(
            product_id=product["product_id"], 
            image_url=product.get("image_url"), 
            css_width=CARD_IMG_CSS_WIDTH
        )
        st.markdown(image_html, unsafe_allow_html=True)
        
        # --- LOGIC UPDATE: Check Pending Changes for Red Highlighting ---
        # Instead of comparing current vs original, we check if the field 
        # is explicitly listed in the pending_changes dictionary.
        idx = product["original_index"]
        pending = project.get('pending_changes', {})
        
        # Handle both integer (runtime) and string (JSON/Firestore) keys
        product_changes = pending.get(idx) or pending.get(str(idx)) or {}
        # ----------------------------------------------------------------

        card_content = ""
        if "Description" in visible_attributes:
            # Only red if "description" is in the pending changes for this product
            desc_class = "changed-attribute" if "description" in product_changes else ""
            card_content += f'<p class="{desc_class}" style="margin-bottom: 4px;"><strong>{product["description"]}</strong></p>'
        
        if "Price" in visible_attributes and product.get("price"):
            # Only red if "price" is in the pending changes
            price_class = "changed-attribute" if "price" in product_changes else ""
            card_content += f'<p class="{price_class}" style="margin-bottom: 8px;">Price: ${product["price"]}</p>'
        
        # Attributes Loop
        for attr in project.get('attributes', []):
            if attr in visible_attributes:
                current_val = product["attributes"].get(attr, "N/A")
                
                # Only red if this specific attribute key is in pending changes
                is_changed = attr in product_changes
                
                style = 'color: #B22222; font-weight: bold;' if is_changed else ''
                clean_attr = attr.replace('ATT ', '')
                
                card_content += f'<div style="font-size: 12px; line-height: 1.4; {style}"><strong>{clean_attr}:</strong> {current_val}</div>'
        
        st.markdown(card_content, unsafe_allow_html=True)

        if not st.session_state.get("client_mode", False):
            if st.button(f"Edit", key=f"edit_{product['original_index']}_{project['id']}", use_container_width=True):
                st.session_state.editing_product = product
                st.rerun()

def show_edit_modal(product, project):
    @st.dialog(f"Edit Product: {product['product_id']}")
    def edit_product_dialog():
        if product.get("image_url"):
            st.markdown(f'<div style="text-align: center; margin-bottom: 20px;"><img src="{product["image_url"]}" style="width:{MODAL_IMG_CSS_WIDTH}px; height:auto;"></div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        new_description = col1.text_input("Description", value=product["description"])
        new_price = col2.text_input("Price", value=product["price"])
        
        st.subheader("Attributes")
        attr_cols = st.columns(2)
        new_attributes = {}
        for i, attr in enumerate(project['attributes']):
            with attr_cols[i % 2]:
                current_val = product["attributes"][attr]
                options = project['filter_options'].get(attr, [])
                if current_val not in options:
                    options.insert(0, current_val)
                
                clean_attr = attr.replace('ATT ', '')
                index = options.index(current_val) if current_val in options else 0
                
                selected_option = st.selectbox(
                    f"{clean_attr}", options + ["[Custom Value]"], index=index,
                    key=f"modal_attr_{attr}_{product['original_index']}"
                )
                
                if selected_option == "[Custom Value]":
                    new_attributes[attr] = st.text_input(
                        f"Custom {clean_attr}", value=current_val, 
                        key=f"modal_custom_{attr}_{product['original_index']}"
                    )
                else:
                    new_attributes[attr] = selected_option
        
        st.markdown("---")
        _, save_col, cancel_col, _ = st.columns([1, 1, 1, 1])
        if save_col.button("💾 Save Changes", type="primary", use_container_width=True):
            idx = product["original_index"]
            if idx not in project['pending_changes']:
                project['pending_changes'][idx] = {}

            if new_description != product["description"]:
                project['pending_changes'][idx]["description"] = new_description
                product["description"] = new_description
            
            if new_price != product["price"]:
                project['pending_changes'][idx]["price"] = new_price
                product["price"] = new_price
            
            for attr, new_val in new_attributes.items():
                if new_val != product["attributes"][attr]:
                    project['pending_changes'][idx][attr] = new_val
                    product["attributes"][attr] = new_val
                    if new_val not in project['filter_options'].get(attr, []):
                        project['filter_options'].setdefault(attr, []).append(new_val)
                        project['filter_options'][attr].sort()
            
            update_project_timestamp(project['id'])
            st.success("✅ Changes saved!")
            del st.session_state.editing_product
            st.rerun()
        
        if cancel_col.button("❌ Cancel", use_container_width=True):
            del st.session_state.editing_product
            st.rerun()

    edit_product_dialog()


# --- PAGE VIEW FUNCTIONS ---
def show_projects_page():
    """Display the main projects page."""
    st.title("📁 Interactive Product Grid")

    with st.container():
        st.markdown('<div class="new-project-section"><h2>🚀 Start a New Project</h2><p>Create a new product grid project with your Excel data and images</p></div>', unsafe_allow_html=True)
        if st.button("➕ Create New Project", type="primary", use_container_width=True):
            st.session_state.page = 'create_project'
            st.rerun()

    summaries = sorted(st.session_state.get("project_summaries", []), key=lambda s: s.get('last_modified', ''), reverse=True)

    if summaries:
        st.header("📋 Your Projects")
        for s in summaries:
            with st.container(border=True):
                col1, col2, col3 = st.columns([5, 1, 1])
                with col1:
                    st.subheader(s.get("name", "Untitled"))
                    if s.get("description"): st.write(s.get("description"))
                    try: lm_disp = datetime.fromisoformat(s['last_modified']).strftime("%Y-%m-%d %H:%M")
                    except: lm_disp = "—"
                    st.markdown(f"""
                    <div class="project-stats">
                        📦 {s.get("num_products", 0)} products | 
                        🏷️ {s.get("num_attributes", 0)} attributes | 
                        ✏️ {s.get("num_pending_changes", 0)} pending | 
                        🕒 Modified: {lm_disp}
                    </div>
                    """, unsafe_allow_html=True)
                
                if col2.button("Open", key=f"open_{s['id']}", type="primary", use_container_width=True):
                    if ensure_project_loaded(s['id']):
                        st.query_params["project"] = s['id']
                        st.session_state.current_project = s['id']
                        st.session_state.page = 'grid'
                        st.rerun()
                        return
                    else: st.error("Could not load project.")

                if col3.button("🗑️", key=f"delete_{s['id']}", use_container_width=True):
                    mgr = st.session_state.get("firestore_manager")
                    if mgr and mgr.delete_project(s['id']):
                        st.session_state.project_summaries = [p for p in st.session_state.project_summaries if p["id"] != s['id']]
                        if s['id'] in st.session_state.projects: del st.session_state.projects[s['id']]
                        if st.session_state.current_project == s['id']: st.session_state.current_project = None
                        st.rerun()

def show_create_project_page():
    """Display the create new project page."""
    st.title("🆕 Create New Project")
    if st.button("← Back to Projects"):
        st.session_state.page = 'projects'
        st.rerun()
    
    with st.form(key="new_project_form"):
        project_name = st.text_input("Project Name *", placeholder="e.g., Q1 2024 Product Launch")
        
        # --- REMOVED: Description Input ---
        
        col1, col2 = st.columns(2)
        uploaded_excel = col1.file_uploader("Upload Product Excel Grid *", type=['xlsx', 'xls'])
        uploaded_images = col2.file_uploader("Upload Product Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
        
        # --- Match Preview Logic ---
        if uploaded_excel and uploaded_images:
            try:
                df_preview = pd.read_excel(uploaded_excel)
                df_preview.columns = [str(c).strip() for c in df_preview.columns]
                id_col = next((c for c in df_preview.columns if 'product id' in c.lower()), None)
                
                if id_col:
                    excel_ids = set()
                    for x in df_preview[id_col].dropna():
                        if isinstance(x, float) and x.is_integer():
                            excel_ids.add(str(int(x)).strip().lower())
                        else:
                            clean_id = str(x).strip().lower()
                            if clean_id.endswith(".0"): clean_id = clean_id[:-2]
                            excel_ids.add(clean_id)
                    
                    image_names = set(os.path.splitext(img.name)[0].strip().lower() for img in uploaded_images)
                    
                    matches = excel_ids.intersection(image_names)
                    match_count = len(matches)
                    
                    if match_count == 0:
                        st.error(f"⚠️ **0 matches found!** Check your filenames. (Excel has {len(excel_ids)} IDs, Uploaded {len(image_names)} images)")
                        st.write("Example Excel ID:", list(excel_ids)[0] if excel_ids else "None")
                        st.write("Example Filename:", list(image_names)[0] if image_names else "None")
                    else:
                        st.success(f"✅ **{match_count}** images matched out of {len(uploaded_images)} uploaded.")
            except Exception:
                pass 
        
        submitted = st.form_submit_button("🚀 Create Project", type="primary", use_container_width=True)
        
        if submitted:
            if not project_name or not uploaded_excel:
                st.warning("Please provide a project name and an Excel file.")
            else:
                with st.spinner("Creating project and uploading assets..."):
                    # 1. Parse the Excel file. 
                    excel_bytes = uploaded_excel.getvalue()
                    products, attrs, dists, filters = load_and_parse_excel(BytesIO(excel_bytes), {})
                    
                    # 2. Manually match uploaded images
                    if uploaded_images:
                        product_lookup = {p['product_id'].lower().strip(): p for p in products}
                        for img in uploaded_images:
                            fname_id = os.path.splitext(img.name)[0].lower().strip()
                            if fname_id in product_lookup:
                                product_lookup[fname_id]['image_data'] = (img.name, img.getvalue())

                    # 3. Create structure (Updated to remove description argument)
                    project_id = create_new_project(project_name)
                    project = st.session_state.projects[project_id]
                    
                    project.update({
                        'products_data': products,
                        'attributes': attrs,
                        'distributions': dists,
                        'filter_options': filters,
                        'excel_file_data': excel_bytes,
                        'excel_filename': uploaded_excel.name,
                    })
                    
                    # 4. Save to cloud
                    if st.session_state.get('firestore_manager'):
                        st.session_state.firestore_manager.save_project(project_id, project)
                    
                    if project_id in st.session_state.projects:
                        del st.session_state.projects[project_id]
                    
                    ensure_project_loaded(project_id)

                    st.success(f"✅ Project '{project_name}' created!")
                    st.balloons()
                    time.sleep(1)
                    
                    st.query_params["project"] = project_id 
                    st.session_state.current_project = project_id
                    st.session_state.page = 'grid'
                    st.rerun()
                    

def show_summary_page():
    """Shows a summary dashboard with pie charts, price distribution, and bulk editing."""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("No project loaded.")
        st.session_state.page = 'projects'; st.rerun()
        return

    project = st.session_state.projects[st.session_state.current_project]
    project_id = project['id']
    is_admin = not st.session_state.get("client_mode", False)

    # --- Header ---
    c1, c2 = st.columns([6, 1])
    with c1:
        st.title(f"📊 Summary: {project['name']}")
    with c2:
        if st.button("⬅️ Back to Grid", use_container_width=True):
            st.session_state.page = 'grid'
            st.rerun()
            
    # --- Sidebar: Options & Filters ---
    all_attrs = project.get('attributes', [])
    clean_attrs = [a.replace('ATT ', '') for a in all_attrs]
    
    with st.sidebar:
        st.header("View Options")
        selected_indices = st.multiselect(
            "Select Attributes to Chart:", 
            range(len(all_attrs)), 
            format_func=lambda i: clean_attrs[i],
            default=range(len(all_attrs))
        )
        selected_attrs = [all_attrs[i] for i in selected_indices]
        
        st.divider()
        
        st.header("🔍 Filters")
        attribute_filters = {
            attr: st.multiselect(
                attr.replace('ATT ', ''), 
                ['All'] + project['filter_options'].get(attr, []), 
                default=['All'], 
                key=f"sum_filt_{attr}"
            ) 
            for attr in project['attributes']
        }
        
        dist_filters = []
        if project['distributions']:
            dist_filters = st.multiselect(
                "Distribution", 
                ['All'] + [d.replace('DIST ', '') for d in project['distributions']], 
                default=['All'], 
                key="sum_filt_dist"
            )

        st.divider()
        status_container = st.container()

    # --- Data Processing (With Filters) ---
    filtered_products = apply_filters(
        project['products_data'], 
        attribute_filters, 
        dist_filters,
        project.get('pending_changes', {}),
        False 
    )

    df = pd.DataFrame(filtered_products)
    
    if df.empty:
        st.warning("No product data matches the current filters.")
        return

    if 'attributes' in df.columns:
        attr_df = pd.DataFrame(list(df['attributes']))
        df = pd.concat([df.drop('attributes', axis=1), attr_df], axis=1)

    pending_renames = [] 
    
    st.markdown(f"### Showing {len(df)} Products")

    # --- 1. Attribute Charts (Rendered First) ---
    for attr in selected_attrs:
        with st.container(border=True):
            col_header, _ = st.columns([3, 1])
            original_attr_name = attr.replace('ATT ', '')
            
            if is_admin:
                new_attr_name_input = st.text_input(
                    f"Attribute Name ({attr})", 
                    value=original_attr_name, 
                    key=f"rename_attr_{attr}",
                    label_visibility="collapsed"
                )
                if new_attr_name_input != original_attr_name:
                    full_new_name = f"ATT {new_attr_name_input}"
                    pending_renames.append(("ATTR", attr, full_new_name, None))
                    st.caption(f"✏️ *Renaming to: {full_new_name}*")
            else:
                st.subheader(original_attr_name)

            c_chart, c_data = st.columns([1, 1])
            
            with c_chart:
                if attr in df.columns:
                    counts = df[attr].value_counts().reset_index()
                    counts.columns = ['Option', 'Count']
                    if not counts.empty:
                        fig = px.pie(counts, values='Count', names='Option', hole=0.4)
                        
                        fig.update_traces(textinfo='none') 
                        
                        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("No data.")

            with c_data:
                st.write("**Edit Option Names**" if is_admin else "**Options Legend**")
                options = sorted(list(df[attr].dropna().unique())) if attr in df.columns else []
                
                container = st.container()
                if len(options) > 10:
                    container = st.expander(f"Show all {len(options)} options")
                
                with container:
                    for val in options:
                        if is_admin:
                            c_opt_1, c_opt_2 = st.columns([3, 7])
                            count = len(df[df[attr]==val])
                            c_opt_1.write(f"{val} ({count})")
                            
                            new_val = c_opt_2.text_input(
                                "Rename", value=val, key=f"rename_val_{attr}_{val}", label_visibility="collapsed"
                            )
                            if new_val != val:
                                pending_renames.append(("OPTION", val, new_val, attr))
                        else:
                            count = len(df[df[attr]==val])
                            st.write(f"- {val} ({count})")

    # --- 2. Price Distribution (Moved to Bottom) ---
    if 'price' in df.columns:
        df['price_num'] = pd.to_numeric(df['price'], errors='coerce')
        valid_prices = df.dropna(subset=['price_num'])
        
        if not valid_prices.empty:
            with st.container(border=True):
                st.subheader("Price Distribution")
                
                fig = px.histogram(
                    valid_prices, 
                    x="price_num", 
                    nbins=20, 
                    labels={'price_num': 'Price ($)'},
                    template="plotly_white",
                    color_discrete_sequence=['#636EFA']
                )
                # UPDATED: Set explicit height to 250px
                fig.update_layout(bargap=0.1, margin=dict(t=20, b=20), height=250)
                st.plotly_chart(fig, use_container_width=True)

    # --- Save Logic ---
    if is_admin and pending_renames:
        with status_container:
            st.warning(f"⚠️ {len(pending_renames)} Pending Changes")
            if st.button("💾 SAVE ALL CHANGES", type="primary", use_container_width=True):
                with st.spinner("Saving changes..."):
                    apply_bulk_renames(project, pending_renames)
                    auto_save_project(project_id)
                    update_project_timestamp(project_id)
                    st.success("Saved!")
                    time.sleep(1)
                    st.rerun()

def apply_bulk_renames(project, renames):
    """
    Applies renames to project data AND updates original_attributes 
    so the changes are accepted as the new baseline (no red text).
    """
    products = project['products_data']
    
    # 1. Option Renames
    option_renames = [r for r in renames if r[0] == "OPTION"]
    for _, old_val, new_val, parent_attr in option_renames:
        for p in products:
            # Update Current Value
            if p['attributes'].get(parent_attr) == old_val:
                p['attributes'][parent_attr] = new_val
                # FIX: Sync Original to Current so it turns Green (accepted as new baseline)
                p['original_attributes'][parent_attr] = new_val
            
            # Update Original/Baseline Value (fallback if Current didn't match but Original did)
            elif p['original_attributes'].get(parent_attr) == old_val:
                p['original_attributes'][parent_attr] = new_val
        
        # Update Filter List
        if parent_attr in project['filter_options']:
            opts = project['filter_options'][parent_attr]
            if old_val in opts:
                opts.remove(old_val)
                if new_val not in opts: opts.append(new_val)
                opts.sort()

    # 2. Attribute Renames
    attr_renames = [r for r in renames if r[0] == "ATTR"]
    for _, old_attr, new_attr, _ in attr_renames:
        if old_attr == new_attr: continue
        
        # Update List
        if old_attr in project['attributes']:
            idx = project['attributes'].index(old_attr)
            project['attributes'][idx] = new_attr
            
        # Update Product Keys (Current & Original)
        for p in products:
            val = None
            if old_attr in p['attributes']:
                val = p['attributes'].pop(old_attr)
                p['attributes'][new_attr] = val
            
            if old_attr in p['original_attributes']:
                p['original_attributes'][new_attr] = p['original_attributes'].pop(old_attr)
            elif val is not None:
                # FIX: Self-healing - if key was missing in original, create it to prevent Red "N/A"
                p['original_attributes'][new_attr] = val
        
        # Update Filter Keys
        if old_attr in project['filter_options']:
            project['filter_options'][new_attr] = project['filter_options'].pop(old_attr)

        # --- Update Session State View Options ---
        view_key = f"view_options_{project['id']}"
        if view_key in st.session_state:
            view_opts = st.session_state[view_key]
            
            # Update 'visible_attributes' list
            if 'visible_attributes' in view_opts:
                if old_attr in view_opts['visible_attributes']:
                    idx = view_opts['visible_attributes'].index(old_attr)
                    view_opts['visible_attributes'][idx] = new_attr
            
            # Update 'sort_by' if currently sorted by the renamed attribute
            if view_opts.get('sort_by') == old_attr:
                view_opts['sort_by'] = new_attr


def show_grid_page():
    """Display the product grid for the current project."""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("No project selected or project not found.")
        st.session_state.page = 'projects'; st.rerun()
        return
    
    project = st.session_state.projects[st.session_state.current_project]
    project_id = project['id']
    is_admin = not st.session_state.get("client_mode", False)

    PRODUCTS_PER_PAGE = 50
    page_state_key = f'page_number_{project_id}'
    if page_state_key not in st.session_state:
        st.session_state[page_state_key] = 1

    def increment_page(): st.session_state[page_state_key] += 1
    def decrement_page(): st.session_state[page_state_key] -= 1

    def render_pagination_controls(total_pages):
        current_page = st.session_state[page_state_key]
        st.write("---")
        p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
        p_col1.button("⬅️ Previous", on_click=decrement_page, disabled=(current_page <= 1), key="prev_top", use_container_width=True)
        p_col2.selectbox(f"Page {current_page} of {total_pages}", range(1, total_pages + 1), key=page_state_key, label_visibility="collapsed")
        p_col3.button("Next ➡️", on_click=increment_page, disabled=(current_page >= total_pages), key="next_top", use_container_width=True)
        st.write("---")

    h_col1, h_col2, h_col3, h_col4 = st.columns([4, 3, 3, 2])
    with h_col1:
        st.title(f"📊 {project['name']}")
    
    # --- UPDATED: Allow Client Access to Summary View ---
    with h_col2:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        # This button is now visible to everyone (Clients & Admins)
        if st.button("📈 Summary View", use_container_width=True):
            st.session_state.page = 'summary'
            st.rerun()

        # Admin-only tools (Excel Replace) remain protected
        if is_admin:
            with h_col2:
                st.markdown("<div><br></div>", unsafe_allow_html=True)
                # This button is now visible to everyone (Clients & Admins) - assuming you kept the previous change
                if st.button("📈 Summary View", use_container_width=True):
                    st.session_state.page = 'summary'
                    st.rerun()
    
                # --- DYNAMIC KEY: Ensures uploader clears after use ---
                excel_ver_key = f"excel_ver_{project_id}"
                if excel_ver_key not in st.session_state: 
                    st.session_state[excel_ver_key] = 0
                
                new_excel = st.file_uploader(
                    "Replace Source Grid", 
                    type=['xlsx', 'xls'], 
                    key=f"replace_{project_id}_{st.session_state[excel_ver_key]}", 
                    label_visibility="collapsed"
                )
    
    with h_col3:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        excel_data = create_download_excel(project)
        if excel_data:
            st.download_button("📥 Download Current Grid", excel_data, f"{project['name']}_updated.xlsx", use_container_width=True)
    
    with h_col4:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        if is_admin:
            if st.button("← Back to Projects", use_container_width=True):
                st.session_state.page = 'projects'
                st.query_params.clear()
                if page_state_key in st.session_state:
                    del st.session_state[page_state_key]
                st.rerun()

    if is_admin and 'new_excel' in locals() and new_excel:
        with st.spinner("Parsing new file and saving to cloud... Please wait."):
            products, attrs, dists, filters = load_and_parse_excel(new_excel, project.get('image_mappings', {}))
            project.update({
                'products_data': products, 'attributes': attrs, 'distributions': dists,
                'filter_options': filters, 'excel_filename': new_excel.name, 'pending_changes': {}
            })
            view_options_key = f'view_options_{project_id}'
            if view_options_key in st.session_state:
                del st.session_state[view_options_key]
            update_project_timestamp(project_id)
            auto_save_project(project_id)
            st.success(f"Project updated with '{new_excel.name}'. Reloading...")
            
            # --- FIX: Increment version to force a fresh uploader widget ---
            st.session_state[excel_ver_key] += 1
            # ---------------------------------------------------------------

            time.sleep(1); st.rerun()
            return

    if is_admin and project.get('pending_changes'):
        st.info(f"You have **{len(project['pending_changes'])}** pending change(s). Click 'Apply All Changes' to make them permanent.")
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("✅ Apply All Changes", type="primary", use_container_width=True):
                with st.spinner("Applying..."):
                    # --- NEW: Save pending changes to 'last_applied' history before clearing ---
                    # This allows the Excel download to know what was just updated.
                    project['last_applied_changes'] = project['pending_changes'].copy()
                    
                    for product in project['products_data']:
                        # Handle string/int key differences
                        idx = product['original_index']
                        changes = project['pending_changes'].get(idx) or project['pending_changes'].get(str(idx))
                        
                        if changes:
                            product['original_description'] = product['description']
                            product['original_price'] = product['price']
                            product['original_attributes'] = product['attributes'].copy()
                    
                    project['pending_changes'] = {}
                    update_project_timestamp(project_id)
                    auto_save_project(project_id)
                    st.success("Saved! These changes will now be highlighted in the Excel download.")
                    time.sleep(1); st.rerun()
        with action_cols[1]:
            if st.button("❌ Reset All Changes", use_container_width=True):
                with st.spinner("Reverting..."):
                    for product in project['products_data']:
                        idx = product['original_index']
                        changes = project['pending_changes'].get(idx) or project['pending_changes'].get(str(idx))
                        
                        if changes:
                            product['description'] = product['original_description']
                            product['price'] = product['original_price']
                            product['attributes'] = product['original_attributes'].copy()
                    project['pending_changes'] = {}
                    st.warning("Discarded."); time.sleep(1); st.rerun()

    if is_admin:
        with st.container(border=True):
            st.markdown('<p style="font-size: 1.1rem; font-weight: bold; margin-top: -5px; margin-bottom: 5px;">🖼️ Add / Replace Images</p>', unsafe_allow_html=True)
            
            # --- 1. DYNAMIC KEY SETUP: Initialize a version counter ---
            img_ver_key = f"img_ver_{project_id}"
            if img_ver_key not in st.session_state:
                st.session_state[img_ver_key] = 0

            # --- 2. USE DYNAMIC KEY: Appending the version ensures a fresh widget on increment ---
            new_images = st.file_uploader(
                "Upload new images.", 
                type=['png', 'jpg', 'jpeg'], 
                accept_multiple_files=True, 
                key=f"add_images_{project_id}_{st.session_state[img_ver_key]}", 
                label_visibility="collapsed"
            )
            
            if new_images:
                with st.spinner(f"Matching {len(new_images)} image(s)..."):
                    product_lookup = {p['product_id'].lower().strip(): p for p in project['products_data']}
                    updated_count = 0
                    for image_file in new_images:
                        pid = os.path.splitext(image_file.name)[0].lower().strip()
                        if pid in product_lookup:
                            product_lookup[pid]['image_data'] = (image_file.name, image_file.getvalue())
                            updated_count += 1
                    if updated_count > 0:
                        st.text(f"Found {updated_count} matches. Uploading...")
                        updated_mappings = auto_save_project(project_id)
                        if updated_mappings:
                            project['image_mappings'] = updated_mappings
                            for p_id, p_data in product_lookup.items():
                                if p_id in updated_mappings and "public_url" in updated_mappings[p_id]:
                                    p_data['image_url'] = updated_mappings[p_id]["public_url"]
                            st.success(f"✅ Added {updated_count} image(s).")
                            
                            # --- 3. INCREMENT VERSION: This forces the uploader to reset ---
                            st.session_state[img_ver_key] += 1
                            time.sleep(1); st.rerun(); return
                        else: st.error("Save failed.")
                    else: st.warning(f"⚠️ No matches.")

    if 'editing_product' in st.session_state:
        show_edit_modal(st.session_state.editing_product, project)

    with st.container(border=True):
        st.markdown("""<style>.stMultiSelect div[data-baseweb="select"] > div:first-child {max-height: 100px; overflow-y: auto;} .stMultiSelect [data-baseweb="tag"] span {font-size: 12px !important;}</style>""", unsafe_allow_html=True)
        
        if f'view_options_{project_id}' not in st.session_state:
            st.session_state[f'view_options_{project_id}'] = {'visible_attributes': ['Description', 'Price'] + project['attributes'], 'sort_by': 'product_id', 'sort_ascending': True}
        view_options = st.session_state[f'view_options_{project_id}']
        
        all_fields = ['Description', 'Price'] + project['attributes']
        def fmt(name): return name.replace('ATT ', '')
        
        st.markdown('<p style="font-size: 1.1rem; font-weight: bold; margin-top: -5px; margin-bottom: 5px;">View & Sort Options</p>', unsafe_allow_html=True)
        v_col1, v_col2 = st.columns(2)
        v_col1.markdown("<p style='font-size: 13px; font-weight: bold; margin-bottom: 0px;'>Show Attributes:</p>", unsafe_allow_html=True)
        
        # --- FIX: Add Key & Safety Check ---
        ms_key = f"ms_vis_attr_{project_id}"
        
        # Safety: If the widget state contains old/invalid attributes (e.g. after a rename), 
        # force a reset to the source of truth (view_options) to prevent a crash.
        if ms_key in st.session_state:
            current_selection = st.session_state[ms_key]
            if not set(current_selection).issubset(set(all_fields)):
                del st.session_state[ms_key]

        view_options['visible_attributes'] = v_col1.multiselect(
            "Show Attributes:", 
            all_fields, 
            default=view_options['visible_attributes'], 
            format_func=fmt, 
            label_visibility="collapsed",
            key=ms_key  # Adding this key fixes the "double click" issue
        )
        # -----------------------------------
        
        s_opts = ['product_id'] + all_fields
        s_col1, s_col2 = v_col2.columns([2,1])
        s_col1.markdown("<p style='font-size: 13px; font-weight: bold; margin-bottom: 0px;'>Sort By:</p>", unsafe_allow_html=True)
        sort_by_index = s_opts.index(view_options['sort_by']) if view_options['sort_by'] in s_opts else 0
        view_options['sort_by'] = s_col1.selectbox("Sort By:", s_opts, index=sort_by_index, format_func=fmt, label_visibility="collapsed")
        s_col2.markdown("<p style='font-size: 13px; font-weight: bold; margin-bottom: 0px;'>Order:</p>", unsafe_allow_html=True)
        view_options['sort_ascending'] = s_col2.radio("Order:", ["🔼", "🔽"], horizontal=True, index=0 if view_options['sort_ascending'] else 1, label_visibility="collapsed") == "🔼"
        
    with st.sidebar:
        if is_admin:
            st.header("🔗 Share Project - NOT READY FOR CLIENTS")
            with st.expander("Generate Client Link"):
                base_url = "https://visualgridvg.streamlit.app/" 
                client_link = f"{base_url}?project={project_id}&mode=client"
                st.code(client_link, language="text")
                st.info("⚠️ This link opens the project in 'Read-Only' mode.")
            st.divider()

        st.header("🔍 Filters")

        show_pending_only = st.checkbox("Show Pending Changes Only", value=False)
        st.divider()
        
        attribute_filters = {attr: st.multiselect(attr.replace('ATT ', ''), ['All'] + project['filter_options'].get(attr, []), default=['All']) for attr in project['attributes']}
        dist_filters = st.multiselect("Distribution", ['All'] + [d.replace('DIST ', '') for d in project['distributions']], default=['All']) if project['distributions'] else []

    filtered_products = apply_filters(
        project['products_data'], 
        attribute_filters, 
        dist_filters,
        project.get('pending_changes', {}),
        show_pending_only
    )
    
    sort_by, is_ascending = view_options['sort_by'], view_options['sort_ascending']
    def get_sort_key(p):
        if sort_by == 'product_id': return int(p['product_id']) if p['product_id'].isdigit() else p['product_id']
        if sort_by == 'Description': return p['description'].lower()
        if sort_by == 'Price': return float(p.get('price', 0))
        return p['attributes'].get(sort_by, '').lower()
    
    sorted_products = sorted(filtered_products, key=get_sort_key, reverse=not is_ascending)
    st.markdown(f"### Showing {len(sorted_products)} of {len(project['products_data'])} products")

    total_pages = max(1, (len(sorted_products) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE)
    current_page = st.session_state[page_state_key] = min(st.session_state.get(page_state_key, 1), total_pages)
    
    if total_pages > 1: render_pagination_controls(total_pages)
        
    start_idx = (current_page - 1) * PRODUCTS_PER_PAGE
    products_to_display = sorted_products[start_idx : start_idx + PRODUCTS_PER_PAGE]
    
    if products_to_display:
        for i in range(0, len(products_to_display), 4):
            cols = st.columns(4)
            for j, product in enumerate(products_to_display[i : i + 4]):
                with cols[j]:
                    display_product_card(product, project, view_options['visible_attributes'])
    else:
        st.info("No products match the current filters.")
        
# --- MAIN APP ROUTER ---
def auto_save_project(project_id):
    """
    Save current project to Firestore and return the result from the save operation.
    """
    if st.session_state.get('firestore_manager'):
        project = st.session_state.projects[project_id]
        return st.session_state.firestore_manager.save_project(project_id, project)
    return False

def main():
    """Main application router."""
    # 1. Determine Mode
    if st.query_params.get("mode") == "client": st.session_state.client_mode = True
    else: st.session_state.client_mode = False

    # 2. Load Project from URL if present
    if "project" in st.query_params and not st.session_state.current_project:
        target_project_id = st.query_params["project"]
        if ensure_project_loaded(target_project_id):
            st.session_state.current_project = target_project_id
            st.session_state.page = 'grid'
        else:
            st.query_params.clear()
            st.error(f"Project {target_project_id} not found.")

    # 3. Client Mode Security & Routing
    if st.session_state.get("client_mode"):
        if not st.session_state.current_project:
            st.error("No project specified for client view.")
            return
        
        # FIX: Only force 'grid' if the user tries to access a restricted page.
        # This allows them to stay on 'summary' if they navigated there.
        if st.session_state.page not in ['grid', 'summary']:
            st.session_state.page = 'grid'

    # 4. Render Page
    if st.session_state.page == 'projects': show_projects_page()
    elif st.session_state.page == 'create_project': show_create_project_page()
    elif st.session_state.page == 'grid': show_grid_page()
    elif st.session_state.page == 'summary': show_summary_page()

if __name__ == "__main__":
    main()
