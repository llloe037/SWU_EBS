# 📁 SWU ERP - Project Structure Documentation

## 🎯 Project Overview

**Project Name**: SWU Equipment Borrowing System (ระบบยืม-คืนอุปกรณ์ มศว)  
**Technology Stack**: Django 6.0.7 + Python + SQLite/MSSQL + Cloudinary + Tailwind CSS  
**Purpose**: Digital equipment borrowing/returning system for Srinakharinwirot University  
**Architecture**: MVC (Model-View-Template) + REST API endpoints

---

## 📂 Root Directory Structure

```
c:\Users\LENOVO\swu_erp\
├── 📁 .git/                           # Git repository
├── 📁 .venv/                          # Python virtual environment
├── 📁 .vscode/                        # VS Code settings
│
├── 📄 .env                            # Environment variables (production)
├── 📄 .env.example                    # Environment template
├── 📄 .gitignore                      # Git ignore rules
├── 📄 requirements.txt                # Python dependencies
├── 📄 manage.py                       # Django management script
├── 📄 db.sqlite3                      # Local SQLite database
├── 📄 SRS.md                          # System Requirement Specification
├── 📄 setup_dev.py                    # Development setup script
│
├── 📁 swu_erp/                        # Django main project folder
├── 📁 borrow_app/                     # Main application logic
├── 📁 templates/                      # HTML templates
├── 📁 media/                          # User uploaded media files
└── 📁 return_evidence/                # Return evidence files (legacy)
```

---

## 🏗️ Main Project Configuration (`swu_erp/`)

```
swu_erp/
├── 📄 __init__.py                     # Python package marker
├── 📄 settings.py                     # Django settings & configuration
├── 📄 urls.py                         # Root URL routing
├── 📄 wsgi.py                         # WSGI application for production
├── 📄 asgi.py                         # ASGI application for async
└── 📁 __pycache__/                    # Python bytecode cache
```

**Key Configuration:**
- Database: SQLite (dev) + MSSQL (production)
- Authentication: Custom User model
- File Storage: Cloudinary for images
- Static Files: Tailwind CSS + Custom styling
- Time Zone: Asia/Bangkok

---

## 🎯 Core Application (`borrow_app/`)

```
borrow_app/
├── 📄 __init__.py                     # App package marker
├── 📄 apps.py                         # App configuration
├── 📄 models.py                       # Database models & business logic
├── 📄 views.py                        # Request handlers & controllers
├── 📄 urls.py                         # App-level URL routing
├── 📄 admin.py                        # Django admin interface
├── 📄 tests.py                        # Unit tests
├── 📄 context_processors.py           # Template context processors
├── 📄 .env                            # App-specific environment variables
│
├── 📁 migrations/                     # Database schema migrations
│   ├── 📄 0001_initial.py             # Initial database schema
│   ├── 📄 0002_equipment.py           # Equipment model creation
│   ├── 📄 0003_borrowitem_equipment_...# Equipment-BorrowItem relation
│   ├── 📄 0004_equipment_image.py     # Image field addition
│   ├── 📄 0005_equipment_acquisition_...# SSMS sync fields
│   ├── 📄 0006_borrowrequest_return_...# Return workflow fields
│   ├── 📄 0007_equipmentgroup_equipment...# Equipment grouping
│   ├── 📄 0008_borrowrequest_approved_...# Approval workflow
│   ├── 📄 0009_alter_borrowrequest_...# DateTime field updates
│   ├── 📄 0010_borrowitem_requested_...# Return status tracking
│   ├── 📄 0011_borrowitem_return_status.py
│   ├── 📄 0011_borrowrequest_return_...# Duplicate migration
│   ├── 📄 0012_borrowitem_received_by_...# Return verification
│   ├── 📄 0013_alter_equipment_status.py
│   ├── 📄 0014_remove_borrowitem_received...# Field cleanup
│   ├── 📄 0015_merge_20260811_1505.py # Migration merge
│   ├── 📄 0016_alter_borrowitem_return...# Status choices update
│   ├── 📄 0017_alter_equipment_status.py
│   ├── 📄 0018_borrowrequest_pickup_...# Pickup evidence
│   ├── 📄 0019_alter_equipment_image_...# Cloudinary integration
│   ├── 📄 0020_alter_borrowrequest_pickup...# Image field updates
│   └── 📄 __init__.py
│
├── 📁 management/                     # Custom Django commands
│   ├── 📄 __init__.py
│   ├── 📁 commands/
│   │   ├── 📄 __init__.py
│   │   └── 📄 import_ssms.py          # SSMS data import command
│   └── 📁 __pycache__/
│
└── 📁 __pycache__/                    # Python bytecode cache
```

