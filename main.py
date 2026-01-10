import os
import json
import re
import pdfplumber
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ================= CONFIGURATION =================
API_KEY = os.getenv("OPENAI_API_KEY")
INPUT_FOLDER = "input_pdfs"
OUTPUT_FOLDER = "output_jsons"
BATCH_FILE_NAME = "batch_input_filtered.jsonl"
BATCH_ID_LOG = "current_batch_id.txt"

# --- [NEW] ตั้งค่าการข้ามไฟล์ ---
# True  = ข้ามไฟล์ที่มี Output JSON อยู่แล้ว (ประหยัดเงิน/เวลา)
# False = บังคับทำใหม่ทั้งหมด (Overwirte ของเดิม)
SKIP_EXISTING = True 

# Model Configuration
MODEL_NAME = "gpt-4o-mini" 

if not API_KEY:
    raise ValueError("OPENAI_API_KEY not found in .env file")

client = OpenAI(api_key=API_KEY)

# ================= 1. EXTRACTION LOGIC =================

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_evidence_section(pdf_path):
    """ดึงเฉพาะส่วน 'หลักฐานการยื่นข้อเสนอ' ด้วย pdfplumber + Regex"""
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
        
        # Pattern: หา "๓. หลักฐาน..." จนถึงก่อนเจอ "๓.๒" หรือ "3.2" หรือ "ส่วนที่ ๒"
        pattern = r"(๓\.\s*หลักฐานการยื่นข้อเสนอ.*?)(?=\n\s*๓\.๒|\n\s*3\.2|\n\s*ส่วนที่\s*๒)"
        
        match = re.search(pattern, full_text, re.DOTALL)
        
        if match:
            extracted_content = match.group(1)
            extracted_content = re.sub(r"^๓\.\s*หลักฐานการยื่นข้อเสนอ", "", extracted_content).strip()
            return clean_text(extracted_content)
        else:
            return None
            
    except Exception as e:
        print(f"❌ Error reading PDF {pdf_path}: {e}")
        return None

# ================= 2. OPENAI BATCH LOGIC =================

TARGET_JSON_SCHEMA = """
{
  "bid_submission_documents_part_1": {
    "1_legal_entity_documents": {
      "case_partnership": { "description": "ห้างหุ้นส่วน...", "required_documents": [] },
      "case_company": { "description": "บริษัทจำกัด...", "required_documents": [] }
    },
    "2_individual_documents": { "description": "บุคคลธรรมดา", "required_documents": [] },
    "3_joint_venture_documents": { "description": "ผู้ร่วมค้า", "required_documents": [] },
    "4_financial_capability_evidence": { "description": "หลักฐานการเงิน", "options": [{"condition": "...", "document": "..."}], "note": "..." },
    "5_general_documents": { "description": "เอกสารอื่นๆ", "required_documents": [] }
  }
}
"""

SYSTEM_PROMPT = f"""
คุณคือผู้ช่วยจัดระเบียบข้อมูล
ฉันจะส่งข้อความส่วน "หลักฐานการยื่นข้อเสนอ" (Section 3) ของ TOR ให้คุณ
หน้าที่ของคุณคือนำรายการเอกสารในข้อความ ไปใส่ลงใน JSON Structure ที่กำหนดให้ถูกต้อง

**JSON Schema:**
{TARGET_JSON_SCHEMA}

**กฎ:**
- ตอบกลับเป็น JSON เท่านั้น
- ถ้าในข้อความไม่มีระบุหัวข้อไหน ให้ใส่ [] หรือ null
- คงชื่อ Key ไว้ตาม Schema เป๊ะๆ
- สามารถเพิ่ม key ได้ตามความสอดคล้องของข้อมูลที่ได้รับ
"""

