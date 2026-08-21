# CONTEXT.md — SWU Equipment Borrowing System (ระบบยืม-คืนครุภัณฑ์ มศว)

> อัปเดตล่าสุด: 21 สิงหาคม 2569 (2026)  
> Branch ปัจจุบัน: `fix/re-design`

---

## 1. ภาพรวมโปรเจกต์

ระบบดิจิทัลสำหรับยืม-คืนครุภัณฑ์ของมหาวิทยาลัยศรีนครินทรวิโรฒ (มศว) แทนที่ระบบเอกสารกระดาษเดิม ระบบเชื่อมต่อกับฐานข้อมูลครุภัณฑ์กลาง (SQL Server / SSMS) แบบ Read-Only และบันทึกธุรกรรมยืม-คืนในฐานข้อมูลท้องถิ่น (SQLite)

---

## 2. ความคืบหน้าที่ทำเสร็จแล้ว ✅

### 2.1 UI / Frontend
- **Redesign หน้า Admin ทั้งหมด** — Dashboard, Manage Requests, Equipment, Manual Request ใช้ Tailwind CSS + สีธีม SWU (`swu-red: #DA2128`)
- **Sidebar + Navbar** — Collapsible sidebar พร้อม role-based menu (Admin vs User), Notification badge แสดงจำนวนที่ยังไม่อ่าน
- **Cart Flow** — หน้า Home → Cart → Request Form → Summary → Confirm

### 2.2 Core Features
- **วงจรคำร้องครบถ้วน**: สร้างคำร้อง → อนุมัติ/ปฏิเสธ → ส่งมอบ → คืน → ตรวจรับ
- **ระบบ Bundle**: ตรวจจับและแสดงครุภัณฑ์ที่เป็นชุดจาก SSMS โดยอัตโนมัติ
- **Per-Item Return Tracking**: ผู้ใช้คืนได้ทีละชิ้น, Admin ตรวจสภาพแต่ละชิ้น (ปกติ/ชำรุด/สูญหาย)
- **Overdue Detection**: `refresh_status()` ตรวจสอบวันเกินกำหนดอัตโนมัติ และเพิ่ม section "เกินกำหนด" ใน Admin
- **Admin Manual Request**: Admin สร้างคำร้องแทน User ได้ (กรณีฉุกเฉิน) Status ข้ามไปเป็น `อนุมัติ` ทันที
- **Notification System**: ระบบแจ้งเตือน In-App เมื่ออนุมัติ/ปฏิเสธ/คืนสำเร็จ

### 2.3 Cloudinary Integration
- **Organize Cloudinary folder paths** — จัดระเบียบ path ทั้งหมดให้อยู่ใต้ `swu_erp/`
- รูปภาพอุปกรณ์ใน Home page ดึงมาจาก `dbo.asset_image` ใน SSMS
- Upload รูปหลักฐานรับ/คืนผ่าน Cloudinary โดยตรง

### 2.4 Bug Fixes
- **Fix req number format** (HEAD) — รูปแบบเลขคำร้องถูกต้อง `69/0001`
- **Fix Bundle grouping ใน Admin Manual Request** — grouping items ถูกต้อง
- **Fix image type validation** — ตรวจสอบนามสกุลไฟล์รูป (jpg/jpeg/png/webp/heic) ก่อน Upload, Wrap ด้วย `@transaction.atomic` และ `try-except cloudinary.exceptions.Error`
- **Fix start date error ใน request form** — แก้ bug วันที่เริ่มต้นใน Request Form
- **Fix qty bug on cancel button** — แก้ bug จำนวนเมื่อกด Cancel
- **Fix users retry incomplete returns** — ผู้ใช้ที่ติดค้างสถานะ "คืนไม่ครบ" สามารถกลับมาส่งคืนซ้ำได้

### 2.5 Database / Backend
- **SSMS Sync**: Live sync (`sync_ssms_direct_view`) และ Full sync (`import_ssms` management command)
- **Equipment Import** ผ่าน Excel (pandas/openpyxl) หรือ Live Sync จาก SSMS — ไม่มี CRUD จากหน้าเว็บ Admin จัดการได้เฉพาะเปลี่ยนสถานะอุปกรณ์เท่านั้น
- **Atomic Approval**: `BorrowRequest.approve()` ตัด `available_quantity` แบบ atomic ป้องกัน race condition

