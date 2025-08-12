def apply_filters(products, attribute_filters, distribution_filters):import streamlit as st
import pandas as pd
import os
import io
from PIL import Image
import json
from datetime import datetime
import uuid
from collections import defaultdict
import streamlit as st

# Set page config
st.set_page_config(
    page_title="Interactive Product Grid",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Enhanced CSS styling
st.markdown("""
<style>
    /* Hide Streamlit elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* Main container styling */
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
    }
    
    /* Header styling */
    .app-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        margin-bottom: 2rem;
        text-align: center;
        color: white;
        box-shadow: 0 4px 20px rgba(0,0,0,0.1);
    }
    
    .app-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 700;
    }
    
    .app-header p {
        margin: 0.5rem 0 0 0;
        font-size: 1.2rem;
        opacity: 0.9;
    }
    
    /* Product card styling - use Streamlit's container */
    .stContainer > div {
        background: white;
        border-radius: 15px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        border: 1px solid #e1e5e9;
        transition: all 0.3s ease;
        height: 100%;
    }
    
    .stContainer > div:hover {
        transform: translateY(-5px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
    }
    
    /* Remove the old product-card class since we're not using it */
    
    .product-image {
        text-align: center;
        margin-bottom: 1rem;
        flex-shrink: 0;
    }
    
    /* Clean up image display - remove all boxes */
    div[data-testid="stImage"] {
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        border: none !important;
    }
    
    div[data-testid="stImage"] > div {
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
    }
    
    /* Target the actual image element */
    div[data-testid="stImage"] img {
        border-radius: 10px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        margin: 0 auto 15px auto;
        display: block;
    }
    
    /* Remove any container styling around images */
    .element-container:has([data-testid="stImage"]) {
        background: transparent !important;
        border: none !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    
    .product-title {
        font-weight: 700;
        font-size: 1.1rem;
        margin-bottom: 0.5rem;
        color: #2c3e50;
        line-height: 1.3;
    }
    
    .product-price {
        font-size: 1.2rem;
        font-weight: 600;
        color: #27ae60;
        margin-bottom: 1rem;
    }
    
    .product-attributes {
        flex-grow: 1;
    }
    
    .attribute-row {
        margin-bottom: 0.5rem;
        padding: 0.3rem 0;
        border-bottom: 1px solid #f1f3f4;
    }
    
    .attribute-label {
        font-weight: 600;
        color: #555;
        font-size: 0.9rem;
    }
    
    .attribute-value {
        color: #333;
        font-size: 0.9rem;
    }
    
    .changed-attribute {
        color: #e74c3c;
        font-weight: 700;
    }
    
    /* View controls styling */
    .view-controls {
        background: #f8f9fa;
        border-radius: 15px;
        padding: 1.5rem;
        margin: 1rem 0;
        border: 1px solid #e1e5e9;
    }
    
    .controls-header {
        font-size: 1.3rem;
        font-weight: 600;
        margin-bottom: 1rem;
        color: #2c3e50;
    }
    
    .control-item {
        background: white;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem;
        border: 1px solid #dee2e6;
        text-align: center;
    }
    
    .control-label {
        font-weight: 500;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
        color: #555;
    }
    
    .sort-buttons {
        display: flex;
        gap: 0.3rem;
        justify-content: center;
        margin-top: 0.5rem;
    }
    
    .sort-btn {
        background: #667eea;
        color: white;
        border: none;
        border-radius: 5px;
        padding: 0.3rem 0.6rem;
        cursor: pointer;
        transition: all 0.2s;
        font-size: 0.8rem;
    }
    
    .sort-btn:hover {
        background: #5a6fd8;
        transform: scale(1.05);
    }
    
    .sort-btn.active {
        background: #2c3e50;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    
    /* Action buttons */
    .action-btn {
        background: linear-gradient(45deg, #667eea, #764ba2);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.7rem 1.5rem;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.3s;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    
    .action-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    
    /* Project cards */
    .project-card {
        background: white;
        border-radius: 15px;
        padding: 2rem;
        margin: 1rem 0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        border: 1px solid #e1e5e9;
        transition: all 0.3s ease;
    }
    
    .project-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 30px rgba(0,0,0,0.15);
    }
    
    .project-title {
        font-size: 1.5rem;
        font-weight: 700;
        color: #2c3e50;
        margin-bottom: 0.5rem;
    }
    
    .project-stats {
        color: #666;
        font-size: 0.95rem;
        margin-top: 1rem;
    }
    
    /* Missing image styling */
    .missing-image {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        color: #666;
        font-size: 1.1rem;
        margin-bottom: 1rem;
    }
    
    /* Filter sidebar */
    .sidebar .stSelectbox > div > div {
        background-color: white;
        border-radius: 8px;
    }
    
    /* Custom scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
    }
    
    ::-webkit-scrollbar-track {
        background: #f1f1f1;
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: #667eea;
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: #5a6fd8;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'projects' not in st.session_state:
    st.session_state.projects = {}
if 'current_project' not in st.session_state:
    st.session_state.current_project = None
if 'page' not in st.session_state:
    st.session_state.page = 'projects'
if 'current_sort' not in st.session_state:
    st.session_state.current_sort = {'field': None, 'direction': 'asc'}

# Default missing image (base64 encoded placeholder)
DEFAULT_MISSING_IMAGE = """data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2Y4ZjlmYSIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTQiIGZpbGw9IiM2NjYiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj7wn5O3IE5vIEltYWdlPC90ZXh0Pjwvc3ZnPg=="""

def sanitize_attr(attr):
    """Sanitize attribute names for use as keys"""
    return attr.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace('+', 'plus').replace(':', '').replace('#', 'num')

def get_filter_options(products, attributes):
    """Generate filter options from products data"""
    opts = defaultdict(set)
    for p in products:
        for attr in attributes:
            opts[attr].add(p["attributes"][attr])
    return {k: sorted(list(v)) for k, v in opts.items()}

def optimize_image_for_display(image_data, max_width=600):
    """Optimize image for faster display while maintaining quality"""
    try:
        img = Image.open(io.BytesIO(image_data))
        
        # Only resize if image is significantly larger than display size
        if img.width > max_width * 1.5:  # Less aggressive resizing
            ratio = max_width / img.width
            new_height = int(img.height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
        # Keep as PNG for better quality if it's already PNG
        if img.format == 'PNG':
            output = io.BytesIO()
            img.save(output, format='PNG', optimize=True)
            return output.getvalue()
        
        # Convert to RGB if necessary (for JPEG output)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Save optimized image to bytes with higher quality
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95, optimize=True)  # Higher quality
        return output.getvalue()
    except Exception:
        return image_data

def find_image_for_product(product_id, uploaded_images):
    """Find matching image for a product ID and optimize for display"""
    for filename, file_data in uploaded_images.items():
        name_part = os.path.splitext(filename)[0].lower()
        if name_part == str(product_id).lower():
            return optimize_image_for_display(file_data)
    return None

def load_and_parse_excel(uploaded_file, uploaded_images):
    """Parse uploaded Excel file"""
    if uploaded_file is None:
        return [], [], [], {}
    
    df = pd.read_excel(uploaded_file)
    headers = df.columns.tolist()
    
    attributes = [h for h in headers if str(h).startswith("ATT")]
    distributions = [h for h in headers if str(h).startswith("DIST")]
    price_col = headers[-1] if any("price" in str(h).lower() for h in headers) else None
    
    products = []
    for idx, row in df.iterrows():
        product_id = str(row.iloc[0]).strip()
        description = str(row.iloc[1]).strip()
        price_str = f"{float(row[price_col]):.2f}" if price_col and not pd.isna(row[price_col]) else ""
        
        image_data = find_image_for_product(product_id, uploaded_images)
        attr_data = {a: str(row[a]).strip() if pd.notna(row[a]) else "" for a in attributes}
        dist_data = {d: "X" in str(row[d]).upper() if pd.notna(row[d]) else False for d in distributions}
        
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
    
    return products, attributes, distributions, get_filter_options(products, attributes)

def create_new_project(name, description=""):
    """Create a new project"""
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

def apply_filters(products, attribute_filters):
    """Apply filters to products"""
    filtered = []
    for product in products:
        show = True
        
        for attr, selected_values in attribute_filters.items():
            if selected_values and 'All' not in selected_values:
                product_value = product["attributes"].get(attr, "")
                if product_value not in selected_values:
                    show = False
                    break
        
        if show:
            filtered.append(product)
    
    return filtered

def sort_products(products, sort_field, sort_direction):
    """Sort products by specified field and direction"""
    if not sort_field:
        return products
    
    def get_sort_value(product):
        if sort_field == 'description':
            return product['description'].lower()
        elif sort_field == 'price':
            return float(product['price']) if product['price'] else 0
        else:
            return product['attributes'].get(sort_field, '').lower()
    
    return sorted(products, key=get_sort_value, reverse=(sort_direction == 'desc'))

def display_product_card(product, project, visibility_settings):
    """Display an enhanced product card"""
    # Use Streamlit's native container and columns for proper structure
    with st.container():
        # Create a clean bordered container
        with st.container():
            # Image section - no additional containers
            if product["image_data"]:
                st.image(product["image_data"], width=180, use_container_width=False)
            else:
                st.markdown("📷 *No Image Available*", unsafe_allow_html=True)
            
            # Description
            if visibility_settings.get('description', True):
                desc_class = "changed-attribute" if product["description"] != product["original_description"] else ""
                if desc_class:
                    st.markdown(f'**{product["description"]}**', unsafe_allow_html=False)
                else:
                    st.markdown(f'**{product["description"]}**')
            
            # Price
            if product["price"] and visibility_settings.get('price', True):
                price_class = "changed-attribute" if product["price"] != product["original_price"] else ""
                st.markdown(f'<span style="color: #27ae60; font-size: 1.2em; font-weight: 600;">${product["price"]}</span>', unsafe_allow_html=True)
            
            # Attributes - clean display
            for attr in project['attributes']:
                if visibility_settings.get(attr, True):
                    current_val = product["attributes"][attr]
                    original_val = product["original_attributes"][attr]
                    clean_attr = attr.replace('ATT ', '')
                    
                    if current_val != original_val:
                        st.markdown(f'<small style="color: #e74c3c; font-weight: bold;"><strong>{clean_attr}:</strong> {current_val}</small>', unsafe_allow_html=True)
                    else:
                        st.markdown(f'<small><strong>{clean_attr}:</strong> {current_val}</small>', unsafe_allow_html=True)
            
            # Edit button
            if st.button("✏️ Edit Product", key=f"edit_{product['original_index']}_{project['id']}", use_container_width=True):
                st.session_state.editing_product = product
                st.rerun()

def show_edit_modal(product, project):
    """Show enhanced edit modal"""
    st.markdown('<div class="app-header"><h1>✏️ Edit Product</h1><p>Make changes to product details</p></div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### Product Image")
        if product["image_data"]:
            st.image(product["image_data"], width=300, use_container_width=False)
        else:
            st.markdown('<div class="missing-image">📷 No Image Available</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown("### Product Details")
        
        # Description
        new_description = st.text_input("📝 Product Description", value=product["description"], key="edit_desc")
        
        # Price
        new_price = st.text_input("💰 Price ($)", value=product["price"], key="edit_price")
        
        # Attributes
        st.markdown("### 🏷️ Attributes")
        new_attributes = {}
        
        for attr in project['attributes']:
            current_val = product["attributes"][attr]
            options = project['filter_options'].get(attr, [current_val])
            if current_val not in options:
                options = [current_val] + options
            
            clean_attr = attr.replace('ATT ', '')
            
            # Use selectbox with option to add custom value
            col_select, col_custom = st.columns([2, 1])
            
            with col_select:
                selected = st.selectbox(
                    f"{clean_attr}",
                    options + ["[Add Custom Value]"],
                    index=0 if current_val in options else len(options),
                    key=f"select_{attr}"
                )
            
            with col_custom:
                if selected == "[Add Custom Value]":
                    custom_val = st.text_input("Custom", value=current_val, key=f"custom_{attr}")
                    new_attributes[attr] = custom_val
                else:
                    new_attributes[attr] = selected
        
        # Action buttons
        st.markdown("---")
        col_save, col_cancel = st.columns(2)
        
        with col_save:
            if st.button("💾 Save Changes", type="primary", use_container_width=True):
                # Update product data
                idx = product["original_index"]
                if idx not in project['pending_changes']:
                    project['pending_changes'][idx] = {}
                
                # Update description
                if new_description != product["original_description"]:
                    project['pending_changes'][idx]["description"] = new_description
                    product["description"] = new_description
                
                # Update price
                if new_price != product["original_price"]:
                    project['pending_changes'][idx]["price"] = new_price
                    product["price"] = new_price
                
                # Update attributes
                for attr, new_val in new_attributes.items():
                    if new_val != product["original_attributes"][attr]:
                        project['pending_changes'][idx][attr] = new_val
                        product["attributes"][attr] = new_val
                
                project['last_modified'] = datetime.now().isoformat()
                st.success("✅ Changes saved successfully!")
                st.balloons()
                del st.session_state.editing_product
                st.rerun()
        
        with col_cancel:
            if st.button("❌ Cancel", use_container_width=True):
                del st.session_state.editing_product
                st.rerun()

def create_download_excel(project):
    """Create Excel download with all changes"""
    if not project['products_data']:
        return None
    
    data = []
    for product in project['products_data']:
        row = [product["product_id"], product["description"]]
        
        # Add attributes
        for attr in project['attributes']:
            row.append(product["attributes"][attr])
        
        # Add distributions
        for dist in project['distributions']:
            row.append("X" if product["distribution"][dist] else "")
        
        # Add price
        row.append(float(product["price"]) if product["price"] else 0)
        data.append(row)
    
    # Create headers
    headers = ["Product ID", "Description"] + project['attributes'] + project['distributions'] + ["Price"]
    df = pd.DataFrame(data, columns=headers)
    
    # Convert to Excel bytes
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    
    return output.getvalue()

def show_projects_page():
    """Display enhanced projects page"""
    # Header
    st.markdown('''
    <div class="app-header">
        <h1>📊 Interactive Product Grid</h1>
        <p>Manage your product catalogs with ease</p>
    </div>
    ''', unsafe_allow_html=True)
    
    # New Project Section
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🚀 Create New Project", type="primary", use_container_width=True):
            st.session_state.page = 'create_project'
            st.rerun()
    
    # Existing Projects
    if st.session_state.projects:
        st.markdown("## 📁 Your Projects")
        
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
                    st.markdown(f'<div class="project-title">{project["name"]}</div>', unsafe_allow_html=True)
                    if project['description']:
                        st.write(project['description'])
                    
                    # Stats
                    num_products = len(project['products_data'])
                    num_attributes = len(project['attributes'])
                    pending_changes = len(project['pending_changes'])
                    last_modified = datetime.fromisoformat(project['last_modified']).strftime("%Y-%m-%d %H:%M")
                    
                    st.markdown(f'''
                    <div class="project-stats">
                        📦 <strong>{num_products}</strong> products | 
                        🏷️ <strong>{num_attributes}</strong> attributes | 
                        ✏️ <strong>{pending_changes}</strong> pending changes<br>
                        🕒 Last modified: {last_modified}
                    </div>
                    ''', unsafe_allow_html=True)
                
                with col2:
                    if st.button("📂 Open", key=f"open_{project_id}", type="primary"):
                        st.session_state.current_project = project_id
                        st.session_state.page = 'grid'
                        st.rerun()
                
                with col3:
                    if st.button("🗑️ Delete", key=f"delete_{project_id}"):
                        if st.session_state.get('confirm_delete') == project_id:
                            del st.session_state.projects[project_id]
                            if 'confirm_delete' in st.session_state:
                                del st.session_state.confirm_delete
                            st.rerun()
                        else:
                            st.session_state.confirm_delete = project_id
                            st.warning("Click again to confirm deletion")
                
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.info("🌟 No projects yet. Create your first project to get started!")

def show_create_project_page():
    """Display enhanced create project page"""
    # Header
    st.markdown('''
    <div class="app-header">
        <h1>🚀 Create New Project</h1>
        <p>Upload your Excel data and product images</p>
    </div>
    ''', unsafe_allow_html=True)
    
    # Back button
    if st.button("← Back to Projects", key="back_to_projects"):
        st.session_state.page = 'projects'
        st.rerun()
    
    # Project details
    st.markdown("## 📝 Project Information")
    project_name = st.text_input("Project Name *", placeholder="e.g., Q1 2024 Product Launch")
    project_description = st.text_area("Description", placeholder="Brief description of this project...")
    
    if not project_name.strip():
        st.warning("⚠️ Please enter a project name to continue.")
        return
    
    # File uploads
    st.markdown("## 📁 Upload Files")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 📊 Excel File")
        uploaded_excel = st.file_uploader(
            "Upload Product Attribute Grid", 
            type=['xlsx', 'xls'],
            help="Excel file with Product ID, Description, ATT columns, DIST columns, and Price"
        )
        
        if uploaded_excel:
            st.success(f"✅ {uploaded_excel.name}")
    
    with col2:
        st.markdown("### 🖼️ Product Images")
        uploaded_images = st.file_uploader(
            "Upload Product Images",
            type=['png', 'jpg', 'jpeg'],
            accept_multiple_files=True,
            help="Upload images named with Product IDs (e.g., '123.jpg' for product ID '123')"
        )
        
        if uploaded_images:
            st.success(f"✅ {len(uploaded_images)} images uploaded")
    
    # Create button
    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if st.button("🎯 Create Project", type="primary", disabled=not uploaded_excel, use_container_width=True):
            if uploaded_excel:
                with st.spinner("🔄 Processing files..."):
                    # Process images
                    image_dict = {}
                    if uploaded_images:
                        for img_file in uploaded_images:
                            image_dict[img_file.name] = img_file.getvalue()
                    
                    # Parse Excel
                    products, attributes, distributions, filter_options = load_and_parse_excel(uploaded_excel, image_dict)
                    
                    # Create project
                    project_id = create_new_project(project_name.strip(), project_description.strip())
                    project = st.session_state.projects[project_id]
                    
                    # Store data
                    project['products_data'] = products
                    project['attributes'] = attributes
                    project['distributions'] = distributions
                    project['filter_options'] = filter_options
                    project['uploaded_images'] = image_dict
                    project['excel_filename'] = uploaded_excel.name
                
                st.success(f"🎉 Project '{project_name}' created with {len(products)} products!")
                st.balloons()
                
                # Redirect to grid
                st.session_state.current_project = project_id
                st.session_state.page = 'grid'
                st.rerun()

def show_grid_page():
    """Display enhanced grid page"""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("❌ No project selected or project not found.")
        st.session_state.page = 'projects'
        st.rerun()
        return
    
    project = st.session_state.projects[st.session_state.current_project]
    
    # Show edit modal if editing
    if 'editing_product' in st.session_state:
        show_edit_modal(st.session_state.editing_product, project)
        return
    
    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f'''
        <div class="app-header">
            <h1>📊 {project['name']}</h1>
            <p>{project['description'] if project['description'] else 'Product Grid View'}</p>
        </div>
        ''', unsafe_allow_html=True)
    
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)  # Spacing
        if st.button("← Back to Projects", key="back_from_grid"):
            st.session_state.page = 'projects'
            st.rerun()
    
    # Sidebar filters
    with st.sidebar:
        st.markdown("### 🔍 Filters")
        
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
    
    # Action buttons
    st.markdown("## ⚡ Actions")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if project['pending_changes']:
            if st.button("💾 Apply Changes", type="primary", use_container_width=True):
                st.success("✅ All changes have been applied!")
                project['pending_changes'] = {}
                project['last_modified'] = datetime.now().isoformat()
                st.balloons()
    
    with col2:
        excel_data = create_download_excel(project)
        if excel_data:
            st.download_button(
                "📥 Download Excel",
                data=excel_data,
                file_name=f"{project['name']}_updated.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    with col3:
        if st.button("🔄 Reset All Changes", use_container_width=True):
            if st.session_state.get('confirm_reset') == project['id']:
                project['pending_changes'] = {}
                for product in project['products_data']:
                    product['description'] = product['original_description']
                    product['price'] = product['original_price']
                    product['attributes'] = product['original_attributes'].copy()
                project['last_modified'] = datetime.now().isoformat()
                if 'confirm_reset' in st.session_state:
                    del st.session_state.confirm_reset
                st.success("🔄 All changes have been reset!")
                st.rerun()
            else:
                st.session_state.confirm_reset = project['id']
                st.warning("Click again to confirm reset")
    
    # View Controls Section
    st.markdown("## 🎛️ View & Sort Controls")
    
    # Get visibility settings
    project_id = project['id']
    visibility_key = f"visibility_{project_id}"
    
    if visibility_key not in st.session_state:
        st.session_state[visibility_key] = {attr: True for attr in project['attributes']}
        st.session_state[visibility_key]['description'] = True
        st.session_state[visibility_key]['price'] = True
    
    # Create view controls
    with st.container():
        st.markdown('<div class="view-controls">', unsafe_allow_html=True)
        st.markdown('<div class="controls-header">🔧 Field Visibility & Sorting</div>', unsafe_allow_html=True)
        
        all_fields = project['attributes'] + ['description', 'price']
        
        # Create responsive columns
        num_cols = min(5, len(all_fields))
        cols = st.columns(num_cols)
        
        for i, field in enumerate(all_fields):
            with cols[i % num_cols]:
                clean_name = field.replace('ATT ', '') if field.startswith('ATT') else field.title()
                
                # Visibility checkbox
                visibility = st.checkbox(
                    f"👁️ Show {clean_name}",
                    value=st.session_state[visibility_key].get(field, True),
                    key=f"vis_{field}_{project_id}"
                )
                st.session_state[visibility_key][field] = visibility
                
                # Sort buttons
                col_asc, col_desc = st.columns(2)
                
                with col_asc:
                    asc_active = (st.session_state.current_sort['field'] == field and 
                                 st.session_state.current_sort['direction'] == 'asc')
                    if st.button(
                        "⬆️ A-Z" if not asc_active else "🔼 A-Z",
                        key=f"sort_asc_{field}_{project_id}",
                        help=f"Sort {clean_name} ascending",
                        use_container_width=True
                    ):
                        st.session_state.current_sort = {'field': field, 'direction': 'asc'}
                        st.rerun()
                
                with col_desc:
                    desc_active = (st.session_state.current_sort['field'] == field and 
                                  st.session_state.current_sort['direction'] == 'desc')
                    if st.button(
                        "⬇️ Z-A" if not desc_active else "🔽 Z-A",
                        key=f"sort_desc_{field}_{project_id}",
                        help=f"Sort {clean_name} descending",
                        use_container_width=True
                    ):
                        st.session_state.current_sort = {'field': field, 'direction': 'desc'}
                        st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Bulk visibility controls
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("👁️ Show All Fields", use_container_width=True):
            for field in all_fields:
                st.session_state[visibility_key][field] = True
            st.rerun()
    
    with col2:
        if st.button("🙈 Hide All Fields", use_container_width=True):
            for field in all_fields:
                st.session_state[visibility_key][field] = False
            st.rerun()
    
    with col3:
        if st.button("🔄 Clear Sort", use_container_width=True):
            st.session_state.current_sort = {'field': None, 'direction': 'asc'}
            st.rerun()
    
    # Compact View Controls Section
    st.markdown("---")
    
    # Get visibility settings
    project_id = project['id']
    visibility_key = f"visibility_{project_id}"
    
    if visibility_key not in st.session_state:
        st.session_state[visibility_key] = {attr: True for attr in project['attributes']}
        st.session_state[visibility_key]['description'] = True
        st.session_state[visibility_key]['price'] = True
    
    # Create compact view controls
    with st.container():
        st.markdown('''
        <div class="view-controls-container">
            <div class="view-controls-header">🎛️ View & Sort Controls</div>
            <div class="control-grid">
        ''', unsafe_allow_html=True)
        
        # Create controls for all fields
        all_fields = project['attributes'] + ['description', 'price']
        
        # Display controls in a responsive grid
        cols = st.columns(min(4, len(all_fields)))  # Max 4 columns
        
        for i, field in enumerate(all_fields):
            with cols[i % len(cols)]:
                clean_name = field.replace('ATT ', '') if field.startswith('ATT') else field.title()
                
                # Visibility checkbox
                visibility = st.checkbox(
                    f"👁️ {clean_name}",
                    value=st.session_state[visibility_key].get(field, True),
                    key=f"vis_{field}_{project_id}"
                )
                st.session_state[visibility_key][field] = visibility
                
                # Sort buttons in columns
                col_asc, col_desc = st.columns(2)
                
                with col_asc:
                    asc_active = (st.session_state.current_sort['field'] == field and 
                                 st.session_state.current_sort['direction'] == 'asc')
                    if st.button(
                        "⬆️" if not asc_active else "🔼",
                        key=f"sort_asc_{field}_{project_id}",
                        help=f"Sort {clean_name} A→Z",
                        use_container_width=True
                    ):
                        st.session_state.current_sort = {'field': field, 'direction': 'asc'}
                        st.rerun()
                
                with col_desc:
                    desc_active = (st.session_state.current_sort['field'] == field and 
                                  st.session_state.current_sort['direction'] == 'desc')
                    if st.button(
                        "⬇️" if not desc_active else "🔽",
                        key=f"sort_desc_{field}_{project_id}",
                        help=f"Sort {clean_name} Z→A",
                        use_container_width=True
                    ):
                        st.session_state.current_sort = {'field': field, 'direction': 'desc'}
                        st.rerun()
        
        st.markdown('</div></div>', unsafe_allow_html=True)
    
    # Bulk controls below the main controls
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if st.button("👁️ Show All", key=f"show_all_{project_id}", use_container_width=True):
            for field in all_fields:
                st.session_state[visibility_key][field] = True
            st.rerun()
    
    with col2:
        if st.button("🙈 Hide All", key=f"hide_all_{project_id}", use_container_width=True):
            for field in all_fields:
                st.session_state[visibility_key][field] = False
            st.rerun()
    
    with col3:
        if st.button("🔄 Clear Sort", key=f"clear_sort_{project_id}", use_container_width=True):
            st.session_state.current_sort = {'field': None, 'direction': 'asc'}
            st.rerun()
    
    with col4:
        # Show current sort status
        if st.session_state.current_sort['field']:
            sort_field = st.session_state.current_sort['field']
            clean_field = sort_field.replace('ATT ', '') if sort_field.startswith('ATT') else sort_field.title()
            direction = "⬆️" if st.session_state.current_sort['direction'] == 'asc' else "⬇️"
            st.write(f"Sort: {clean_field} {direction}")
    
    st.markdown("---") and sorting
    filtered_products = apply_filters(project['products_data'], attribute_filters)
    sorted_products = sort_products(
        filtered_products, 
        st.session_state.current_sort['field'],
        st.session_state.current_sort['direction']
    )
    
    # Display current sort info
    if st.session_state.current_sort['field']:
        sort_field = st.session_state.current_sort['field']
        sort_dir = st.session_state.current_sort['direction']
        clean_field = sort_field.replace('ATT ', '') if sort_field.startswith('ATT') else sort_field.title()
        direction_text = "A→Z" if sort_dir == 'asc' else "Z→A"
        st.info(f"🔄 Currently sorted by **{clean_field}** ({direction_text})")
    
    # Products display
    st.markdown(f"## 📦 Products ({len(sorted_products)} of {len(project['products_data'])} shown)")
    
    if sorted_products:
        # Display products in responsive grid
        cols_per_row = 4
        
        for i in range(0, len(sorted_products), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, product in enumerate(sorted_products[i:i+cols_per_row]):
                with cols[j]:
                    display_product_card(product, project, st.session_state[visibility_key])
    else:
        st.info("🔍 No products match the current filters. Try adjusting your filter settings.")

def main():
    """Main application router"""
    if st.session_state.page == 'projects':
        show_projects_page()
    elif st.session_state.page == 'create_project':
        show_create_project_page()
    elif st.session_state.page == 'grid':
        show_grid_page()

if __name__ == "__main__":
    main()
