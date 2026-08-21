import traceback
import hashlib
import uuid
import json
import os
import pandas as pd
import datetime as dt
from datetime import datetime, timedelta
import cloudinary.exceptions
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


def _parse_date(date_str):
    if not date_str:
        return None

    # รองรับทั้งแบบมี T (datetime-local) และแบบวันที่ล้วน
    formats = [
        "%Y-%m-%dT%H:%M",  # จาก <input type="datetime-local"> (เช่น 2026-08-13T10:30)
        "%Y-%m-%dT%H:%M:%S",  # รูปแบบพร้อมวินาที
        "%Y-%m-%d %H:%M",  # แบบมีเว้นวรรค
        "%Y-%m-%d",  # แบบวันที่อย่างเดียว
    ]

    for fmt in formats:
        try:
            # แปลงเป็น datetime แล้วดึงเอาเฉพาะส่วนวันที่ (.date())
            return datetime.strptime(str(date_str).strip(), fmt).date()
        except (ValueError, TypeError):
            continue

    return None


def _clean_asset_no(val):
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def build_equipment_type_summary(query="", category="", status=""):
    filters = Q()

    if query:
        filters &= Q(
            Q(name__icontains=query)
            | Q(code__icontains=query)
            | Q(inventory_no__icontains=query)
            | Q(category__icontains=query)
            | Q(group__account_determ__icontains=query)
            | Q(group__asset_description__icontains=query)
        )

    if category and category != "-- หมวดหมู่ทั้งหมด --":
        filters &= Q(category=category) | Q(group__account_determ=category)

    if status and status != "-- สถานะทั้งหมด --":
        if status in ["พร้อมให้ยืม", "พร้อมใช้งาน"]:
            filters &= Q(status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"])
        elif status in ["ถูกยืม", "ติดยืม"]:
            filters &= Q(status="กำลังถูกยืม")
        else:
            filters &= Q(status=status)

    summary = (
        Equipment.objects.select_related("group")
        .filter(filters)
        .values("category", "name")
        .annotate(
            available_count=Sum(
                "available_quantity",
                filter=Q(status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]),
            ),
            total_count=Sum("total_quantity"),
            asset_no_main=Min("asset_no_main"),  # 🟢 เพิ่มการหาค่า asset_no_main
        )
        .order_by("category", "name")
    )

    return [
        {
            "category": item["category"],
            "name": item["name"],
            "asset_no_main": item["asset_no_main"]
            or "",  # 🟢 แนบ asset_no_main ส่งไปให้ home.html
            "available_count": int(item["available_count"] or 0),
            "total_count": int(item["total_count"] or 0),
        }
        for item in summary
    ]