### 🗄️ Database Models

**Core Entities:**
- `EquipmentGroup` - Equipment categories/types
- `Equipment` - Individual equipment items with inventory tracking
- `BorrowRequest` - Main borrowing transactions
- `BorrowItem` - Line items within each request
- `Notification` - System notifications & audit trail

---

## 🖼️ Template System (`templates/`)

```
templates/
├── 📄 base.html                       # Base template with common layout
├── 📄 swu_erp - Shortcut.lnk         # Windows shortcut (ignore)
│
└── 📁 borrow_app/                     # App-specific templates
    ├── 📄 home.html                   # Landing page - equipment browse
    ├── 📄 login.html                  # User authentication
    ├── 📄 request-form.html           # Borrow request creation form
    ├── 📄 request-summary.html        # Request review before submit
    ├── 📄 my-requests.html            # User's request history
    ├── 📄 return-form.html            # Return request form
    ├── 📄 history.html                # User's completed transactions
    │
    ├── 📄 admin_dashboard.html        # Admin overview dashboard
    ├── 📄 admin_manage_requests.html  # Request approval interface
    ├── 📄 admin_manual_request.html   # Manual request creation
    ├── 📄 admin_equipment.html        # Equipment management
    └── 📄 admin_all_history.html      # All system transactions
```

