import traceback
import hashlib
import uuid
import pandas as pd
import datetime as dt
from datetime import datetime
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.contrib.auth.models import User
from .models import BorrowRequest, BorrowItem, Equipment, EquipmentGroup, Notification
from django.db import connections
from django.db import models
from django.db.models import Count, Q, Sum, Min
from django.db import transaction


def _parse_date(value):
    if not value or value == '-':
        return None
    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value[:len(fmt)], fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def build_equipment_type_summary(query='', category='', status=''):
    filters = Q()

    if query:
        filters &= Q(
            Q(name__icontains=query) |
            Q(code__icontains=query) |
            Q(inventory_no__icontains=query) |
            Q(category__icontains=query) |
            Q(group__account_determ__icontains=query) |
            Q(group__asset_description__icontains=query)
        )

    if category and category != '-- หมวดหมู่ทั้งหมด --':
        filters &= Q(category=category) | Q(group__account_determ=category)

    if status and status != '-- สถานะทั้งหมด --':
        if status in ['พร้อมให้ยืม', 'พร้อมใช้งาน']:
            filters &= Q(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])
        elif status in ['ถูกยืม', 'ติดยืม']:
            filters &= Q(status='กำลังถูกยืม')
        else:
            filters &= Q(status=status)

    summary = (
        Equipment.objects.select_related('group')
        .filter(filters)
        .values('category', 'name')
        .annotate(
            available_count=Sum('available_quantity', filter=Q(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])),
            total_count=Sum('total_quantity'),
            asset_no_main=Min('asset_no_main')  # 🟢 เพิ่มการหาค่า asset_no_main
        )
        .order_by('category', 'name')
    )

    return [
        {
            'category': item['category'],
            'name': item['name'],
            'asset_no_main': item['asset_no_main'] or '',  # 🟢 แนบ asset_no_main ส่งไปให้ home.html
            'available_count': int(item['available_count'] or 0),
            'total_count': int(item['total_count'] or 0),
        }
        for item in summary
    ]

def get_equipment_items_for_type(selected_type='', query='', category='', status=''):
    if not selected_type:
        return Equipment.objects.none()

    selected_category = ''
    selected_name = ''

    if '|' in selected_type:
        selected_category, selected_name = [part.strip() for part in selected_type.split('|', 1)]
    else:
        selected_name = selected_type.strip()

    filters = Q()
    if selected_category:
        filters &= Q(category=selected_category)
    if selected_name:
        filters &= Q(name=selected_name)

    if query:
        filters &= Q(
            Q(name__icontains=query) |
            Q(code__icontains=query) |
            Q(inventory_no__icontains=query) |
            Q(category__icontains=query) |
            Q(group__account_determ__icontains=query) |
            Q(group__asset_description__icontains=query)
        )

    if category and category != '-- หมวดหมู่ทั้งหมด --':
        filters &= Q(category=category) | Q(group__account_determ=category)

    if status and status != '-- สถานะทั้งหมด --':
        if status in ['พร้อมให้ยืม', 'พร้อมใช้งาน']:
            filters &= Q(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])
        elif status in ['ถูกยืม', 'ติดยืม']:
            filters &= Q(status='กำลังถูกยืม')
        else:
            filters &= Q(status=status)

    return (
        Equipment.objects.select_related('group')
        .filter(filters)
        .order_by('category', 'name', 'code')
    )


def fetch_ssms_grouped_equipments(query='', category=''):
    query_filters = []
    params = []

    if query:
        like_query = f"%{query}%"
        query_filters.append("(assetDescription LIKE %s OR inventoryNo LIKE %s OR assetNoMain LIKE %s OR assetNoSub LIKE %s)")
        params.extend([like_query, like_query, like_query, like_query])

    if category and category != '-- หมวดหมู่ทั้งหมด --':
        query_filters.append("accountDeterm = %s")
        params.append(category)

    where_clause = " AND ".join(query_filters)
    if where_clause:
        where_clause = ' AND ' + where_clause

    sql = f"""
        SELECT accountDeterm AS account_determ,
               assetDescription AS asset_description,
               COUNT(*) AS available_count,
               COUNT(*) AS total_count
        FROM dbo.asset
        WHERE 1=1{where_clause}
        GROUP BY accountDeterm, assetDescription
        ORDER BY COUNT(*) DESC, accountDeterm, assetDescription
    """

    with connections['ssms_db'].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        grouped = []
        for row in rows:
            key = hashlib.md5(f"{row[0]}|{row[1]}".encode('utf-8')).hexdigest()
            grouped.append({
                'id': key,
                'account_determ': row[0] or 'ทั่วไป',
                'asset_description': row[1] or 'ไม่ระบุ',
                'available_count': int(row[2] or 0),
                'total_count': int(row[3] or 0),
            })

        cursor.execute("SELECT DISTINCT accountDeterm FROM dbo.asset ORDER BY accountDeterm")
        categories = [row[0] for row in cursor.fetchall() if row[0]]

    return categories, grouped


