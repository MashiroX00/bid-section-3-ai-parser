import os
import json
import re
import asyncio
import time
import pdfplumber
import psycopg2
from psycopg2.extras import Json
from openai import OpenAI
from dotenv import load_dotenv

# โหลดตัวแปรสภาพแวดล้อม
load_dotenv()

# ================= CONFIGURATION =================
API_KEY = os.getenv("OPENAI_API_KEY")
INPUT_FOLDER = "input_pdfs"
BATCH_FILE_NAME = "batch_input_pg.jsonl"
BATCH_ID_LOG = "current_batch_id.txt"
INTERVAL_TIME = 120 # 2 นาที
# Database Config
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "postgres")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")

# System Options
SKIP_EXISTING = True       # True = ถ้ามีใน DB แล้วจะไม่ส่งไป AI ใหม่
MODEL_NAME = "gpt-4o-mini" 
CONCURRENT_LIMIT = 20      # จำนวนไฟล์ที่ประมวลผลพร้อมกัน

if not API_KEY:
    raise ValueError("❌ Error: OPENAI_API_KEY not found in .env file")

client = OpenAI(api_key=API_KEY)

# ================= PROMPT & SCHEMA =================
TARGET_JSON_SCHEMA = """
{
  "bid_submission_documents_part_1": {
    "1_legal_entity_documents": {
      "case_partnership": { "description": "ระบุประเภท เช่น ห้างหุ้นส่วน", "required_documents": [] },
      "case_company": { "description": "ระบุประเภท เช่น บริษัทจำกัด", "required_documents": [] }
    },
    "2_individual_documents": { "description": "บุคคลธรรมดา", "required_documents": [] },
    "3_joint_venture_documents": { "description": "ผู้ร่วมค้า", "required_documents": [] },
    "4_financial_capability_evidence": { "description": "หลักฐานการเงิน", "options": [{"condition": "...", "document": "..."}], "note": "..." },
    "5_general_documents": { "description": "เอกสารอื่นๆ", "required_documents": [] }
  }
}
"""

SYSTEM_PROMPT = f"""
คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์เอกสาร TOR
หน้าที่: สกัดข้อมูลรายการเอกสารจากข้อความ "ส่วนที่ 1 (หลักฐานการยื่นข้อเสนอ)" ที่ได้รับ
Output: JSON ตาม Schema นี้เท่านั้น:
{TARGET_JSON_SCHEMA}

กฎ:
- ตอบกลับเป็น JSON เท่านั้น
- ถ้าข้อมูลส่วนไหนไม่มี ให้ใส่ [] หรือ null
- ห้ามเพิ่ม Key อื่นนอกเหนือจาก Schema
"""

# ================= DATABASE LAYER =================

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS
    )