def get_equipment_items_for_type(selected_type="", query="", category="", status=""):
    if not selected_type:
        return Equipment.objects.none()

    selected_category = ""
    selected_name = ""

    if "|" in selected_type:
        selected_category, selected_name = [
            part.strip() for part in selected_type.split("|", 1)
        ]
    else:
        selected_name = selected_type.strip()

    filters = Q()
    if selected_category:
        filters &= Q(category=selected_category)
    if selected_name:
        filters &= Q(name=selected_name)

    if query:
        filters &= Q(
            Q(name__icontains=query)
            | Q(code__icontains=query)
            | Q(inventory_no__icontains=query)
            | Q(category__icontains=query)
            | Q(group__account_determ__icontains=query)
            | Q(group__asset_description__icontains=query)
        )

    if category and category != "-- หมวดหมู่ทั้งหมด --":
        filters &= Q(category=category) | Q(group__account_determ=category)

    if status and status != "-- สถานะทั้งหมด --":
        if status in ["พร้อมให้ยืม", "พร้อมใช้งาน"]:
            filters &= Q(status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"])
        elif status in ["ถูกยืม", "ติดยืม"]:
            filters &= Q(status="กำลังถูกยืม")
        else:
            filters &= Q(status=status)

    return (
        Equipment.objects.select_related("group")
        .filter(filters)
        .order_by("category", "name", "code")
    )


def _norm_text(s):
    """ตัดช่องว่างหัว-ท้าย และยุบช่องว่างซ้ำ/แปลงเป็นตัวพิมพ์เดียวกัน เพื่อกันปัญหาจับคู่ข้อความไทยไม่ตรงกัน"""
    if s is None:
        return ""
    return " ".join(str(s).strip().split()).casefold()


def fetch_ssms_asset_images():
    """
    ดึงรูปภาพอุปกรณ์จากตาราง dbo.asset_image (accountDeterm, assetDescription, image_url)
    รูปถูกอัปโหลดไว้บน Cloudinary โฟลเดอร์ "equipments" แล้วนำ URL มาเก็บไว้ในตารางนี้
    จับคู่ด้วย accountDeterm + assetDescription (normalize ช่องว่าง/ตัวพิมพ์ก่อนเทียบ กันปัญหาช่องว่างเกิน/ตัวพิมพ์เล็กใหญ่)
    คืนค่าเป็น dict: { "accountDeterm|assetDescription" (normalized): [image_url, ...] }
    หนึ่งคีย์อาจมีได้หลายรูป (จะแสดงเป็นแบบเลื่อนดูในหน้า home)
    """
    images_map = {}
    try:
        with connections["ssms_db"].cursor() as cursor:
            cursor.execute("""
                SELECT accountDeterm, assetDescription, image_url
                FROM dbo.asset_image
                WHERE image_url IS NOT NULL AND image_url <> ''
                ORDER BY ID
            """)
            rows = cursor.fetchall()
        for acc_determ, desc, url in rows:
            if not desc or not url:
                continue
            key = f"{_norm_text(acc_determ)}|{_norm_text(desc)}"
            images_map.setdefault(key, []).append(str(url).strip())
    except Exception:
        # ถ้าตาราง dbo.asset_image ยังไม่พร้อม/ดึงไม่ได้ ให้ไม่มีรูปแทนที่จะทำให้หน้า home พัง
        pass
    return images_map


def fetch_ssms_grouped_equipments(query="", category="", status=""):
    query_filters = []
    params = []

    if query:
        like_query = f"%{query}%"
        query_filters.append(
            "(assetDescription LIKE %s OR inventoryNo LIKE %s OR assetNoMain LIKE %s OR assetNoSub LIKE %s)"
        )
        params.extend([like_query, like_query, like_query, like_query])

    if category and category != "-- หมวดหมู่ทั้งหมด --":
        query_filters.append("accountDeterm = %s")
        params.append(category)

    where_clause = " AND ".join(query_filters)
    if where_clause:
        where_clause = " AND " + where_clause

    sql = f"""
        SELECT assetNoMain, assetNoSub, assetDescription, accountDeterm, inventoryNo
        FROM dbo.asset
        WHERE 1=1{where_clause}
        ORDER BY TRY_CAST(assetNoMain AS BIGINT), TRY_CAST(assetNoSub AS INT)
    """

    # 🟢 normalize สถานะที่ใช้กรอง ('พร้อมให้ยืม' และ 'พร้อมใช้งาน' ถือว่าเป็นสถานะเดียวกัน เหมือน logic เดิมในหน้า equipment_manage_view)
    status_filter = (status or "").strip()
    if status_filter in ("พร้อมให้ยืม", "พร้อมใช้งาน"):
        status_filter = "พร้อมให้ยืม"

    unavailable_mains = set()
    status_main_map = (
        {}
    )  # 🟢 main_no -> set ของสถานะที่มีอยู่ในชุดนั้น (ใช้กรองการ์ด Bundle ตามสถานะ)
    status_key_map = (
        {}
    )  # 🟢 "accountDeterm|assetDescription" -> set ของสถานะ (ใช้กรองการ์ด Single ตามสถานะ)

    # ดึงรายการอุปกรณ์ทั้งหมดจาก Local DB มาสร้างทั้ง unavailable_mains และ map สถานะสำหรับกรองการ์ด
    for eq in Equipment.objects.all():
        st = (eq.status or "").strip()
        norm_st = "พร้อมให้ยืม" if st in ("พร้อมให้ยืม", "พร้อมใช้งาน") else st
        is_unavail = (
            st in ["กำลังถูกยืม", "ติดยืม", "อยู่ระหว่างซ่อม", "ชำรุด", "ถูกยืม"]
            or (eq.available_quantity or 0) <= 0
        )

        main_key_candidates = []
        if eq.asset_no_main:
            main_key_candidates.append(str(eq.asset_no_main).strip())
        if eq.code and "-" in eq.code:
            main_key_candidates.append(eq.code.split("-")[0].strip())
        for mk in main_key_candidates:
            if is_unavail:
                unavailable_mains.add(mk)
            status_main_map.setdefault(mk, set()).add(norm_st)

        key_name = f"{(eq.category or '').strip()}|{(eq.name or '').strip()}"
        status_key_map.setdefault(key_name, set()).add(norm_st)

    local_avail_map = {}
    local_qs = Equipment.objects.values("category", "name").annotate(
        total_avail=Sum("available_quantity")
    )
    for l in local_qs:
        cat = (l["category"] or "").strip()
        name = (l["name"] or "").strip()
        key_name = f"{cat}|{name}"
        local_avail_map[key_name] = l["total_avail"] or 0

    with connections["ssms_db"].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

        cursor.execute(
            "SELECT DISTINCT accountDeterm FROM dbo.asset ORDER BY accountDeterm"
        )
        categories = [row[0] for row in cursor.fetchall() if row[0]]

    # 🟢 ดึง map รูปภาพอุปกรณ์ (assetDescription -> [image_url, ...]) จาก dbo.asset_image
    asset_images = fetch_ssms_asset_images()

    # Step 1: แยกกลุ่ม assetNoMain เพื่อตรวจว่าเป็น Bundle หรือ Single
    main_no_groups = {}
    no_main_rows = []

    for row in rows:
        # 🟢 เปลี่ยนมาใช้ _clean_asset_no(row[0])
        main_no = _clean_asset_no(row[0])
        if main_no:
            main_no_groups.setdefault(main_no, []).append(row)
        else:
            no_main_rows.append(row)

    bundle_mains = {}
    single_rows = list(no_main_rows)

    for main_no, item_rows in main_no_groups.items():
        distinct_descs = set((r[2] or "").strip() for r in item_rows if r[2])
        # Rule 2: assetNoMain เดียวกัน แต่ assetDescription ต่างกัน (>1 ชื่อ) -> จัดเป็น Bundle
        if len(distinct_descs) > 1:
            bundle_mains[main_no] = item_rows
        # Rule 1 & 3: assetDescription เหมือนกันทั้งหมด (เช่น เก้าอี้ 10 ตัว) -> จัดเป็น Single
        else:
            single_rows.extend(item_rows)

    # Step 2: สร้างการ์ดสำหรับแสดงผล
    grouped_dict = {}

    # 2a. ประมวลผลกลุ่ม Bundle
    for main_no, item_rows in bundle_mains.items():

        def get_sub_int(r):
            sub_str = str(r[1]).strip() if r[1] is not None else "999999"
            try:
                return int(sub_str)
            except ValueError:
                return 999999

        sorted_item_rows = sorted(item_rows, key=get_sub_int)
        min_sub_item = sorted_item_rows[0]

        bundle_title = (min_sub_item[2] or "ไม่ระบุชื่อ").strip()
        acc_determ = (min_sub_item[3] or "ทั่วไป").strip()

        # เช็คสถานะยืม ถ้าอยู่ใน unavailable_mains ให้คงเหลือเป็น 0
        is_bundle_avail = 0 if main_no in unavailable_mains else 1

        # 🟢 รวมรูปภาพของทุกชิ้นส่วนย่อยในชุด (ไม่ใช่แค่รูปของรายการหลัก) เพื่อให้เลื่อนดูได้ครบทุกชิ้น
        bundle_images = []
        seen_urls = set()
        for r in sorted_item_rows:
            r_desc = (r[2] or "").strip()
            r_acc = (r[3] or acc_determ).strip()
            if not r_desc:
                continue
            r_key = f"{_norm_text(r_acc)}|{_norm_text(r_desc)}"
            for url in asset_images.get(r_key, []):
                if url not in seen_urls:
                    bundle_images.append(url)
                    seen_urls.add(url)

        key = f"BUNDLE_{main_no}"
        grouped_dict[key] = {
            "id": key,
            "account_determ": acc_determ,
            "asset_description": f"{bundle_title} (ชุด)",
            "asset_no_main": main_no,
            "is_bundle": True,
            "available_count": is_bundle_avail,
            "total_count": len(
                item_rows
            ),  # 🟢 เปลี่ยนจาก 1 เป็น len(item_rows) เพื่อบอกจำนวนชิ้นในชุด
            "images": bundle_images,  # 🟢 รวมรูปทุกชิ้นส่วนย่อยในชุด ไม่ใช่แค่รายการหลัก
        }

    # 2b. ประมวลผลกลุ่ม Single (รวมกลุ่มตาม Category + assetDescription)
    for row in single_rows:
        acc_determ = (row[3] or "ทั่วไป").strip()
        asset_desc = (row[2] or "ไม่ระบุ").strip()
        key_name = f"{acc_determ}|{asset_desc}"
        key = hashlib.md5(key_name.encode("utf-8")).hexdigest()

        if key not in grouped_dict:
            avail_c = local_avail_map.get(key_name, 0)
            grouped_dict[key] = {
                "id": key,
                "account_determ": acc_determ,
                "asset_description": asset_desc,
                "asset_no_main": None,
                "is_bundle": False,
                "available_count": avail_c,
                "total_count": 0,
                "images": asset_images.get(
                    f"{_norm_text(acc_determ)}|{_norm_text(asset_desc)}", []
                ),  # 🟢 จับคู่ด้วย accountDeterm + assetDescription (normalize แล้ว)
            }
        grouped_dict[key]["total_count"] += 1
        if key_name not in local_avail_map:
            grouped_dict[key]["available_count"] += 1

    result_list = list(grouped_dict.values())

    # 🟢 กรองการ์ดตามสถานะที่เลือก (ถ้ามี) — เช็คว่ากลุ่มนั้นมีอุปกรณ์สถานะที่ต้องการอยู่จริงหรือไม่
    if status_filter:
        filtered_list = []
        for item in result_list:
            if item["is_bundle"]:
                statuses = status_main_map.get(
                    str(item["asset_no_main"]).strip(), set()
                )
            else:
                key_name = f"{item['account_determ']}|{item['asset_description']}"
                statuses = status_key_map.get(key_name, set())
            if status_filter in statuses:
                filtered_list.append(item)
        result_list = filtered_list

    return categories, result_list


def fetch_ssms_stats():
    with connections["ssms_db"].cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM dbo.asset")
        total = cursor.fetchone()[0] or 0

    return {
        "total": int(total),
        "available": int(total),
        "borrowed": 0,
        "maintenance": 0,
        "damaged": 0,
    }


def fetch_ssms_group_items(account_determ, asset_description, asset_no_main=None):
    if asset_no_main:
        # 🟢 Clean ค่า asset_no_main และใช้ LTRIM(RTRIM()) ใน SQL
        clean_main = _clean_asset_no(asset_no_main)
        sql = """
            SELECT assetNoMain, assetNoSub, assetDescription, inventoryNo, accountDeterm
            FROM dbo.asset
            WHERE LTRIM(RTRIM(assetNoMain)) = %s
            ORDER BY TRY_CAST(assetNoSub AS INT)
        """
        params = [clean_main]
    else:
        # หากเป็น Single ให้ดึงรายการทั้งหมดตาม หมวดหมู่ + ชื่ออุปกรณ์
        sql = """
            SELECT assetNoMain, assetNoSub, assetDescription, inventoryNo, accountDeterm
            FROM dbo.asset
            WHERE accountDeterm = %s AND assetDescription = %s
            ORDER BY TRY_CAST(assetNoMain AS BIGINT), TRY_CAST(assetNoSub AS INT)
        """
        params = [account_determ, asset_description]

    with connections["ssms_db"].cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    items = []
    codes = set()
    for row in rows:
        main_no = str(row[0]).strip() if row[0] is not None else ""
        sub_no = str(row[1]).strip() if row[1] is not None else "0"
        code = f"{main_no}-{sub_no}" if main_no else str(row[3] or "")

        items.append(
            {
                "code": code,
                "name": row[2] or "ไม่ระบุ",
                "category": row[4] or "ทั่วไป",
                "inventory_no": row[3] or "-",
                "status": "พร้อมให้ยืม",
                "available_quantity": 1,
            }
        )
        if code:
            codes.add(code)

    local_equipment_map = {
        eq.code: eq for eq in Equipment.objects.filter(code__in=codes)
    }
    for item in items:
        equipment = local_equipment_map.get(item["code"])
        if equipment:
            item["id"] = equipment.id
            item["group_id"] = equipment.group_id
            item["status"] = equipment.status
            item["available_quantity"] = equipment.available_quantity

    return items


@login_required
def home_view(request):
    if request.user.is_staff:
        return redirect("borrow_app:admin_dashboard")
    query = request.GET.get("q", "")
    category = request.GET.get("category", "")
    status = request.GET.get("status", "")
    group_id = request.GET.get("group_id", "")
    selected_equipment_type = request.GET.get("equipment_type", "").strip()

    group_filter = Q()
    if query:
        group_filter &= Q(
            Q(asset_description__icontains=query)
            | Q(account_determ__icontains=query)
            | Q(equipments__name__icontains=query)
            | Q(equipments__code__icontains=query)
            | Q(equipments__inventory_no__icontains=query)
        )

    if category and category != "-- หมวดหมู่ทั้งหมด --":
        group_filter &= Q(account_determ=category)

    if status and status != "-- สถานะทั้งหมด --":
        if status in ["พร้อมให้ยืม", "พร้อมใช้งาน"]:
            group_filter &= Q(equipments__status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"])
        elif status in ["ถูกยืม", "ติดยืม"]:
            group_filter &= Q(equipments__status="กำลังถูกยืม")
        else:
            group_filter &= Q(equipments__status=status)

    cart_items = request.session.get("borrow_cart", [])

    grouped_equipments = None
    categories = []
    try:
        categories, grouped_equipments_ssms = fetch_ssms_grouped_equipments(
            query=query, category=category
        )

        # ⭐ เพิ่มการ filter
        if grouped_equipments_ssms:
            pictures = fetch_ssms_asset_images()

            # Filter เฉพาะ available > 0
            filtered_list = [
                item
                for item in grouped_equipments_ssms
                if item.get("available_count", 0) > 0
            ]

            # Update image URL
            for item in filtered_list:
                account = item.get("account_determ", "").strip()
                asset = item.get("asset_description", "").strip()
                key = f"{account}|{asset}"

                if key in pictures:
                    item["image_url"] = pictures[key]
                else:
                    item["image_url"] = None

            grouped_equipments = filtered_list
    except Exception:
        categories = list(
            EquipmentGroup.objects.values_list("account_determ", flat=True).distinct()
        )

    if grouped_equipments is None:
        grouped_equipments = (
            EquipmentGroup.objects.filter(group_filter)
            .annotate(
                available_count=Sum(
                    "equipments__available_quantity",
                    filter=Q(equipments__status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]),
                ),
                total_count=Sum("equipments__total_quantity"),
            )
            .filter(available_count__gt=0)
            .order_by("-available_count", "account_determ", "asset_description")
        )

    equipment_type_summary = build_equipment_type_summary(
        query=query, category=category, status=status
    )
    selected_equipment_items = (
        get_equipment_items_for_type(
            selected_equipment_type,
            query=query,
            category=category,
            status=status,
        )
        if selected_equipment_type
        else Equipment.objects.none()
    )

    selected_equipment_type_label = ""
    if selected_equipment_type and "|" in selected_equipment_type:
        selected_category_value, selected_name_value = [
            part.strip() for part in selected_equipment_type.split("|", 1)
        ]
        selected_equipment_type_label = (
            f"{selected_name_value} ({selected_category_value})"
        )
    elif selected_equipment_type:
        selected_equipment_type_label = selected_equipment_type

    group_id = request.GET.get("group_id")

    selected_group_items = None
    selected_group = None
    if group_id:
        if isinstance(grouped_equipments, list):
            # ค้นหาการ์ดใบที่ผู้ใช้กดเลือก
            selected_group = next(
                (g for g in grouped_equipments if g["id"] == group_id), None
            )
            if selected_group:
                # เช็คว่าเป็น Bundle หรือไม่ หากใช่จะส่ง asset_no_main ไปดึงชิ้นส่วนย่อย
                asset_main = (
                    selected_group.get("asset_no_main")
                    if selected_group.get("is_bundle")
                    else None
                )
                selected_group_items = fetch_ssms_group_items(
                    selected_group["account_determ"],
                    selected_group["asset_description"],
                    asset_no_main=asset_main,
                )

    context = {
        "grouped_equipments": grouped_equipments,
        "equipment_type_summary": equipment_type_summary,
        "selected_equipment_items": selected_equipment_items,
        "selected_equipment_type": selected_equipment_type,
        "selected_equipment_type_label": selected_equipment_type_label,
        "selected_group_items": selected_group_items,
        "selected_group": selected_group,
        "categories": categories,
        "query": query,
        "selected_category": category,
        "selected_status": status,
        "group_id": group_id,
        "cart_count": len(cart_items),
    }
    return render(request, "borrow_app/home.html", context)


@login_required
def request_form_view(request):
    cart_items = request.session.get("borrow_cart", [])
    if not cart_items:
        return redirect("borrow_app:home")

    if request.method == "POST":
        request.session["borrow_details"] = {
            "start_datetime": request.POST.get("start_datetime"),
            "end_datetime": request.POST.get("end_datetime"),
            "location": request.POST.get("location"),
            "purpose": request.POST.get("purpose"),
            "pickup_method": request.POST.get("pickup_method"),
        }
        return redirect("borrow_app:request_summary")
    now = datetime.now()
    default_start = now.strftime("%Y-%m-%dT%H:%M")  # format: 2569-08-12T14:30
    default_end = (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")  # +3 วัน
    min_date = now.strftime("%Y-%m-%dT%H:%M")

    context = {
        "cart_items": cart_items,
        "default_start": default_start,
        "default_end": default_end,
        "min_date": min_date,
    }

    return render(request, "borrow_app/request-form.html", context)


@login_required
def request_summary_view(request):
    cart_items = request.session.get("borrow_cart", [])
    details = request.session.get("borrow_details", None)

    if not cart_items or not details:
        return redirect("borrow_app:request_form")

    context = {
        "cart_items": cart_items,
        "details": details,
        "today_date": datetime.now().strftime("%d/%m/%Y"),
    }
    return render(request, "borrow_app/request-summary.html", context)


@login_required
def confirm_request_view(request):
    if request.method == "POST":
        cart_items = request.session.get("borrow_cart", [])
        details = request.session.get("borrow_details", {})

        if not cart_items or not details:
            return redirect("borrow_app:request_form")

        # 🟢 1. ดึงปี พ.ศ. 2 หลักท้าย (เช่น 2569 -> '69')
        thai_year_short = str(datetime.now().year + 543)[-2:]
        year_prefix = f"{thai_year_short}/"

        # 🟢 2. นับจำนวนคำร้องที่มี Prefix ของปีนี้ เพื่อให้รีเซ็ตเริ่ม 0001 ใหม่ทุกปี
        count_this_year = (
            BorrowRequest.objects.filter(request_number__startswith=year_prefix).count()
            + 1
        )
        new_req_no = f"{year_prefix}{count_this_year:04d}"

        borrow_req = BorrowRequest.objects.create(
            request_number=new_req_no,
            user=request.user,
            start_datetime=_parse_date(details.get("start_datetime")),
            end_datetime=_parse_date(details.get("end_datetime")),
            purpose=details.get("purpose", "-"),
            location=details.get("location", "-"),
            pickup_method=details.get("pickup_method", "-"),
            status="รอการอนุมัติ",
        )

        for item in cart_items:
            item_code = item.get("code", "")
            equipment_obj = None

            if item_code:
                equipment_obj = Equipment.objects.filter(code=item_code).first()

            # 🟢 ถ้าไม่มี code ให้ Fallback หาจากชื่อและหมวดหมู่ชิ้นที่พร้อมให้ยืมใน DB
            if not equipment_obj:
                equipment_obj = Equipment.objects.filter(
                    category=item.get("category", ""),
                    name=item.get("name", ""),
                    status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"],
                    available_quantity__gt=0,
                ).first()

            BorrowItem.objects.create(
                borrow_request=borrow_req,
                equipment=equipment_obj,
                item_name=item.get("name", ""),
                requested_category=item.get("category", ""),
                quantity=int(item.get("qty", 1)),
                return_status="ยังไม่คืน",
            )

        request.session.pop("borrow_cart", None)
        request.session.pop("borrow_details", None)
        request.session.modified = True

        return redirect("borrow_app:my_requests")

    return redirect("borrow_app:request_summary")


@login_required
def my_requests_view(request):
    active_statuses = [
        "รอการอนุมัติ",
        "อนุมัติ",
        "รอตรวจสอบการคืน",
        "คืนไม่ครบ",
        "เกินกำหนด",
    ]
    active_requests = BorrowRequest.objects.filter(
        user=request.user, status__in=active_statuses
    ).order_by("-created_at")

    for borrow_req in active_requests:
        borrow_req.refresh_status()

    active_requests = list(active_requests)
    active_requests.sort(key=lambda req: req.created_at, reverse=True)

    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)

    return render(
        request, "borrow_app/my-requests.html", {"requests_list": active_requests}
    )


@login_required
def history_view(request):
    history_statuses = ["ยกเลิก", "ไม่อนุมัติ", "คืนสำเร็จ"]
    history_requests = BorrowRequest.objects.filter(
        user=request.user, status__in=history_statuses
    ).order_by("-created_at")

    return render(
        request, "borrow_app/history.html", {"requests_list": history_requests}
    )


@login_required
def cancel_request_view(request, request_id):
    if request.method == "POST":
        borrow_request = get_object_or_404(
            BorrowRequest,
            request_number=request_id,
            user=request.user,
            status="รอการอนุมัติ",
        )

        # คำร้องสถานะ "รอการอนุมัติ" ยังไม่ได้รับการอนุมัติ
        # ดังนั้น available_quantity ของ Equipment ยังไม่ถูกหักออก — ไม่ต้อง restore อะไรเลย
        borrow_request.status = "ยกเลิก"
        borrow_request.save(update_fields=["status"])

    return redirect("borrow_app:history")

    return redirect("borrow_app:history")


@login_required
def add_to_cart_view(request):
    if request.method == "POST":
        selected_sub_items = request.POST.getlist("selected_sub_items")

        # รับข้อมูลอุปกรณ์หลัก (Parent Bundle) จาก Form POST
        main_item_code = request.POST.get("main_item_code", "").strip()
        main_item_name = request.POST.get("main_item_name", "").strip()
        main_item_category = request.POST.get(
            "main_item_category", "ชุดอุปกรณ์"
        ).strip()

        cart = list(request.session.get("borrow_cart", []))

        # 🟢 ดึง map รูปภาพครั้งเดียว แล้วนำไปจับคู่กับแต่ละรายการที่ใส่ลงตะกร้า
        asset_images = fetch_ssms_asset_images()

        def _eq_image_url(eq):
            if not eq:
                return ""
            urls = asset_images.get(
                f"{_norm_text(eq.category)}|{_norm_text(eq.name)}", []
            )
            return urls[0] if urls else ""

        # หากมีข้อมูลอุปกรณ์หลัก ให้ Push ลง Cart เป็นรายการแรกก่อน
        if main_item_code or main_item_name:
            eq_main = (
                Equipment.objects.filter(code=main_item_code).first()
                if main_item_code
                else None
            )
            cart.append(
                {
                    "code": main_item_code or (eq_main.code if eq_main else ""),
                    "category": eq_main.category if eq_main else main_item_category,
                    "name": (
                        f"{eq_main.name} (รหัส: {eq_main.code})"
                        if eq_main
                        else main_item_name
                    ),
                    "qty": 1,
                    "image_url": _eq_image_url(eq_main),  # 🟢 รูปภาพอุปกรณ์หลัก
                }
            )

        if selected_sub_items:
            sub_codes = [code for code in selected_sub_items if code != main_item_code]
            equipments = Equipment.objects.filter(code__in=sub_codes)
            eq_map = {eq.code: eq for eq in equipments}

            for code in selected_sub_items:
                eq = eq_map.get(code)
                if eq:
                    cart.append(
                        {
                            "code": eq.code,
                            "category": eq.category,
                            "name": f"{eq.name} (รหัส: {eq.code})",
                            "qty": 1,
                            "image_url": _eq_image_url(eq),  # 🟢 รูปภาพอุปกรณ์ย่อย
                        }
                    )
                else:
                    cart.append(
                        {
                            "code": code,
                            "category": "อุปกรณ์ในชุด",
                            "name": f"อุปกรณ์ย่อยรหัส {code}",
                            "qty": 1,
                            "image_url": "",
                        }
                    )

        elif not (main_item_code or main_item_name):
            item_category = request.POST.get("item_category", "")
            item_name = request.POST.get("item_name", "")
            qty = request.POST.get("quantity", 1)

            if item_name:
                eq_match = Equipment.objects.filter(
                    category=item_category,
                    name=item_name,
                    status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"],
                    available_quantity__gt=0,
                ).first()

                cart.append(
                    {
                        "code": eq_match.code if eq_match else "",
                        "category": item_category,
                        "name": item_name,
                        "qty": qty,
                        "image_url": _eq_image_url(
                            eq_match
                        ),  # 🟢 รูปภาพอุปกรณ์ชิ้นเดียว
                    }
                )

        request.session["borrow_cart"] = cart
        request.session.modified = True

    return redirect("borrow_app:request_form")


@login_required
def add_group_to_cart_view(request, group_id):
    if request.method == "POST":
        cart = list(request.session.get("borrow_cart", []))
        ssms_group = None
        equipment_obj = None

        if group_id.isdigit():
            equipment_obj = (
                Equipment.objects.filter(
                    group_id=int(group_id), status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]
                )
                .order_by("code")
                .first()
            )
            group_name = None
            if equipment_obj and equipment_obj.group:
                group_name = equipment_obj.group.asset_description

            if equipment_obj:
                # 🟢 รูปภาพอุปกรณ์ (จับคู่ตาม accountDeterm + assetDescription เหมือนหน้า home)
                asset_images = fetch_ssms_asset_images()
                img_urls = asset_images.get(
                    f"{_norm_text(equipment_obj.category)}|{_norm_text(equipment_obj.name)}",
                    [],
                )
                cart.append(
                    {
                        "id": equipment_obj.code,
                        "name": equipment_obj.category,
                        "type": "Bundle" if equipment_obj.is_bundle else "ครุภัณฑ์หลัก",
                        "qty": 1,
                        "image_url": img_urls[0] if img_urls else "",
                    }
                )
                request.session["borrow_cart"] = cart
                request.session.modified = True
                messages.success(
                    request,
                    f'เพิ่ม 1 รายการจากหมวด "{group_name or equipment_obj.name}" ลงคำร้องเรียบร้อยแล้ว',
                )
                return redirect("borrow_app:request_form")

        try:
            categories, grouped = fetch_ssms_grouped_equipments()
            ssms_group = next((g for g in grouped if g["id"] == group_id), None)
        except Exception:
            ssms_group = None

        if ssms_group:
            # --- เริ่มต้นส่วนที่มีการแก้ไข ---
            asset_main = (
                ssms_group.get("asset_no_main") if ssms_group.get("is_bundle") else None
            )
            items = fetch_ssms_group_items(
                ssms_group["account_determ"],
                ssms_group["asset_description"],
                asset_no_main=asset_main,
            )
            # --- สิ้นสุดส่วนที่มีการแก้ไข ---

            if not items:
                messages.warning(request, "ไม่พบอุปกรณ์พร้อมให้ยืมในหมวดนี้")
                return redirect("borrow_app:home")

            first_item = items[0]
            cart.append(
                {
                    "code": first_item.get("code", ""),
                    "category": first_item.get("category", ""),
                    "name": first_item.get("name", ""),
                    "type": "Bundle",
                    "qty": 1,
                    "image_url": (ssms_group.get("images") or [""])[
                        0
                    ],  # 🟢 ใช้รูปแรกของกลุ่ม (รวมรูปทุกชิ้นในชุดแล้วจากหน้า home)
                }
            )
            request.session["borrow_cart"] = cart
            request.session.modified = True
            messages.success(
                request,
                f'เพิ่ม 1 รายการจากหมวด "{ssms_group["asset_description"]}" ลงคำร้องเรียบร้อยแล้ว',
            )
            return redirect("borrow_app:request_form")

        messages.warning(
            request, "ไม่สามารถเพิ่มคำร้องได้ เนื่องจากไม่พบหมวดหมู่อุปกรณ์ที่เลือก"
        )

    return redirect("borrow_app:request_form")