def fetch_ssms_stats():
    with connections['ssms_db'].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM dbo.asset")
        total = cursor.fetchone()[0] or 0

    return {
        'total': int(total),
        'available': int(total),
        'borrowed': 0,
        'maintenance': 0,
        'damaged': 0,
    }


def fetch_ssms_group_items(account_determ, asset_description):
    sql = """
        SELECT assetNoMain, assetNoSub, assetDescription, inventoryNo
        FROM dbo.asset
        WHERE accountDeterm = %s AND assetDescription = %s
        ORDER BY TRY_CAST(assetNoMain AS BIGINT), TRY_CAST(assetNoSub AS INT)
    """
    with connections['ssms_db'].cursor() as cursor:
        cursor.execute(sql, [account_determ, asset_description])
        rows = cursor.fetchall()

    items = []
    codes = set()
    for row in rows:
        main_no = str(row[0]).strip() if row[0] is not None else ''
        sub_no = str(row[1]).strip() if row[1] is not None else '0'
        
        # 🟢 กำหนดรูปแบบรหัส assetNoMain-assetNoSub
        code = f"{main_no}-{sub_no}" if main_no else str(row[3] or '')
        
        items.append({
            'code': code,
            'name': row[2] or 'ไม่ระบุ',
            'inventory_no': row[3] or '-',
            'status': 'พร้อมให้ยืม',
            'available_quantity': 1,
        })
        if code:
            codes.add(code)

    local_equipment_map = {
        eq.code: eq for eq in Equipment.objects.filter(code__in=codes)
    }
    for item in items:
        equipment = local_equipment_map.get(item['code'])
        if equipment:
            item['id'] = equipment.id
            item['group_id'] = equipment.group_id
            item['status'] = equipment.status

    return items


@login_required
def home_view(request):
    if request.user.is_staff:
        return redirect('borrow_app:admin_dashboard')
    query = request.GET.get('q', '')
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    group_id = request.GET.get('group_id', '')
    selected_equipment_type = request.GET.get('equipment_type', '').strip()

    group_filter = Q()
    if query:
        group_filter &= Q(
            Q(asset_description__icontains=query) |
            Q(account_determ__icontains=query) |
            Q(equipments__name__icontains=query) |
            Q(equipments__code__icontains=query) |
            Q(equipments__inventory_no__icontains=query)
        )

    if category and category != '-- หมวดหมู่ทั้งหมด --':
        group_filter &= Q(account_determ=category)

    if status and status != '-- สถานะทั้งหมด --':
        if status in ['พร้อมให้ยืม', 'พร้อมใช้งาน']:
            group_filter &= Q(equipments__status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])
        elif status in ['ถูกยืม', 'ติดยืม']:
            group_filter &= Q(equipments__status='กำลังถูกยืม')
        else:
            group_filter &= Q(equipments__status=status)

    cart_items = request.session.get('borrow_cart', [])

    grouped_equipments = None
    categories = []
    try:
        categories, grouped_equipments = fetch_ssms_grouped_equipments(query=query, category=category)
    except Exception:
        categories = list(EquipmentGroup.objects.values_list('account_determ', flat=True).distinct())

    if grouped_equipments is None:
        grouped_equipments = EquipmentGroup.objects.filter(group_filter).annotate(
            available_count=Sum('equipments__available_quantity', filter=Q(equipments__status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])),
            total_count=Sum('equipments__total_quantity')
        ).filter(available_count__gt=0).order_by('-available_count', 'account_determ', 'asset_description')

    equipment_type_summary = build_equipment_type_summary(query=query, category=category, status=status)
    selected_equipment_items = get_equipment_items_for_type(
        selected_equipment_type,
        query=query,
        category=category,
        status=status,
    ) if selected_equipment_type else Equipment.objects.none()

    selected_equipment_type_label = ''
    if selected_equipment_type and '|' in selected_equipment_type:
        selected_category_value, selected_name_value = [part.strip() for part in selected_equipment_type.split('|', 1)]
        selected_equipment_type_label = f"{selected_name_value} ({selected_category_value})"
    elif selected_equipment_type:
        selected_equipment_type_label = selected_equipment_type

    selected_group_items = None
    selected_group = None
    if group_id:
        selected_group = EquipmentGroup.objects.filter(id=group_id).first()
        selected_group_items = Equipment.objects.filter(
            group_id=group_id,
            status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน']
        ).order_by('code')

    context = {
        'grouped_equipments': grouped_equipments,
        'equipment_type_summary': equipment_type_summary,
        'selected_equipment_items': selected_equipment_items,
        'selected_equipment_type': selected_equipment_type,
        'selected_equipment_type_label': selected_equipment_type_label,
        'selected_group_items': selected_group_items,
        'selected_group': selected_group,
        'categories': categories,
        'query': query,
        'selected_category': category,
        'selected_status': status,
        'group_id': group_id,
        'cart_count': len(cart_items),
    }
    return render(request, 'borrow_app/home.html', context)

