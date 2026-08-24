# School Room Status

ระบบจองห้องเรียน Flask + SQLite เวอร์ชันปรับปรุง

## สิ่งที่เพิ่ม
- จองได้เฉพาะวันปัจจุบัน และคิวเริ่มใหม่อัตโนมัติเมื่อเปลี่ยนวัน
- เก็บประวัติย้อนหลังใน SQLite โดยไม่ลบข้อมูลเก่า
- ยกเลิกได้เฉพาะเจ้าของการจองจาก session เดียวกัน
- การยกเลิกเป็น soft cancel (`status=cancelled`) ไม่ DELETE ข้อมูล
- CSRF protection และตรวจสอบห้อง/เวลา/ข้อมูลก่อนบันทึก
- ป้องกันการจองห้องเดียวกันซ้ำในวันเดียวกันด้วย unique database index
- ใช้เวลา `Asia/Bangkok`
- UI ใหม่ Responsive ธีมขาว ไม่มี Bootstrap, Font Awesome หรือ CDN
- SVG icons อยู่ในโปรเจกต์ทั้งหมด

## Database
ระบบสร้าง `data/database.db` อัตโนมัติเมื่อเปิดครั้งแรก และรองรับ migration จากตาราง `booking` เวอร์ชันเดิม

ถ้าต้องการเก็บ DB ไว้ตำแหน่งอื่น ให้กำหนด environment variable:

```text
DATABASE_PATH=/path/to/database.db
```

ตั้ง `SECRET_KEY` บน production ได้จาก environment variable เช่นกัน ถ้าไม่ได้ตั้ง ระบบจะสร้าง `data/.secret_key` ให้อัตโนมัติ

## Run

```bash
pip install -r requirements.txt
python app.py
```


## การคืนสถานะห้องอัตโนมัติ
- เมื่อถึง `end_time` รายการ active จะเปลี่ยนเป็น `completed` อัตโนมัติ
- ห้องกลับเป็นว่างและจองรอบถัดไปในวันเดียวกันได้
- รายการเดิมยังอยู่ในฐานข้อมูลและแสดงในประวัติย้อนหลัง
- หน้าสถานะห้องและหน้ารายการจองจะรีเฟรชตรงเวลาสิ้นสุดโดยอัตโนมัติ


## Render expiry fix
- การหมดเวลาใช้ Python datetime จริง ไม่ใช้การเทียบข้อความ HH:MM ใน SQL
- รองรับข้อมูลเก่าที่เวลาเป็น `8:30`, `08:30`, หรือ `08:30:00`
- `/api/live-bookings` และ `/api/server-time` ปิด cache
- หน้าเว็บตรวจสถานะสดทุก 3 วินาที พร้อม cache-buster
- เปิด `/api/server-time` เพื่อตรวจว่า Render มองเวลาไทย UTC+7 ถูกต้อง
