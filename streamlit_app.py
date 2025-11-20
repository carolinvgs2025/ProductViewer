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
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {display:none;}
div[data-testid="stToolbar"] {visibility: hidden;}
div[data-testid="stDecoration"] {visibility: hidden;}
div[data-testid="stStatusWidget"] {visibility: hidden;}
#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}
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
        padding: 10px;
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
MODAL_IMG_CSS_WIDTH = 300
RETINA_FACTOR = 2

@st.cache_data(show_spinner=False)
def get_image_html_from_url(product_id: str, image_url: str, css_width: int):
    """Creates a simple <img> tag from a URL. Caches against the product_id."""
    if not image_url:
        return f'<div style="height: {css_width}px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; border-radius: 8px;">📷 No image</div>'
    
    return f'<img src="{image_url}" style="width:{css_width}px;height:auto;display:block;margin-left:auto;margin-right:auto;image-rendering:auto;" alt="Product Image">'

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
    return f"""
    <img
      src="{uri_1x}"
      srcset="{uri_1x} 1x, {uri_2x} {RETINA_FACTOR}x"
      style="width:{css_width}px;height:auto;display:block;margin-left:auto;margin-right:auto;image-rendering:auto;"
      alt="Product Image"
    />
    """

@st.cache_data(show_spinner=False)
def get_cached_product_image_html(product_id: str, image_bytes: bytes, css_width: int):
    """
    Processes and caches the image HTML against the product_id.
    This prevents re-processing the same image on every rerun, boosting performance.
    """
    if not image_bytes:
        return f'<div style="height: {css_width}px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; border-radius: 8px;">📷 No image</div>'
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
            product_id = str(row[id_col]).strip()
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
        
        
def apply_filters(products, attribute_filters, distribution_filters):
    """Apply filters to products and return filtered list."""
    if not products:
        return []

    filtered_products = products
    
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
    """Create Excel file with current changes for download."""
    if not project['products_data']:
        return None
    
    data = []
    for product in project['products_data']:
        row = [product["product_id"], product["description"]]
        row.extend(product["attributes"].get(attr, "") for attr in project['attributes'])
        row.extend("X" if product["distribution"].get(dist, False) else "" for dist in project['distributions'])
        row.append(float(product["price"]) if product["price"] else 0.0)
        data.append(row)
    
    headers = ["Product ID", "Description"] + project['attributes'] + project['distributions'] + ["Price"]
    df = pd.DataFrame(data, columns=headers)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    
    return output.getvalue()


# --- UI DISPLAY FUNCTIONS ---
def display_product_card(product, project, visible_attributes):
    """
    Display a single product card using the high-performance image URL.
    This function no longer processes raw image bytes, making it much faster.
    """
    with st.container():
        st.markdown('<div class="product-card">', unsafe_allow_html=True)
        
        # --- OPTIMIZATION: Use the image URL directly ---
        # This calls the simple function that just creates an <img> tag from a URL.
        # The user's browser handles the loading, not your Streamlit app.
        image_html = get_image_html_from_url(
            product_id=product["product_id"], 
            image_url=product.get("image_url"), # Use .get() for safety
            css_width=CARD_IMG_CSS_WIDTH
        )
        st.markdown(image_html, unsafe_allow_html=True)
        
        # Build the text content for the card
        card_content = ""
        if "Description" in visible_attributes:
            desc_class = "changed-attribute" if product["description"] != product["original_description"] else ""
            card_content += f'<p class="{desc_class}"><strong>{product["description"]}</strong></p>'
        
        if "Price" in visible_attributes and product.get("price"):
            price_class = "changed-attribute" if product["price"] != product["original_price"] else ""
            card_content += f'<p class="{price_class}">Price: ${product["price"]}</p>'
        
        for attr in project.get('attributes', []):
            if attr in visible_attributes:
                current_val = product["attributes"].get(attr, "N/A")
                original_val = product["original_attributes"].get(attr, "N/A")
                attr_class = "changed-attribute" if current_val != original_val else ""
                clean_attr = attr.replace('ATT ', '')
                card_content += f'<small class="{attr_class}"><strong>{clean_attr}:</strong> {current_val}</small><br>'
        
        st.markdown(card_content, unsafe_allow_html=True)

        # The edit button remains at the bottom
        if st.button(f"Edit Product", key=f"edit_{product['original_index']}_{project['id']}", use_container_width=True):
            st.session_state.editing_product = product
            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