@login_required
def request_form_view(request):
    cart_items = request.session.get('borrow_cart', [])
    if not cart_items:
        return redirect('borrow_app:home')

    if request.method == 'POST':
        request.session['borrow_details'] = {
            'start_datetime': request.POST.get('start_datetime', '-'),
            'end_datetime': request.POST.get('end_datetime', '-'),
            'purpose': request.POST.get('purpose', '-'),
            'location': request.POST.get('location', 'ไม่ระบุ'),
            'pickup_method': request.POST.get('pickup_method', 'รับด้วยตนเองที่ห้องพัสดุ'),
        }
        request.session.modified = True
        return redirect('borrow_app:request_summary')

    return render(request, 'borrow_app/request-form.html', {'cart_items': cart_items})

@login_required
def request_summary_view(request):
    cart_items = request.session.get('borrow_cart', [])
    details = request.session.get('borrow_details', None)

    if not cart_items or not details:
        return redirect('borrow_app:request_form')

    context = {
        'cart_items': cart_items,
        'details': details,
        'today_date': datetime.now().strftime("%d/%m/%Y")
    }
    return render(request, 'borrow_app/request-summary.html', context)

@login_required
def confirm_request_view(request):
    if request.method == 'POST':
        cart_items = request.session.get('borrow_cart', [])
        details = request.session.get('borrow_details', {})

        if not cart_items or not details:
            return redirect('borrow_app:request_form')

        count_today = BorrowRequest.objects.count() + 1
        new_req_no = f"BR{datetime.now().strftime('%y%m%d')}-{count_today:04d}"

        borrow_req = BorrowRequest.objects.create(
            request_number=new_req_no,
            user=request.user,
            start_datetime=_parse_date(details.get('start_datetime')),
            end_datetime=_parse_date(details.get('end_datetime')),
            purpose=details.get('purpose', '-'),
            location=details.get('location', '-'),
            pickup_method=details.get('pickup_method', '-'),
            status='รอการอนุมัติ'
        )

        for item in cart_items:
            item_code = item.get('code', '')
            equipment_obj = Equipment.objects.filter(code=item_code).first() if item_code else None

            BorrowItem.objects.create(
                borrow_request=borrow_req,
                equipment=equipment_obj,
                item_name=item.get('name', ''),
                requested_category=item.get('category', ''),
                quantity=int(item.get('qty', 1)),
                return_status='ยังไม่คืน'
            )

        request.session.pop('borrow_cart', None)
        request.session.pop('borrow_details', None)
        request.session.modified = True

        return redirect('borrow_app:my_requests')

    return redirect('borrow_app:request_summary')

@login_required
def my_requests_view(request):
    active_statuses = ['รอการอนุมัติ', 'อนุมัติ', 'รอตรวจสอบการคืน', 'คืนไม่ครบ', 'เกินกำหนด']
    active_requests = BorrowRequest.objects.filter(
        user=request.user,
        status__in=active_statuses
    ).order_by('-created_at')

    for borrow_req in active_requests:
        borrow_req.refresh_status()

    active_requests = list(active_requests)
    active_requests.sort(key=lambda req: req.created_at, reverse=True)

    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

    return render(request, 'borrow_app/my-requests.html', {'requests_list': active_requests})

@login_required
def history_view(request):
    history_statuses = ['ยกเลิก', 'ไม่อนุมัติ', 'คืนสำเร็จ']
    history_requests = BorrowRequest.objects.filter(
        user=request.user,
        status__in=history_statuses
    ).order_by('-created_at')

    return render(request, 'borrow_app/history.html', {'requests_list': history_requests})

@login_required
def cancel_request_view(request, request_id):
    if request.method == 'POST':
        BorrowRequest.objects.filter(
            request_number=request_id, 
            user=request.user, 
            status='รอการอนุมัติ'
        ).update(status='ยกเลิก')

    return redirect('borrow_app:history')

