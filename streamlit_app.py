import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
from collections import defaultdict
import base64
from io import BytesIO
import zipfile
import json
from datetime import datetime
import uuid
from PIL import Image, ImageOps

# Set page config
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
        height: 100%; /* Ensure cards in a row are same height */
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
    .filter-section {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
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
    .project-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
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

# --------------------------------------------------------------------
# Retina-crisp image helpers using <img> + srcset
# --------------------------------------------------------------------
CARD_IMG_CSS_WIDTH = 200
MODAL_IMG_CSS_WIDTH = 300
RETINA_FACTOR = 2

@st.cache_data(show_spinner=False)
def _encode_png_uri(im: Image.Image) -> str:
    """Return a PNG data URI for a PIL image."""
    b = BytesIO()
    im.save(b, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode("ascii")

def _resize_lanczos(img: Image.Image, target_w: int) -> Image.Image:
    """High-quality downscale while preserving aspect ratio."""
    if img.width <= target_w:
        return img.copy()
    r = target_w / img.width
    new_w = target_w
    new_h = max(1, int(round(img.height * r)))
    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)

@st.cache_data(show_spinner=False)
def build_img_srcset(image_bytes: bytes, css_width: int, retina_factor: int = RETINA_FACTOR) -> str:
    """Return an <img> HTML string with srcset (1x/2x) as PNG data URIs."""
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    one_x = _resize_lanczos(img, css_width)
    two_x = _resize_lanczos(img, css_width * retina_factor)
    uri_1x = _encode_png_uri(one_x)
    uri_2x = _encode_png_uri(two_x)
    html = f"""
    <img
      src="{uri_1x}"
      srcset="{uri_1x} 1x, {uri_2x} {retina_factor}x"
      style="width:{css_width}px;height:auto;display:block;image-rendering:auto;"
      alt="Product Image"
    />
    """
    return html
# --------------------------------------------------------------------

# Initialize session state for projects
if 'projects' not in st.session_state:
    st.session_state.projects = {}
if 'current_project' not in st.session_state:
    st.session_state.current_project = None
if 'page' not in st.session_state:
    st.session_state.page = 'projects'

# Project data structure
def create_new_project(name, description=""):
    """Create a new project with empty data structure"""
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
    """Update the last modified timestamp for a project"""
    if project_id in st.session_state.projects:
        st.session_state.projects[project_id]['last_modified'] = datetime.now().isoformat()

def sanitize_attr(attr):
    """Sanitize attribute names for use as keys"""
    return attr.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace('+', 'plus').replace(':', '')

def get_filter_options(products, attributes):
    """Generate filter options from products data"""
    opts = defaultdict(set)
    for p in products:
        for attr in attributes:
            opts[attr].add(p["attributes"][attr])
    return {k: sorted(v) for k, v in opts.items()}

def find_image_for_product(product_id, uploaded_images):
    """Find matching image for a product ID"""
    for filename, file_data in uploaded_images.items():
        name_part = os.path.splitext(filename)[0].lower()
        if name_part == str(product_id).lower():
            return file_data
    return None

def load_and_parse_excel(uploaded_file, uploaded_images):
    """Parse uploaded Excel file and return structured data"""
    if uploaded_file is None:
        return [], [], [], {}
    
    df = pd.read_excel(uploaded_file)
    headers = df.columns.tolist()
    
    attributes = [h for h in headers if str(h).startswith("ATT")]
    distributions = [h for h in headers if str(h).startswith("DIST")]
    price_col = headers[-1] if "price" in headers[-1].lower() else None
    
    products = []
    for idx, row in df.iterrows():
        product_id = str(row.iloc[0]).strip()
        description = str(row.iloc[1]).strip()
        
        # Handle price conversion safely
        try:
            price_val = float(row[price_col]) if price_col and not pd.isna(row[price_col]) else 0.0
            price_str = f"{price_val:.2f}"
        except (ValueError, TypeError):
            price_str = "0.00"

        image_data = find_image_for_product(product_id, uploaded_images)
        attr_data = {a: str(row[a]).strip() for a in attributes}
        dist_data = {d: "X" in str(row[d]).upper() for d in distributions}
        
        products.append({
            "original_index": idx,
            "product_id": product_id,
            "image_data": image_data,
            "description": description,
            "original_description": description,
            "price": price_str,
            "original_price": price_str,
            "attributes": attr_data,
            "original_attributes": attr_data.copy(),
            "distribution": dist_data
        })
    
    filter_options = get_filter_options(products, attributes)
    return products, attributes, distributions, filter_options

def apply_filters(products, attribute_filters, distribution_filters):
    """Apply filters to products and return filtered list"""
    filtered = []
    for product in products:
        show = True
        
        # Apply attribute filters
        for attr, selected_values in attribute_filters.items():
            if selected_values and 'All' not in selected_values:
                product_value = product["attributes"].get(attr, "")
                if product_value not in selected_values:
                    show = False
                    break
        
        # Apply distribution filters
        if show and distribution_filters and 'All' not in distribution_filters:
            dist_match = False
            for dist in distribution_filters:
                # Check against the original distribution key
                for orig_dist in product["distribution"].keys():
                    if orig_dist.replace('DIST ', '') == dist:
                        if product["distribution"].get(orig_dist, False):
                            dist_match = True
                            break
                if dist_match:
                    break
            if not dist_match:
                show = False
        
        if show:
            filtered.append(product)
    
    return filtered

def display_product_card(product, col_index, project, visible_attributes):
    """Display a single product card with visibility controls."""
    with st.container():
        st.markdown('<div class="product-card">', unsafe_allow_html=True)
        
        # IMAGE
        if product["image_data"]:
            html = build_img_srcset(product["image_data"], css_width=CARD_IMG_CSS_WIDTH)
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="height: {CARD_IMG_CSS_WIDTH}px; display: flex; align-items: center; justify-content: center; background-color: #f0f2f6; border-radius: 8px;">📷 No image</div>', unsafe_allow_html=True)
        
        # Description
        if "Description" in visible_attributes:
            desc_class = "changed-attribute" if product["description"] != product["original_description"] else ""
            st.markdown(f'<p class="{desc_class}"><strong>{product["description"]}</strong></p>', unsafe_allow_html=True)
        
        # Price
        if "Price" in visible_attributes and product["price"]:
            price_class = "changed-attribute" if product["price"] != product["original_price"] else ""
            st.markdown(f'<p class="{price_class}">Price: ${product["price"]}</p>', unsafe_allow_html=True)
        
        # Attributes
        for attr in project['attributes']:
            if attr in visible_attributes:
                current_val = product["attributes"][attr]
                original_val = product["original_attributes"][attr]
                attr_class = "changed-attribute" if current_val != original_val else ""
                clean_attr = attr.replace('ATT ', '')
                st.markdown(f'<small class="{attr_class}"><strong>{clean_attr}:</strong> {current_val}</small>', unsafe_allow_html=True)
        
        # Edit button
        if st.button(f"Edit Product", key=f"edit_{product['original_index']}_{project['id']}"):
            st.session_state.editing_product = product
            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

def show_edit_modal(product, project):
    """Show edit modal for a product"""
    st.subheader(f"Edit Product: {product['product_id']}")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        if product["image_data"]:
            html = build_img_srcset(product["image_data"], css_width=MODAL_IMG_CSS_WIDTH)
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.write("📷 No image")
    
    with col2:
        new_description = st.text_input("Description", value=product["description"])
        new_price = st.text_input("Price", value=product["price"])
        
        st.subheader("Attributes")
        new_attributes = {}
        for attr in project['attributes']:
            current_val = product["attributes"][attr]
            options = project['filter_options'].get(attr, [current_val])
            if current_val not in options:
                options.append(current_val)
            
            clean_attr = attr.replace('ATT ', '')
            selected_option = st.selectbox(
                f"{clean_attr}",
                options + ["[Custom Value]"],
                index=options.index(current_val) if current_val in options else 0,
                key=f"attr_{attr}_{product['original_index']}_{project['id']}"
            )
            
            if selected_option == "[Custom Value]":
                new_attributes[attr] = st.text_input(f"Custom {clean_attr}", value=current_val, key=f"custom_{attr}_{product['original_index']}_{project['id']}")
            else:
                new_attributes[attr] = selected_option
        
        col_save, col_cancel = st.columns(2)
        
        with col_save:
            if st.button("Save Changes", type="primary"):
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
                
                update_project_timestamp(project['id'])
                st.success("Changes saved! Click 'Apply Changes' to make them permanent.")
                del st.session_state.editing_product
                st.rerun()
        
        with col_cancel:
            if st.button("Cancel"):
                del st.session_state.editing_product
                st.rerun()

def create_download_excel(project):
    """Create Excel file with current changes for download"""
    if not project['products_data']:
        return None
    
    data = []
    for product in project['products_data']:
        row = [product["product_id"], product["description"]]
        for attr in project['attributes']:
            row.append(product["attributes"][attr])
        for dist in project['distributions']:
            row.append("X" if product["distribution"][dist] else "")
        row.append(float(product["price"]) if product["price"] else 0.0)
        data.append(row)
    
    headers = ["Product ID", "Description"] + project['attributes'] + project['distributions'] + ["Price"]
    df = pd.DataFrame(data, columns=headers)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    
    return output.getvalue()

def show_projects_page():
    """Display the main projects page"""
    st.title("📁 Product Grid Projects")
    
    with st.container():
        st.markdown("""
        <div class="new-project-section">
            <h2>🚀 Start a New Project</h2>
            <p>Create a new product grid project with your Excel data and images</p>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("➕ Create New Project", type="primary", use_container_width=True):
            st.session_state.page = 'create_project'
            st.rerun()
    
    if st.session_state.projects:
        st.header("📋 Your Projects")
        
        sorted_projects = sorted(
            st.session_state.projects.items(),
            key=lambda x: x[1]['last_modified'],
            reverse=True
        )
        
        for project_id, project in sorted_projects:
            with st.container():
                st.markdown('<div class="project-card">', unsafe_allow_html=True)
                
                col1, col2, col3 = st.columns([3, 1, 1])
                
                with col1:
                    st.markdown(f"### {project['name']}")
                    if project['description']:
                        st.write(project['description'])
                    
                    num_products = len(project['products_data'])
                    num_attributes = len(project['attributes'])
                    pending_changes = len(project['pending_changes'])
                    last_modified = datetime.fromisoformat(project['last_modified']).strftime("%Y-%m-%d %H:%M")
                    
                    st.markdown(f"""
                    <div class="project-stats">
                        📦 {num_products} products | 🏷️ {num_attributes} attributes | 
                        ✏️ {pending_changes} pending changes | 🕒 Last modified: {last_modified}
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    if st.button("Open", key=f"open_{project_id}", type="primary"):
                        st.session_state.current_project = project_id
                        st.session_state.page = 'grid'
                        st.rerun()
                
                with col3:
                    if st.button("🗑️ Delete", key=f"delete_{project_id}"):
                        del st.session_state.projects[project_id]
                        st.rerun()
                
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("No projects yet. Create your first project to get started!")

def show_create_project_page():
    """Display the create new project page"""
    st.title("🆕 Create New Project")
    
    if st.button("← Back to Projects"):
        st.session_state.page = 'projects'
        st.rerun()
    
    project_name = st.text_input("Project Name", placeholder="e.g., Q1 2024 Product Launch")
    project_description = st.text_area("Description (optional)", placeholder="Brief description of this project...")
    
    if not project_name:
        st.warning("Please enter a project name to continue.")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 Excel File")
        uploaded_excel = st.file_uploader(
            "Upload Product Attribute Grid", 
            type=['xlsx', 'xls'],
            help="Excel file with Product ID, Description, ATT columns, DIST columns, and Price",
            key="create_excel"
        )
        if uploaded_excel:
            st.success(f"✅ {uploaded_excel.name}")
    
    with col2:
        st.subheader("🖼️ Product Images")
        uploaded_images = st.file_uploader(
            "Upload Product Images",
            type=['png', 'jpg', 'jpeg'],
            accept_multiple_files=True,
            help="Upload images named with Product IDs (e.g., '123.jpg' for product ID '123')",
            key="create_images"
        )
        if uploaded_images:
            st.success(f"✅ {len(uploaded_images)} images uploaded")
    
    if st.button("🚀 Create Project", type="primary", disabled=not uploaded_excel):
        if uploaded_excel:
            image_dict = {img_file.name: img_file.getvalue() for img_file in uploaded_images} if uploaded_images else {}
            products, attributes, distributions, filter_options = load_and_parse_excel(uploaded_excel, image_dict)
            
            project_id = create_new_project(project_name, project_description)
            project = st.session_state.projects[project_id]
            
            project['products_data'] = products
            project['attributes'] = attributes
            project['distributions'] = distributions
            project['filter_options'] = filter_options
            project['uploaded_images'] = image_dict
            project['excel_filename'] = uploaded_excel.name
            
            st.success(f"✅ Project '{project_name}' created with {len(products)} products!")
            st.balloons()
            
            st.session_state.current_project = project_id
            st.session_state.page = 'grid'
            st.rerun()

def show_grid_page():
    """Display the product grid for the current project"""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("No project selected or project not found.")
        st.session_state.page = 'projects'
        st.rerun()
        return
    
    project = st.session_state.projects[st.session_state.current_project]
    project_id = project['id']
    
    # Header with project info and navigation
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"📊 {project['name']}")
        if project['description']:
            st.write(project['description'])
    
    with col2:
        if st.button("← Back to Projects"):
            st.session_state.page = 'projects'
            st.rerun()
    
    # Show edit modal if editing
    if 'editing_product' in st.session_state:
        show_edit_modal(st.session_state.editing_product, project)
        return
    
    # --- NEW: VIEW AND SORT CONTROL BAND ---
    with st.container(border=True):
        # Initialize view options in session state if they don't exist for this project
        if f'view_options_{project_id}' not in st.session_state:
            st.session_state[f'view_options_{project_id}'] = {
                'visible_attributes': ['Description', 'Price'] + project['attributes'],
                'sort_by': 'product_id',
                'sort_ascending': True
            }
        view_options = st.session_state[f'view_options_{project_id}']
        
        # Get all possible fields to show/sort by
        all_fields = ['Description', 'Price'] + project['attributes']

        st.subheader("View & Sort Options")
        c1, c2 = st.columns(2)

        with c1:
            # --- Visibility Control ---
            visible_attributes = st.multiselect(
                "Show/Hide Attributes on Cards:",
                options=all_fields,
                default=view_options['visible_attributes'],
                key=f"visibility_multiselect_{project_id}"
            )
            view_options['visible_attributes'] = visible_attributes

        with c2:
            # --- Sorting Control ---
            sort_cols = st.columns([2, 1])
            selected_sort_by = sort_cols[0].selectbox(
                "Sort Products By:",
                options=['product_id'] + all_fields,
                index=(['product_id'] + all_fields).index(view_options['sort_by']) if view_options['sort_by'] in (['product_id'] + all_fields) else 0,
                key=f"sort_by_{project_id}"
            )
            view_options['sort_by'] = selected_sort_by

            sort_direction = sort_cols[1].radio(
                "Direction:", 
                ["🔼 Asc", "🔽 Desc"], 
                index=0 if view_options['sort_ascending'] else 1,
                key=f"sort_dir_{project_id}",
                horizontal=True
            )
            view_options['sort_ascending'] = (sort_direction == "🔼 Asc")

    st.markdown("---")

    # Sidebar filters
    with st.sidebar:
        st.header("🔍 Filters")
        attribute_filters = {}
        for attr in project['attributes']:
            clean_attr = attr.replace('ATT ', '')
            options = ['All'] + project['filter_options'].get(attr, [])
            selected = st.multiselect(
                clean_attr,
                options,
                default=['All'],
                key=f"filter_{sanitize_attr(attr)}_{project['id']}"
            )
            attribute_filters[attr] = selected
        
        if project['distributions']:
            st.subheader("Distribution")
            dist_options = ['All'] + [d.replace('DIST ', '') for d in project['distributions']]
            distribution_filters = st.multiselect(
                "Available at",
                dist_options,
                default=['All'],
                key=f"filter_distribution_{project['id']}"
            )
        else:
            distribution_filters = ['All']
    
    # Main content area - Action buttons
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if project['pending_changes']:
            if st.button("🔄 Apply Changes", type="primary"):
                st.success("✅ Changes applied!")
                project['pending_changes'] = {}
                update_project_timestamp(project['id'])
    with col2:
        excel_data = create_download_excel(project)
        if excel_data:
            st.download_button(
                "📥 Download Excel",
                data=excel_data,
                file_name=f"{project['name']}_updated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    with col3:
        if st.button("🔄 Reset Changes"):
            project['pending_changes'] = {}
            for product in project['products_data']:
                product['description'] = product['original_description']
                product['price'] = product['original_price']
                product['attributes'] = product['original_attributes'].copy()
            update_project_timestamp(project['id'])
            st.rerun()
    
    # Apply filters
    filtered_products = apply_filters(
        project['products_data'],
        attribute_filters,
        distribution_filters
    )

    # --- NEW: Apply Sorting ---
    sort_by = view_options['sort_by']
    is_ascending = view_options['sort_ascending']

    def get_sort_key(product):
        if sort_by == 'product_id':
            # Try to convert to number for numeric sorting if possible
            try:
                return int(product['product_id'])
            except ValueError:
                return product['product_id']
        elif sort_by == 'Description':
            return product['description'].lower()
        elif sort_by == 'Price':
            try:
                return float(product['price'])
            except (ValueError, TypeError):
                return 0.0 # Default value for non-numeric prices
        else: # It's an attribute
            return product['attributes'].get(sort_by, '').lower()

    sorted_products = sorted(filtered_products, key=get_sort_key, reverse=not is_ascending)
    
    st.markdown(f"### Showing {len(sorted_products)} of {len(project['products_data'])} products")
    
    # Display products in grid
    if sorted_products:
        cols_per_row = 4
        for i in range(0, len(sorted_products), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, product in enumerate(sorted_products[i:i+cols_per_row]):
                with cols[j]:
                    # Pass the visible attributes to the card display function
                    display_product_card(product, j, project, view_options['visible_attributes'])
    else:
        st.info("No products match the current filters.")

def main():
    """Main application logic"""
    if st.session_state.page == 'projects':
        show_projects_page()
    elif st.session_state.page == 'create_project':
        show_create_project_page()
    elif st.session_state.page == 'grid':
        show_grid_page()

if __name__ == "__main__":
    main()