def show_edit_modal(product, project):
    @st.dialog(f"Edit Product: {product['product_id']}")
    def edit_product_dialog():
        # --- MODIFIED BLOCK ---
        if product.get("image_url"):
            # Use the URL directly in a simple img tag
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
    st.title("📁 Product Grid Projects")

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
        project_description = st.text_area("Description (optional)")
        
        col1, col2 = st.columns(2)
        uploaded_excel = col1.file_uploader("Upload Product Excel Grid *", type=['xlsx', 'xls'])
        uploaded_images = col2.file_uploader("Upload Product Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True)
        
        submitted = st.form_submit_button("🚀 Create Project", type="primary", use_container_width=True)
        
        if submitted:
            if not project_name or not uploaded_excel:
                st.warning("Please provide a project name and an Excel file.")
            else:
                with st.spinner("Creating project and uploading assets..."):
                    # 1. Parse the Excel file. 
                    excel_bytes = uploaded_excel.getvalue()
                    products, attrs, dists, filters = load_and_parse_excel(BytesIO(excel_bytes), {})
                    
                    # 2. Manually match uploaded images to the parsed products
                    if uploaded_images:
                        product_lookup = {p['product_id'].lower().strip(): p for p in products}
                        
                        for img in uploaded_images:
                            fname_id = os.path.splitext(img.name)[0].lower().strip()
                            if fname_id in product_lookup:
                                # Inject the tuple (filename, bytes) so save_project detects it
                                product_lookup[fname_id]['image_data'] = (img.name, img.getvalue())

                    # 3. Create the project structure
                    project_id = create_new_project(project_name, project_description)
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

                    # --- THE FIX IS HERE ---
                    # Delete the local "stale" version (which has bytes but no URLs)
                    if project_id in st.session_state.projects:
                        del st.session_state.projects[project_id]
                    
                    # Immediately re-fetch the "fresh" version from the Cloud (which has the URLs)
                    ensure_project_loaded(project_id)
                    # -----------------------
                    
                    st.success(f"✅ Project '{project_name}' created!")
                    st.balloons()
                    time.sleep(1)
                    
                    # 5. Load the grid page
                    st.session_state.current_project = project_id
                    st.session_state.page = 'grid'
                    st.rerun()
                    
def show_grid_page():
    """Display the product grid for the current project."""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("No project selected or project not found.")
        st.session_state.page = 'projects'; st.rerun()
        return
    
    project = st.session_state.projects[st.session_state.current_project]
    project_id = project['id']
    
    PRODUCTS_PER_PAGE = 50
    page_state_key = f'page_number_{project_id}'
    if page_state_key not in st.session_state:
        st.session_state[page_state_key] = 1

    # --- HELPER FUNCTIONS (Scoped to this page) ---
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

    # --- PAGE HEADER ---
    h_col1, h_col2, h_col3, h_col4 = st.columns([4, 3, 3, 2])
    with h_col1:
        st.title(f"📊 {project['name']}")
    with h_col2:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        new_excel = st.file_uploader("Replace Source Grid", type=['xlsx', 'xls'], key=f"replace_{project_id}", label_visibility="collapsed")
    with h_col3:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        excel_data = create_download_excel(project)
        if excel_data:
            st.download_button("📥 Download Current Grid", excel_data, f"{project['name']}_updated.xlsx", use_container_width=True)
    with h_col4:
        st.markdown("<div><br></div>", unsafe_allow_html=True)
        if st.button("← Back to Projects", use_container_width=True):
            st.session_state.page = 'projects'; st.rerun()

    # --- FILE REPLACEMENT LOGIC ---
    if new_excel:
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
            time.sleep(1); st.rerun()
            return

    # --- PENDING CHANGES ACTION BAR ---
    if project.get('pending_changes'):
        st.info(f"You have **{len(project['pending_changes'])}** pending change(s). Click 'Apply All Changes' to make them permanent.")
        
        action_cols = st.columns(2)
        with action_cols[0]:
            if st.button("✅ Apply All Changes", type="primary", use_container_width=True):
                with st.spinner("Applying and saving changes..."):
                    for product in project['products_data']:
                        if product['original_index'] in project['pending_changes']:
                            product['original_description'] = product['description']
                            product['original_price'] = product['price']
                            product['original_attributes'] = product['attributes'].copy()
                    
                    project['pending_changes'] = {}
                    update_project_timestamp(project_id)
                    auto_save_project(project_id)
                    
                    st.success("All changes have been applied and saved.")
                    time.sleep(1); st.rerun()

        with action_cols[1]:
            if st.button("❌ Reset All Changes", use_container_width=True):
                with st.spinner("Reverting all pending changes..."):
                    for product in project['products_data']:
                        if product['original_index'] in project['pending_changes']:
                            product['description'] = product['original_description']
                            product['price'] = product['original_price']
                            product['attributes'] = product['original_attributes'].copy()
                    
                    project['pending_changes'] = {}
                    st.warning("All pending changes have been discarded."); time.sleep(1); st.rerun()

    # --- (RESTORED) ADD/REPLACE IMAGES SECTION ---
# In show_grid_page() in your streamlit_app.py file

    # --- (CORRECTED) ADD/REPLACE IMAGES SECTION ---
    with st.container(border=True):
        st.subheader("🖼️ Add / Replace Images")
        new_images = st.file_uploader(
            "Upload new images. Filenames must match Product IDs (e.g., '123.png'). Existing images will be replaced.",
            type=['png', 'jpg', 'jpeg'],
            accept_multiple_files=True,
            key=f"add_images_{project_id}"
        )

        if new_images:
            with st.spinner(f"Matching {len(new_images)} image(s) to products..."):
                product_lookup = {p['product_id'].lower().strip(): p for p in project['products_data']}
                
                updated_count = 0
                for image_file in new_images:
                    product_id_from_filename = os.path.splitext(image_file.name)[0].lower().strip()
                    
                    if product_id_from_filename in product_lookup:
                        product_lookup[product_id_from_filename]['image_data'] = (image_file.name, image_file.getvalue())
                        updated_count += 1

                if updated_count > 0:
                    st.text(f"Found {updated_count} matches. Uploading to cloud storage...")
                    
                    # --- THIS IS THE CHANGE ---
                    # auto_save_project now returns the updated image mappings
                    updated_mappings = auto_save_project(project_id)

                    if updated_mappings:
                        # Update the local project data with the new URLs before reloading
                        project['image_mappings'] = updated_mappings
                        for p_id, p_data in product_lookup.items():
                            if p_id in updated_mappings and "public_url" in updated_mappings[p_id]:
                                p_data['image_url'] = updated_mappings[p_id]["public_url"]
                        
                        st.success(f"✅ Successfully added/updated {updated_count} image(s).")
                        time.sleep(1)
                        st.rerun()
                        return
                    else:
                        st.error("Failed to save the project after uploading images.")

                else:
                    st.warning(f"⚠️ No products found matching the {len(new_images)} uploaded image filename(s). Please check that the filenames (without extension) match the Product IDs.")
    # --- (CONTINUED) ---

    if 'editing_product' in st.session_state:
        show_edit_modal(st.session_state.editing_product, project)

    # --- VIEW/SORT CONTROLS & SIDEBAR FILTERS ---
    with st.container(border=True):
        if f'view_options_{project_id}' not in st.session_state:
            st.session_state[f'view_options_{project_id}'] = {'visible_attributes': ['Description', 'Price'] + project['attributes'], 'sort_by': 'product_id', 'sort_ascending': True}
        view_options = st.session_state[f'view_options_{project_id}']
        all_fields = ['Description', 'Price'] + project['attributes']
        def fmt(name): return name.replace('ATT ', '')
        
        st.subheader("View & Sort Options")
        v_col1, v_col2 = st.columns(2)
        view_options['visible_attributes'] = v_col1.multiselect("Show Attributes:", all_fields, default=view_options['visible_attributes'], format_func=fmt)
        s_opts = ['product_id'] + all_fields
        s_col1, s_col2 = v_col2.columns([2,1])
        sort_by_index = s_opts.index(view_options['sort_by']) if view_options['sort_by'] in s_opts else 0
        view_options['sort_by'] = s_col1.selectbox("Sort By:", s_opts, index=sort_by_index, format_func=fmt)
        view_options['sort_ascending'] = s_col2.radio("Order:", ["🔼", "🔽"], horizontal=True, index=0 if view_options['sort_ascending'] else 1) == "🔼"

    with st.sidebar:
        st.header("🔍 Filters")
        attribute_filters = {attr: st.multiselect(attr.replace('ATT ', ''), ['All'] + project['filter_options'].get(attr, []), default=['All']) for attr in project['attributes']}
        dist_filters = st.multiselect("Distribution", ['All'] + [d.replace('DIST ', '') for d in project['distributions']], default=['All']) if project['distributions'] else []

    # --- FILTERING, SORTING, AND DISPLAY ---
    filtered_products = apply_filters(project['products_data'], attribute_filters, dist_filters)
    
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
        # --- THIS IS THE FIX ---
        # Capture and return the result from the manager's save function.
        return st.session_state.firestore_manager.save_project(project_id, project)
    
    # Return False if the manager doesn't exist, indicating failure.
    return False

def main():
    """Main application router."""
    if st.session_state.page == 'projects':
        show_projects_page()
    elif st.session_state.page == 'create_project':
        show_create_project_page()
    elif st.session_state.page == 'grid':
        show_grid_page()

if __name__ == "__main__":
    main()