@login_required
def add_to_cart_view(request):
    if request.method == 'POST':
        selected_sub_items = request.POST.getlist('selected_sub_items')
        cart = list(request.session.get('borrow_cart', []))

        # 🟢 กรณีที่ 1: ส่งมาจาก Modal เลือกชุดอุปกรณ์ย่อย (Bundle)
        if selected_sub_items:
            # ค้นหาอุปกรณ์ย่อยจาก DB Local เพื่อดึงชื่อและหมวดหมู่ที่ถูกต้อง
            equipments = Equipment.objects.filter(code__in=selected_sub_items)
            eq_map = {eq.code: eq for eq in equipments}

            for code in selected_sub_items:
                eq = eq_map.get(code)
                if eq:
                    cart.append({
                        'code': eq.code,
                        'category': eq.category,
                        'name': f"{eq.name} (รหัส: {eq.code})",
                        'qty': 1,
                    })
                else:
                    # Fallback กรณีอุปกรณ์อยู่ใน SSMS แต่ยังไม่ได้ Sync ลง Local DB
                    cart.append({
                        'code': code,
                        'category': 'อุปกรณ์ในชุด',
                        'name': f"อุปกรณ์ย่อยรหัส {code}",
                        'qty': 1,
                    })

        # 🟢 กรณีที่ 2: กดเพิ่มอุปกรณ์เดี่ยวแบบปกติ
        else:
            item_category = request.POST.get('item_category', '')
            item_name = request.POST.get('item_name', '')
            qty = request.POST.get('quantity', 1)

            if item_name:
                cart.append({
                    'code': '',
                    'category': item_category,
                    'name': item_name,
                    'qty': qty,
                })

        request.session['borrow_cart'] = cart
        request.session.modified = True

    return redirect('borrow_app:request_form')

