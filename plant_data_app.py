import streamlit as st
import pandas as pd
import re
from datetime import datetime
from openpyxl import load_workbook
import io
import base64

# ===================== CONFIGURATION =====================
st.set_page_config(
    page_title="Plant Data Processor",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for bigger buttons
st.markdown("""
<style>
/* Big action buttons (Process and Download) */
.big-action-button .stButton > button {
    width: 100% !important;
    height: 150px !important;
    font-size: 36px !important;
    font-weight: bold !important;
    border: none !important;
    border-radius: 20px !important;
    cursor: pointer !important;
    transition: all 0.3s !important;
    padding: 30px 50px !important;
    margin: 20px 0 !important;
}

.big-action-button .stButton > button:hover {
    transform: translateY(-5px) !important;
    box-shadow: 0 10px 20px rgba(0,0,0,0.4) !important;
}

/* Process button specific styling */
.process-button .stButton > button {
    background-color: #FF6B35 !important;
    color: white !important;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3) !important;
    box-shadow: 0 4px 8px rgba(255,107,53,0.3) !important;
}

.process-button .stButton > button:hover {
    background-color: #E55A2B !important;
    box-shadow: 0 6px 12px rgba(255,107,53,0.4) !important;
}

/* Download button specific styling */
.download-button .stButton > button {
    background-color: #4CAF50 !important;
    color: white !important;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3) !important;
    box-shadow: 0 4px 8px rgba(76,175,80,0.3) !important;
}

.download-button .stButton > button:hover {
    background-color: #45a049 !important;
    box-shadow: 0 6px 12px rgba(76,175,80,0.4) !important;
}

/* Individual file download buttons */
.stDownloadButton > button {
    width: 100% !important;
    height: 60px !important;
    font-size: 18px !important;
    font-weight: bold !important;
    background-color: #4CAF50 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    cursor: pointer !important;
    transition: background-color 0.3s !important;
    padding: 10px 20px !important;
}

.stDownloadButton > button:hover {
    background-color: #45a049 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 8px rgba(0,0,0,0.2) !important;
}

/* Bulk download button */
.bulk-download .stDownloadButton > button {
    width: 100% !important;
    height: 150px !important;
    font-size: 36px !important;
    font-weight: bold !important;
    background-color: #2196F3 !important;
    color: white !important;
    border: none !important;
    border-radius: 20px !important;
    cursor: pointer !important;
    transition: all 0.3s !important;
    margin: 20px 0 !important;
    padding: 30px 50px !important;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3) !important;
    box-shadow: 0 10px 20px rgba(33,150,243,0.4) !important;
}

.bulk-download .stDownloadButton > button:hover {
    background-color: #1976D2 !important;
    transform: translateY(-6px) !important;
    box-shadow: 0 15px 30px rgba(33,150,243,0.6) !important;
}
</style>
""", unsafe_allow_html=True)

# Template file location (in same directory as the app)
TEMPLATE_FILE = "z-sheet.xlsx"

# ===================== HELPER FUNCTIONS =====================
def standardize_tube(val):
    """
    Normalize Tube Code to exactly 'TUBE <digits>'.
    Fixes cases like '100005674.0' -> 'TUBE 100005674' and
    prevents 'TUBE 0' by selecting the correct digit sequence.
    Empty/NaN -> None (true blank).
    """
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "":
        return None

    # 1) Numeric-looking inputs first (handles floats cleanly)
    try:
        f = float(s)
        if f.is_integer():
            return f"TUBE {int(f)}"
    except:
        pass

    # 2) Otherwise, pick the LONGEST digit sequence anywhere in the string
    nums = re.findall(r'\d+', s)
    if nums:
        longest = max(nums, key=len)
        return f"TUBE {longest}"

    # 3) Fallback: if it looks like 'tube <token>', keep digits or token
    m2 = re.search(r'tube\s*([A-Za-z0-9]+)\s*$', s, flags=re.IGNORECASE)
    if m2:
        token = m2.group(1)
        digits = re.sub(r'\D', '', token)
        return f"TUBE {digits}" if digits else f"TUBE {token}"

    return None


def standardize_clone(val):
    """Keep empty cells empty; convert datetime to YYYY-MM-DD; keep everything else as string."""
    if pd.isna(val) or str(val).strip() == "":
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return str(val)


def make_plant_codes_unique(df):
    """Append (1), (2), (3)... to duplicate Plant Codes to make them unique."""
    counts = {}
    new_codes = []
    for code in df["Plant Code"]:
        if pd.isna(code) or str(code).strip() == "":
            new_codes.append(code)
            continue
        if code not in counts:
            counts[code] = 0
            new_codes.append(code)
        else:
            counts[code] += 1
            new_codes.append(f"{code} ({counts[code]})")
    df["Plant Code"] = new_codes
    return df


def clean_empty(val):
    """Ensure empty/NaN values are written as None (blank cell)."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "" or s.lower() in ["nan", "none"]:
        return None
    return val


def _finalize_df(df):
    """Select required columns, uniquify Plant Codes, and convert empties to None."""
    required = ["Plant Code", "Tube Code", "Strain", "Clone", "Notes"]
    available = [c for c in required if c in df.columns]
    df = df[available]
    for col in required:
        if col not in df.columns:
            df[col] = None
    df = df[required]
    df = make_plant_codes_unique(df)
    df = df.applymap(clean_empty)
    return df


def clean_old_format(df):
    """Clean the old single-sheet format (CSV or simple XLSX)."""
    if "Number" in df.columns:
        df = df.drop(columns=["Number"])
    if "Tube Code" in df.columns:
        df["Tube Code"] = df["Tube Code"].apply(standardize_tube)
    if "Clone" in df.columns:
        df["Clone"] = df["Clone"].apply(standardize_clone)
    df = _finalize_df(df)
    return df


def clean_new_format(uploaded_file):
    """
    Clean the new multi-sheet XLSX format by processing only the active (open) sheet.
    Auto-map headers to: Plant Code, Tube Code, Strain, Clone, Notes.
    """
    # Read the workbook from the uploaded file
    wb = load_workbook(uploaded_file, data_only=True)
    active_sheet = wb.active.title
    
    # Reset file pointer and read with pandas
    uploaded_file.seek(0)
    df = pd.read_excel(uploaded_file, sheet_name=active_sheet)

    # Normalize headers
    normalized_cols = (
        df.columns.str.lower()
        .str.strip()
        .str.replace("*", "", regex=False)
        .str.replace("  ", " ")
    )

    # Auto-map columns
    col_map = {}
    for col in normalized_cols:
        if "tube" in col:
            col_map[col] = "Tube Code"
        elif "plant" in col:
            col_map[col] = "Plant Code"
        elif "strain" in col:
            col_map[col] = "Strain"
        elif "clone" in col:
            col_map[col] = "Clone"
        elif "note" in col:
            col_map[col] = "Notes"

    df.columns = [col_map.get(c, c) for c in normalized_cols]
    df = df.loc[:, ~df.columns.duplicated()]  # drop duplicates by name

    if "Tube Code" in df.columns:
        df["Tube Code"] = df["Tube Code"].apply(standardize_tube)
    if "Clone" in df.columns:
        df["Clone"] = df["Clone"].apply(standardize_clone)

    df = _finalize_df(df)
    return df


def fill_template(cleaned_df, template_file):
    """Fill z-sheet template with cleaned data, writing None for empty cells."""
    wb = load_workbook(template_file)
    ws = wb.active

    column_mapping = {
        "Plant Code": "B",
        "Tube Code": "C",
        "Strain": "E",
        "Clone": "F",
        "Notes": "G"
    }

    for i, row in cleaned_df.iterrows():
        excel_row = i + 2  # Start at row 2
        for col_name, col_letter in column_mapping.items():
            value = row[col_name]
            ws[f"{col_letter}{excel_row}"] = value if value not in ["", "nan", "NaN"] else None

    # Save to bytes buffer
    output_buffer = io.BytesIO()
    wb.save(output_buffer)
    output_buffer.seek(0)
    return output_buffer


def check_template_exists():
    """Check if the template file exists in the repository."""
    import os
    return os.path.exists(TEMPLATE_FILE)


def process_single_file(uploaded_file, filename):
    """Process a single uploaded file."""
    try:
        if filename.endswith(".xlsx"):
            df_clean = clean_new_format(uploaded_file)
        else:
            # Reset file pointer for pandas
            uploaded_file.seek(0)
            if filename.endswith(".csv"):
                df_raw = pd.read_csv(uploaded_file)
            else:
                df_raw = pd.read_excel(uploaded_file)
            df_clean = clean_old_format(df_raw)

        # Fill template
        output_buffer = fill_template(df_clean, TEMPLATE_FILE)
        base_name = filename.rsplit('.', 1)[0]
        output_filename = f"{base_name}_filled.xlsx"
        
        return df_clean, output_buffer, output_filename, None
    except Exception as e:
        return None, None, None, str(e)


# ===================== STREAMLIT APP =====================
def main():
    st.title("🌱 Plant Data Processor")
    st.markdown("Upload your plant data files (CSV/Excel) to process and standardize the data.")
    
    # Check if template exists
    if not check_template_exists():
        st.error(f"❌ Template file '{TEMPLATE_FILE}' not found in the repository!")
        st.info("Please ensure 'z-sheet.xlsx' is in the same directory as this application.")
        return
    
    st.success(f"✅ Template file '{TEMPLATE_FILE}' found and ready to use!")
    
    # Sidebar for instructions
    with st.sidebar:
        st.header("📋 Instructions")
        st.markdown(f"""
        **Template:** Using `{TEMPLATE_FILE}` from repository
        
        **Step 1:** Upload your data files (CSV or Excel)
        
        **Step 2:** Review the processed data
        
        **Step 3:** Download the results
        
        ---
        
        **Supported formats:**
        - CSV files
        - Excel files (.xlsx)
        
        **Data columns processed:**
        - Plant Code
        - Tube Code
        - Strain
        - Clone
        - Notes
        """)
    
    # Data files upload section
    st.header("📊 Data Files Upload")
    uploaded_files = st.file_uploader(
        "Upload your data files (CSV or Excel)",
        type=['csv', 'xlsx'],
        accept_multiple_files=True,
        key="data_files",
        help="You can upload multiple files at once. Each file will be processed separately."
    )
    
    if not uploaded_files:
        st.info("Please upload one or more data files to process.")
        return
    
    # Processing section
    st.header("⚙️ Processing Results")
    
    # Center the process button properly
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown('<div class="big-action-button process-button">', unsafe_allow_html=True)
        process_clicked = st.button("🚀 Process All Files", type="primary")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Initialize session state for results
    if 'processed_results' not in st.session_state:
        st.session_state.processed_results = None
    
    if process_clicked:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            
            # Process the file
            df_clean, output_buffer, output_filename, error = process_single_file(
                uploaded_file, uploaded_file.name
            )
            
            if error:
                st.error(f"❌ Error processing {uploaded_file.name}: {error}")
            else:
                results.append({
                    'original_name': uploaded_file.name,
                    'output_name': output_filename,
                    'data': df_clean,
                    'file_buffer': output_buffer
                })
                st.success(f"✅ Successfully processed {uploaded_file.name}")
            
            progress_bar.progress((i + 1) / len(uploaded_files))
        
        status_text.text("Processing complete!")
        
        # Store results in session state and show download options immediately
        if results:
            st.session_state.processed_results = results
            st.success(f"✅ Successfully processed {len(results)} files!")
            
            st.header("📥 Download Results")
            
            # Show summary
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Files Processed", len(results))
            with col2:
                total_rows = sum(len(result['data']) for result in results)
                st.metric("Total Rows Processed", total_rows)
            
            # Individual file downloads
            st.subheader("Download Files")
            
            # If only one file, show one large download button
            if len(results) == 1:
                result = results[0]
                col1, col2, col3 = st.columns([1, 2, 1])
                with col2:
                    st.markdown('<div class="bulk-download">', unsafe_allow_html=True)
                    st.download_button(
                        label=f"📥 Download {result['output_name']}",
                        data=result['file_buffer'].getvalue(),
                        file_name=result['output_name'],
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    )
                    st.markdown('</div>', unsafe_allow_html=True)
            
            # If multiple files, show individual download buttons
            else:
                for result in results:
                    col1, col2, col3 = st.columns([1.5, 0.5, 2])
                    
                    with col1:
                        st.text(f"📄 {result['output_name']}")
                        st.text(f"Rows: {len(result['data'])}")
                    
                    with col2:
                        st.text("")  # Spacer
                    
                    with col3:
                        st.markdown('<div class="bulk-download">', unsafe_allow_html=True)
                        st.download_button(
                            label="📥 Download",
                            data=result['file_buffer'].getvalue(),
                            file_name=result['output_name'],
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            key=f"download_{result['output_name']}"
                        )
                        st.markdown('</div>', unsafe_allow_html=True)
            
            # Show file previews without download buttons
            st.subheader("Processed Files Preview")
            for result in results:
                with st.expander(f"📄 {result['output_name']} ({len(result['data'])} rows)"):
                    st.dataframe(result['data'].head(10), use_container_width=True)
                    st.text(f"Original file: {result['original_name']}")
    
    # Data preview section
    if uploaded_files:
        st.header("👀 Data Preview")
        selected_file = st.selectbox(
            "Select a file to preview:",
            options=[f.name for f in uploaded_files]
        )
        
        if selected_file:
            file_obj = next(f for f in uploaded_files if f.name == selected_file)
            
            try:
                # Reset file pointer
                file_obj.seek(0)
                
                if selected_file.endswith('.csv'):
                    preview_df = pd.read_csv(file_obj).head(10)
                else:
                    preview_df = pd.read_excel(file_obj).head(10)
                
                st.subheader(f"Preview of {selected_file} (first 10 rows)")
                st.dataframe(preview_df, use_container_width=True)
                
                # Show column info
                st.subheader("Column Information")
                col_info = pd.DataFrame({
                    'Column': preview_df.columns,
                    'Type': preview_df.dtypes,
                    'Non-null Count': preview_df.count()
                })
                st.dataframe(col_info, use_container_width=True)
                
            except Exception as e:
                st.error(f"Error previewing file: {str(e)}")


if __name__ == "__main__":
    main()
