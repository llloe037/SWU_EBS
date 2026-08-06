from django.db import models
from django.contrib.auth.models import User

class EquipmentGroup(models.Model):
    account_determ = models.CharField(max_length=255, verbose_name="accountDeterm / หมวดหมู่")
    asset_description = models.CharField(max_length=255, verbose_name="assetDescription / ประเภท")
    image = models.ImageField(upload_to='equipment_group_images/', blank=True, null=True, verbose_name="รูปภาพหมวดหมู่")

    class Meta:
        unique_together = ('account_determ', 'asset_description')
        verbose_name = 'หมวด/ประเภทอุปกรณ์'
        verbose_name_plural = 'หมวด/ประเภทอุปกรณ์'

    def __str__(self):
        return f"{self.account_determ} / {self.asset_description}"


class Equipment(models.Model):
    STATUS_CHOICES = [
        ('พร้อมให้ยืม', 'พร้อมให้ยืม'),
        ('กำลังถูกยืม', 'กำลังถูกยืม'),
        ('อยู่ระหว่างซ่อม', 'อยู่ระหว่างซ่อม'),
        ('ชำรุด', 'ชำรุด'),
    ]

    # --- ฟิลด์เดิมในระบบ ---
    code = models.CharField(max_length=100, unique=True, verbose_name="รหัสอุปกรณ์/เลขครุภัณฑ์")
    name = models.CharField(max_length=255, verbose_name="ชื่ออุปกรณ์ (assetDescription)")
    category = models.CharField(max_length=100, verbose_name="หมวดหมู่ (equipmentCategory)")
    group = models.ForeignKey('EquipmentGroup', null=True, blank=True, on_delete=models.SET_NULL, related_name='equipments', verbose_name='หมวด/ประเภทอุปกรณ์')
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='พร้อมให้ยืม', verbose_name="สถานะอุปกรณ์")
    is_bundle = models.BooleanField(default=False, verbose_name="เป็นชุด Bundle")
    image = models.ImageField(upload_to='equipments/', blank=True, null=True)

    # --- ฟิลด์เพิ่มเติมจาก SSMS ---
    seq_no = models.IntegerField(null=True, blank=True, verbose_name="ลำดับ (seqNo)")
    asset_no_main = models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัสหลัก (assetNoMain)")
    asset_no_sub = models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัสย่อย (assetNoSub)")
    inventory_no = models.CharField(max_length=100, null=True, blank=True, verbose_name="เลขบาร์โค้ด/Serial (inventoryNo)")

    # การจัดการจำนวน
    total_quantity = models.IntegerField(default=1, verbose_name="จำนวนทั้งหมด (quantity)")
    available_quantity = models.IntegerField(default=1, verbose_name="จำนวนคงเหลือ")

    # ข้อมูลการจัดซื้อและมูลค่า
    acquisition_method = models.CharField(max_length=100, null=True, blank=True, verbose_name="วิธีได้มา (acquisitionMethod)")
    acquisition_date = models.CharField(max_length=50, null=True, blank=True, verbose_name="วันที่ได้มา (acquisitionDate)")
    funding_source = models.CharField(max_length=150, null=True, blank=True, verbose_name="แหล่งเงิน (fundingSource)")
    amount_posted = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="มูลค่า (amountPosted)")

    # ข้อมูลการตรวจนับ
    last_count_year = models.CharField(max_length=10, null=True, blank=True, verbose_name="ปีที่นับล่าสุด")
    count_result = models.CharField(max_length=100, null=True, blank=True, verbose_name="ผลการตรวจนับ")

    # ข้อมูลผู้ถือครอง / หน่วยงาน
    holder_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัสผู้ถือครอง")
    holder_name = models.CharField(max_length=150, null=True, blank=True, verbose_name="ผู้ถือครอง (holderName)")
    holder_dept_code = models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัสหน่วยงาน")
    holder_department = models.CharField(max_length=200, null=True, blank=True, verbose_name="หน่วยงาน (holderDepartment)")

    last_synced_at = models.DateTimeField(auto_now=True, verbose_name="อัปเดตข้อมูลล่าสุด")

    def save(self, *args, **kwargs):
        # รวม assetNoMain-assetNoSub เป็น code ให้อัตโนมัติกรณี Import ข้อมูล SSMS เข้ามา
        if not self.code and self.asset_no_main:
            sub = self.asset_no_sub if self.asset_no_sub else "0001"
            self.code = f"{self.asset_no_main}-{sub}"

        if self.category and self.name:
            group, _ = EquipmentGroup.objects.get_or_create(
                account_determ=self.category.strip(),
                asset_description=self.name.strip()
            )
            self.group = group

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class BorrowRequest(models.Model):
    STATUS_CHOICES = [
        ('รอการอนุมัติ', 'รอการอนุมัติ'),
        ('อนุมัติ', 'อนุมัติ'),
        ('ไม่อนุมัติ', 'ไม่อนุมัติ'),
        ('รอตรวจสอบการคืน', 'รอตรวจสอบการคืน'),
        ('คืนไม่ครบ', 'คืนไม่ครบ'),
        ('คืนสำเร็จ', 'คืนสำเร็จ'),
        ('เกินกำหนด', 'เกินกำหนด'),
    ]

    request_number = models.CharField(max_length=20, unique=True, verbose_name="เลขที่คำร้อง")
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="ผู้ขอยืม")
    start_datetime = models.CharField(max_length=100, verbose_name="วันที่ยืม")
    end_datetime = models.CharField(max_length=100, verbose_name="กำหนดส่งคืน")
    purpose = models.TextField(verbose_name="วัตถุประสงค์")
    location = models.CharField(max_length=255, verbose_name="สถานที่นำไปใช้")
    pickup_method = models.CharField(max_length=100, verbose_name="ช่องทางการรับอุปกรณ์")
    return_note = models.TextField(blank=True, null=True, verbose_name="หมายเหตุการคืน")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='รอการอนุมัติ', verbose_name="สถานะ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่สร้างคำร้อง")

    def __str__(self):
        return self.request_number

    # สรุปชื่อรายการอุปกรณ์สำหรับแสดงในตาราง
    @property
    def items_summary(self):
        items = list(self.items.all())
        if not items:
            return "-"
        names = [item.equipment.name if item.equipment else item.item_name for item in items]
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} และอื่นๆ {len(names)-2} รายการ"

    # สี Badge ของสถานะ
    @property
    def badge_style(self):
        styles = {
            'รอการอนุมัติ': 'bg-amber-50 text-amber-700 border-amber-300',
            'อนุมัติ': 'bg-emerald-50 text-emerald-700 border-emerald-300',
            'ไม่อนุมัติ': 'bg-rose-50 text-rose-700 border-rose-300',
            'รอตรวจสอบการคืน': 'bg-sky-50 text-sky-700 border-sky-300',
            'คืนไม่ครบ': 'bg-orange-50 text-orange-700 border-orange-300',
            'คืนสำเร็จ': 'bg-emerald-50 text-emerald-700 border-emerald-300',
            'เกินกำหนด': 'bg-red-50 text-red-700 border-red-300',
        }
        return styles.get(self.status, 'bg-gray-50 text-gray-700 border-gray-300')

    # ไอคอนของสถานะ
    @property
    def icon(self):
        icons = {
            'รอการอนุมัติ': 'clock',
            'อนุมัติ': 'check',
            'ไม่อนุมัติ': 'x',
            'รอตรวจสอบการคืน': 'clock',
            'คืนไม่ครบ': 'alert',
            'คืนสำเร็จ': 'check',
            'เกินกำหนด': 'alert',
        }
        return icons.get(self.status, 'clock')


class BorrowItem(models.Model):
    borrow_request = models.ForeignKey(BorrowRequest, related_name='items', on_delete=models.CASCADE)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, null=True, blank=True, verbose_name="อุปกรณ์")
    item_id = models.CharField(max_length=50, null=True, blank=True)
    item_name = models.CharField(max_length=255, null=True, blank=True)
    item_type = models.CharField(max_length=50, null=True, blank=True)
    quantity = models.IntegerField(default=1)

    def __str__(self):
        if self.equipment:
            return f"{self.equipment.name} (x{self.quantity})"
        return f"{self.item_name} (x{self.quantity})"