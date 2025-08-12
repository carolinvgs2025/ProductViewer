import streamlit as st
import pandas as pd
import os
import tempfile
import shutil
from collections import defaultdict
import base64
from io import BytesIO
import zipfile

# Set page config
st.set_page_config(
    page_title="Interactive Product Grid",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'products_data' not in st.session_state:
    st.session_state.products_data = []
if 'attributes' not in st.session_state:
    st.session_state.attributes = []
if 'distributions' not in st.session_state:
    st.session_state.distributions = []
if 'filter_options' not in st.session_state:
    st.session_state.filter_options = {}
if 'pending_changes' not in st.session_state:
    st.session_state.pending_changes = {}
if 'uploaded_images' not in st.session_state:
    st.session_state.uploaded_images = {}

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
        price_str = f"{row[price_col]:.2f}" if price_col and not pd.isna(row[price_col]) else ""
        
        # Find matching image
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
                safe_dist = sanitize_attr(dist)
                if product["distribution"].get(dist, False):
                    dist_match = True
                    break
            if not dist_match:
                show = False
        
        if show:
            filtered.append(product)
    
    return filtered

def display_product_card(product, col_index):
    """Display a single product card"""
    with st.container():
        st.markdown('<div class="product-card">', unsafe_allow_html=True)
        
        # Image
        if product["image_data"]:
            st.image(product["image_data"], width=200)
        else:
            st.write("📷 No image")
        
        # Description
        desc_class = "changed-attribute" if product["description"] != product["original_description"] else ""
        st.markdown(f'<p class="{desc_class}"><strong>{product["description"]}</strong></p>', unsafe_allow_html=True)
        
        # Price
        if product["price"]:
            price_class = "changed-attribute" if product["price"] != product["original_price"] else ""
            st.markdown(f'<p class="{price_class}">Price: ${product["price"]}</p>', unsafe_allow_html=True)
        
        # Attributes
        for attr in st.session_state.attributes:
            current_val = product["attributes"][attr]
            original_val = product["original_attributes"][attr]
            attr_class = "changed-attribute" if current_val != original_val else ""
            clean_attr = attr.replace('ATT ', '')
            st.markdown(f'<small class="{attr_class}"><strong>{clean_attr}:</strong> {current_val}</small>', unsafe_allow_html=True)
        
        # Edit button
        if st.button(f"Edit Product", key=f"edit_{product['original_index']}"):
            st.session_state.editing_product = product
            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)

def show_edit_modal(product):
    """Show edit modal for a product"""
    st.subheader(f"Edit Product: {product['product_id']}")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Image
        if product["image_data"]:
            st.image(product["image_data"], width=200)
        else:
            st.write("📷 No image")
    
    with col2:
        # Description
        new_description = st.text_input("Description", value=product["description"])
        
        # Price
        new_price = st.text_input("Price", value=product["price"])
        
        # Attributes
        st.subheader("Attributes")
        new_attributes = {}
        for attr in st.session_state.attributes:
            current_val = product["attributes"][attr]
            options = st.session_state.filter_options.get(attr, [current_val])
            if current_val not in options:
                options.append(current_val)
            
            clean_attr = attr.replace('ATT ', '')
            selected_option = st.selectbox(
                f"{clean_attr}",
                options + ["[Custom Value]"],
                index=options.index(current_val) if current_val in options else 0,
                key=f"attr_{attr}_{product['original_index']}"
            )
            
            if selected_option == "[Custom Value]":
                new_attributes[attr] = st.text_input(f"Custom {clean_attr}", value=current_val, key=f"custom_{attr}_{product['original_index']}")
            else:
                new_attributes[attr] = selected_option
        
        # Save/Cancel buttons
        col_save, col_cancel = st.columns(2)
        
        with col_save:
            if st.button("Save Changes", type="primary"):
                # Update product data
                idx = product["original_index"]
                if idx not in st.session_state.pending_changes:
                    st.session_state.pending_changes[idx] = {}
                
                # Update description
                if new_description != product["original_description"]:
                    st.session_state.pending_changes[idx]["description"] = new_description
                    product["description"] = new_description
                
                # Update price
                if new_price != product["original_price"]:
                    st.session_state.pending_changes[idx]["price"] = new_price
                    product["price"] = new_price
                
                # Update attributes
                for attr, new_val in new_attributes.items():
                    if new_val != product["original_attributes"][attr]:
                        st.session_state.pending_changes[idx][attr] = new_val
                        product["attributes"][attr] = new_val
                
                st.success("Changes saved! Click 'Apply Changes' to make them permanent.")
                del st.session_state.editing_product
                st.rerun()
        
        with col_cancel:
            if st.button("Cancel"):
                del st.session_state.editing_product
                st.rerun()

