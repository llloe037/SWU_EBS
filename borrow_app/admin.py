from django.contrib import admin
from .models import BorrowRequest, BorrowItem

# ตารางแสดงรายการอุปกรณ์ย่อยซ้อนในหน้าคำร้อง
class BorrowItemInline(admin.TabularInline):
    model = BorrowItem
    extra = 0
    readonly_fields = ('item_id', 'item_name', 'item_type', 'quantity')

@admin.register(BorrowRequest)
class BorrowRequestAdmin(admin.ModelAdmin):
    list_display = ('request_number', 'user', 'items_summary', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('request_number', 'user__username', 'purpose')
    list_editable = ('status',)  # แอดมินปรับเปลี่ยนสถานะจากหน้าตารางได้เลย
    inlines = [BorrowItemInline]