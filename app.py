import streamlit as st
import psycopg2
import pandas as pd
import json
import os
from dotenv import load_dotenv

# โหลดตัวแปรจาก .env
load_dotenv()

# ================= CONFIGURATION =================
st.set_page_config(
    page_title="TOR Document Viewer",
    page_icon="📂",
    layout="wide"
)

# Database Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")

# ================= DATABASE FUNCTIONS =================

# ใช้ cache_resource เพื่อเชื่อมต่อ DB ครั้งเดียว ไม่ต้องต่อใหม่ทุกครั้งที่คลิก
@st.cache_resource
def init_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

def get_all_project_ids():
    """ดึงรายชื่อ Project ID ทั้งหมดมาแสดงใน Sidebar (แก้ Warning)"""
    conn = init_connection()
    try:
        # ใช้ cursor แทน pd.read_sql โดยตรง
        with conn.cursor() as cur:
            query = "SELECT project_id, created_at FROM batch_data.batch_json ORDER BY created_at DESC"
            cur.execute(query)
            data = cur.fetchall()
            
            # ดึงชื่อคอลัมน์
            colnames = [desc[0] for desc in cur.description]
            
            # สร้าง DataFrame เอง
            df = pd.DataFrame(data, columns=colnames)
            return df
            
    except Exception as e:
        st.error(f"Database Error: {e}")
        return pd.DataFrame()

def get_project_data(project_id):
    """ดึง JSON ข้อมูลของ Project นั้นๆ"""
    conn = init_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT json, created_at FROM batch_data.batch_json WHERE project_id = %s", (project_id,))
        row = cur.fetchone()
        return row
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return None

# ================= UI HELPER FUNCTIONS =================

def display_document_list(title, docs_list, icon="📄"):
    """ฟังก์ชันช่วยแสดงรายการเอกสารให้สวยงาม"""
    if docs_list and len(docs_list) > 0:
        st.markdown(f"**{title}**")
        for doc in docs_list:
            st.info(f"{icon} {doc}")
    else:
        # ถ้าไม่มีข้อมูล ให้แสดงข้อความจางๆ
        st.markdown(f"**{title}**")
        st.caption("*(ไม่มีรายการเอกสาร)*")

# ================= MAIN APP =================

def main():
    st.title("📂 TOR Document Extraction Viewer")
    st.markdown("---")

    # --- SIDEBAR ---
    st.sidebar.header("🔍 เลือกโครงการ")
    
    df_projects = get_all_project_ids()
    
    if df_projects.empty:
        st.sidebar.warning("ไม่พบข้อมูลในฐานข้อมูล")
        st.stop()
        
    # สร้าง List สำหรับ Selectbox (แสดง ID คู่กับวันที่)
    project_options = df_projects['project_id'].tolist()
    
    selected_id = st.sidebar.selectbox(
        "Project ID:", 
        project_options,
        index=0
    )
    
    # ปุ่ม Refresh
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_resource.clear()
        st.rerun()

    # --- MAIN CONTENT ---
    if selected_id:
        row = get_project_data(selected_id)
        if row:
            json_data, created_at = row
            
            # Header Info
            c1, c2 = st.columns([3, 1])
            c1.subheader(f"📌 Project ID: {selected_id}")
            c2.caption(f"Extraction Date: {created_at}")
            
            # Parse Data Logic
            # เข้าถึง Root Key (บางที AI อาจตอบมาเริ่มที่ root หรือเริ่มที่ sub key ต้องกันเหนียว)
            root = json_data.get('bid_submission_documents_part_1', {})
            if not root:
                # เผื่อ AI ตอบมาแบบไม่มี root key
                root = json_data 

            # แบ่ง Tabs เพื่อความอ่านง่าย
            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "🏢 นิติบุคคล", 
                "👤 บุคคลธรรมดา", 
                "🤝 กิจการร่วมค้า", 
                "💰 หลักฐานการเงิน", 
                "📎 เอกสารอื่นๆ"
            ])

            # --- TAB 1: นิติบุคคล ---
            with tab1:
                st.markdown("### 1. เอกสารสำหรับนิติบุคคล")
                legal_docs = root.get('1_legal_entity_documents', {})
                
                col_a, col_b = st.columns(2)
                
                with col_a:
                    st.markdown("#### ห้างหุ้นส่วนสามัญ/จำกัด")
                    partnership = legal_docs.get('case_partnership', {})
                    display_document_list("รายการเอกสาร:", partnership.get('required_documents', []))
                
                with col_b:
                    st.markdown("#### บริษัทจำกัด")
                    company = legal_docs.get('case_company', {})
                    display_document_list("รายการเอกสาร:", company.get('required_documents', []))

            # --- TAB 2: บุคคลธรรมดา ---
            with tab2:
                st.markdown("### 2. เอกสารสำหรับบุคคลธรรมดา")
                indiv = root.get('2_individual_documents', {})
                display_document_list("รายการเอกสาร:", indiv.get('required_documents', []), icon="👤")

            # --- TAB 3: กิจการร่วมค้า ---
            with tab3:
                st.markdown("### 3. เอกสารสำหรับผู้ร่วมค้า")
                joint = root.get('3_joint_venture_documents', {})
                display_document_list("รายการเอกสาร:", joint.get('required_documents', []), icon="🤝")

            # --- TAB 4: หลักฐานการเงิน ---
            with tab4:
                st.markdown("### 4. หลักฐานแสดงฐานะการเงิน")
                finance = root.get('4_financial_capability_evidence', {})
                
                # Note
                if finance.get('note'):
                    st.warning(f"⚠️ หมายเหตุ: {finance.get('note')}")
                
                # Options (เงื่อนไข)
                options = finance.get('options', [])
                if options:
                    for idx, opt in enumerate(options, 1):
                        with st.expander(f"ทางเลือกที่ {idx}: {opt.get('condition', 'เงื่อนไข')}", expanded=True):
                            st.write(f"📄 **เอกสารที่ต้องใช้:** {opt.get('document', '-')}")
                else:
                    st.caption("ไม่มีข้อมูลทางเลือก")

            # --- TAB 5: เอกสารอื่นๆ ---
            with tab5:
                st.markdown("### 5. เอกสารอื่นๆ / บัญชีเอกสาร")
                general = root.get('5_general_documents', {})
                display_document_list("รายการเอกสาร:", general.get('required_documents', []), icon="📎")

            # --- RAW DATA (For Debugging) ---
            st.markdown("---")
            with st.expander("🛠️ View Raw JSON Data"):
                st.json(json_data)

if __name__ == "__main__":
    main()