### 🎨 UI Framework
- **CSS Framework**: Tailwind CSS
- **Icons**: Heroicons (SVG)
- **Colors**: SWU Red (#9e1b32) + Gray palette
- **Responsive**: Mobile-first design
- **Components**: Cards, forms, tables, modals

---

## 📁 Media Files (`media/`)

```
media/
├── 📁 pickup_evidence/                # Equipment pickup photos
│   └── 📁 2026/08/17/                # Organized by date (YYYY/MM/DD)
│       ├── 📄 Screenshot_2026-08-03_152109.png
│       ├── 📄 Screenshot_2026-08-03_152810.png
│       └── ...
│
└── 📁 return_evidence/                # Equipment return photos
    ├── 📄 Screenshot_2026-08-03_152109.png
    ├── 📄 Screenshot_2026-08-03_152810.png
    └── ... (return evidence files)
```

### 🌤️ Cloud Storage
- **Provider**: Cloudinary
- **Purpose**: Image hosting & transformation
- **Folders**: `equipment_groups/`, `equipments/`, `pickup_evidence/`, `return_evidence/`
- **Auto-optimization**: Yes (compression, format conversion)

---

## 🔧 Dependencies (`requirements.txt`)

```python
# Core Framework
Django==6.0.7                         # Main web framework
asgiref==3.12.1                       # ASGI interface

# Database Connectors
mssql-django==1.7.4                   # MSSQL database adapter
pyodbc==5.3.0                         # ODBC database interface

# Data Processing
pandas==2.3.3                         # Data analysis & CSV handling
numpy==2.5.2                          # Numerical computing
openpyxl==3.1.5                       # Excel file processing
et-xmlfile==2.0.0                     # XML support for Excel

# Image Handling
Pillow==12.0.0                        # Image processing library
cloudinary==1.41.0                    # Cloudinary cloud storage
django-cloudinary-storage==0.3.0      # Django-Cloudinary integration

# Utilities
python-dotenv==1.2.2                  # Environment variable management
python-dateutil==2.9.0.post0          # Advanced date parsing
pytz==2026.3.post1                    # Timezone handling
tzdata==2026.3                        # Timezone database
six==1.17.0                           # Python 2/3 compatibility
sqlparse==0.5.5                       # SQL parsing utilities
```

---

## 🚀 Application Flow

### 📊 User Journey
```
User Login → Browse Equipment → Add to Cart → Fill Request Form 
    ↓
Submit Request → Admin Review → Approve/Reject
    ↓
Equipment Pickup → Usage Period → Return Request
    ↓
Admin Verification → Equipment Condition Check → Complete Return
```

### 🔗 URL Routing
```
/ (home)                              # Equipment browsing & search
/login/                               # Authentication
/request/                             # Request creation form
/request/summary/                     # Request review
/request/confirm/                     # Final submission
/my-requests/                         # User's active requests
/return-request/<id>/                 # Return form
/admin-console/dashboard/             # Admin overview
/admin-console/requests/              # Request management
/admin-console/equipment/             # Inventory management
```

### 🗃️ Data Workflow
```
SSMS (Central DB) ──sync──► Equipment (Local)
                               ↓
User Selection ──cart──► BorrowRequest + BorrowItems
                               ↓
Admin Approval ──deduct──► Equipment.available_quantity
                               ↓
Return Process ──verify──► Equipment.status + quantity restore
```

---

## 🔐 Security & Integration

### 🔑 Authentication
- **Method**: Django's built-in User model
- **Future**: SSO integration with Buasri ID
- **Permissions**: User vs Admin vs Staff roles

### 🌐 External Systems
- **SSMS Integration**: Equipment data sync via custom Django command
- **Central Database**: Read-only connection for user & asset data
- **File Storage**: Cloudinary CDN for scalable media hosting

### 🛡️ Data Protection
- **Environment Variables**: Sensitive data in `.env`
- **File Uploads**: Image validation & secure storage
- **Database**: Transaction-safe operations with atomic updates

---

## 🔄 Development Workflow

### 📝 Management Commands
```bash
# Database migrations
python manage.py makemigrations
python manage.py migrate

# SSMS data import
python manage.py import_ssms

# Development server
python manage.py runserver

# Create admin user
python manage.py createsuperuser
```

### 🧪 Testing
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test borrow_app

# Test coverage (if configured)
python manage.py test --with-coverage
```

---

## 📈 Key Features

### ✅ Implemented
- **Equipment Browsing**: Search, filter, pagination
- **Request Management**: Cart system, approval workflow
- **Return Process**: Photo evidence, condition tracking
- **Admin Dashboard**: Request review, inventory management
- **Notification System**: Status updates, audit trail
- **Image Upload**: Cloudinary integration
- **Responsive Design**: Mobile-friendly UI

### 🔄 Data Models
- **Equipment Tracking**: Real-time quantity management
- **Status Workflow**: Complete borrowing lifecycle
- **Audit Trail**: All actions logged with timestamps
- **User Management**: Role-based permissions

### 🎯 Business Logic
- **Atomic Operations**: Prevent inventory conflicts
- **Status Transitions**: Comprehensive state machine
- **Evidence Collection**: Photo documentation
- **Flexible Returns**: Partial/damaged item handling

---

## 📚 Documentation Files

- **`SRS.md`**: System Requirements Specification
- **`PROJECT_STRUCTURE.md`**: This document
- **Migration Files**: Database schema evolution history
- **Admin Interface**: Built-in Django admin for data management

---

## 🎯 Summary for AI Context

This is a **Django-based Equipment Borrowing Management System** with:

1. **📱 Frontend**: HTML templates with Tailwind CSS
2. **🔧 Backend**: Django MVT architecture with SQLite/MSSQL
3. **🗄️ Data**: 5 main models (Equipment, BorrowRequest, etc.)
4. **🖼️ Media**: Cloudinary integration for photo evidence
5. **👥 Users**: Student borrowers + Admin staff workflow
6. **🔄 Process**: Complete borrow-return lifecycle with approval
7. **📊 Integration**: SSMS sync for central equipment database

The system handles the full workflow from equipment selection → approval → pickup → return → verification with photo documentation and real-time inventory tracking.

---

**Generated**: August 20, 2026  
**Version**: 1.0  
**Author**: AI Assistant