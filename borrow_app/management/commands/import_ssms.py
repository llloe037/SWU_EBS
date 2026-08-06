import pandas as pd
from django.core.management.base import BaseCommand
from borrow_app.models import Equipment

class Command(BaseCommand):
    help = 'นำเข้าข้อมูลอุปกรณ์จากไฟล์ Excel ของ SSMS'

    def add_arguments(self, parser):
        # รับ Path ของไฟล์ Excel เช่น python manage.py import_ssms ssms_data.xlsx
        parser.add_argument('excel_file', type=str, help='Path ไฟล์ Excel ของ SSMS')

    def handle(self, *args, **options):
        file_path = options['excel_file']
        
        try:
            # อ่านไฟล์ Excel
            df = pd.read_excel(file_path)
            
            # ลบช่องว่างหัวคอลัมน์
            df.columns = df.columns.str.strip()
            
            count_created = 0
            count_updated = 0

            for _, row in df.iterrows():
                main_no = str(row.get('assetNoMain', '')).strip() if pd.notna(row.get('assetNoMain')) else ''
                sub_no = str(row.get('assetNoSub', '0001')).strip() if pd.notna(row.get('assetNoSub')) else '0001'
                
                # ถ้าไม่มี assetNoMain ให้ใช้ inventoryNo หรือ seqNo แทน
                if main_no:
                    code = f"{main_no}-{sub_no}"
                else:
                    code = str(row.get('inventoryNo', row.get('seqNo', ''))).strip()

                if not code:
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

            self.stdout.write(self.style.SUCCESS(f'นำเข้าข้อมูลสำเร็จ! เพิ่มใหม่ {count_created} รายการ / อัปเดต {count_updated} รายการ'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'เกิดข้อผิดพลาด: {str(e)}'))