def create_download_excel():
    """Create Excel file with current changes for download"""
    if not st.session_state.products_data:
        return None
    
    # Recreate the original DataFrame structure
    data = []
    for product in st.session_state.products_data:
        row = [product["product_id"], product["description"]]
        
        # Add attribute columns
        for attr in st.session_state.attributes:
            row.append(product["attributes"][attr])
        
        # Add distribution columns
        for dist in st.session_state.distributions:
            row.append("X" if product["distribution"][dist] else "")
        
        # Add price
        row.append(float(product["price"]) if product["price"] else 0)
        
        data.append(row)
    
    # Create column headers
    headers = ["Product ID", "Description"]
    headers.extend(st.session_state.attributes)
    headers.extend(st.session_state.distributions)
    headers.append("Price")
    
    df = pd.DataFrame(data, columns=headers)
    
    # Convert to Excel bytes
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Products')
    
    return output.getvalue()

def main():
    # Header
    col1, col2 = st.columns([1, 4])
    with col1:
        st.image("static/images/Vista Grande.png", width=100) if os.path.exists("static/images/Vista Grande.png") else st.write("🏢")
    with col2:
        st.title("Interactive Product Grid")
    
    # File upload section
    if not st.session_state.products_data:
        st.markdown("### Upload Your Product Data")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Excel File")
            uploaded_excel = st.file_uploader(
                "Upload Product Attribute Grid", 
                type=['xlsx', 'xls'],
                help="Excel file with Product ID, Description, ATT columns, DIST columns, and Price"
            )
        
        with col2:
            st.subheader("🖼️ Product Images")
            uploaded_images = st.file_uploader(
                "Upload Product Images",
                type=['png', 'jpg', 'jpeg'],
                accept_multiple_files=True,
                help="Upload images named with Product IDs (e.g., '123.jpg' for product ID '123')"
            )
        
        if uploaded_excel:
            # Process uploaded images
            image_dict = {}
            if uploaded_images:
                for img_file in uploaded_images:
                    image_dict[img_file.name] = img_file.getvalue()
            
            st.session_state.uploaded_images = image_dict
            
            # Parse Excel
            products, attributes, distributions, filter_options = load_and_parse_excel(uploaded_excel, image_dict)
            
            st.session_state.products_data = products
            st.session_state.attributes = attributes
            st.session_state.distributions = distributions
            st.session_state.filter_options = filter_options
            
            st.success(f"✅ Loaded {len(products)} products with {len(attributes)} attributes!")
            st.rerun()
    
    else:
        # Show edit modal if editing
        if 'editing_product' in st.session_state:
            show_edit_modal(st.session_state.editing_product)
            return
        
        # Sidebar filters
        with st.sidebar:
            st.header("🔍 Filters")
            
            # Attribute filters
            attribute_filters = {}
            for attr in st.session_state.attributes:
                clean_attr = attr.replace('ATT ', '')
                options = ['All'] + st.session_state.filter_options.get(attr, [])
                selected = st.multiselect(
                    clean_attr,
                    options,
                    default=['All'],
                    key=f"filter_{sanitize_attr(attr)}"
                )
                attribute_filters[attr] = selected
            
            # Distribution filters
            st.subheader("Distribution")
            dist_options = ['All'] + [d.replace('DIST ', '') for d in st.session_state.distributions]
            distribution_filters = st.multiselect(
                "Available at",
                dist_options,
                default=['All'],
                key="filter_distribution"
            )
        
        # Main content area
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            if st.session_state.pending_changes:
                if st.button("🔄 Apply Changes", type="primary"):
                    st.success("✅ Changes applied! (In a real deployment, this would update your database)")
                    st.session_state.pending_changes = {}
        
        with col2:
            excel_data = create_download_excel()
            if excel_data:
                st.download_button(
                    "📥 Download Excel",
                    data=excel_data,
                    file_name="updated_product_grid.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
        with col3:
            if st.button("🔄 Reset"):
                for key in ['products_data', 'attributes', 'distributions', 'filter_options', 'pending_changes', 'uploaded_images']:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
        
        # Apply filters
        filtered_products = apply_filters(
            st.session_state.products_data,
            attribute_filters,
            distribution_filters
        )
        
        st.markdown(f"### Showing {len(filtered_products)} of {len(st.session_state.products_data)} products")
        
        # Display products in grid
        if filtered_products:
            # Create columns for grid layout
            cols_per_row = 4
            for i in range(0, len(filtered_products), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, product in enumerate(filtered_products[i:i+cols_per_row]):
                    with cols[j]:
                        display_product_card(product, j)

if __name__ == "__main__":
    main()