---

## 3. ข้อตกลง / Logic พิเศษที่ต้องจำ ⚠️

### 3.1 รูปแบบเลขคำร้อง
```
รูปแบบ: YY/NNNN  (พ.ศ. 2 หลักสุดท้าย / ลำดับ 4 หลัก)
ตัวอย่าง: 69/0001, 69/0042, 70/0001
```
- `YY` = 2 หลักสุดท้ายของปี พ.ศ. (ปี ค.ศ. + 543) เช่น 2026 → 2569 → "69"
- `NNNN` = นับจำนวน BorrowRequest ที่ขึ้นต้นด้วย `"YY/"` แล้ว +1 (reset เป็น 0001 ทุกปีอัตโนมัติ)
- Logic อยู่ทั้งใน `confirm_request_view` และ `admin_manual_request_view`

### 3.2 Bundle Detection Logic (จาก SSMS)
1. Query `dbo.asset` แล้วกลุ่มตาม `assetNoMain`
2. ถ้าทุก row ใน `assetNoMain` เดียวกันมี `assetDescription` **เหมือนกัน** → **Single** (หลายชิ้น)
3. ถ้า `assetDescription` **ต่างกัน** → **Bundle** (แสดงเป็น "{ชื่อหลัก} (ชุด)")
4. row ที่ไม่มี `assetNoMain` → Single เสมอ
5. Bundle พร้อมยืมได้ต่อเมื่อ **ทุกชิ้นย่อย** ว่างอยู่ (ถ้าชิ้นใดชิ้นหนึ่งถูกยืม → ทั้งชุด `available_count = 0`)

### 3.3 Cloudinary Folder Paths
| ประเภทรูป | Folder Path |
|---|---|
| รูปอุปกรณ์ (Equipment) | `swu_erp/equipments` |
| รูปหมวดหมู่ (EquipmentGroup) | `swu_erp/equipment_groups` |
| รูปหลักฐานรับอุปกรณ์ (ก่อนยืม) | `swu_erp/pickup_evidence` |
| รูปหลักฐานคืนอุปกรณ์ | `swu_erp/return_evidence` |

> รูปในหน้า Home Catalogue ดึงมาจาก SSMS table `dbo.asset_image` โดยตรง (ไม่ใช่ CloudinaryField บน model)

### 3.4 Status Workflow
**BorrowRequest:**
```
รอการอนุมัติ → อนุมัติ / ไม่อนุมัติ / ยกเลิก
อนุมัติ / เกินกำหนด → รอตรวจสอบการคืน
รอตรวจสอบการคืน → คืนสำเร็จ / คืนไม่ครบ
คืนไม่ครบ → รอตรวจสอบการคืน (retry) / คืนสำเร็จ
```

**BorrowItem (Per-item):**
```
ยังไม่คืน → รอตรวจรับ → คืนแล้ว / ชำรุด / สูญหาย
```

**Equipment:**
```
พร้อมให้ยืม ↔ กำลังถูกยืม (toggle ตอน approve/complete return — ระบบจัดการอัตโนมัติ)
พร้อมให้ยืม → อยู่ระหว่างซ่อม / ชำรุด / สูญหาย (Admin เปลี่ยนสถานะ via change_status, available_quantity = 0)
ชำรุด / สูญหาย / อยู่ระหว่างซ่อม → พร้อมให้ยืม (Admin เปลี่ยนสถานะ via change_status, available_quantity restore = total_quantity)
หมายเหตุ: "กำลังถูกยืม" Admin เปลี่ยนไม่ได้ — ระบบจัดการอัตโนมัติเท่านั้น
```

### 3.5 Dual Database Architecture
- **`default` (SQLite)**: ข้อมูลธุรกรรมทั้งหมด — Users, BorrowRequest, BorrowItem, Equipment (local copy), Notification
- **`ssms_db` (SQL Server / mssql-django)**: ฐานข้อมูลกลางของมหาวิทยาลัย — Read-Only, ตาราง `dbo.asset` (ข้อมูลครุภัณฑ์) + `dbo.asset_image` (รูปภาพ)
- ไม่มี Django DB Router — ใช้ `connections["ssms_db"].cursor()` (raw SQL) เท่านั้น