def create_batch_file():
    """ขั้นตอนที่ 1: ตรวจสอบไฟล์ -> อ่าน PDF -> สร้าง JSONL"""
    if not os.path.exists(INPUT_FOLDER):
        print(f"ไม่พบโฟลเดอร์ {INPUT_FOLDER}")
        return None

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    pdf_files = [f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print("ไม่พบไฟล์ PDF")
        return None

    print(f"--- เริ่มเตรียมข้อมูล ({len(pdf_files)} ไฟล์) ---")
    print(f"Option SKIP_EXISTING: {SKIP_EXISTING}")
    
    tasks = []
    skipped_count = 0
    regex_failed_count = 0

    for filename in pdf_files:
        file_path = os.path.join(INPUT_FOLDER, filename)
        
        # --- [NEW] Check Existing Output ---
        # Logic: ถ้าชื่อไฟล์ input คือ "A.pdf", output จะเป็น "A.pdf.json"
        expected_output_name = f"{filename}.json" 
        expected_output_path = os.path.join(OUTPUT_FOLDER, expected_output_name)

        if SKIP_EXISTING and os.path.exists(expected_output_path):
            print(f"⏩ ข้าม: {filename} (มี Output อยู่แล้ว)")
            skipped_count += 1
            continue
        # -----------------------------------
        
        # Extract Text
        extracted_text = extract_evidence_section(file_path)
        
        if not extracted_text:
            print(f"⚠️  Regex ไม่ตรง: {filename} (ข้าม)")
            regex_failed_count += 1
            continue

        print(f"📄 เพิ่มลง Batch: {filename} ({len(extracted_text)} chars)")

        # Create Request Object
        task = {
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
        tasks.append(task)

    # สรุปผลการเตรียมข้อมูล
    print(f"\n--- สรุป ---")
    print(f"⏩ ข้าม (มีแล้ว): {skipped_count}")
    print(f"⚠️  ข้าม (Regex ไม่เจอ): {regex_failed_count}")
    print(f"✅ พร้อมส่ง (New Tasks): {len(tasks)}")

    if not tasks:
        print("❌ ไม่มีงานใหม่ต้องส่ง")
        return None

    # เขียนลงไฟล์ .jsonl
    with open(BATCH_FILE_NAME, "w", encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
            
    print(f"💾 บันทึกไฟล์ Batch สำเร็จ: {BATCH_FILE_NAME}")
    return BATCH_FILE_NAME

def upload_and_submit_batch(jsonl_file):
    """ขั้นตอนที่ 2: Upload & Submit"""
    print("\n☁️  กำลังอัปโหลดไฟล์ Batch...")
    batch_input_file = client.files.create(
        file=open(jsonl_file, "rb"),
        purpose="batch"
    )
    
    print("🚀 กำลังส่งคำสั่ง (Submit)...")
    batch_job = client.batches.create(
        input_file_id=batch_input_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )
    
    with open(BATCH_ID_LOG, "w") as f:
        f.write(batch_job.id)
        
    print(f"✅ เรียบร้อย! Batch ID: {batch_job.id}")
    print("👉 รันคำสั่ง 'Check Status' ในภายหลังเพื่อรับผลลัพธ์")

def check_and_retrieve_results():
    """ขั้นตอนที่ 3: Check Status & Download"""
    if not os.path.exists(BATCH_ID_LOG):
        print("❌ ไม่พบ Batch ID")
        return

    with open(BATCH_ID_LOG, "r") as f:
        batch_id = f.read().strip()
    
    print(f"🔍 Checking Batch ID: {batch_id} ...")
    try:
        batch_job = client.batches.retrieve(batch_id)
        print(f"   Status: {batch_job.status}")
        
        if batch_job.status == "completed":
            if not batch_job.output_file_id:
                print("❌ Completed but no output file (Check errors in dashboard)")
                return

            print("🎉 งานเสร็จแล้ว! กำลังโหลดผลลัพธ์...")
            content = client.files.content(batch_job.output_file_id).text
            
            if not os.path.exists(OUTPUT_FOLDER):
                os.makedirs(OUTPUT_FOLDER)
                
            success_count = 0
            for line in content.strip().split('\n'):
                data = json.loads(line)
                filename = data['custom_id']
                
                # Check logic output path again just in case
                output_path = os.path.join(OUTPUT_FOLDER, f"{filename}.json")
                
                try:
                    ai_response = json.loads(data['response']['body']['choices'][0]['message']['content'])
                    
                    # Save JSON
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump({"file": filename, "data": ai_response}, f, ensure_ascii=False, indent=4)
                    success_count += 1
                except Exception as e:
                    print(f"❌ Error saving {filename}: {e}")
                    
            print(f"✅ Saved {success_count} files to {OUTPUT_FOLDER}")
            
            # (Optional) ลบไฟล์ Batch ID ทิ้งเมื่อเสร็จงาน
            # os.remove(BATCH_ID_LOG)
            
        elif batch_job.status == "failed":
            print(f"❌ Job Failed: {batch_job.errors}")
        else:
            print("⏳ ยังไม่เสร็จ (in_progress/validating) - รอสักพักแล้วลองใหม่")
    except Exception as e:
        print(f"Error checking batch: {e}")

# ================= MAIN =================
if __name__ == "__main__":
    print("1. Scan PDFs & Submit Batch (Prepare & Upload)")
    print("2. Check Status & Download Results")
    choice = input("Select (1/2): ").strip()
    
    if choice == "1":
        f = create_batch_file()
        if f: upload_and_submit_batch(f)
    elif choice == "2":
        check_and_retrieve_results()