@login_required
def remove_from_cart_view(request, index):
    cart = list(request.session.get("borrow_cart", []))
    if 0 <= index < len(cart):
        cart.pop(index)
        request.session["borrow_cart"] = cart
        request.session.modified = True

    if not cart:
        return redirect("borrow_app:home")

    return redirect("borrow_app:request_form")


@login_required
@transaction.atomic
def return_request_view(request, request_id):
    borrow_req = get_object_or_404(
        BorrowRequest, request_number=request_id, user=request.user
    )

    # รองรับข้อมูลคำร้อง "คืนไม่ครบ" เดิมที่รายการอาจยังค้างเป็น "รอตรวจรับ"
    returnable_statuses = ["ยังไม่คืน"]
    if borrow_req.status == "คืนไม่ครบ":
        returnable_statuses.append("รอตรวจรับ")

    if request.method == "POST":
        if borrow_req.status in ["อนุมัติ", "เกินกำหนด", "คืนไม่ครบ"]:
            selected_ids = request.POST.getlist("return_item_ids")
            selected_items = borrow_req.items.filter(
                id__in=selected_ids, return_status__in=returnable_statuses
            )
            if not selected_items.exists():
                messages.error(
                    request, "กรุณาเลือกรายการอุปกรณ์ที่ต้องการคืนอย่างน้อย 1 รายการ"
                )
                return redirect("borrow_app:return_request", request_id=request_id)

            # ตรวจสอบนามสกุลไฟล์ก่อนบันทึก/อัปโหลด
            return_image_file = request.FILES.get("return_image")
            if return_image_file:
                allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
                _, ext = os.path.splitext(return_image_file.name.lower())
                if ext not in allowed_extensions:
                    messages.error(
                        request,
                        f"ไฟล์ '{return_image_file.name}' ไม่รองรับ — กรุณาอัปโหลดไฟล์รูปภาพ (.jpg, .jpeg, .png, .webp, .heic) เท่านั้น",
                    )
                    return redirect("borrow_app:return_request", request_id=request_id)

            try:
                borrow_req.return_note = request.POST.get("return_note", "").strip()
                if return_image_file:
                    borrow_req.return_image = return_image_file
                selected_items.update(return_status="รอตรวจรับ")
                borrow_req.status = "รอตรวจสอบการคืน"
                borrow_req.save()
            except cloudinary.exceptions.Error as e:
                messages.error(
                    request,
                    f"เกิดข้อผิดพลาดขณะอัปโหลดรูปภาพ กรุณาลองใหม่อีกครั้ง ({e})",
                )
                return redirect("borrow_app:return_request", request_id=request_id)

            messages.success(
                request, "คำขอคืนอุปกรณ์ถูกส่งแล้ว โปรดรอการตรวจสอบจากผู้ดูแลระบบ"
            )
        else:
            messages.warning(request, "ไม่สามารถส่งคำขอคืนได้ในสถานะปัจจุบัน")
        return redirect("borrow_app:my_requests")

    today_date = datetime.now().strftime("%Y-%m-%d")

    return render(
        request,
        "borrow_app/return-form.html",
        {
            "borrow_req": borrow_req,
            "returnable_items": borrow_req.items.filter(
                return_status__in=returnable_statuses
            ),
            "today_date": today_date,
        },
    )


