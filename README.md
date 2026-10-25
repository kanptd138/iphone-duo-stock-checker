# iPhone Stock Checker (Apple Store TH)

บอทเช็คสต็อก iPhone สำหรับ**รับที่ร้าน Apple Store ในไทย** ทุก 5 นาทีบน GitHub Actions แล้วแจ้งเข้า LINE ทันทีที่มีของ

## สินค้าที่เช็คอยู่

| รุ่น | Part number |
|---|---|
| iPhone Duo 256GB สตาร์ไวท์ | `MK2D4ZP/A` |
| iPhone Duo 256GB ไนท์สกาย | `MK2E4ZP/A` |
| iPhone 18 Pro 256GB ธารน้ำแข็ง | `MJRT4ZP/A` |

รหัสไปรษณีย์ที่ใช้ค้นหาร้าน: `11000` (แก้ได้ใน [`config.json`](config.json))

## ทำงานยังไง

1. GitHub Actions รัน [`check_stock.py`](check_stock.py) ทุก 5 นาที ([workflow](.github/workflows/check-stock.yml))
2. Script เรียก API ตัวเดียวกับที่หน้าเว็บ Apple ใช้แสดงสต็อกหน้าร้าน:
   `https://www.apple.com/th/shop/sba/availability-message?parts.0=<part>&location=<zip>`
   แล้วดูค่า `availableAtAnyStore`
3. ถ้ารุ่นไหนเปลี่ยนจาก "ไม่มีของ" เป็น "มีของ" จะส่งข้อความเข้า LINE หนึ่งครั้ง (ข้อความแยกตามรุ่น) และไม่ส่งซ้ำตราบที่ของยังมีอยู่
4. สถานะล่าสุดของแต่ละรุ่นเก็บไว้ใน [`state.json`](state.json) และบอทจะ commit ไฟล์นี้กลับเข้า repo เฉพาะตอนที่สถานะเปลี่ยน

**ข้อควรรู้**
- เช็คเฉพาะ **"มีของให้รับวันนี้"** เท่านั้น ข้อความบนเว็บแบบ "พร้อมจำหน่าย วันพรุ่งนี้" ยังไม่นับว่ามีของ ระบบจะแจ้งตอนที่ของเข้าร้านจริง
- ไม่ได้เช็คการจัดส่งถึงบ้าน (delivery)
- เวลาที่ GitHub เริ่มรันแต่ละรอบอาจคลาดจาก 5 นาทีไปบ้าง โดยเฉพาะช่วงที่ GitHub คนใช้เยอะ
- Apple ไม่มีเวลา restock ที่ตายตัว จึงต้องเช็คตลอด 24 ชั่วโมง

## ถ้ามีอะไรพัง

ถ้าเช็คกับ Apple ไม่สำเร็จ (เช่น Apple เปลี่ยน API หรือบล็อก) หรือส่ง LINE ไม่ถึง รอบนั้นจะขึ้นว่า **failed** และ GitHub จะส่งอีเมลแจ้งเจ้าของ repo ถ้าแจ้งเตือนส่งไม่ถึง รอบถัดไปจะส่งใหม่ให้เอง

ดูประวัติการทำงานแต่ละรอบได้ที่แท็บ **Actions** หรือกด **Run workflow** เพื่อสั่งเช็คทันที

## เพิ่มรุ่นหรือสีใหม่

1. เปิดหน้าสินค้าบน apple.com/th เลือกรุ่น สี และความจุที่ต้องการ แล้วคัดลอก URL
2. หา part number จาก HTML ของหน้านั้น: ค้นหาบล็อก `"partNumber":"XXXXXZP/A"` ที่มี `"dimensionCapacity"` และ `"dimensionColor"` ตรงกับที่เลือก
3. ทดสอบว่า API ตอบกลับถูกต้อง:
   ```bash
   curl -s "https://www.apple.com/th/shop/sba/availability-message?parts.0=XXXXXZP%2FA&location=11000"
   ```
4. เพิ่มรายการใหม่ใน `products` ของ [`config.json`](config.json):
   ```json
   {
     "part_number": "XXXXXZP/A",
     "label": "ชื่อที่จะโชว์ในข้อความ LINE",
     "country_path": "th",
     "zip_code": "11000",
     "product_page_url": "https://www.apple.com/th/shop/buy-iphone/..."
   }
   ```
5. ก่อน push ให้ `git pull` ก่อนเสมอ เพราะบอทอาจ commit `state.json` เข้ามาแล้ว

## การตั้งค่าการแจ้งเตือน

ห้ามใส่ token หรือรหัสผ่านใน `config.json` เพราะ repo นี้เป็น public ให้เก็บไว้ใน **Settings → Secrets and variables → Actions**

| Secret | ใช้ทำอะไร |
|---|---|
| `LINE_CHANNEL_ACCESS_TOKEN` | Channel access token ของ LINE Messaging API |
| `GMAIL_APP_PASSWORD` | (ไม่บังคับ) Gmail App Password ถ้าเปิดแจ้งเตือนทางอีเมล |

**LINE**: LINE Notify ปิดบริการไปแล้วตั้งแต่มีนาคม 2025 จึงต้องใช้ Messaging API แทน
1. สร้าง LINE Official Account ที่ manager.line.biz แล้วเปิด Messaging API ในหน้า ตั้งค่า → Messaging API
2. ใน LINE Developers Console เข้าแท็บ Messaging API ของ channel แล้วกด Issue เพื่อออก channel access token
3. สแกน QR code เพื่อเพิ่มบอทเป็นเพื่อน (บอทส่งแบบ broadcast ถึงเพื่อนทุกคน จึงไม่ต้องหา user ID)

**อีเมล** (ปิดอยู่): ตั้ง `email.enabled` เป็น `true` และกรอก `from_addr` / `to_addr` ใน `config.json` แล้วเพิ่ม secret `GMAIL_APP_PASSWORD`

## รันบนเครื่องตัวเอง

ใช้แค่ไลบรารีพื้นฐานของ Python 3 ไม่ต้องติดตั้งอะไรเพิ่ม

```bash
LINE_CHANNEL_ACCESS_TOKEN=xxx python3 check_stock.py
```

Repo นี้เป็น public เพื่อให้ใช้ GitHub Actions ได้ไม่จำกัด (repo แบบ private ได้แค่ 2,000 นาทีต่อเดือน ไม่พอสำหรับการเช็คทุก 5 นาที) และ workflow จะทำ commit ว่างให้เองถ้าไม่มี commit เลยครบ 50 วัน เพราะ GitHub จะปิด cron ของ repo ที่ไม่เคลื่อนไหวเกิน 60 วัน
