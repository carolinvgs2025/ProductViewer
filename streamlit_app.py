import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
from collections import defaultdict
import base64
import io
from PIL import Image
import zipfile
import json
from datetime import datetime
import uuid

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
.product-card {
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 15px;
    margin: 5px;
    background-color: white;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
}
.product-card img {
    max-width: 100%;
    height: auto;
    border: none;
    outline: none;
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
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# Initialize session state
if 'projects' not in st.session_state:
    st.session_state.projects = {}
if 'current_project' not in st.session_state:
    st.session_state.current_project = None
if 'page' not in st.session_state:
    st.session_state.page = 'projects'

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
    """Find matching image for a product ID"""
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
    price_col = headers[-1] if "price" in headers[-1].lower() else None
    
    products = []
    for idx, row in df.iterrows():
        product_id = str(row.iloc[0]).strip()
        description = str(row.iloc[1]).strip()
        price_str = f"{row[price_col]:.2f}" if price_col and not pd.isna(row[price_col]) else ""
        
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

def apply_filters(products, attribute_filters, distribution_filters):
    """Apply filters to products"""
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
        
        if show:
            filtered.append(product)
    
    return filtered

def display_product_card(product, project):
    """Display a product card"""
    project_id = project['id']
    visibility_key = f"visibility_{project_id}"
    
    if visibility_key not in st.session_state:
        st.session_state[visibility_key] = {attr: True for attr in project['attributes']}
        st.session_state[visibility_key]['description'] = True
        st.session_state[visibility_key]['price'] = True
    
    with st.container():
        st.markdown('<div class="product-card">', unsafe_allow_html=True)
        
        # Image
        if product["image_data"]:
            st.image(product["image_data"], width=200, use_container_width=False)
        else:
            st.markdown("📷 *No image*")
        
        # Description
        if st.session_state[visibility_key].get('description', True):
            desc_class = "changed-attribute" if product["description"] != product["original_description"] else ""
            st.markdown(f'<p class="{desc_class}"><strong>{product["description"]}</strong></p>', unsafe_allow_html=True)
        
        # Price
        if product["price"] and st.session_state[visibility_key].get('price', True):
            price_class = "changed-attribute" if product["price"] != product["original_price"] else ""
            st.markdown(f'<p class="{price_class}">Price: ${product["price"]}</p>', unsafe_allow_html=True)
        
        # Attributes
        for attr in project['attributes']:
            if st.session_state[visibility_key].get(attr, True):
                current_val = product["attributes"][attr]
                original_val = product["original_attributes"][attr]
                attr_class = "changed-attribute" if current_val != original_val else ""
                clean_attr = attr.replace('ATT ', '')
                st.markdown(f'<small class="{attr_class}"><strong>{clean_attr}:</strong> {current_val}</small>', unsafe_allow_html=True)
        
        # Edit button
        if st.button(f"Edit", key=f"edit_{product['original_index']}_{project['id']}"):
            st.session_state.editing_product = product
            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

def show_edit_modal(product, project):
    """Show edit modal"""
    st.subheader(f"Edit Product: {product['product_id']}")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        if product["image_data"]:
            st.image(product["image_data"], width=300, use_container_width=False)
        else:
            st.markdown("📷 *No image*")
    
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
            new_attributes[attr] = st.selectbox(f"{clean_attr}", options, index=options.index(current_val))
        
        col_save, col_cancel = st.columns(2)
        
        with col_save:
            if st.button("Save Changes", type="primary"):
                idx = product["original_index"]
                if idx not in project['pending_changes']:
                    project['pending_changes'][idx] = {}
                
                if new_description != product["original_description"]:
                    project['pending_changes'][idx]["description"] = new_description
                    product["description"] = new_description
                
                if new_price != product["original_price"]:
                    project['pending_changes'][idx]["price"] = new_price
                    product["price"] = new_price
                
                for attr, new_val in new_attributes.items():
                    if new_val != product["original_attributes"][attr]:
                        project['pending_changes'][idx][attr] = new_val
                        product["attributes"][attr] = new_val
                
                st.success("Changes saved!")
                del st.session_state.editing_product
                st.rerun()
        
        with col_cancel:
            if st.button("Cancel"):
                del st.session_state.editing_product
                st.rerun()

def create_download_excel(project):
    """Create Excel download"""
    if not project['products_data']:
        return None
    
    data = []
    for product in project['products_data']:
        row = [product["product_id"], product["description"]]
        for attr in project['attributes']:
            row.append(product["attributes"][attr])
        for dist in project['distributions']:
            row.append("X" if product["distribution"][dist] else "")
        row.append(float(product["price"]) if product["price"] else 0)
        data.append(row)
    
    headers = ["Product ID", "Description"] + project['attributes'] + project['distributions'] + ["Price"]
    df = pd.DataFrame(data, columns=headers)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    
    return output.getvalue()

def show_projects_page():
    """Display projects page"""
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
                    
                    st.write(f"📦 {num_products} products | 🏷️ {num_attributes} attributes | ✏️ {pending_changes} pending changes")
                
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
    """Display create project page"""
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
        uploaded_excel = st.file_uploader("Upload Product Attribute Grid", type=['xlsx', 'xls'], key="create_excel")
        if uploaded_excel:
            st.success(f"✅ {uploaded_excel.name}")
    
    with col2:
        st.subheader("🖼️ Product Images")
        uploaded_images = st.file_uploader("Upload Product Images", type=['png', 'jpg', 'jpeg'], accept_multiple_files=True, key="create_images")
        if uploaded_images:
            st.success(f"✅ {len(uploaded_images)} images uploaded")
    
    if st.button("🚀 Create Project", type="primary", disabled=not uploaded_excel):
        if uploaded_excel:
            image_dict = {}
            if uploaded_images:
                for img_file in uploaded_images:
                    image_dict[img_file.name] = img_file.getvalue()
            
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
    """Display grid page"""
    if not st.session_state.current_project or st.session_state.current_project not in st.session_state.projects:
        st.error("No project selected or project not found.")
        st.session_state.page = 'projects'
        st.rerun()
        return
    
    project = st.session_state.projects[st.session_state.current_project]
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"📊 {project['name']}")
        if project['description']:
            st.write(project['description'])
    
    with col2:
        if st.button("← Back to Projects"):
            st.session_state.page = 'projects'
            st.rerun()
    
    if 'editing_product' in st.session_state:
        show_edit_modal(st.session_state.editing_product, project)
        return
    
    # Sidebar filters
    with st.sidebar:
        st.header("🔍 Filters")
        
        attribute_filters = {}
        for attr in project['attributes']:
            clean_attr = attr.replace('ATT ', '')
            options = ['All'] + project['filter_options'].get(attr, [])
            selected = st.multiselect(clean_attr, options, default=['All'], key=f"filter_{sanitize_attr(attr)}_{project['id']}")
            attribute_filters[attr] = selected
    
    # Action buttons
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if project['pending_changes']:
            if st.button("🔄 Apply Changes", type="primary"):
                st.success("✅ Changes applied!")
                project['pending_changes'] = {}
    
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
            st.rerun()
    
    # View controls
    st.subheader("🎛️ View Controls")
    
    project_id = project['id']
    visibility_key = f"visibility_{project_id}"
    
    if visibility_key not in st.session_state:
        st.session_state[visibility_key] = {attr: True for attr in project['attributes']}
        st.session_state[visibility_key]['description'] = True
        st.session_state[visibility_key]['price'] = True
    
    # Create view controls in columns
    all_fields = project['attributes'] + ['description', 'price']
    cols = st.columns(min(len(all_fields), 5))
    
    for i, field in enumerate(all_fields):
        with cols[i % 5]:
            clean_name = field.replace('ATT ', '') if field.startswith('ATT') else field.title()
            visibility = st.checkbox(f"Show {clean_name}", value=st.session_state[visibility_key].get(field, True), key=f"vis_{field}_{project_id}")
            st.session_state[visibility_key][field] = visibility
    
    # Apply filters
    filtered_products = apply_filters(project['products_data'], attribute_filters, {})
    
    st.markdown(f"### Showing {len(filtered_products)} of {len(project['products_data'])} products")
    
    # Display products
    if filtered_products:
        cols_per_row = 4
        for i in range(0, len(filtered_products), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, product in enumerate(filtered_products[i:i+cols_per_row]):
                with cols[j]:
                    display_product_card(product, project)
    else:
        st.info("No products match the current filters.")

def main():
    """Main application"""
    if st.session_state.page == 'projects':
        show_projects_page()
    elif st.session_state.page == 'create_project':
        show_create_project_page()
    elif st.session_state.page == 'grid':
        show_grid_page()

if __name__ == "__main__":
    main()