def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("borrow_app:admin_dashboard")
        return redirect("borrow_app:home")

    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.is_staff:
                return redirect("borrow_app:admin_dashboard")
            return redirect("borrow_app:home")
    else:
        form = AuthenticationForm()

    return render(request, "borrow_app/login.html", {"form": form})


@staff_member_required
def admin_dashboard_view(request):
    eq_stats = {
        "total": Equipment.objects.count(),
        "available": Equipment.objects.filter(
            status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]
        ).count(),
        "borrowed": Equipment.objects.filter(status="กำลังถูกยืม").count(),
        "maintenance": Equipment.objects.filter(status="อยู่ระหว่างซ่อม").count(),
        "damaged": Equipment.objects.filter(status="ชำรุด").count(),
    }

    pending_count = BorrowRequest.objects.filter(status="รอการอนุมัติ").count()
    return_pending_count = BorrowRequest.objects.filter(
        status="รอตรวจสอบการคืน"
    ).count()
    active_count = BorrowRequest.objects.filter(status="อนุมัติ").count()
    overdue_count = BorrowRequest.objects.filter(status="เกินกำหนด").count()
    total_request_count = BorrowRequest.objects.count()

    # 📊 Chart 1: Top 5 อุปกรณ์ที่ถูกยืมมากที่สุด
    top_items_qs = (
        BorrowItem.objects.values("item_name")
        .annotate(total_borrowed=Sum("quantity"))
        .order_by("-total_borrowed")[:5]
    )
    chart_top_labels = [item["item_name"] or "ไม่ระบุชื่อ" for item in top_items_qs]
    chart_top_data = [item["total_borrowed"] for item in top_items_qs]

    # 📊 Chart 2: สัดส่วนอุปกรณ์ในคลังตามหมวดหมู่
    cat_qs = (
        Equipment.objects.values("category")
        .annotate(total=Count("id"))
        .order_by("-total")[:5]
    )
    chart_cat_labels = [c["category"] or "หมวดหมู่ทั่วไป" for c in cat_qs]
    chart_cat_data = [c["total"] for c in cat_qs]

    context = {
        "pending_count": pending_count,
        "return_pending_count": return_pending_count,
        "active_count": active_count,
        "overdue_count": overdue_count,
        "total_request_count": total_request_count,
        "recent_requests": BorrowRequest.objects.filter(status="รอการอนุมัติ").order_by(
            "-created_at"
        )[:5],
        "eq_stats": eq_stats,
        # ส่งค่า JSON สำหรับ Chart.js
        "chart_top_labels": json.dumps(chart_top_labels),
        "chart_top_data": json.dumps(chart_top_data),
        "chart_cat_labels": json.dumps(chart_cat_labels),
        "chart_cat_data": json.dumps(chart_cat_data),
    }
    return render(request, "borrow_app/admin_dashboard.html", context)


