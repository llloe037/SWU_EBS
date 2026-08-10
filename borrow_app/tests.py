from datetime import datetime, timedelta

from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse

from borrow_app.models import BorrowItem, BorrowRequest, Equipment, EquipmentGroup
from borrow_app.views import build_equipment_type_summary, get_equipment_items_for_type


class EquipmentTypeSummaryTests(TestCase):
    def setUp(self):
        self.group = EquipmentGroup.objects.create(
            account_determ='คอมพิวเตอร์',
            asset_description='อุปกรณ์สำนักงาน'
        )

        Equipment.objects.create(
            code='EQ-001',
            name='Laptop',
            category='คอมพิวเตอร์',
            group=self.group,
            status='พร้อมให้ยืม',
            total_quantity=2,
            available_quantity=2,
        )
        Equipment.objects.create(
            code='EQ-002',
            name='Laptop',
            category='คอมพิวเตอร์',
            group=self.group,
            status='กำลังถูกยืม',
            total_quantity=3,
            available_quantity=0,
        )
        Equipment.objects.create(
            code='EQ-003',
            name='Projector',
            category='โสตทัศนูปกรณ์',
            group=self.group,
            status='พร้อมให้ยืม',
            total_quantity=1,
            available_quantity=1,
        )

    def test_build_equipment_type_summary_groups_by_name_and_category(self):
        summary = build_equipment_type_summary()

        self.assertEqual(len(summary), 2)

        laptop = next(item for item in summary if item['name'] == 'Laptop')
        self.assertEqual(laptop['category'], 'คอมพิวเตอร์')
        self.assertEqual(laptop['available_count'], 2)
        self.assertEqual(laptop['total_count'], 5)

        projector = next(item for item in summary if item['name'] == 'Projector')
        self.assertEqual(projector['available_count'], 1)
        self.assertEqual(projector['total_count'], 1)

    def test_get_equipment_items_for_type_returns_matching_items(self):
        items = get_equipment_items_for_type('คอมพิวเตอร์|Laptop')

        self.assertEqual(len(items), 2)
        self.assertEqual({item.code for item in items}, {'EQ-001', 'EQ-002'})


class HomePageBorrowFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='borrower', password='secret123')
        self.group = EquipmentGroup.objects.create(
            account_determ='คอมพิวเตอร์',
            asset_description='Laptop'
        )
        self.equipment = Equipment.objects.create(
            code='EQ-200',
            name='Laptop',
            category='คอมพิวเตอร์',
            group=self.group,
            status='พร้อมให้ยืม',
            total_quantity=1,
            available_quantity=1,
        )

    def test_home_page_renders_add_to_cart_form_for_selected_equipment(self):
        self.client.login(username='borrower', password='secret123')

        response = self.client.get(reverse('borrow_app:home'), {'equipment_type': 'คอมพิวเตอร์|Laptop'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="item_category"')
        self.assertContains(response, 'name="item_name"')
        self.assertContains(response, 'name="quantity"')

    def test_posting_from_home_page_adds_item_to_borrow_cart(self):
        self.client.login(username='borrower', password='secret123')

        response = self.client.post(reverse('borrow_app:add_to_cart'), {
            'item_category': self.equipment.category,
            'item_name': self.equipment.name,
            'quantity': '1',
        })

        self.assertRedirects(response, reverse('borrow_app:request_form'))
        self.assertEqual(self.client.session['borrow_cart'][0]['name'], self.equipment.name)

    def test_home_page_always_shows_type_summary_cards(self):
        self.client.login(username='borrower', password='secret123')

        response = self.client.get(reverse('borrow_app:home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="item_category"')
        self.assertContains(response, 'name="item_name"')


class BorrowRequestWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='borrower', password='secret123')
        self.group = EquipmentGroup.objects.create(
            account_determ='คอมพิวเตอร์',
            asset_description='Laptop'
        )
        self.equipment = Equipment.objects.create(
            code='EQ-100',
            name='Laptop',
            category='คอมพิวเตอร์',
            group=self.group,
            status='พร้อมให้ยืม',
            total_quantity=2,
            available_quantity=2,
        )
        self.request = BorrowRequest.objects.create(
            request_number='BR-001',
            user=self.user,
            start_datetime=datetime(2026, 8, 7).date(),
            end_datetime=datetime(2026, 8, 10).date(),
            purpose='ทดสอบ',
            location='ห้องพัสดุ',
            pickup_method='รับด้วยตนเอง',
            status='รอการอนุมัติ',
        )
        BorrowItem.objects.create(
            borrow_request=self.request,
            equipment=self.equipment,
            quantity=1,
        )

    def test_approve_updates_equipment_status(self):
        borrow_item = self.request.items.first()
        self.request.approve(self.user, {str(borrow_item.id): str(self.equipment.id)})

        self.request.refresh_from_db()
        self.equipment.refresh_from_db()

        self.assertEqual(self.request.status, 'อนุมัติ')
        self.assertEqual(self.request.approved_by, self.user)
        self.assertEqual(self.equipment.status, 'กำลังถูกยืม')
        self.assertEqual(self.equipment.available_quantity, 1)

    def test_return_flow_updates_status(self):
        borrow_item = self.request.items.first()
        self.request.approve(self.user, {str(borrow_item.id): str(self.equipment.id)})
        self.request.mark_return_pending('คืนแล้ว')
        self.request.mark_return_completed(self.user)

        self.request.refresh_from_db()
        self.equipment.refresh_from_db()

        self.assertEqual(self.request.status, 'คืนสำเร็จ')
        self.assertEqual(self.request.received_by, self.user)
        self.assertIsNotNone(self.request.returned_at)
        self.assertEqual(self.equipment.status, 'พร้อมให้ยืม')
        self.assertEqual(self.equipment.available_quantity, 2)

    def test_admin_can_add_comment_when_marking_return_incomplete(self):
        admin = User.objects.create_superuser(username='admin', password='secret123')
        self.request.status = 'รอตรวจสอบการคืน'
        self.request.save(update_fields=['status'])

        self.client.login(username='admin', password='secret123')
        response = self.client.post(reverse('borrow_app:admin_manage_requests'), {
            'request_id': self.request.id,
            'action': 'reject',
            'return_incomplete_comment': 'ยังไม่ได้คืนสายชาร์จ',
        })

        self.assertRedirects(response, reverse('borrow_app:admin_manage_requests'))
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'คืนไม่ครบ')
        self.assertEqual(self.request.return_incomplete_comment, 'ยังไม่ได้คืนสายชาร์จ')

        self.client.login(username='borrower', password='secret123')
        response = self.client.get(reverse('borrow_app:my_requests'))
        self.assertContains(response, 'ยังไม่ได้คืนสายชาร์จ')

        response = self.client.get(reverse('borrow_app:return_request', args=[self.request.request_number]))
        self.assertContains(response, 'ยังไม่ได้คืนสายชาร์จ')

    def test_admin_must_add_comment_when_marking_return_incomplete(self):
        User.objects.create_superuser(username='admin', password='secret123')
        self.request.status = 'รอตรวจสอบการคืน'
        self.request.save(update_fields=['status'])

        self.client.login(username='admin', password='secret123')
        response = self.client.post(reverse('borrow_app:admin_manage_requests'), {
            'request_id': self.request.id,
            'action': 'reject',
            'return_incomplete_comment': '',
        }, follow=True)

        self.assertContains(response, 'กรุณาระบุคอมเมนต์ก่อนแจ้งว่าคืนอุปกรณ์ไม่ครบ')
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, 'รอตรวจสอบการคืน')

    def test_overdue_status_updates_when_due_date_has_passed(self):
        yesterday = datetime.now().date() - timedelta(days=1)
        self.request.status = 'อนุมัติ'
        self.request.end_datetime = yesterday
        self.request.save(update_fields=['status', 'end_datetime'])

        self.request.refresh_status()
        self.request.refresh_from_db()

        self.assertEqual(self.request.status, 'เกินกำหนด')
