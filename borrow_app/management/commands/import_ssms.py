import os
import pyodbc
import pandas as pd
from django.core.management.base import BaseCommand
from borrow_app.models import Equipment
from dotenv import load_dotenv

# โหลดค่าจากไฟล์ .env
load_dotenv()

class Command(BaseCommand):
    help = 'ดึงข้อมูลอุปกรณ์ตรงจากฐานข้อมูล SSMS (SQL Server)'

    def handle(self, *args, **options):
        # 1. ดึงค่าการเชื่อมต่อจาก Environment Variables
        db_host = os.getenv('SSMS_DB_HOST', '10.1.21.151')
        db_name = os.getenv('SSMS_DB_NAME', 'SWU_EBS')
        db_user = os.getenv('SSMS_DB_USER', '')
        db_pass = os.getenv('SSMS_DB_PASSWORD', '')
        table_name = os.getenv('SSMS_TABLE_NAME', 'dbo.asset')

        # 2. Connection String ปรับข้าม SSL Check และรองรับพอร์ตมาตรฐาน
        conn_str = (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={db_host};"
            f"DATABASE={db_name};"
            f"UID={db_user};"
            f"PWD={db_pass};"
            f"Encrypt=no;"
            f"TrustServerCertificate=yes;"
        )

        try:
            self.stdout.write(f"กำลังเชื่อมต่อไปยังฐานข้อมูล SSMS ({db_host})...")
            # ขยาย timeout เป็น 30 วินาที
            conn = pyodbc.connect(conn_str, timeout=30)
            
            # ใช้ WITH (NOLOCK) เพื่อป้องกันการล็อกตารางในระบบ SSMS
            query = f"SELECT * FROM {table_name} WITH (NOLOCK)"
            
            self.stdout.write("กำลังดึงข้อมูล...")
            df = pd.read_sql(query, conn)
            conn.close()

            # ลบช่องว่างหัวคอลัมน์
            df.columns = df.columns.str.strip()

            count_created = 0
            count_updated = 0

            # 3. ประมวลผลข้อมูลบันทึกลง Django DB
            for _, row in df.iterrows():
                main_no = str(row.get('assetNoMain', '')).strip() if pd.notna(row.get('assetNoMain')) else ''
                sub_no = str(row.get('assetNoSub', '0001')).strip() if pd.notna(row.get('assetNoSub')) else '0001'

                if main_no:
                    code = f"{main_no}-{sub_no}"
                else:
                    code = str(row.get('inventoryNo', row.get('seqNo', ''))).strip()

                if not code or code == 'nan':
                    continue

                total_qty = int(row.get('quantity', 1)) if pd.notna(row.get('quantity')) else 1

                equipment, created = Equipment.objects.update_or_create(
                    code=code,
                    defaults={
                        'name': str(row.get('assetDescription', 'ไม่ระบุชื่อ')).strip(),
                        'category': str(row.get('equipmentCategory', 'ทั่วไป')).strip(),
                        'seq_no': int(row.get('seqNo')) if pd.notna(row.get('seqNo')) else None,
                        'asset_no_main': main_no,
                        'asset_no_sub': sub_no,
                        'inventory_no': str(row.get('inventoryNo', '')).strip() if pd.notna(row.get('inventoryNo')) else '',
                        'total_quantity': total_qty,
                        'available_quantity': total_qty,
                        'acquisition_method': str(row.get('acquisitionMethod', '')).strip() if pd.notna(row.get('acquisitionMethod')) else '',
                        'acquisition_date': str(row.get('acquisitionDate', '')).strip() if pd.notna(row.get('acquisitionDate')) else '',
                        'funding_source': str(row.get('fundingSource', '')).strip() if pd.notna(row.get('fundingSource')) else '',
                        'amount_posted': float(row.get('amountPosted')) if pd.notna(row.get('amountPosted')) else None,
                        'holder_code': str(row.get('holderCode', '')).strip() if pd.notna(row.get('holderCode')) else '',
                        'holder_name': str(row.get('holderName', '')).strip() if pd.notna(row.get('holderName')) else '',
                        'holder_dept_code': str(row.get('holderDeptCode', '')).strip() if pd.notna(row.get('holderDeptCode')) else '',
                        'holder_department': str(row.get('holderDepartment', '')).strip() if pd.notna(row.get('holderDepartment')) else '',
                    }
                )

                if created:
                    count_created += 1
                else:
                    count_updated += 1

            self.stdout.write(self.style.SUCCESS(f'Sync ข้อมูลจาก SSMS เรียบร้อย! เพิ่มใหม่ {count_created} / อัปเดต {count_updated} รายการ'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'เกิดข้อผิดพลาดในการดึงข้อมูล: {str(e)}'))