@staff_member_required
def admin_manage_requests_view(request):
    if request.method == "POST":
        req_id = request.POST.get("request_id")
        action = request.POST.get("action")

        borrow_req = get_object_or_404(BorrowRequest, id=req_id)

        if borrow_req.status == "รอการอนุมัติ":
            if action == "approve":
                assignments = {}
                for item in borrow_req.items.all():
                    eq_id = request.POST.get(f"equipment_for_{item.id}", "")
                    if eq_id:
                        assignments[str(item.id)] = eq_id
                if "pickup_image" in request.FILES:
                    borrow_req.pickup_image = request.FILES["pickup_image"]
                    borrow_req.save()

                try:
                    borrow_req.approve(request.user, assignments)
                except ValueError as exc:
                    messages.error(request, str(exc))
                    return redirect("borrow_app:admin_manage_requests")
            else:
                reason = request.POST.get("reject_reason", "").strip()
                if "pickup_image" in request.FILES:
                    borrow_req.pickup_image = request.FILES["pickup_image"]
                    borrow_req.save()
                borrow_req.reject(reason)

        elif borrow_req.status == "รอตรวจสอบการคืน":
            if action == "approve":
                conditions = {
                    str(item.id): request.POST.get(
                        f"return_condition_{item.id}", "ปกติ"
                    )
                    for item in borrow_req.items.filter(return_status="รอตรวจรับ")
                }
                borrow_req.verify_pending_return_items(
                    request.user,
                    conditions,
                    request.POST.get("return_incomplete_comment", "").strip(),
                )
            else:
                comment = request.POST.get("return_incomplete_comment", "").strip()
                if not comment:
                    messages.error(
                        request, "กรุณาระบุคอมเมนต์ก่อนแจ้งว่าคืนอุปกรณ์ไม่ครบ"
                    )
                    return redirect("borrow_app:admin_manage_requests")
                borrow_req.mark_return_incomplete(comment)

        return redirect("borrow_app:admin_manage_requests")

    selected_status = request.GET.get("status", "")
    search_q = request.GET.get("q", "").strip()

    # support 'all' to show every block
    show_all = selected_status == "all" or selected_status == ""

    def _apply_search(qs):
        if not search_q:
            return qs
        return qs.filter(
            Q(request_number__icontains=search_q)
            | Q(user__username__icontains=search_q)
            | Q(user__first_name__icontains=search_q)
            | Q(user__last_name__icontains=search_q)
        )

    if show_all or selected_status == "รอการอนุมัติ":
        requests_list = _apply_search(
            BorrowRequest.objects.filter(status="รอการอนุมัติ").order_by("-created_at")
        )
    else:
        requests_list = BorrowRequest.objects.none()

    # รวม "เกินกำหนด" เข้า section อนุมัติแล้ว เพื่อให้ admin เห็นและดำเนินการได้
    if show_all or selected_status in ("อนุมัติ", "เกินกำหนด"):
        active_requests = _apply_search(
            BorrowRequest.objects.filter(
                status__in=["อนุมัติ", "เกินกำหนด"]
            ).order_by("-created_at")
        )
    else:
        active_requests = BorrowRequest.objects.none()

    if show_all or selected_status == "รอตรวจสอบการคืน":
        return_requests = _apply_search(
            BorrowRequest.objects.filter(
                status="รอตรวจสอบการคืน"
            ).order_by("-created_at")
        )
    else:
        return_requests = BorrowRequest.objects.none()

    # when 'all' requested, pass full list for a single-table overview
    all_requests = None
    if selected_status == "all":
        all_requests = _apply_search(
            BorrowRequest.objects.all().order_by("-created_at")
        )

    return render(
        request,
        "borrow_app/admin_manage_requests.html",
        {
            "requests_list": requests_list,
            "active_requests": active_requests,
            "return_requests": return_requests,
            "all_requests": all_requests,
            "selected_status": selected_status,
            "search_q": search_q,
        },
    )


