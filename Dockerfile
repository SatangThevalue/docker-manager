# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# ติดตั้ง Dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ด
COPY ./app /app

EXPOSE 8000
# รันแอป
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]