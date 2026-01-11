import streamlit as st
import psycopg2
from psycopg2 import pool
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

# ================= DATABASE CONNECTION POOL =================

@st.cache_resource
def init_db_pool():
    """สร้าง Connection Pool เพียงครั้งเดียวและ Cache ไว้"""
    try:
        pool_obj = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,  # รองรับได้สูงสุด 10 connections พร้อมกัน
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        print("✅ Database Connection Pool created")
        return pool_obj
    except Exception as e:
        st.error(f"Failed to create connection pool: {e}")
        return None

def query_db(query, params=None, fetch_df=False):
    """ฟังก์ชันกลางสำหรับดึงข้อมูลผ่าน Pool"""
    db_pool = init_db_pool()
    if not db_pool:
        return None

    # ยืม Connection จาก Pool
    conn = db_pool.getconn()
    result = None
    
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            
            if fetch_df:
                # กรณีต้องการ DataFrame (แก้ Warning Pandas ตรงนี้)
                data = cur.fetchall()
                colnames = [desc[0] for desc in cur.description]
                result = pd.DataFrame(data, columns=colnames)
            else:
                # กรณีต้องการแค่ Row เดียว หรือข้อมูลดิบ
                result = cur.fetchall()
                
    except Exception as e:
        st.error(f"Database Query Error: {e}")
        # ถ้า Connection เสีย ให้ reset pool (optional logic)
    finally:
        # คืน Connection กลับเข้า Pool เสมอ (สำคัญมาก!)
        db_pool.putconn(conn)
        
    return result

# ================= DATA FETCHING FUNCTIONS =================

def get_all_project_ids():
    """ดึงรายชื่อ Project ID ทั้งหมด"""
    query = "SELECT project_id, created_at FROM batch_data.batch_json ORDER BY created_at DESC"
    df = query_db(query, fetch_df=True)
    return df if df is not None else pd.DataFrame()

def get_project_data(project_id):
    """ดึง JSON ข้อมูลของ Project นั้นๆ"""
    query = "SELECT json, created_at FROM batch_data.batch_json WHERE project_id = %s"
    rows = query_db(query, params=(project_id,))
    
    if rows and len(rows) > 0:
        return rows[0]  # คืนค่า (json_data, created_at)
    return None

# ================= UI HELPER FUNCTIONS =================

def display_document_list(title, docs_list, icon="📄"):
    if docs_list and len(docs_list) > 0:
        st.markdown(f"**{title}**")
        for doc in docs_list:
            st.info(f"{icon} {doc}")
    else:
        st.markdown(f"**{title}**")
        st.caption("*(ไม่มีรายการเอกสาร)*")

# ================= MAIN APP =================

def main():
    st.title("📂 TOR Document Extraction Viewer")
    st.markdown("---")

    # --- SIDEBAR ---
    st.sidebar.header("🔍 เลือกโครงการ")
    
    # ดึงข้อมูลผ่าน Pool
    df_projects = get_all_project_ids()
    
    if df_projects.empty:
        st.sidebar.warning("ไม่พบข้อมูลในฐานข้อมูล")
        st.stop()
        
    project_options = df_projects['project_id'].tolist()
    
    selected_id = st.sidebar.selectbox(
        "Project ID:", 
        project_options,
        index=0
    )
    
    if st.sidebar.button("🔄 Refresh Data"):
        # Clear Cache เพื่อบังคับให้โหลดข้อมูลใหม่ (แต่ Pool ยังอยู่)
        st.rerun()

    # --- MAIN CONTENT ---
    if selected_id:
        row = get_project_data(selected_id)
        if row:
            json_data, created_at = row
            
            c1, c2 = st.columns([3, 1])
            c1.subheader(f"📌 Project ID: {selected_id}")
            c2.caption(f"Extraction Date: {created_at}")
            
            root = json_data.get('bid_submission_documents_part_1', {})
            if not root: root = json_data 

            tab1, tab2, tab3, tab4, tab5 = st.tabs([
                "🏢 นิติบุคคล", 
                "👤 บุคคลธรรมดา", 
                "🤝 กิจการร่วมค้า", 
                "💰 หลักฐานการเงิน", 
                "📎 เอกสารอื่นๆ"
            ])

            with tab1:
                st.markdown("### 1. เอกสารสำหรับนิติบุคคล")
                legal_docs = root.get('1_legal_entity_documents', {})
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("#### ห้างหุ้นส่วนสามัญ/จำกัด")
                    display_document_list("รายการเอกสาร:", legal_docs.get('case_partnership', {}).get('required_documents', []))
                with col_b:
                    st.markdown("#### บริษัทจำกัด")
                    display_document_list("รายการเอกสาร:", legal_docs.get('case_company', {}).get('required_documents', []))

            with tab2:
                st.markdown("### 2. เอกสารสำหรับบุคคลธรรมดา")
                display_document_list("รายการเอกสาร:", root.get('2_individual_documents', {}).get('required_documents', []), icon="user")

            with tab3:
                st.markdown("### 3. เอกสารสำหรับผู้ร่วมค้า")
                display_document_list("รายการเอกสาร:", root.get('3_joint_venture_documents', {}).get('required_documents', []), icon="🤝")

            with tab4:
                st.markdown("### 4. หลักฐานแสดงฐานะการเงิน")
                finance = root.get('4_financial_capability_evidence', {})
                if finance.get('note'): st.warning(f"⚠️ หมายเหตุ: {finance.get('note')}")
                options = finance.get('options', [])
                if options:
                    for idx, opt in enumerate(options, 1):
                        with st.expander(f"ทางเลือกที่ {idx}: {opt.get('condition', 'เงื่อนไข')}", expanded=True):
                            st.write(f"📄 **เอกสารที่ต้องใช้:** {opt.get('document', '-')}")
                else:
                    st.caption("ไม่มีข้อมูลทางเลือก")

            with tab5:
                st.markdown("### 5. เอกสารอื่นๆ / บัญชีเอกสาร")
                display_document_list("รายการเอกสาร:", root.get('5_general_documents', {}).get('required_documents', []), icon="📎")

            st.markdown("---")
            with st.expander("🛠️ View Raw JSON Data"):
                st.json(json_data)

if __name__ == "__main__":
    main()