# ใช้ Base Image เป็น Python 3.12-slim เพื่อขนาดที่เล็ก
FROM python:3.12-slim

# ตั้งค่า Working Directory
WORKDIR /app

# ติดตั้ง Dependencies ที่จำเป็นสำหรับ app.py เท่านั้น
# ใช้ psycopg2-binary แทน psycopg2 เพื่อลดการติดตั้ง system libraries (gcc, libpq-dev)
RUN pip install --no-cache-dir \
    streamlit \
    psycopg2-binary \
    pandas \
    python-dotenv

# Copy ไฟล์ application
COPY app.py .

# เปิด Port 8501 สำหรับ Streamlit
EXPOSE 8501

# Healthcheck using Python (no need for curl)
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# คำสั่งรัน Application
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]
