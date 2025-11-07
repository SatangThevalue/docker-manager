# app/hosts_manager.py
import os
import re
import threading
from typing import Set

# 1. กำหนดค่าต่างๆ
# เราจะ mount /etc/hosts ของ host มาไว้ที่ /app/hosts.file ภายใน container
HOST_FILE_PATH = os.getenv("HOST_FILE_PATH", "/app/hosts.file")
MARKER_BEGIN = "# BEGIN DYNAMIC HOSTS"
MARKER_END = "# END DYNAMIC HOSTS"
HOST_REGEX = re.compile(r'Host\("([^"]+)"\)') # Regex สำหรับดึง Host("...")

# 2. ใช้ Lock เพื่อป้องกันการเขียนไฟล์พร้อมกัน
file_lock = threading.Lock()

def _read_file_lines() -> list[str]:
    """อ่านไฟล์ hosts ทั้งหมด"""
    if not os.path.exists(HOST_FILE_PATH):
        return []
    with open(HOST_FILE_PATH, "r") as f:
        return f.readlines()

def _write_file_lines(lines: list[str]):
    """เขียนทับไฟล์ hosts"""
    try:
        with open(HOST_FILE_PATH, "w") as f:
            f.writelines(lines)
    except PermissionError:
        print(f"❌ ERROR: ไม่สามารถเขียนไฟล์ {HOST_FILE_PATH} ได้")
        print("   โปรดตรวจสอบว่าได้รัน Container นี้ด้วยสิทธิ์ที่ถูกต้อง")
    except Exception as e:
        print(f"❌ ERROR: เกิดข้อผิดพลาดในการเขียนไฟล์: {e}")

def parse_traefik_labels(labels: dict) -> Set[str]:
    """
    ค้นหา Hostname จาก Traefik labels ทั้งหมด
    เช่น 'traefik.http.routers.my-app.rule=Host("my-app.local")'
    """
    found_hosts = set()
    for key, value in labels.items():
        if "traefik.http.routers" in key and ".rule" in key:
            matches = HOST_REGEX.findall(value)
            for host in matches:
                # กันกรณีมีหลาย Host ใน Rule เดียว เช่น Host("a.local"),Host("b.local")
                found_hosts.update(h.strip() for h in host.split(','))
    
    if found_hosts:
        print(f"   -> 🔎 พบ Hostnames: {found_hosts}")
    return found_hosts

def get_current_dynamic_hosts() -> Set[str]:
    """อ่าน Hostnames ที่เราจัดการอยู่ (ระหว่าง Markers)"""
    with file_lock:
        lines = _read_file_lines()
        in_dynamic_section = False
        hosts = set()
        
        for line in lines:
            if line.startswith(MARKER_END):
                in_dynamic_section = False
            if in_dynamic_section:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "127.0.0.1":
                    hosts.add(parts[1])
            if line.startswith(MARKER_BEGIN):
                in_dynamic_section = True
        return hosts

def resync_hosts(hosts_to_set: Set[str]):
    """
    เขียนทับไฟล์ /etc/hosts ด้วย Set ของ Hostnames ล่าสุด
    """
    with file_lock:
        print(f"🔄 กำลัง Resync /etc/hosts... (มี {len(hosts_to_set)} hosts)")
        
        lines = _read_file_lines()
        new_lines = []
        in_dynamic_section = False

        # 1. คัดลอกเฉพาะส่วนที่เราไม่ได้จัดการ
        for line in lines:
            if line.startswith(MARKER_BEGIN):
                in_dynamic_section = True
            if not in_dynamic_section:
                new_lines.append(line)
            if line.startswith(MARKER_END):
                in_dynamic_section = False

        # 2. สร้างส่วน Dynamic ใหม่
        new_lines.append(f"{MARKER_BEGIN}\n")
        if hosts_to_set:
            for host in sorted(list(hosts_to_set)):
                new_lines.append(f"127.0.0.1       {host}\n")
        else:
            new_lines.append("# (ไม่มี dynamic hosts)\n")
        new_lines.append(f"{MARKER_END}\n")

        # 3. เขียนไฟล์
        _write_file_lines(new_lines)
        print("✅ Resync /etc/hosts สำเร็จ")