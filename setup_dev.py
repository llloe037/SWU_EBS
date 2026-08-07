"""
SWU EBS - สคริปต์ตั้งค่าระบบสำหรับนักพัฒนาใหม่
รันด้วย: python setup_dev.py
"""
import subprocess
import sys
import os


def run(cmd, desc=""):
    print(f"\n>>> {desc or cmd}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"[ERROR] คำสั่งล้มเหลว: {cmd}")
        sys.exit(1)


def main():
    print("=" * 55)
    print("  SWU EBS - ตั้งค่าระบบสำหรับนักพัฒนา")
    print("=" * 55)

    # 1. Install dependencies
    run("pip install -r requirements.txt", "ติดตั้ง Python packages")

    # 2. Create .env from example if not exists
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            import shutil
            shutil.copy(".env.example", ".env")
            print("\n[OK] สร้างไฟล์ .env จาก .env.example แล้ว (แก้ไขค่าตามต้องการ)")
        else:
            print("\n[WARN] ไม่พบ .env.example - ข้ามขั้นตอนนี้")
    else:
        print("\n[OK] มีไฟล์ .env อยู่แล้ว")

    # 3. Run migrations
    run("python manage.py migrate", "รัน database migrations")

    # 4. Create superuser
    print("\n>>> สร้าง Admin user สำหรับเข้าระบบ")
    print("     (กรอก username, email, password ตามต้องการ)")
    subprocess.run("python manage.py createsuperuser", shell=True)

    print("\n" + "=" * 55)
    print("  ✅ ตั้งค่าเสร็จแล้ว!")
    print("  รัน: python manage.py runserver")
    print("  เปิด: http://127.0.0.1:8000/")
    print("=" * 55)


if __name__ == "__main__":
    main()