### 3.6 Atomic Approval
`BorrowRequest.approve()` ทำงานแบบ `transaction.atomic`:
1. Select-for-update ทุก BorrowItem + Equipment ที่เกี่ยวข้อง
2. ตรวจสอบ `available_quantity` **ทั้งหมดก่อน** (ไม่ตัดระหว่างทาง)
3. ตัด quantity ครั้งเดียวต่อ equipment (รวม qty จาก items ทุก row ก่อน)

### 3.7 Image Validation (Return)
ตรวจสอบนามสกุลไฟล์ก่อน Upload: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`  
Wrap ด้วย `@transaction.atomic` + `try-except cloudinary.exceptions.Error` เพื่อ rollback DB ถ้า Cloudinary ล้มเหลว

### 3.8 `_clean_asset_no()` Helper
SSMS ส่งค่า `assetNoMain` เป็น float บางครั้ง (เช่น `"12345.0"`) ต้องตัด `.0` ออกก่อนใช้ในทุก SQL query

---

## 4. Tech Stack & Libraries

### Backend
| Package | Version | หน้าที่ |
|---|---|---|
| Django | 6.0.7 | Web Framework |
| mssql-django | 1.7.4 | SQL Server Backend |
| pyodbc | 5.3.0 | ODBC Driver สำหรับ SSMS |
| cloudinary | 1.41.0 | Cloudinary SDK |
| django-cloudinary-storage | 0.3.0 | Django Storage Backend |
| pandas | 2.3.3 | Excel Import |
| openpyxl | 3.1.5 | อ่านไฟล์ Excel |
| pillow | 12.0.0 | Image Processing |
| python-dotenv | 1.2.2 | โหลด .env |

### Frontend (CDN — ไม่มี Build Step)
| Library | หน้าที่ |
|---|---|
| Tailwind CSS | Utility-first CSS Framework |
| Lucide Icons | Icon Set |
| Chart.js | กราฟใน Admin Dashboard |
| Google Fonts (Prompt) | ฟอนต์ภาษาไทย |

### Database
| DB | Engine | ใช้ทำอะไร |
|---|---|---|
| `db.sqlite3` | SQLite | Main App DB (transactions) |
| `SWU_EBS` (10.1.21.151) | SQL Server | ฐานข้อมูลครุภัณฑ์กลาง (Read-Only) |

### SWU Brand Colors (Tailwind Config)
```js
'swu-red': '#DA2128'
'swu-red-dark': '#B81920'
'swu-gray': '#63666A'
```

---

## 5. โครงสร้างโปรเจกต์

```
swu_erp/
├── swu_erp/               ← Project package (settings.py, urls.py)
├── borrow_app/            ← Main App
│   ├── models.py          ← EquipmentGroup, Equipment, BorrowRequest, BorrowItem, Notification
│   ├── views.py           ← Views ทั้งหมด 20+ + helpers (SSMS, Bundle, Cart)
│   ├── urls.py            ← 22 URL patterns
│   ├── admin.py           ← Django Admin registration
│   ├── context_processors.py  ← inject unread_notifications ทุก template
│   └── management/commands/import_ssms.py  ← Full SSMS sync CLI
├── templates/
│   ├── base.html          ← Layout หลัก (sidebar, navbar, messages)
│   └── borrow_app/        ← 12 page templates
├── media/                 ← Local fallback (Cloudinary คือ primary)
├── SRS.md                 ← System Requirements Specification
├── .env                   ← Credentials (ไม่ commit)
└── db.sqlite3             ← Local Database
```

---

## 6. URL Map (สำคัญ)

| URL | View | หมายเหตุ |
|---|---|---|
| `/` | `home_view` | Catalogue; Admin → redirect dashboard |
| `/request/` | `request_form_view` | กรอกวัน/วัตถุประสงค์ |
| `/request/summary/` | `request_summary_view` | Preview ก่อน submit |
| `/request/confirm/` | `confirm_request_view` | สร้าง BorrowRequest จริง |
| `/my-requests/` | `my_requests_view` | คำร้อง Active ของ User |
| `/history/` | `history_view` | ประวัติที่เสร็จสิ้น |
| `/return-request/<id>/` | `return_request_view` | User ส่งคืน |
| `/cancel-request/<id>/` | `cancel_request_view` | ยกเลิก (เฉพาะ รอการอนุมัติ) |
| `/admin-console/dashboard/` | `admin_dashboard_view` | Stats + Charts |
| `/admin-console/requests/` | `admin_manage_requests_view` | อนุมัติ/ปฏิเสธ/ตรวจรับคืน |
| `/admin-console/manual-request/` | `admin_manual_request_view` | Admin สร้างคำร้องแทน User |
| `/admin-console/equipment/` | `equipment_manage_view` | CRUD + Excel import |
| `/admin-console/history/` | `admin_all_history_view` | ประวัติทั้งหมด |
| `/equipment/sync-ssms/` | `sync_ssms_direct_view` | Live sync จาก SSMS |
| `/api/bundle/<asset_no_main>/` | `bundle_detail_api` | JSON API ข้อมูล Bundle |

---

## 7. งานที่ต้องทำต่อ (Backlog) 📋

### ลำดับความสำคัญสูง
- [ ] **SSO / Buasri ID Authentication** — SRS กำหนดให้ Login ผ่าน Buasri ID (OAuth/SSO) ปัจจุบันยังใช้ Django `AuthenticationForm` (username/password ธรรมดา)
- [ ] **Export รายงาน Excel / PDF** — SRS ต้องการ Export รายงานยืม-คืน และรายงานครุภัณฑ์ชำรุด/ตัดจำหน่าย ยังไม่มี view ใดรองรับ
- [ ] **Email / LINE Notify Notifications** — SRS กำหนดส่งแจ้งเตือนผ่าน Email และ LINE ปัจจุบันมีแค่ In-App Notification

### ลำดับความสำคัญกลาง
- [ ] **Pre-return Reminder (แจ้งเตือนก่อนครบกำหนด 1 วัน)** — ยังไม่มี cron job / scheduled task
- [ ] **Audit Log** — SRS ต้องการ Immutable Audit Trail ระบุผู้กระทำ + Timestamp ยังไม่มี AuditLog model
- [ ] **Terms & Conditions Acceptance** — SRS กำหนดให้ User กดยอมรับก่อน Submit ยังไม่มี checkbox + field บน model
- [ ] **Admin: ส่งเมล์ทวงถาม Overdue** — SRS ต้องการปุ่ม "ส่งเมล์ทวง" ใน Admin ยังไม่มี

### ลำดับความสำคัญต่ำ / เทคนิค
- [ ] **SSMS Sync จำนวน (`available_quantity`)** — ปัจจุบัน sync จงใจข้ามการ overwrite `available_quantity` เพื่อรักษาสถานะยืม แต่ถ้า SSMS แก้ไขจำนวนจริง จะไม่ sync มา ต้องคิด logic จัดการ
- [ ] **`dbo.asset_image` table** — `fetch_ssms_asset_images()` จะ swallow error ถ้า table ยังไม่มีใน SSMS ต้องตรวจสอบว่า table พร้อม
- [ ] **Executive Dashboard Stats** — SRS ต้องการสถิติเพิ่มเติม: อัตราค้างส่ง, รายการชำรุดบ่อย ยังไม่ครบ
- [ ] **SQLite → PostgreSQL/SQL Server Migration** — สำหรับ Production จริงควรเปลี่ยน default DB

---

## 8. Environment Variables ที่ต้องตั้งค่า

```bash
# .env
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# Cloudinary
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...

# SQL Server (SSMS)
SSMS_DB_NAME=SWU_EBS
SSMS_DB_USER=...
SSMS_DB_PASSWORD=...
SSMS_DB_HOST=10.1.21.151
SSMS_DB_PORT=
```

---

## 9. หมายเหตุสำคัญ

- `available_quantity` บน Equipment model **ต้องถูกเสมอ** — ทุกการ approve/return ต้องผ่าน method บน model ห้าม update ตรง
- SSMS connection อาจ timeout ได้ — views ทุกตัวที่ใช้ SSMS ต้องมี try-except fallback ไปดึงข้อมูลจาก local DB
- ระวัง `assetNoMain` จาก SSMS มาเป็น float string เช่น `"12345.0"` — ต้องผ่าน `_clean_asset_no()` เสมอ
- Tailwind CSS ใช้แบบ CDN (ไม่มี build step) — ถ้าต้องการ custom config ต้องเพิ่ม `<script>` block ใน base.html
- ถ้าแก้ไขหรือทำอะไรไปแล้วให้อัพเดทข้อมูลในไฟล์นี้ด้วย
