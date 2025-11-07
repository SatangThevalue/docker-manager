# app/main.py
import docker
import threading
from fastapi import FastAPI, Response, status
from app import hosts_manager # Import logic จากไฟล์เมื่อกี้

app = FastAPI(
    title="Traefik Host Auto-Discovery",
    description="ดักฟัง Docker events และอัปเดต /etc/hosts อัตโนมัติ"
)

# 1. เชื่อมต่อ Docker
try:
    docker_client = docker.from_env()
    docker_client.ping()
    print("✅ เชื่อมต่อ Docker Daemon สำเร็จ")
    DOCKER_CONNECTED = True
except Exception as e:
    print(f"❌ ไม่สามารถเชื่อมต่อ Docker Daemon: {e}")
    print("   โปรดตรวจสอบว่า /var/run/docker.sock ถูก mount ถูกต้อง")
    DOCKER_CONNECTED = False
    # เราจะไม่ exit(1) แต่จะปล่อยให้ health check รายงานสถานะแทน


def resync_all_docker_hosts():
    """
    Scan container ที่ 'กำลังรัน' ทั้งหมด และสร้าง /etc/hosts ใหม่
    """
    if not DOCKER_CONNECTED:
        print("--- SCANNING: ข้ามไปเพราะไม่ได้เชื่อมต่อ Docker ---")
        return

    print("---  SCANNING: เริ่ม Scan Container ทั้งหมด ---")
    all_hosts = set()
    try:
        running_containers = docker_client.containers.list()
        print(f"พบ Container ที่กำลังรัน: {len(running_containers)} ตัว")
        
        for container in running_containers:
            labels = container.labels
            hosts = hosts_manager.parse_traefik_labels(labels)
            all_hosts.update(hosts)
        
        # ทำการ Resync กับไฟล์ /etc/hosts
        hosts_manager.resync_hosts(all_hosts)
        
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดระหว่าง Scan: {e}")
    print("--- SCANNING: สิ้นสุดการ Scan ---")

def docker_event_loop():
    """
    Thread ที่จะรันค้างไว้เพื่อดักฟัง Events
    """
    if not DOCKER_CONNECTED:
        print("🎧 ไม่ได้เริ่มดักฟัง Docker Events (เชื่อมต่อล้มเหลว)")
        return

    print("🎧 เริ่มดักฟัง Docker Events (start, stop)...")
    event_filter = {"type": "container", "action": ["start", "stop", "die"]}
    
    try:
        for event in docker_client.events(filters=event_filter, decode=True):
            action = event['Action']
            container_id = event['id'][:12]
            print(f"\n🔔 ได้รับ Event: {action.upper()} จาก Container: {container_id}")
            
            # ไม่ว่าจะเป็น 'start' หรือ 'stop' 
            # เราจะใช้วิธีที่ปลอดภัยที่สุดคือ "Scan ใหม่ทั้งหมด"
            # เพื่อป้องกัน state ไม่ตรงกัน
            resync_all_docker_hosts()
    except Exception as e:
        print(f"❌ Error ใน Docker event loop: {e}")
        # อาจจะต้องเพิ่ม logic reconnect ที่นี่ถ้าจำเป็น


@app.on_event("startup")
def on_startup():
    """
    สิ่งที่ทำตอน FastAPI เริ่มทำงาน
    """
    # 1. Scan หนึ่งครั้งตอนเริ่มต้น
    print("🚀 FastAPI เริ่มทำงาน, ทำการ Scan ครั้งแรก...")
    resync_all_docker_hosts()
    
    # 2. เริ่ม Thread ดักฟัง Event
    print("🚀 เริ่ม Background Thread สำหรับ Docker Events...")
    thread = threading.Thread(target=docker_event_loop, daemon=True)
    thread.start()

# --- API Endpoints ---

@app.get("/", summary="สถานะ")
def get_root():
    return {"status": "running", "monitoring": "docker_events", "docker_connected": DOCKER_CONNECTED}

@app.get("/health", status_code=status.HTTP_200_OK, summary="Health Check")
def health_check(response: Response):
    """
    Endpoint สำหรับ Docker Health Check
    จะตรวจสอบว่าเชื่อมต่อ Docker Daemon ได้หรือไม่
    """
    if DOCKER_CONNECTED:
        # ตรวจสอบการเชื่อมต่อ Docker อีกครั้ง (เผื่อ daemon ล่มทีหลัง)
        try:
            docker_client.ping()
            return {"status": "ok", "docker_connected": True}
        except Exception:
            # ถ้าเคยต่อได้ แต่ตอนนี้ต่อไม่ได้
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "error", "detail": "Lost connection to Docker daemon"}
    else:
        # ถ้าตอน startup ต่อไม่ได้เลย
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "detail": "Cannot connect to Docker daemon"}

@app.get("/hosts", summary="ดู Host ที่จัดการอยู่")
def get_managed_hosts():
    """
    ดึงรายชื่อ Host ที่จัดการอยู่จากไฟล์ /etc/hosts
    """
    return {"managed_hosts": list(hosts_manager.get_current_dynamic_hosts())}

@app.post("/refresh", summary="บังคับ Rescan")
def trigger_refresh():
    """
    บังคับให้ Scan Container ทั้งหมดและอัปเดต /etc/hosts ทันที
    """
    resync_all_docker_hosts()
    return {
        "status": "refreshed", 
        "managed_hosts": list(hosts_manager.get_current_dynamic_hosts())
    }