@login_required
@staff_member_required
def admin_manual_request_view(request):
    if request.method == "POST":
        borrower_name = request.POST.get("borrower_name")
        department = request.POST.get("department")
        start_date = request.POST.get("start_date")
        start_time = request.POST.get("start_time", "")
        location = request.POST.get("location")
        purpose = request.POST.get("purpose")
        end_date = request.POST.get("end_date")

        selected_equipment_ids = request.POST.getlist("equipment_ids")

        user = User.objects.filter(username=borrower_name).first() or request.user
        req_num = f"REQ-{uuid.uuid4().hex[:8].upper()}"

        borrow_request = BorrowRequest.objects.create(
            request_number=req_num,
            user=user,
            start_datetime=_parse_date(start_date),
            end_datetime=_parse_date(end_date),
            purpose=f"[ผู้ขอยืม: {borrower_name} / สังกัด: {department}] {purpose}",
            location=location,
            status="อนุมัติ",
        )

        for eq_id in selected_equipment_ids:
            equipment = Equipment.objects.filter(id=eq_id).first()
            if equipment:
                BorrowItem.objects.create(
                    borrow_request=borrow_request,
                    equipment=equipment,
                    item_id=str(equipment.id),
                    item_name=equipment.name,
                )
                equipment.status = "กำลังถูกยืม"
                if equipment.available_quantity > 0:
                    equipment.available_quantity -= 1
                equipment.save()

        return redirect("borrow_app:admin_dashboard")

    equipments = Equipment.objects.filter(status="พร้อมให้ยืม")
    return render(
        request, "borrow_app/admin_manual_request.html", {"equipments": equipments}
    )


