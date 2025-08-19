import streamlit as st
import pandas as pd
import re
from datetime import datetime
from openpyxl import load_workbook
import openpyxl
import xlrd
import io
import base64
import os
from typing import List, Tuple, Optional

# ===================== CONFIGURATION =====================
st.set_page_config(
    page_title="Plant Data Suite",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for styling
st.markdown("""
<style>
/* Navigation styling */
.nav-header {
    background: linear-gradient(90deg, #4CAF50, #45a049);
    padding: 1rem;
    border-radius: 10px;
    margin-bottom: 2rem;
    color: white;
    text-align: center;
    font-size: 24px;
    font-weight: bold;
}

/* Section separators */
.section-divider {
    border-top: 3px solid #4CAF50;
    margin: 2rem 0;
    opacity: 0.3;
}

/* Big action buttons */
.big-action-button .stButton > button {
    width: 100% !important;
    height: 120px !important;
    font-size: 28px !important;
    font-weight: bold !important;
    border: none !important;
    border-radius: 15px !important;
    cursor: pointer !important;
    transition: all 0.3s !important;
    padding: 20px 40px !important;
    margin: 15px 0 !important;
}

.big-action-button .stButton > button:hover {
    transform: translateY(-3px) !important;
    box-shadow: 0 8px 16px rgba(0,0,0,0.3) !important;
}

/* Process button styling */
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

/* Download button styling */
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

/* Combine button styling */
.combine-button .stButton > button {
    background-color: #2196F3 !important;
    color: white !important;
    text-shadow: 1px 1px 2px rgba(0,0,0,0.3) !important;
    box-shadow: 0 4px 8px rgba(33,150,243,0.3) !important;
}

.combine-button .stButton > button:hover {
    background-color: #1976D2 !important;
    box-shadow: 0 6px 12px rgba(33,150,243,0.4) !important;
}

/* Individual download buttons */
.stDownloadButton > button {
    width: 100% !important;
    height: 50px !important;
    font-size: 16px !important;
    font-weight: bold !important;
    background-color: #4CAF50 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    cursor: pointer !important;
    transition: all 0.3s !important;
}

.stDownloadButton > button:hover {
    background-color: #45a049 !important;
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 8px rgba(0,0,0,0.2) !important;
}

/* Function cards */
.function-card {
    border: 2px solid #e0e0e0;
    border-radius: 10px;
    padding: 1rem;
    margin: 1rem 0;
    background-color: #f9f9f9;
}

.function-card.active {
    border-color: #4CAF50;
    background-color: #f0f8f0;
}
</style>
""", unsafe_allow_html=True)

# Template file location
TEMPLATE_FILE = "z-sheet.xlsx"

# ===================== PLANT DATA PROCESSOR FUNCTIONS =====================
def standardize_tube(val):
    """Normalize Tube Code to exactly 'TUBE <digits>'."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    if s == "":
        return None

    try:
        f = float(s)
        if f.is_integer():
            return f"TUBE {int(f)}"
    except:
        pass

    nums = re.findall(r'\d+', s)
    if nums:
        longest = max(nums, key=len)
        return f"TUBE {longest}"

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
    """Clean the new multi-sheet XLSX format by processing only the active sheet."""
    wb = load_workbook(uploaded_file, data_only=True)
    active_sheet = wb.active.title
    
    uploaded_file.seek(0)
    df = pd.read_excel(uploaded_file, sheet_name=active_sheet)

    normalized_cols = (
        df.columns.str.lower()
        .str.strip()
        .str.replace("*", "", regex=False)
        .str.replace("  ", " ")
    )

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
    df = df.loc[:, ~df.columns.duplicated()]

    if "Tube Code" in df.columns:
        df["Tube Code"] = df["Tube Code"].apply(standardize_tube)
    if "Clone" in df.columns:
        df["Clone"] = df["Clone"].apply(standardize_clone)

    df = _finalize_df(df)
    return df

def fill_template(cleaned_df, template_file_buffer):
    """Fill z-sheet template with cleaned data."""
    wb = load_workbook(template_file_buffer)
    ws = wb.active

    column_mapping = {
        "Plant Code": "B",
        "Tube Code": "C",
        "Strain": "E",
        "Clone": "F",
        "Notes": "G"
    }

    for i, row in cleaned_df.iterrows():
        excel_row = i + 2
        for col_name, col_letter in column_mapping.items():
            value = row[col_name]
            ws[f"{col_letter}{excel_row}"] = value if value not in ["", "nan", "NaN"] else None

    output_buffer = io.BytesIO()
    wb.save(output_buffer)
    output_buffer.seek(0)
    return output_buffer

def process_single_file(uploaded_file, filename, template_buffer):
    """Process a single uploaded file."""
    try:
        if filename.endswith(".xlsx"):
            df_clean = clean_new_format(uploaded_file)
        else:
            uploaded_file.seek(0)
            if filename.endswith(".csv"):
                df_raw = pd.read_csv(uploaded_file)
            else:
                df_raw = pd.read_excel(uploaded_file)
            df_clean = clean_old_format(df_raw)

        output_buffer = fill_template(df_clean, template_buffer)
        base_name = filename.rsplit('.', 1)[0]
        output_filename = f"{base_name}_filled.xlsx"
        
        return df_clean, output_buffer, output_filename, None
    except Exception as e:
        return None, None, None, str(e)

# ===================== EXCEL COMBINER FUNCTIONS =====================
def collect_tube_data_from_files(uploaded_files):
    """Collect tube data from uploaded Excel files."""
    tube_data = []
    
    for uploaded_file in uploaded_files:
        filename = uploaded_file.name
        uploaded_file.seek(0)
        
        try:
            if filename.endswith(".xls"):
                # Handle .xls files
                file_contents = uploaded_file.read()
                wb = xlrd.open_workbook(file_contents=file_contents)
                sheet = wb.sheet_by_index(0)
                
                for row in range(1, sheet.nrows):
                    tube_value = sheet.cell_value(row, 2)  # column C
                    if tube_value:
                        tube_data.append([tube_value, "", "", "", ""])
                        
            elif filename.endswith(".xlsx"):
                # Handle .xlsx files
                wb = openpyxl.load_workbook(uploaded_file)
                sheet = wb.active
                
                for row in range(2, sheet.max_row + 1):
                    tube_value = sheet.cell(row=row, column=3).value  # column C
                    if tube_value:
                        tube_data.append([tube_value, "", "", "", ""])
                        
        except Exception as e:
            st.error(f"Error processing {filename}: {str(e)}")
            continue
    
    return tube_data

def remove_duplicates(tube_data):
    """Remove duplicate tube entries."""
    seen = set()
    unique_data = []
    
    for row in tube_data:
        tube_id = row[0]
        if tube_id not in seen:
            seen.add(tube_id)
            unique_data.append(row)
    
    return unique_data

def normalize_tube_ids(df, column="Tube ID"):
    """Normalize tube IDs for matching."""
    df = df.copy()
    df["_normalized_tube"] = df[column].astype(str).str.strip().str.lower()
    return df

def extract_plant_code(tube_id):
    """Extract plant code from tube ID."""
    match = re.search(r'(\d+)', str(tube_id))
    return match.group(1) if match else ""

def match_and_process(combined_df, reference_df):
    """Match combined data with reference file and process."""
    combined_df = normalize_tube_ids(combined_df)
    reference_df = normalize_tube_ids(reference_df)
    
    ref_lookup = reference_df.set_index("_normalized_tube")
    final_rows = []
    
    for _, row in combined_df.iterrows():
        tube_id_norm = row["_normalized_tube"]
        original_tube_id = row["Tube ID"]
        
        if tube_id_norm in ref_lookup.index:
            matched_row = ref_lookup.loc[tube_id_norm]
            if isinstance(matched_row, pd.DataFrame):
                matched_row = matched_row.iloc[0]
            matched_row = matched_row.drop(labels=["_normalized_tube"], errors="ignore")
            
            # Auto-fill plant code if missing
            if pd.isna(matched_row.get("Plant Code", None)) or str(matched_row.get("Plant Code")).strip() == "":
                matched_row["Plant Code"] = extract_plant_code(original_tube_id)
            matched_row["__missing"] = False
            final_rows.append(matched_row)
        else:
            plant_code = extract_plant_code(original_tube_id)
            new_row = {
                "Plant Code": plant_code,
                "Tube ID": original_tube_id,
                "Clone #": "",
                "Strain": "",
                "Notes": "Tube missing from reference Excel sheet",
                "__missing": True
            }
            final_rows.append(pd.Series(new_row))
    
    final_df = pd.DataFrame(final_rows)
    
    # Reorder columns and add empty column
    final_df.insert(2, " ", "")
    final_df = final_df[["Plant Code", "Tube ID", " ", "Strain", "Clone #", "Notes", "__missing"]]
    
    # Sort missing tubes to bottom
    final_df.sort_values(by="__missing", inplace=True)
    final_df.drop(columns=["__missing"], inplace=True)
    
    return final_df

# ===================== STREAMLIT APP FUNCTIONS =====================
def plant_data_processor():
    """Plant Data Processor function."""
    st.markdown('<div class="nav-header">🌱 Plant Data Processor</div>', unsafe_allow_html=True)
    
    # Check if template is uploaded
    template_file = st.file_uploader(
        "Upload Template File (z-sheet.xlsx)",
        type=['xlsx'],
        key="template_upload",
        help="Upload your z-sheet template file"
    )
    
    if not template_file:
        st.warning("⚠️ Please upload the z-sheet template file to continue.")
        return
    
    st.success("✅ Template file uploaded successfully!")
    
    # Data files upload
    st.header("📊 Data Files Upload")
    uploaded_files = st.file_uploader(
        "Upload your data files (CSV or Excel)",
        type=['csv', 'xlsx'],
        accept_multiple_files=True,
        key="data_files"
    )
    
    if not uploaded_files:
        st.info("Please upload one or more data files to process.")
        return
    
    # Process button
    st.markdown('<div class="big-action-button process-button">', unsafe_allow_html=True)
    process_clicked = st.button("🚀 Process All Files", key="process_data")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if process_clicked:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            
            # Create template buffer for each file
            template_file.seek(0)
            template_buffer = io.BytesIO(template_file.read())
            
            df_clean, output_buffer, output_filename, error = process_single_file(
                uploaded_file, uploaded_file.name, template_buffer
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
        
        if results:
            st.header("📥 Download Results")
            
            for result in results:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.text(f"📄 {result['output_name']} ({len(result['data'])} rows)")
                with col2:
                    st.download_button(
                        label="📥 Download",
                        data=result['file_buffer'].getvalue(),
                        file_name=result['output_name'],
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key=f"download_{result['output_name']}"
                    )

def excel_combiner():
    """Excel File Combiner & Processor function."""
    st.markdown('<div class="nav-header">📋 Excel File Combiner & Processor</div>', unsafe_allow_html=True)
    
    st.markdown("""
    This tool combines multiple Excel files, removes duplicates, and matches against a reference file.
    
    **Process:**
    1. Upload multiple Excel files to combine
    2. Upload a reference file for data matching
    3. The tool will extract tube data, remove duplicates, and create a final processed file
    """)
    
    # Step 1: Upload files to combine
    st.header("📁 Step 1: Upload Files to Combine")
    combine_files = st.file_uploader(
        "Upload Excel files to combine (.xls or .xlsx)",
        type=['xls', 'xlsx'],
        accept_multiple_files=True,
        key="combine_files",
        help="These files will be combined and processed"
    )
    
    # Step 2: Upload reference file
    st.header("📄 Step 2: Upload Reference File")
    reference_file = st.file_uploader(
        "Upload reference Excel file",
        type=['xlsx'],
        key="reference_file",
        help="This file contains the reference data for matching"
    )
    
    if not combine_files or not reference_file:
        st.info("Please upload both the files to combine and the reference file.")
        return
    
    # Process button
    st.markdown('<div class="big-action-button combine-button">', unsafe_allow_html=True)
    combine_clicked = st.button("🔄 Combine & Process Files", key="combine_process")
    st.markdown('</div>', unsafe_allow_html=True)
    
    if combine_clicked:
        try:
            # Step 1: Collect tube data
            st.info("🔍 Collecting tube data from uploaded files...")
            tube_data = collect_tube_data_from_files(combine_files)
            st.success(f"✅ Collected {len(tube_data)} tube entries")
            
            # Step 2: Remove duplicates
            st.info("🧹 Removing duplicates...")
            unique_data = remove_duplicates(tube_data)
            duplicates_removed = len(tube_data) - len(unique_data)
            st.success(f"✅ Removed {duplicates_removed} duplicates, {len(unique_data)} unique entries remain")
            
            # Step 3: Create combined DataFrame
            combined_df = pd.DataFrame(unique_data, columns=["Tube ID", "Plant Code", "Clone #", "Strain", "Notes"])
            
            # Step 4: Load reference file
            st.info("📖 Loading reference file...")
            reference_file.seek(0)
            reference_df = pd.read_excel(reference_file)
            st.success(f"✅ Loaded reference file with {len(reference_df)} entries")
            
            # Step 5: Match and process
            st.info("🔗 Matching data and processing...")
            final_df = match_and_process(combined_df, reference_df)
            st.success(f"✅ Processing complete! Final file has {len(final_df)} entries")
            
            # Save results
            output_buffer = io.BytesIO()
            final_df.to_excel(output_buffer, index=False)
            output_buffer.seek(0)
            
            # Display results
            st.header("📊 Results Summary")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Original Entries", len(tube_data))
            with col2:
                st.metric("After Deduplication", len(unique_data))
            with col3:
                st.metric("Matched Entries", len(final_df[final_df['Notes'] != "Tube missing from reference Excel sheet"]))
            with col4:
                st.metric("Missing Entries", len(final_df[final_df['Notes'] == "Tube missing from reference Excel sheet"]))
            
            # Download button
            st.header("📥 Download Results")
            st.markdown('<div class="big-action-button download-button">', unsafe_allow_html=True)
            st.download_button(
                label="📥 Download Final Processed File",
                data=output_buffer.getvalue(),
                file_name="Final_Combined_Output.xlsx",
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="download_final"
            )
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Preview
            st.header("👀 Data Preview")
            st.dataframe(final_df.head(20), use_container_width=True)
            
        except Exception as e:
            st.error(f"❌ Error during processing: {str(e)}")

def function_3():
    """Placeholder for third function."""
    st.markdown('<div class="nav-header">⚙️ Function 3 - Coming Soon</div>', unsafe_allow_html=True)
    
    st.info("🚧 This function is under development. Please check back later!")
    
    st.markdown("""
    **Planned Features:**
    - Additional data processing capabilities
    - Advanced analytics and reporting
    - Custom data transformations
    
    Stay tuned for updates! 🌱
    """)

def main():
    """Main application function."""
    # Sidebar navigation
    st.sidebar.title("🌱 Plant Data Suite")
    st.sidebar.markdown("---")
    
    # Navigation options
    app_mode = st.sidebar.radio(
        "Choose Function:",
        [
            "🌱 Plant Data Processor", 
            "📋 Excel Combiner & Processor",
            "⚙️ Function 3"
        ],
        key="main_nav"
    )
    
    # Function descriptions in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📖 Function Descriptions")
    
    if "Plant Data Processor" in app_mode:
        st.sidebar.markdown("""
        **🌱 Plant Data Processor**
        - Standardize plant data formats
        - Fill template spreadsheets
        - Process multiple files at once
        """)
    elif "Excel Combiner" in app_mode:
        st.sidebar.markdown("""
        **📋 Excel Combiner & Processor**
        - Combine multiple Excel files
        - Remove duplicate entries
        - Match against reference data
        """)
    else:
        st.sidebar.markdown("""
        **⚙️ Function 3**
        - Coming soon!
        - Advanced processing features
        - Custom data transformations
        """)
    
    # Route to appropriate function
    if "Plant Data Processor" in app_mode:
        plant_data_processor()
    elif "Excel Combiner" in app_mode:
        excel_combiner()
    elif "Function 3" in app_mode:
        function_3()

if __name__ == "__main__":
    main()