def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS batch_data;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS batch_data.batch_json(
                    project_id varchar(255) primary key not null,
                    json jsonb,
                    created_at timestamp not null default current_timestamp
                );
            """)
        conn.commit()
    except Exception as e:
        print(f"❌ DB Init Error: {e}")
    finally:
        conn.close()

def get_all_existing_ids():
    conn = get_db_connection()
    existing_ids = set()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT project_id FROM batch_data.batch_json")
            rows = cur.fetchall()
            for row in rows:
                existing_ids.add(row[0])
    finally:
        conn.close()
    return existing_ids

def save_results_to_db(results_list):
    conn = get_db_connection()
    success_count = 0
    try:
        with conn.cursor() as cur:
            query = """
                INSERT INTO batch_data.batch_json (project_id, json, created_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (project_id) 
                DO UPDATE SET 
                    json = EXCLUDED.json, 
                    created_at = CURRENT_TIMESTAMP;
            """
            data_tuples = [(item['id'], Json(item['data'])) for item in results_list]
            cur.executemany(query, data_tuples)
            success_count = len(results_list)
        conn.commit()
    except Exception as e:
        print(f"❌ Database Insert Error: {e}")
        conn.rollback()
    finally:
        conn.close()
    return success_count

# ================= TEXT EXTRACTION LAYER =================

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_evidence_section(pdf_path):
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        
        pattern = r"(๓\.\s*หลักฐานการยื่นข้อเสนอ.*?)(?=\n\s*๓\.๒|\n\s*3\.2|\n\s*ส่วนที่\s*๒)"
        match = re.search(pattern, full_text, re.DOTALL)
        
        if match:
            extracted_content = match.group(1)
            extracted_content = re.sub(r"^๓\.\s*หลักฐานการยื่นข้อเสนอ", "", extracted_content).strip()
            return clean_text(extracted_content)
        else:
            return None
    except Exception as e:
        return None

# ================= ASYNC PROCESS (STEP 1) =================

async def process_single_file(sem, filename, existing_ids):
    async with sem:
        project_id = os.path.splitext(filename)[0]

        if SKIP_EXISTING and project_id in existing_ids:
            return "SKIPPED"

        file_path = os.path.join(INPUT_FOLDER, filename)
        extracted_text = await asyncio.to_thread(extract_evidence_section, file_path)

        if not extracted_text:
            return "REGEX_FAILED"

        return {
            "custom_id": filename,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"ข้อมูลเอกสาร:\n{extracted_text}"}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
        }

async def create_batch_file_async():
    if not os.path.exists(INPUT_FOLDER):
        print(f"❌ ไม่พบโฟลเดอร์ {INPUT_FOLDER}")
        return None

    pdf_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print("❌ ไม่พบไฟล์ PDF")
        return None

    print("⏳ กำลังเตรียม Database...")
    await asyncio.to_thread(init_db)
    existing_ids = await asyncio.to_thread(get_all_existing_ids)
    print(f"📋 พบข้อมูลเดิมใน DB {len(existing_ids)} รายการ")

    print(f"🚀 เริ่มประมวลผล {len(pdf_files)} ไฟล์ (พร้อมกัน {CONCURRENT_LIMIT} threads)...")
    
    sem = asyncio.Semaphore(CONCURRENT_LIMIT)
    tasks = []
    for filename in pdf_files:
        tasks.append(process_single_file(sem, filename, existing_ids))

    results = await asyncio.gather(*tasks)

    valid_tasks = []
    skipped_count = 0
    regex_failed_count = 0

    for res in results:
        if res == "SKIPPED":
            skipped_count += 1
        elif res == "REGEX_FAILED":
            regex_failed_count += 1
        elif isinstance(res, dict):
            valid_tasks.append(res)

    print(f"\n--- สรุปผลการเตรียมข้อมูล ---")
    print(f"⏩ ข้าม (มีใน DB แล้ว): {skipped_count}")
    print(f"⚠️  ข้าม (หา Section ไม่เจอ): {regex_failed_count}")
    print(f"✅ พร้อมส่ง (งานใหม่): {len(valid_tasks)}")

    if not valid_tasks:
        print("❌ ไม่มีงานใหม่ให้ส่ง")
        return None

    with open(BATCH_FILE_NAME, "w", encoding="utf-8") as f:
        for task in valid_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
            
    print(f"💾 สร้างไฟล์ Batch เรียบร้อย: {BATCH_FILE_NAME}")
    return BATCH_FILE_NAME

# ================= SHARED LOGIC (SUBMIT & PROCESS) =================

def upload_and_submit_batch(jsonl_file):
    """ส่ง Batch ไป OpenAI และคืนค่า Batch ID"""
    print("\n☁️  กำลังอัปโหลดและส่งคำสั่ง...")
    try:
        batch_input_file = client.files.create(
            file=open(jsonl_file, "rb"),
            purpose="batch"
        )
        
        batch_job = client.batches.create(
            input_file_id=batch_input_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        
        with open(BATCH_ID_LOG, "w") as f:
            f.write(batch_job.id)
            
        print(f"✅ ส่งคำสั่งสำเร็จ! Batch ID: {batch_job.id}")
        return batch_job.id
        
    except Exception as e:
        print(f"❌ Submit Error: {e}")
        return None

def download_and_save_results(batch_id):
    """โหลดผลลัพธ์และบันทึกลง DB"""
    print(f"⬇️  กำลังดาวน์โหลดผลลัพธ์ (ID: {batch_id})...")
    try:
        batch_job = client.batches.retrieve(batch_id)
        content = client.files.content(batch_job.output_file_id).text
        
        lines = content.strip().split('\n')
        data_to_save = []
        
        for line in lines:
            try:
                data = json.loads(line)
                filename = data['custom_id']
                project_id = os.path.splitext(filename)[0]
                
                response_body = data['response']['body']
                if 'choices' in response_body:
                    ai_content = response_body['choices'][0]['message']['content']
                    parsed_json = json.loads(ai_content)
                    
                    data_to_save.append({
                        "id": project_id,
                        "data": parsed_json
                    })
            except Exception as e:
                print(f"   ❌ Parse Error: {e}")
        
        if data_to_save:
            print(f"💾 กำลังบันทึก {len(data_to_save)} รายการลง Database...")
            saved_count = save_results_to_db(data_to_save)
            print(f"✅ บันทึกเสร็จสิ้น {saved_count} รายการ")
            return True
    except Exception as e:
        print(f"❌ Save Error: {e}")
        return False

# ================= OPTION 3: AUTO PILOT =================

async def run_auto_pilot():
    print("\n" + "="*40)
    print("   🚀 STARTING AUTO PILOT MODE")
    print("="*40)
    
    # 1. Prepare & Submit
    jsonl_path = await create_batch_file_async()
    if not jsonl_path:
        return

    batch_id = upload_and_submit_batch(jsonl_path)
    if not batch_id:
        return

    # 2. Polling Loop
    print(f"\n--- 🔄 เข้าสู่โหมดติดตามสถานะอัตโนมัติ (ตรวจสอบทุก 2 นาที) ---")
    start_time = time.time()
    
    while True:
        try:
            batch_job = client.batches.retrieve(batch_id)
            status = batch_job.status
            elapsed = int((time.time() - start_time) / 60)
            
            print(f"⏱️  [{elapsed} นาที] Status: {status.upper()}")

            if status == "completed":
                print("🎉 งานเสร็จสิ้นแล้ว! เริ่มกระบวนการบันทึกข้อมูล...")
                download_and_save_results(batch_id)
                print("✅ Auto Pilot เสร็จสมบูรณ์")
                break
            
            elif status in ["failed", "expired", "cancelled"]:
                print(f"❌ งานล้มเหลว (Status: {status})")
                if batch_job.errors:
                    print(f"Errors: {batch_job.errors}")
                break
                
            else:
                # validating, in_progress, finalizing
                print(f"💤 ยังไม่เสร็จ... รอตรวจสอบใหม่ใน {INTERVAL_TIME // 60} นาที")
                await asyncio.sleep(INTERVAL_TIME)  # รอ INTERVAL_TIME วินาที (2 นาที)
                
        except Exception as e:
            print(f"⚠️ Error checking status: {e}")
            await asyncio.sleep(60) # ถ้า Error ให้รอ 1 นาทีแล้วลองใหม่

# ================= MAIN MENU =================

def main_menu():
    print("\n=========================================")
    print("   TOR PDF EXTRACTOR (PGSQL + BATCH)   ")
    print("=========================================")
    print("1. ส่งงาน (Submit Only) - สร้าง Batch แล้วจบ")
    print("2. รับงาน (Check & Save) - ตรวจสอบ ID ล่าสุด")
    print("3. ออโต้ (Auto Pilot) - ส่งงาน + รอจนเสร็จ + บันทึก")
    
    choice = input("\nเลือกคำสั่ง (1/2/3): ").strip()
    
    if choice == "1":
        jsonl_path = asyncio.run(create_batch_file_async())
        if jsonl_path:
            upload_and_submit_batch(jsonl_path)
            
    elif choice == "2":
        if os.path.exists(BATCH_ID_LOG):
            with open(BATCH_ID_LOG, "r") as f:
                batch_id = f.read().strip()
            
            # เช็คสถานะก่อน
            try:
                job = client.batches.retrieve(batch_id)
                print(f"Status: {job.status}")
                if job.status == "completed":
                    download_and_save_results(batch_id)
                else:
                    print("⏳ งานยังไม่เสร็จครับ")
            except Exception as e:
                print(f"Error: {e}")
        else:
            print("❌ ไม่พบ Batch ID เดิม")
            
    elif choice == "3":
        asyncio.run(run_auto_pilot())
        
    else:
        print("ตัวเลือกไม่ถูกต้อง")

if __name__ == "__main__":
    main_menu()