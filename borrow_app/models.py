from datetime import datetime
import datetime as dt

from django.db import models
from django.db.models import Q
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
    start_datetime = models.DateField(null=True, blank=True, verbose_name="วันที่ยืม")
    end_datetime = models.DateField(null=True, blank=True, verbose_name="กำหนดส่งคืน")
    purpose = models.TextField(verbose_name="วัตถุประสงค์")
    location = models.CharField(max_length=255, verbose_name="สถานที่นำไปใช้")
    pickup_method = models.CharField(max_length=100, verbose_name="ช่องทางการรับอุปกรณ์")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_requests', verbose_name="ผู้อนุมัติ")
    reject_reason = models.TextField(blank=True, null=True, verbose_name="เหตุผลที่ไม่อนุมัติ")
    return_note = models.TextField(blank=True, null=True, verbose_name="หมายเหตุการคืน")
    return_incomplete_comment = models.TextField(blank=True, null=True, verbose_name="ความเห็นกรณีคืนไม่ครบ")
    return_image = models.ImageField(upload_to='return_evidence/', blank=True, null=True, verbose_name="รูปหลักฐานการคืน")
    returned_at = models.DateTimeField(null=True, blank=True, verbose_name="วันที่คืน")
    received_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='received_returns', verbose_name="ผู้รับคืน")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='รอการอนุมัติ', verbose_name="สถานะ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่สร้างคำร้อง")

    def __str__(self):
        return self.request_number

    def approve(self, approved_by_user, item_equipment_assignments=None):
        self.status = 'อนุมัติ'
        self.approved_by = approved_by_user
        self.save(update_fields=['status', 'approved_by'])
        assignments = item_equipment_assignments or {}
        for item in self.items.all():
            eq_id = assignments.get(str(item.id))
            equipment = Equipment.objects.filter(id=eq_id).first() if eq_id else item.equipment
            if equipment:
                item.equipment = equipment
                item.save(update_fields=['equipment'])
                equipment.status = 'กำลังถูกยืม'
                if equipment.available_quantity > 0:
                    equipment.available_quantity -= item.quantity
                equipment.save(update_fields=['status', 'available_quantity'])
        Notification.objects.create(
            user=self.user,
            borrow_request=self,
            message=f'คำร้อง {self.request_number} ได้รับการอนุมัติแล้ว กรุณาติดต่อผู้ดูแลเพื่อรับอุปกรณ์',
        )

    def reject(self, reason=''):
        self.status = 'ไม่อนุมัติ'
        self.reject_reason = reason
        self.save(update_fields=['status', 'reject_reason'])
        msg = f'คำร้อง {self.request_number} ไม่ได้รับการอนุมัติ'
        if reason:
            msg += f' เหตุผล: {reason}'
        Notification.objects.create(user=self.user, borrow_request=self, message=msg)

    def mark_return_pending(self, return_note=''):
        self.return_note = return_note
        self.status = 'รอตรวจสอบการคืน'
        self.save(update_fields=['return_note', 'status'])

    def mark_return_completed(self, received_by_user=None):
        from django.utils import timezone
        self.status = 'คืนสำเร็จ'
        self.received_by = received_by_user
        self.returned_at = timezone.now()
        self.save(update_fields=['status', 'received_by', 'returned_at'])
        for item in self.items.all():
            if item.equipment:
                item.equipment.status = 'พร้อมให้ยืม'
                item.equipment.available_quantity += item.quantity
                item.equipment.save(update_fields=['status', 'available_quantity'])
                
            # อัปเดตสถานะของไอเทมย่อยด้วย
            item.return_status = 'คืนแล้ว'
            item.return_condition = item.return_condition or 'ปกติ'
            item.returned_at = timezone.now()
            item.save(update_fields=['return_status', 'return_condition', 'returned_at'])

        Notification.objects.create(
            user=self.user,
            borrow_request=self,
            message=f'การคืนอุปกรณ์ในคำร้อง {self.request_number} ได้รับการยืนยันเรียบร้อยแล้ว',
        )

    def mark_return_incomplete(self, comment):
        self.status = 'คืนไม่ครบ'
        self.return_incomplete_comment = comment
        self.save(update_fields=['status', 'return_incomplete_comment'])
        Notification.objects.create(
            user=self.user,
            borrow_request=self,
            message=f'คำขอคืน {self.request_number} ยังคืนไม่ครบ: {comment}',
        )

    def refresh_status(self, now=None):
        if self.status not in ['อนุมัติ', 'รอตรวจสอบการคืน', 'คืนไม่ครบ']:
            return self.status

        if not self.end_datetime:
            return self.status

        today = (now.date() if hasattr(now, 'date') else now) if now else dt.date.today()
        end_date = self.end_datetime if isinstance(self.end_datetime, dt.date) else None
        if end_date is None:
            return self.status

        if today > end_date:
            self.status = 'เกินกำหนด'
            self.save(update_fields=['status'])

        return self.status

    @property
    def approved_by_display(self):
        if not self.approved_by_id:
            return '-'
        return self.approved_by.get_full_name() or self.approved_by.username

    @property
    def received_by_display(self):
        if not self.received_by_id:
            return '-'
        return self.received_by.get_full_name() or self.received_by.username

    @property
    def items_summary(self):
        items = list(self.items.all())
        if not items:
            return "-"
        names = [item.equipment.name if item.equipment else item.item_name for item in items]
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} และอื่นๆ {len(names)-2} รายการ"

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
    RETURN_STATUS_CHOICES = [
        ('ยังไม่คืน', 'ยังไม่คืน'),
        ('รอตรวจรับ', 'รอตรวจรับ'),
        ('คืนแล้ว', 'คืนแล้ว'),
        ('ชำรุด', 'ชำรุด'),
        ('สูญหาย', 'สูญหาย'),
    ]

    borrow_request = models.ForeignKey(BorrowRequest, related_name='items', on_delete=models.CASCADE)
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, null=True, blank=True, verbose_name="อุปกรณ์ที่จัดสรร")
    item_id = models.CharField(max_length=50, null=True, blank=True)
    item_name = models.CharField(max_length=255, null=True, blank=True)
    requested_category = models.CharField(max_length=100, null=True, blank=True, verbose_name="หมวดหมู่ที่ขอยืม")
    item_type = models.CharField(max_length=50, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    return_status = models.CharField(max_length=50, default='ยังไม่คืน')

    # --- ฟิลด์เพิ่มเติมสำหรับการคืนรายชิ้น ---
    return_status = models.CharField(
        max_length=50, 
        choices=RETURN_STATUS_CHOICES, 
        default='ยังไม่คืน', 
        verbose_name="สถานะการคืนรายชิ้น"
    )
    return_condition = models.CharField(
        max_length=50, 
        choices=[('ปกติ', 'ปกติ'), ('ชำรุด', 'ชำรุด'), ('สูญหาย', 'สูญหาย')], 
        null=True, 
        blank=True, 
        verbose_name="สภาพอุปกรณ์ตอนคืน"
    )
    return_comment = models.TextField(null=True, blank=True, verbose_name="หมายเหตุการคืนรายชิ้น")
    returned_at = models.DateTimeField(null=True, blank=True, verbose_name="วันที่คืนรายการนี้")

    def available_equipment_options(self):
        filters = Q(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'], available_quantity__gt=0)
        if self.requested_category:
            filters &= Q(category=self.requested_category) | Q(group__account_determ=self.requested_category)
        if self.item_name:
            filters &= Q(name=self.item_name)
        return Equipment.objects.filter(filters).order_by('code')

    def __str__(self):
        if self.equipment:
            return f"{self.equipment.name} (x{self.quantity}) - {self.return_status}"
        return f"{self.item_name} (x{self.quantity}) - {self.return_status}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="ผู้รับ")
    borrow_request = models.ForeignKey(BorrowRequest, on_delete=models.CASCADE, null=True, blank=True)
    message = models.CharField(max_length=500, verbose_name="ข้อความ")
    is_read = models.BooleanField(default=False, verbose_name="อ่านแล้ว")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่สร้าง")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.message[:50]}"