@staff_member_required
def admin_all_history_view(request):
    all_requests = BorrowRequest.objects.all().order_by("-created_at")
    return render(
        request, "borrow_app/admin_all_history.html", {"requests_list": all_requests}
    )


# จัดการคลังอุปกรณ์ + Import SSMS Excel
@staff_member_required
def equipment_manage_view(request):
    stats = {
        "total": Equipment.objects.count(),
        "available": Equipment.objects.filter(
            status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]
        ).count(),
        "borrowed": Equipment.objects.filter(status="กำลังถูกยืม").count(),
        "maintenance": Equipment.objects.filter(status="อยู่ระหว่างซ่อม").count(),
        "damaged": Equipment.objects.filter(status="ชำรุด").count(),
    }

    selected_status = request.GET.get("status", "")
    if selected_status == "all":
        selected_status = ""

    group_id = request.GET.get("group_id", "")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            main_no = request.POST.get("asset_no_main", "").strip()
            sub_no = request.POST.get("asset_no_sub", "0001").strip()
            code = request.POST.get("code") or f"{main_no}-{sub_no}"
            total_qty = int(request.POST.get("total_quantity", 1))

            Equipment.objects.create(
                name=request.POST.get("name"),
                code=code,
                category=request.POST.get("category"),
                status=request.POST.get("status", "พร้อมให้ยืม"),
                asset_no_main=main_no,
                asset_no_sub=sub_no,
                inventory_no=request.POST.get("inventory_no", ""),
                holder_name=request.POST.get("holder_name", ""),
                holder_department=request.POST.get("holder_department", ""),
                total_quantity=total_qty,
                available_quantity=total_qty,
                image=request.FILES.get("image"),
            )
            return redirect("borrow_app:equipment_manage")

        elif action == "edit":
            equipment_id = request.POST.get("equipment_id")
            eq = get_object_or_404(Equipment, id=equipment_id)

            eq.name = request.POST.get("name")
            eq.code = request.POST.get("code")
            eq.category = request.POST.get("category")
            eq.status = request.POST.get("status")
            eq.asset_no_main = request.POST.get("asset_no_main", "")
            eq.asset_no_sub = request.POST.get("asset_no_sub", "")
            eq.inventory_no = request.POST.get("inventory_no", "")
            eq.holder_name = request.POST.get("holder_name", "")
            eq.holder_department = request.POST.get("holder_department", "")

            if request.POST.get("total_quantity"):
                eq.total_quantity = int(request.POST.get("total_quantity"))

            if "image" in request.FILES:
                eq.image = request.FILES["image"]

            eq.save()
            return redirect("borrow_app:equipment_manage")

        elif action == "delete":
            equipment_id = request.POST.get("equipment_id")
            Equipment.objects.filter(id=equipment_id).delete()
            return redirect("borrow_app:equipment_manage")

        elif action == "import_excel":
            excel_file = request.FILES.get("excel_file")
            if excel_file:
                try:
                    df = pd.read_excel(excel_file)
                    df.columns = df.columns.str.strip()

                    for _, row in df.iterrows():
                        main_no = (
                            str(row.get("assetNoMain", "")).strip()
                            if pd.notna(row.get("assetNoMain"))
                            else ""
                        )
                        sub_no = (
                            str(row.get("assetNoSub", "0001")).strip()
                            if pd.notna(row.get("assetNoSub"))
                            else "0001"
                        )

                        code = (
                            f"{main_no}-{sub_no}"
                            if main_no
                            else str(
                                row.get("inventoryNo", row.get("seqNo", ""))
                            ).strip()
                        )
                        if not code:
                            continue

                        qty = (
                            int(row.get("quantity", 1))
                            if pd.notna(row.get("quantity"))
                            else 1
                        )

                        Equipment.objects.update_or_create(
                            code=code,
                            defaults={
                                "name": str(
                                    row.get("assetDescription", "ไม่ระบุชื่อ")
                                ).strip(),
                                "category": str(
                                    row.get("equipmentCategory", "ทั่วไป")
                                ).strip(),
                                "seq_no": (
                                    int(row.get("seqNo"))
                                    if pd.notna(row.get("seqNo"))
                                    else None
                                ),
                                "asset_no_main": main_no,
                                "asset_no_sub": sub_no,
                                "inventory_no": (
                                    str(row.get("inventoryNo", "")).strip()
                                    if pd.notna(row.get("inventoryNo"))
                                    else ""
                                ),
                                "total_quantity": qty,
                                "available_quantity": qty,
                                "holder_code": (
                                    str(row.get("holderCode", "")).strip()
                                    if pd.notna(row.get("holderCode"))
                                    else ""
                                ),
                                "holder_name": (
                                    str(row.get("holderName", "")).strip()
                                    if pd.notna(row.get("holderName"))
                                    else ""
                                ),
                                "holder_dept_code": (
                                    str(row.get("holderDeptCode", "")).strip()
                                    if pd.notna(row.get("holderDeptCode"))
                                    else ""
                                ),
                                "holder_department": (
                                    str(row.get("holderDepartment", "")).strip()
                                    if pd.notna(row.get("holderDepartment"))
                                    else ""
                                ),
                            },
                        )
                    messages.success(request, "นำเข้าข้อมูล SSMS สำเร็จเรียบร้อยแล้ว!")
                except Exception as e:
                    messages.error(request, f"เกิดข้อผิดพลาดในการอ่านไฟล์: {str(e)}")
            return redirect("borrow_app:equipment_manage")

    if selected_status:
        status_filter = selected_status
        if selected_status in ["พร้อมให้ยืม", "พร้อมใช้งาน"]:
            status_filter = "พร้อมให้ยืม"
        equipments = Equipment.objects.filter(status=status_filter).order_by("-id")
    else:
        equipments = Equipment.objects.all().order_by("-id")

    grouped_equipments = None
    selected_group_items = None
    selected_group = None

    # --- เริ่มต้นส่วนที่มีการแก้ไข ---
    try:
        categories, grouped_equipments = fetch_ssms_grouped_equipments(
            query="", category="", status=selected_status
        )
        if group_id and grouped_equipments:
            selected_group = next(
                (g for g in grouped_equipments if g["id"] == group_id), None
            )
            if selected_group:
                # ตรวจสอบและส่ง asset_no_main เพิ่มกรณีเป็น Bundle
                asset_main = (
                    selected_group.get("asset_no_main")
                    if selected_group.get("is_bundle")
                    else None
                )
                selected_group_items = fetch_ssms_group_items(
                    selected_group["account_determ"],
                    selected_group["asset_description"],
                    asset_no_main=asset_main,
                )
                grouped_equipments = [selected_group]
    except Exception:
        grouped_equipments = (
            EquipmentGroup.objects.annotate(
                available_count=Sum(
                    "equipments__available_quantity",
                    filter=Q(equipments__status__in=["พร้อมให้ยืม", "พร้อมใช้งาน"]),
                ),
                total_count=Sum("equipments__total_quantity"),
            )
            .filter(available_count__gt=0)
            .order_by("-available_count", "account_determ", "asset_description")
        )

        if group_id:
            selected_group = EquipmentGroup.objects.filter(id=group_id).first()
            if selected_group:
                # แก้ไขการดึงค่าจาก Model Object (ใช้ dot notation) และส่ง Parameters ให้ถูกต้อง
                selected_group_items = fetch_ssms_group_items(
                    selected_group.account_determ, selected_group.asset_description
                )
    # --- สิ้นสุดส่วนที่มีการแก้ไข ---

    return render(
        request,
        "borrow_app/admin_equipment.html",
        {
            "equipments": equipments,
            "stats": stats,
            "selected_status": selected_status,
            "grouped_equipments": grouped_equipments,
            "selected_group_items": selected_group_items,
            "selected_group": selected_group,
            "group_id": group_id,
        },
    )