@login_required
def add_group_to_cart_view(request, group_id):
    if request.method == 'POST':
        cart = list(request.session.get('borrow_cart', []))
        ssms_group = None
        equipment_obj = None

        if group_id.isdigit():
            equipment_obj = Equipment.objects.filter(group_id=int(group_id), status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน']).order_by('code').first()
            group_name = None
            if equipment_obj and equipment_obj.group:
                group_name = equipment_obj.group.asset_description

            if equipment_obj:
                cart.append({
                    'id': equipment_obj.id,
                    'name': equipment_obj.name,
                    'type': 'Bundle' if equipment_obj.is_bundle else 'ครุภัณฑ์หลัก',
                    'qty': 1
                })
                request.session['borrow_cart'] = cart
                request.session.modified = True
                messages.success(request, f'เพิ่ม 1 รายการจากหมวด "{group_name or equipment_obj.name}" ลงคำร้องเรียบร้อยแล้ว')
                return redirect('borrow_app:request_form')

        try:
            categories, grouped = fetch_ssms_grouped_equipments()
            ssms_group = next((g for g in grouped if g['id'] == group_id), None)
        except Exception:
            ssms_group = None

        if ssms_group:
            items = fetch_ssms_group_items(ssms_group['account_determ'], ssms_group['asset_description'])
            if not items:
                messages.warning(request, 'ไม่พบอุปกรณ์พร้อมให้ยืมในหมวดนี้')
                return redirect('borrow_app:home')

            first_item = items[0]
            cart.append({
                'id': first_item.get('code', ''),
                'name': first_item.get('name', ''),
                'type': 'Bundle',
                'qty': 1
            })
            request.session['borrow_cart'] = cart
            request.session.modified = True
            messages.success(request, f'เพิ่ม 1 รายการจากหมวด "{ssms_group["asset_description"]}" ลงคำร้องเรียบร้อยแล้ว')
            return redirect('borrow_app:request_form')

        messages.warning(request, 'ไม่สามารถเพิ่มคำร้องได้ เนื่องจากไม่พบหมวดหมู่อุปกรณ์ที่เลือก')

    return redirect('borrow_app:request_form')

@login_required
def remove_from_cart_view(request, index):
    cart = list(request.session.get('borrow_cart', []))
    if 0 <= index < len(cart):
        cart.pop(index)
        request.session['borrow_cart'] = cart
        request.session.modified = True

    if not cart:
        return redirect('borrow_app:home')
        
    return redirect('borrow_app:request_form')

@login_required
def return_request_view(request, request_id):
    borrow_req = get_object_or_404(BorrowRequest, request_number=request_id, user=request.user)

    if request.method == 'POST':
        if borrow_req.status in ['อนุมัติ', 'เกินกำหนด', 'คืนไม่ครบ']:
            borrow_req.return_note = request.POST.get('return_note', '').strip()
            if request.FILES.get('return_image'):
                borrow_req.return_image = request.FILES['return_image']
            borrow_req.status = 'รอตรวจสอบการคืน'
            borrow_req.save()
            messages.success(request, 'คำขอคืนอุปกรณ์ถูกส่งแล้ว โปรดรอการตรวจสอบจากผู้ดูแลระบบ')
        else:
            messages.warning(request, 'ไม่สามารถส่งคำขอคืนได้ในสถานะปัจจุบัน')
        return redirect('borrow_app:my_requests')

    return render(request, 'borrow_app/return-form.html', {'borrow_req': borrow_req})

def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect('borrow_app:admin_dashboard')
        return redirect('borrow_app:home')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.is_staff:
                return redirect('borrow_app:admin_dashboard')
            return redirect('borrow_app:home')
    else:
        form = AuthenticationForm()
        
    return render(request, 'borrow_app/login.html', {'form': form})

@staff_member_required
def admin_dashboard_view(request):
    eq_stats = {
        'total': Equipment.objects.count(),
        'available': Equipment.objects.filter(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน']).count(),
        'borrowed': Equipment.objects.filter(status='กำลังถูกยืม').count(),
        'maintenance': Equipment.objects.filter(status='อยู่ระหว่างซ่อม').count(),
        'damaged': Equipment.objects.filter(status='ชำรุด').count(),
    }

    pending_count = BorrowRequest.objects.filter(status='รอการอนุมัติ').count()
    return_pending_count = BorrowRequest.objects.filter(status='รอตรวจสอบการคืน').count()
    active_count = BorrowRequest.objects.filter(status='อนุมัติ').count()
    overdue_count = BorrowRequest.objects.filter(status='เกินกำหนด').count()
    total_request_count = BorrowRequest.objects.count()

    context = {
        'pending_count': pending_count,
        'return_pending_count': return_pending_count,
        'active_count': active_count,
        'overdue_count': overdue_count,
        'total_request_count': total_request_count,
        'recent_requests': BorrowRequest.objects.filter(status='รอการอนุมัติ').order_by('-created_at')[:5],
        'eq_stats': eq_stats,
    }
    return render(request, 'borrow_app/admin_dashboard.html', context)

@staff_member_required
def admin_manage_requests_view(request):
    if request.method == 'POST':
        req_id = request.POST.get('request_id')
        action = request.POST.get('action')
        
        borrow_req = get_object_or_404(BorrowRequest, id=req_id)

        if borrow_req.status == 'รอการอนุมัติ':
            if action == 'approve':
                assignments = {}
                for item in borrow_req.items.all():
                    eq_id = request.POST.get(f'equipment_for_{item.id}', '')
                    if eq_id:
                        assignments[str(item.id)] = eq_id
                borrow_req.approve(request.user, assignments)
            else:
                reason = request.POST.get('reject_reason', '').strip()
                borrow_req.reject(reason)

        elif borrow_req.status == 'รอตรวจสอบการคืน':
            if action == 'approve':
                borrow_req.mark_return_completed(request.user)
            else:
                borrow_req.status = 'คืนไม่ครบ'
                borrow_req.save(update_fields=['status'])

        return redirect('borrow_app:admin_manage_requests')

    selected_status = request.GET.get('status', '')

    # support 'all' to show every block
    show_all = (selected_status == 'all' or selected_status == '')

    if show_all or selected_status == 'รอการอนุมัติ':
        requests_list = BorrowRequest.objects.filter(status='รอการอนุมัติ').order_by('-created_at')
    else:
        requests_list = BorrowRequest.objects.none()

    if show_all or selected_status == 'อนุมัติ':
        active_requests = BorrowRequest.objects.filter(status='อนุมัติ').order_by('-created_at')
    else:
        active_requests = BorrowRequest.objects.none()

    if show_all or selected_status == 'รอตรวจสอบการคืน':
        return_requests = BorrowRequest.objects.filter(status='รอตรวจสอบการคืน').order_by('-created_at')
    else:
        return_requests = BorrowRequest.objects.none()

    # when 'all' requested, pass full list for a single-table overview
    all_requests = None
    if selected_status == 'all':
        all_requests = BorrowRequest.objects.all().order_by('-created_at')

    return render(request, 'borrow_app/admin_manage_requests.html', {
        'requests_list': requests_list,
        'active_requests': active_requests,
        'return_requests': return_requests,
        'all_requests': all_requests,
        'selected_status': selected_status,
    })

@login_required
@staff_member_required
def admin_manual_request_view(request):
    if request.method == 'POST':
        borrower_name = request.POST.get('borrower_name')
        department = request.POST.get('department')
        start_date = request.POST.get('start_date')
        start_time = request.POST.get('start_time', '')
        location = request.POST.get('location')
        purpose = request.POST.get('purpose')
        end_date = request.POST.get('end_date')
        
        selected_equipment_ids = request.POST.getlist('equipment_ids')

        user = User.objects.filter(username=borrower_name).first() or request.user
        req_num = f"REQ-{uuid.uuid4().hex[:8].upper()}"

        borrow_request = BorrowRequest.objects.create(
            request_number=req_num,
            user=user,
            start_datetime=_parse_date(start_date),
            end_datetime=_parse_date(end_date),
            purpose=f"[ผู้ขอยืม: {borrower_name} / สังกัด: {department}] {purpose}",
            location=location,
            status='อนุมัติ'
        )

        for eq_id in selected_equipment_ids:
            equipment = Equipment.objects.filter(id=eq_id).first()
            if equipment:
                BorrowItem.objects.create(
                    borrow_request=borrow_request,
                    equipment=equipment,
                    item_id=str(equipment.id),
                    item_name=equipment.name
                )
                equipment.status = 'กำลังถูกยืม'
                if equipment.available_quantity > 0:
                    equipment.available_quantity -= 1
                equipment.save()

        return redirect('borrow_app:admin_dashboard')

    equipments = Equipment.objects.filter(status='พร้อมให้ยืม')
    return render(request, 'borrow_app/admin_manual_request.html', {'equipments': equipments})

@staff_member_required
def admin_all_history_view(request):
    all_requests = BorrowRequest.objects.all().order_by('-created_at')
    return render(request, 'borrow_app/admin_all_history.html', {'requests_list': all_requests})

# จัดการคลังอุปกรณ์ + Import SSMS Excel
@staff_member_required
def equipment_manage_view(request):
    stats = {
        'total': Equipment.objects.count(),
        'available': Equipment.objects.filter(status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน']).count(),
        'borrowed': Equipment.objects.filter(status='กำลังถูกยืม').count(),
        'maintenance': Equipment.objects.filter(status='อยู่ระหว่างซ่อม').count(),
        'damaged': Equipment.objects.filter(status='ชำรุด').count(),
    }

    selected_status = request.GET.get('status', '')
    if selected_status == 'all':
        selected_status = ''

    group_id = request.GET.get('group_id', '')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            main_no = request.POST.get('asset_no_main', '').strip()
            sub_no = request.POST.get('asset_no_sub', '0001').strip()
            code = request.POST.get('code') or f"{main_no}-{sub_no}"
            total_qty = int(request.POST.get('total_quantity', 1))

            Equipment.objects.create(
                name=request.POST.get('name'),
                code=code,
                category=request.POST.get('category'),
                status=request.POST.get('status', 'พร้อมให้ยืม'),
                asset_no_main=main_no,
                asset_no_sub=sub_no,
                inventory_no=request.POST.get('inventory_no', ''),
                holder_name=request.POST.get('holder_name', ''),
                holder_department=request.POST.get('holder_department', ''),
                total_quantity=total_qty,
                available_quantity=total_qty,
                image=request.FILES.get('image')
            )
            return redirect('borrow_app:equipment_manage')

        elif action == 'edit':
            equipment_id = request.POST.get('equipment_id')
            eq = get_object_or_404(Equipment, id=equipment_id)
            
            eq.name = request.POST.get('name')
            eq.code = request.POST.get('code')
            eq.category = request.POST.get('category')
            eq.status = request.POST.get('status')
            eq.asset_no_main = request.POST.get('asset_no_main', '')
            eq.asset_no_sub = request.POST.get('asset_no_sub', '')
            eq.inventory_no = request.POST.get('inventory_no', '')
            eq.holder_name = request.POST.get('holder_name', '')
            eq.holder_department = request.POST.get('holder_department', '')
            
            if request.POST.get('total_quantity'):
                eq.total_quantity = int(request.POST.get('total_quantity'))

            if 'image' in request.FILES:
                eq.image = request.FILES['image']
                
            eq.save()
            return redirect('borrow_app:equipment_manage')

        elif action == 'delete':
            equipment_id = request.POST.get('equipment_id')
            Equipment.objects.filter(id=equipment_id).delete()
            return redirect('borrow_app:equipment_manage')

        elif action == 'import_excel':
            excel_file = request.FILES.get('excel_file')
            if excel_file:
                try:
                    df = pd.read_excel(excel_file)
                    df.columns = df.columns.str.strip()
                    
                    for _, row in df.iterrows():
                        main_no = str(row.get('assetNoMain', '')).strip() if pd.notna(row.get('assetNoMain')) else ''
                        sub_no = str(row.get('assetNoSub', '0001')).strip() if pd.notna(row.get('assetNoSub')) else '0001'
                        
                        code = f"{main_no}-{sub_no}" if main_no else str(row.get('inventoryNo', row.get('seqNo', ''))).strip()
                        if not code:
                            continue

                        qty = int(row.get('quantity', 1)) if pd.notna(row.get('quantity')) else 1

                        Equipment.objects.update_or_create(
                            code=code,
                            defaults={
                                'name': str(row.get('assetDescription', 'ไม่ระบุชื่อ')).strip(),
                                'category': str(row.get('equipmentCategory', 'ทั่วไป')).strip(),
                                'seq_no': int(row.get('seqNo')) if pd.notna(row.get('seqNo')) else None,
                                'asset_no_main': main_no,
                                'asset_no_sub': sub_no,
                                'inventory_no': str(row.get('inventoryNo', '')).strip() if pd.notna(row.get('inventoryNo')) else '',
                                'total_quantity': qty,
                                'available_quantity': qty,
                                'holder_code': str(row.get('holderCode', '')).strip() if pd.notna(row.get('holderCode')) else '',
                                'holder_name': str(row.get('holderName', '')).strip() if pd.notna(row.get('holderName')) else '',
                                'holder_dept_code': str(row.get('holderDeptCode', '')).strip() if pd.notna(row.get('holderDeptCode')) else '',
                                'holder_department': str(row.get('holderDepartment', '')).strip() if pd.notna(row.get('holderDepartment')) else '',
                            }
                        )
                    messages.success(request, 'นำเข้าข้อมูล SSMS สำเร็จเรียบร้อยแล้ว!')
                except Exception as e:
                    messages.error(request, f'เกิดข้อผิดพลาดในการอ่านไฟล์: {str(e)}')
            return redirect('borrow_app:equipment_manage')

    if selected_status:
        status_filter = selected_status
        if selected_status in ['พร้อมให้ยืม', 'พร้อมใช้งาน']:
            status_filter = 'พร้อมให้ยืม'
        equipments = Equipment.objects.filter(status=status_filter).order_by('-id')
    else:
        equipments = Equipment.objects.all().order_by('-id')

    grouped_equipments = None
    selected_group_items = None
    selected_group = None

    try:
        categories, grouped_equipments = fetch_ssms_grouped_equipments(query='', category='')
        if group_id and grouped_equipments:
            selected_group = next((g for g in grouped_equipments if g['id'] == group_id), None)
            if selected_group:
                selected_group_items = fetch_ssms_group_items(selected_group['account_determ'], selected_group['asset_description'])
                grouped_equipments = [selected_group]
    except Exception:
        grouped_equipments = EquipmentGroup.objects.annotate(
            available_count=Sum('equipments__available_quantity', filter=Q(equipments__status__in=['พร้อมให้ยืม', 'พร้อมใช้งาน'])),
            total_count=Sum('equipments__total_quantity')
        ).filter(available_count__gt=0).order_by('-available_count', 'account_determ', 'asset_description')

        if group_id:
            selected_group = EquipmentGroup.objects.filter(id=group_id).first()
            selected_group_items = Equipment.objects.filter(group_id=group_id).order_by('code')
            if selected_group:
                grouped_equipments = [selected_group]

    return render(request, 'borrow_app/admin_equipment.html', {
        'equipments': equipments,
        'stats': stats,
        'selected_status': selected_status,
        'grouped_equipments': grouped_equipments,
        'selected_group_items': selected_group_items,
        'selected_group': selected_group,
        'group_id': group_id,
    })

def logout_view(request):
    logout(request)
    return redirect('borrow_app:login')

admin_equipment_view = equipment_manage_view

@staff_member_required
def sync_ssms_direct_view(request):
    try:
        with connections['ssms_db'].cursor() as cursor:
            cursor.execute("""
                SELECT assetNoMain, assetNoSub, assetDescription, accountDeterm, inventoryNo 
                FROM dbo.asset
            """)
            rows = cursor.fetchall()

        # ดึงรหัสอุปกรณ์ที่มีอยู่ในระบบ Local ทั้งหมดมาไว้ใน Memory เพื่อลด Query
        existing_equipments = {eq.code: eq for eq in Equipment.objects.all()}

        count_created = 0
        count_updated = 0

        # ใช้ transaction.atomic เพื่อเร่งความเร็วในการประมวลผล (จากนาทีเหลือเพียงไม่กี่วินาที)
        with transaction.atomic():
            for row in rows:
                main_no = str(row[0]).strip() if row[0] is not None else ''
                sub_no = str(row[1]).strip() if row[1] is not None else '0'
                name = str(row[2]).strip() if row[2] else 'ไม่ระบุชื่อ'
                category = str(row[3]).strip() if row[3] else 'ทั่วไป'
                inventory_no = str(row[4]).strip() if row[4] else ''

                # 🟢 กำหนดรหัสเลขครุภัณฑ์ให้เป็นรูปแบบ assetNoMain-assetNoSub
                if main_no:
                    code = f"{main_no}-{sub_no}"
                else:
                    code = inventory_no

                if not code:
                    continue

                # กรณีมีรายการนี้อยู่แล้วในระบบ
                if code in existing_equipments:
                    eq = existing_equipments[code]
                    eq.name = name
                    eq.category = category
                    eq.asset_no_main = main_no
                    eq.asset_no_sub = sub_no
                    eq.inventory_no = inventory_no
                    # 🟢 ไม่เขียนทับ status และ available_quantity เพื่อป้องกันสถานะการยืมถูกรีเซ็ต
                    eq.save()
                    count_updated += 1
                # กรณีเป็นรายการใหม่
                else:
                    Equipment.objects.create(
                        code=code,
                        name=name,
                        category=category,
                        asset_no_main=main_no,
                        asset_no_sub=sub_no,
                        inventory_no=inventory_no,
                        total_quantity=1,
                        available_quantity=1,
                        status='พร้อมให้ยืม'
                    )
                    count_created += 1

        messages.success(request, f'Sync ข้อมูลจาก SSMS สำเร็จ! เพิ่มใหม่ {count_created} รายการ / อัปเดต {count_updated} รายการ')
    except Exception as e:
        messages.error(request, f'ไม่สามารถเชื่อมต่อ SSMS ได้: {str(e)}')

    return redirect('borrow_app:equipment_manage')

def get_bundle_structure(asset_no_main):
    if not asset_no_main or str(asset_no_main).strip() in ['None', '']:
        return None

    # 🟢 คลีนรหัสครุภัณฑ์ เอาเฉพาะส่วนแรกก่อนเครื่องหมาย , หรือช่องว่าง
    clean_asset_main = str(asset_no_main).split(',')[0].strip()

    # 1. พยายามดึงจาก SSMS DB Direct SQL ก่อน
    try:
        if 'ssms_db' in connections:
            with connections['ssms_db'].cursor() as cursor:
                cursor.execute("""
                    SELECT assetNoMain, assetNoSub, assetDescription, accountDeterm, inventoryNo
                    FROM dbo.asset
                    WHERE assetNoMain = %s
                    ORDER BY TRY_CAST(assetNoSub AS INT)
                """, [clean_asset_main])
                rows = cursor.fetchall()
                
            if rows:
                main_item = None
                sub_items = []
                for row in rows:
                    sub_no = str(row[1]).strip() if row[1] is not None else '0'
                    item_data = {
                        'code': f"{row[0]}-{sub_no}",
                        'name': row[2] or 'ไม่ระบุชื่อ',
                        'category': row[3] or 'ทั่วไป',
                        'inventory_no': row[4] or '-',
                        'sub_no': sub_no
                    }
                    if sub_no in ['0', '0000', '0001'] and not main_item:
                        main_item = item_data
                    else:
                        sub_items.append(item_data)
                
                if not main_item and sub_items:
                    main_item = sub_items.pop(0)

                return {
                    'main_item': main_item,
                    'sub_items': sub_items,
                    'total_count': len(rows)
                }
    except Exception:
        pass  # สลับไปใช้ Django ORM ด้านล่างหากคิวรี SSMS ขัดข้อง

    # 2. Fallback ดึงจาก Django ORM Equipment Model
    items = Equipment.objects.filter(
        Q(code__startswith=f"{clean_asset_main}-") | 
        Q(code=clean_asset_main) |
        Q(inventory_no__icontains=clean_asset_main)
    )

    if hasattr(Equipment, 'asset_no_main'):
        items = items | Equipment.objects.filter(asset_no_main=clean_asset_main)

    items = items.distinct()

    if not items.exists():
        return None

    main_item = None
    sub_items = []
    for item in items:
        code_str = str(item.code or '')
        sub_no = code_str.split('-')[-1] if '-' in code_str else '0'
        item_data = {
            'code': item.code or f"{clean_asset_main}-{sub_no}",
            'name': item.name or 'ไม่ระบุชื่อ',
            'category': item.category or 'ทั่วไป',
            'inventory_no': item.inventory_no or '-',
            'sub_no': sub_no
        }
        if sub_no in ['0', '0000', '0001'] and not main_item:
            main_item = item_data
        else:
            sub_items.append(item_data)

    if not main_item and sub_items:
        main_item = sub_items.pop(0)

    return {
        'main_item': main_item,
        'sub_items': sub_items,
        'total_count': items.count()
    }

def bundle_detail_api(request, asset_no_main):
    try:
        data = get_bundle_structure(asset_no_main)
        if not data:
            return JsonResponse({'error': f'ไม่พบข้อมูลอุปกรณ์ย่อยสำหรับรหัส {asset_no_main}'}, status=404)
        return JsonResponse(data)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'error': f'เซิร์ฟเวอร์ขัดข้อง: {str(e)}'}, status=500)