def logout_view(request):
    logout(request)
    return redirect("borrow_app:login")


admin_equipment_view = equipment_manage_view


@staff_member_required
def sync_ssms_direct_view(request):
    try:
        with connections["ssms_db"].cursor() as cursor:
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
            for idx, row in enumerate(rows):
                main_no = _clean_asset_no(row[0])
                sub_no = str(row[1]).strip() if row[1] is not None else str(idx + 1)
                name = str(row[2]).strip() if row[2] else "ไม่ระบุชื่อ"
                category = str(row[3]).strip() if row[3] else "ทั่วไป"
                inventory_no = str(row[4]).strip() if row[4] else ""
                quantity = 1

                # 🟢 ป้องกัน code ซ้ำ และรองรับ sub_no ที่เป็นค่าว่าง
                if main_no and sub_no:
                    code = f"{main_no}-{sub_no}"
                elif inventory_no:
                    code = inventory_no
                else:
                    code = f"SSMS-{main_no}-{idx}"

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
                        total_quantity=quantity,
                        available_quantity=quantity,
                        status="พร้อมให้ยืม",
                    )
                    count_created += 1

        messages.success(
            request,
            f"Sync ข้อมูลจาก SSMS สำเร็จ! เพิ่มใหม่ {count_created} รายการ / อัปเดต {count_updated} รายการ",
        )
    except Exception as e:
        messages.error(request, f"ไม่สามารถเชื่อมต่อ SSMS ได้: {str(e)}")

    return redirect("borrow_app:equipment_manage")


def get_bundle_structure(asset_no_main):
    if not asset_no_main or str(asset_no_main).strip() in ["None", ""]:
        return None

    # 🟢 Clean ค่า asset_no_main
    clean_asset_main = _clean_asset_no(str(asset_no_main).split(",")[0])

    try:
        if "ssms_db" in connections:
            with connections["ssms_db"].cursor() as cursor:
                # 🟢 ปรับ SQL เป็น LTRIM(RTRIM(assetNoMain)) = %s
                cursor.execute(
                    """
                    SELECT assetNoMain, assetNoSub, assetDescription, accountDeterm, inventoryNo
                    FROM dbo.asset
                    WHERE LTRIM(RTRIM(assetNoMain)) = %s
                    ORDER BY TRY_CAST(assetNoSub AS INT)
                """,
                    [clean_asset_main],
                )
                rows = cursor.fetchall()

            if rows:
                # Rule 2 Validation: ถ้าชื่อเหมือนกันทั้งหมด ไม่ถือว่าเป็น Bundle
                distinct_names = set(row[2] for row in rows if row[2])
                if len(distinct_names) <= 1:
                    return None

                # ดึงชิ้นที่มี assetNoSub น้อยที่สุดเป็น main_item (บรรทัดแรกหลัง ORDER BY)
                main_row = rows[0]
                sub_no_main = (
                    str(main_row[1]).strip() if main_row[1] is not None else "0"
                )

                main_item = {
                    "code": f"{main_row[0]}-{sub_no_main}",
                    "name": main_row[2] or "ไม่ระบุชื่อ",
                    "category": main_row[3] or "ทั่วไป",
                    "inventory_no": main_row[4] or "-",
                    "sub_no": sub_no_main,
                }

                sub_items = []
                for row in rows[1:]:
                    sub_no = str(row[1]).strip() if row[1] is not None else "0"
                    sub_items.append(
                        {
                            "code": f"{row[0]}-{sub_no}",
                            "name": row[2] or "ไม่ระบุชื่อ",
                            "category": row[3] or "ทั่วไป",
                            "inventory_no": row[4] or "-",
                            "sub_no": sub_no,
                        }
                    )

                return {
                    "main_item": main_item,
                    "sub_items": sub_items,
                    "total_count": len(rows),
                }
    except Exception:
        pass
    return None

    # สลับไปใช้ Django ORM ด้านล่างหากคิวรี SSMS ขัดข้อง
    # 2. Fallback ดึงจาก Django ORM Equipment Model
    items = Equipment.objects.filter(
        Q(code__startswith=f"{clean_asset_main}-")
        | Q(code=clean_asset_main)
        | Q(inventory_no__icontains=clean_asset_main)
    )

    if hasattr(Equipment, "asset_no_main"):
        items = items | Equipment.objects.filter(asset_no_main=clean_asset_main)

    items = items.distinct()

    if not items.exists():
        return None

    main_item = None
    sub_items = []
    for item in items:
        code_str = str(item.code or "")
        sub_no = code_str.split("-")[-1] if "-" in code_str else "0"
        item_data = {
            "code": item.code or f"{clean_asset_main}-{sub_no}",
            "name": item.name or "ไม่ระบุชื่อ",
            "category": item.category or "ทั่วไป",
            "inventory_no": item.inventory_no or "-",
            "sub_no": sub_no,
        }
        if sub_no in ["0", "0000", "0001"] and not main_item:
            main_item = item_data
        else:
            sub_items.append(item_data)

    if not main_item and sub_items:
        main_item = sub_items.pop(0)

    return {
        "main_item": main_item,
        "sub_items": sub_items,
        "total_count": items.count(),
    }


def bundle_detail_api(request, asset_no_main):
    try:
        data = get_bundle_structure(asset_no_main)
        if not data:
            return JsonResponse(
                {"error": f"ไม่พบข้อมูลอุปกรณ์ย่อยสำหรับรหัส {asset_no_main}"},
                status=404,
            )
        return JsonResponse(data)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({"error": f"เซิร์ฟเวอร์ขัดข้อง: {str(e)}"}, status=500)
