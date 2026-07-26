import os
import json
import st
import requests
import threading
import time
import re
import streamlit as st
from datetime import datetime, timedelta
from google.oauth2 import service_account
import google.auth.transport.requests

# ==========================================
# 0. 系統核心設定與跨平台路徑相容（Windows D槽 / 雲端 Linux 通用）
# ==========================================
# 🚨【LINE 通知總開關】：
# 測試階段請保持 False（關閉通知，測試不耗費額度）
# 正式營運請改成 True（開啟通知，自動推播 LINE 給笑長）
ENABLE_LINE_NOTIFY = False  

LINE_ACCESS_TOKEN = "1dMN8FEd8exukAB6SgrBrUhJHv3YmIBg8pLjfEcoKI8RNFdDN5AvbKHPZQRtq4bcrSGVetzcxIu46h8cehoqGbpUroacvuFJiNnL0l0Ly5iXQ+kUUVezT++Vl7rCDdxzN91VWqxfQqbDnkiy5R4udgdB04t89/1O/w1cDnyilFU="
BOSS_USER_ID = "Uf87ce7cf80152b10026141791c07432f"

# 💡 智慧相容：判斷電腦是否有 D 槽目錄，若在雲端主機上則自動使用相對路徑
BASE_DIR = "d:/心境整理室" if os.path.exists("d:/心境整理室") else "."

CACHE_PATH = os.path.normpath(os.path.join(BASE_DIR, "網頁客戶快取.json"))
BOOKING_DB_PATH = os.path.normpath(os.path.join(BASE_DIR, "已預約時段.json"))
PREORDER_TEMP_PATH = os.path.normpath(os.path.join(BASE_DIR, "預約收款暫存.json"))
UPLOAD_DIR = os.path.normpath(os.path.join(BASE_DIR, "付款截圖"))
CLIENT_FILES_DIR = os.path.normpath(os.path.join(BASE_DIR, "05_客戶檔案")) 

# 🔐 笑長後台登入密碼
ADMIN_PASSWORD = "05210809"

# 確保所有本地與雲端儲存資料夾皆存在
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(CLIENT_FILES_DIR, exist_ok=True)
except Exception:
    pass

# 網頁初始設定
st.set_page_config(page_title="心境整理室 - 線上預約系統", page_icon="🌱", layout="centered")

# ==========================================
# ☁️ Google 雲端硬碟自動上傳與刪除核心函式 (雙通道智慧備援版)
# ==========================================
def upload_to_google_drive(file_bytes, filename, mime_type):
    """雙通道 Google 雲端硬碟自動上傳 (GAS 小幫手 + GCP Service Account)"""
    err_messages = []
    
    # 管道 1：優先嘗試 Google Apps Script (GAS) 雲端接收小幫手
    if "gas_url" in st.secrets and str(st.secrets["gas_url"]).strip() and "http" in str(st.secrets["gas_url"]):
        try:
            gas_url = str(st.secrets["gas_url"]).strip()
            import base64
            base64_data = base64.b64encode(file_bytes).decode('utf-8')
            payload = {
                "filename": filename,
                "mime_type": mime_type if mime_type else "image/jpeg",
                "file_base64": base64_data
            }
            res = requests.post(gas_url, json=payload, timeout=25)
            if res.status_code == 200:
                res_json = res.json()
                if res_json.get("status") == "success":
                    return True, f"✅ 成功透過 GAS 小幫手寫入 Google 雲端硬碟 (檔案 ID: {res_json.get('file_id')})", res_json.get('file_id')
                else:
                    err_messages.append(f"GAS 小幫手回報錯誤: {res_json.get('message')}")
            else:
                err_messages.append(f"GAS 小幫手連線失敗 (HTTP 代碼 {res.status_code})")
        except Exception as e:
            err_messages.append(f"GAS 傳送例外: {str(e)}")

    # 管道 2：若 GAS 未設定或失敗，嘗試 GCP Service Account 機器人 API
    if "gcp_service_account" in st.secrets and "drive_folder_id" in st.secrets:
        try:
            service_account_info = dict(st.secrets["gcp_service_account"])
            if "private_key" in service_account_info:
                pk = str(service_account_info["private_key"]).replace("\\n", "\n")
                service_account_info["private_key"] = pk
                
            folder_id = st.secrets["drive_folder_id"]
            scopes = ['https://www.googleapis.com/auth/drive']
            
            creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            access_token = creds.token
            
            upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            
            metadata = {
                "name": filename,
                "parents": [folder_id]
            }
            
            import uuid
            boundary = 'foo_bar_baz_' + uuid.uuid4().hex
            
            body = (
                f'--{boundary}\r\n'
                f'Content-Type: application/json; charset=UTF-8\r\n\r\n'
                f'{json.dumps(metadata)}\r\n'
                f'--{boundary}\r\n'
                f'Content-Type: {mime_type if mime_type else "image/jpeg"}\r\n\r\n'
            ).encode('utf-8') + file_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}"
            }
            
            response = requests.post(upload_url, headers=headers, data=body, timeout=25)
            if response.status_code == 200:
                res_json = response.json()
                file_id = res_json.get('id')
                return True, f"✅ 成功透過 GCP 機器人寫入 Google 雲端硬碟 (檔案 ID: {file_id})", file_id
            else:
                err_messages.append(f"GCP 拒絕寫入 (代碼 {response.status_code}): {response.text}")

        except Exception as e:
            err_messages.append(f"GCP API 連線異常: {str(e)}")

    if not err_messages:
        return False, "❌ 未設定任何雲端上傳金鑰 (請檢查 Secrets 的 gas_url 或 gcp_service_account)", None
    else:
        return False, "❌ 雲端寫入失敗，原因如下：\n" + "\n".join(err_messages), None

def delete_google_drive_file(file_id):
    """刪除 Google 雲端硬碟上的指定圖片檔案"""
    if not file_id:
        return False, "無雲端檔案 ID，跳過雲端刪除。"
        
    if "gcp_service_account" in st.secrets:
        try:
            service_account_info = dict(st.secrets["gcp_service_account"])
            if "private_key" in service_account_info:
                pk = str(service_account_info["private_key"]).replace("\\n", "\n")
                service_account_info["private_key"] = pk
                
            scopes = ['https://www.googleapis.com/auth/drive']
            creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)
            access_token = creds.token
            
            delete_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            response = requests.delete(delete_url, headers=headers, timeout=15)
            if response.status_code in [200, 204]:
                return True, f"✅ 已成功從 Google 雲端硬碟刪除照片 (ID: {file_id})"
            else:
                return False, f"⚠️ 雲端刪除回應代碼 {response.status_code}"
        except Exception as e:
            return False, f"⚠️ 雲端刪除例外：{str(e)}"
            
    return False, "未設定 GCP 金鑰，無法從雲端自動刪除。"

def generate_obsidian_customer_note(booking_info):
    """預約完成時，自動建立或更新 Obsidian 05_客戶檔案/ 下的 .md 客戶主檔"""
    try:
        os.makedirs(CLIENT_FILES_DIR, exist_ok=True)
        customer_name = booking_info.get("name", "未具名")
        
        max_id = 0
        existing_filename = None
        for fn in os.listdir(CLIENT_FILES_DIR):
            if customer_name in fn and fn.endswith(".md"):
                existing_filename = fn
                break
            m = re.search(r'C(\d{4})', fn)
            if m:
                num = int(m.group(1))
                if num > max_id: max_id = num
                
        if existing_filename:
            full_md_path = os.path.join(CLIENT_FILES_DIR, existing_filename)
        else:
            new_id = f"C{max_id + 1:04d}"
            full_md_path = os.path.join(CLIENT_FILES_DIR, f"[{new_id}] {customer_name}.md")
            meta_header = (
                "---\n"
                f"ID: {new_id}\n"
                f"真實姓名: {booking_info.get('real_name', '')}\n"
                f"稱呼方式: {customer_name}\n"
                f"性別: {booking_info.get('gender', '')}\n"
                f"年齡: {booking_info.get('age', '')}\n"
                f"居住地: {booking_info.get('city', '')}{booking_info.get('district', '')}\n"
                f"手機: {booking_info.get('phone', '')}\n"
                f"Line ID: {booking_info.get('line_id', '')}\n"
                f"檔案建立日期: {datetime.now().strftime('%Y-%m-%d')}\n"
                "---\n\n"
                f"# 👤 客戶全紀錄主檔：{customer_name}\n\n"
                f"⚠️ 注意：本檔案已連線自動化系統，歷次談話與預約紀錄將會依時間軸自動追加於下方。\n"
            )
            with open(full_md_path, "w", encoding="utf-8") as f:
                f.write(meta_header)
                
        record_entry = (
            f"\n\n---\n\n"
            f"## 📅 線上預約登記時間：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"- 🗓️ **預約服務時段**：{booking_info.get('date')} {booking_info.get('start')} ~ {booking_info.get('end')}\n"
            f"- 💬 **服務陪伴方式**：{booking_info.get('service_type')}\n"
            f"- 💰 **預約付款金額**：NT$ {booking_info.get('fee')} 元\n"
            f"- 🖼️ **轉帳截圖檔名**：{booking_info.get('filename')} (雲端 ID: {booking_info.get('drive_file_id', '無')})\n"
        )
        with open(full_md_path, "a", encoding="utf-8") as f:
            f.write(record_entry)
        return True
    except Exception as e:
        print("Obsidian 筆記寫入提醒:", e)
        return False

# 台灣行政區完整資料
TAIWAN_CITIES = {
    "台北市": ["中正區", "大同區", "中山區", "松山區", "大安區", "萬華區", "信義區", "士林區", "北投區", "內湖區", "南港區", "文山區"],
    "新北市": ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "樹林區", "鶯歌區", "三峽區", "淡水區", "汐止區", "瑞芳區", "土城區", "蘆洲區", "五股區", "泰山區", "林口區", "深坑區", "石碇區", "坪林區", "三芝區", "石門區", "八里區", "平溪區", "雙溪區", "貢寮區", "金山區", "萬里區", "烏來區"],
    "桃園市": ["桃園區", "中壢區", "大溪區", "楊梅區", "蘆竹區", "大園區", "龜山區", "八德區", "龍潭區", "平鎮區", "新屋區", "觀音區", "復興區"],
    "台中市": ["中區", "東區", "南區", "西區", "北區", "北屯區", "西屯區", "南屯區", "太平區", "大里區", "霧峰區", "烏日區", "豐原區", "後里區", "石岡區", "東勢區", "和平區", "新社區", "潭子區", "大雅區", "神岡區", "大肚區", "沙鹿區", "龍井區", "梧棲區", "清水區", "大甲區", "外埔區", "大安區"],
    "台南市": ["中西區", "東區", "南區", "北區", "安平區", "安南區", "永康區", "歸仁區", "新化區", "左鎮區", "玉井區", "楠西區", "南化區", "仁德區", "關廟區", "龍崎區", "官田區", "麻豆區", "佳里區", "西港區", "七股區", "將軍區", "學甲區", "北門區", "新營區", "後壁區", "白河區", "東山區", "六甲區", "下營區", "柳營區", "鹽水區", "善化區", "大內區", "山上區", "新市區", "安定區"],
    "高雄市": ["新興區", "前金區", "苓雅區", "鹽埕區", "鼓山區", "旗津區", "前鎮區", "三民區", "楠梓區", "小港區", "左營區", "仁武區", "大社區", "岡山區", "路竹區", "阿蓮區", "田寮區", "燕巢區", "橋頭區", "梓官區", "彌陀區", "永安區", "湖內區", "鳳山區", "大寮區", "林園區", "鳥松區", "大樹區", "旗山區", "美濃區", "六龜區", "內門區", "杉林區", "甲仙區", "桃源區", "茂林區", "茄萣區"],
    "基隆市": ["仁愛區", "信義區", "中正區", "中山區", "安樂區", "暖暖區", "七堵區"],
    "新竹市": ["東區", "北區", "香山區"],
    "新竹縣": ["竹北市", "竹東鎮", "新埔鎮", "關西鎮", "湖口鄉", "新豐鄉", "芎林鄉", "橫山鄉", "北埔鄉", "寶山鄉", "峨眉鄉", "尖石鄉", "五峰鄉"],
    "苗栗縣": ["苗栗市", "頭份市", "竹南鎮", "後龍鎮", "通霄鎮", "苑裡鎮", "頭屋鄉", "公館鄉", "銅鑼鄉", "三義鄉", "造橋鄉", "三灣鄉", "獅潭鄉", "大湖鄉", "泰安鄉", "卓蘭鎮", "西湖鄉", "南莊鄉"],
    "彰化縣": ["彰化市", "鹿港鎮", "和美鎮", "線西鄉", "伸港鄉", "福興鄉", "秀水鄉", "花壇鄉", "芬園鄉", "員林市", "溪湖鎮", "田中鎮", "大村鄉", "埔鹽鄉", "埔心鄉", "永靖鄉", "社頭鄉", "二水鄉", "北斗鎮", "二林鎮", "田尾鄉", "埤頭鄉", "芳苑鄉", "大城鄉", "竹塘鄉", "溪州鄉"],
    "南投縣": ["南投市", "埔里鎮", "草屯鎮", "竹山鎮", "集集鎮", "名間鄉", "鹿谷鄉", "中寮鄉", "魚池鄉", "國姓鄉", "水里鄉", "信義鄉", "仁愛鄉"],
    "雲林縣": ["斗六市", "斗南鎮", "虎尾鎮", "西螺鎮", "土庫鎮", "北港鎮", "古坑鄉", "大埤鄉", "莿桐鄉", "林內鄉", "二崙鄉", "崙背鄉", "麥寮鄉", "東勢鄉", "褒忠鄉", "臺西鄉", "元長鄉", "四湖鄉", "口湖鄉", "水林鄉"],
    "嘉義市": ["東區", "西區"],
    "嘉義縣": ["太保市", "朴子市", "布袋鎮", "大林鎮", "民雄鄉", "溪口鄉", "新港鄉", "六腳鄉", "東石鄉", "義竹鄉", "鹿草鄉", "水上鄉", "中埔鄉", "竹崎鄉", "梅山鄉", "番路鄉", "大埔鄉", "阿里山鄉"],
    "屏東縣": ["屏東市", "三地門鄉", "霧臺鄉", "瑪家鄉", "九如鄉", "里港鄉", "高樹鄉", "鹽埔鄉", "長治鄉", "麟洛鄉", "竹田鄉", "內埔鄉", "萬丹鄉", "潮州鎮", "泰武鄉", "來義鄉", "萬巒鄉", "嵌頂鄉", "新埤鄉", "南州鄉", "林邊鄉", "東港鎮", "琉球鄉", "佳冬鄉", "新園鄉", "枋寮鄉", "枋山鄉", "春日鄉", "獅子鄉", "牡丹鄉", "車城鄉", "滿州鄉", "恆春鎮"],
    "宜蘭縣": ["宜蘭市", "羅東鎮", "蘇澳鎮", "頭城鎮", "礁溪鄉", "壯圍鄉", "員山鄉", "冬山鄉", "五結鄉", "三星鄉", "大同鄉", "南澳鄉"],
    "花蓮縣": ["花蓮市", "鳳林鎮", "玉里鎮", "新城鄉", "吉安鄉", "壽豐鄉", "光復鄉", "豐濱鄉", "瑞穗鄉", "富里鄉", "秀林鄉", "萬榮鄉", "卓溪鄉"],
    "台東縣": ["台東市", "成功鎮", "關山鎮", "卑南鄉", "大武鄉", "太麻里鄉", "東河鄉", "長濱鄉", "鹿野鄉", "池上鄉", "綠島鄉", "延平鄉", "海端鄉", "達仁鄉", "金峰鄉", "蘭嶼鄉"],
    "澎湖縣": ["馬公市", "湖西鄉", "白沙鄉", "西嶼鄉", "望安鄉", "七美鄉"],
    "金門縣": ["金城鎮", "金沙鎮", "金湖鎮", "金寧鄉", "烈嶼鄉", "烏坵鄉"],
    "連江縣": ["南竿鄉", "北竿鄉", "莒光鄉", "東引鄉"],
    "其他": ["其他區域"]
}

def load_json_file(path, default_val):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except: return default_val
    return default_val

def save_json_file(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)
    except: pass

def send_line_message(message_text):
    if not ENABLE_LINE_NOTIFY:
        print("【系統提示】LINE 通知目前為關閉狀態（測試模式），未發送訊息。")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    payload = {"to": BOSS_USER_ID, "messages": [{"type": "text", "text": message_text}]}
    try: requests.post(url, headers=headers, json=payload)
    except: pass

# 背景 1 小時提醒監控 Daemon
@st.cache_resource
def start_reminder_daemon():
    def reminder_loop():
        while True:
            try:
                now = datetime.now()
                booked_list = load_json_file(BOOKING_DB_PATH, [])
                updated = False
                
                for b in booked_list:
                    b_datetime = datetime.strptime(f"{b['date']} {b['start']}", "%Y-%m-%d %H:%M")
                    time_diff = b_datetime - now
                    
                    if timedelta(minutes=50) <= time_diff <= timedelta(minutes=60):
                        if not b.get('reminder_sent'):
                            reminder_msg = (
                                f"⏰【心境整理室 - 1小時前準備通知】\n\n"
                                f"笑長您好！您與客戶【{b['name']}】的預約即將在 1 小時後開始囉！\n"
                                f"📅 服務時間：{b['date']} {b['start']} ~ {b['end']}\n"
                                f"🛠️ 服務方式：{b.get('service_type', '未設定')}\n"
                                f"💬 客戶 Line ID：{b.get('line_id', '未提供')}\n\n"
                                f"※ 請笑長記得提前開啟 LINE 聯繫客戶，做好對話準備喔！🌱"
                            )
                            send_line_message(reminder_msg)
                            b['reminder_sent'] = True
                            updated = True
                            
                if updated:
                    save_json_file(BOOKING_DB_PATH, booked_list)
            except:
                pass
            time.sleep(60)

    t = threading.Thread(target=reminder_loop, daemon=True)
    t.start()
    return True

start_reminder_daemon()

# 網頁視覺 CSS 樣式美化
st.markdown("""
    <style>
    .stApp { background-color: #f6f0e5 !important; color: #423730 !important; }
    
    div[data-testid="stWidgetLabel"] p, label, label p, .stMarkdown p {
        color: #423730 !important;
        font-size: 16px !important;
        font-weight: 600 !important;
    }
    
    div[data-testid="stAlert"] p, 
    div[data-testid="stNotification"] p, 
    div[data-testid="stAlert"] div,
    .stAlert p {
        color: #5c4033 !important;
    }
    
    div[data-testid="stCheckbox"] label span p, div[data-testid="stFileUploaderFileName"], small {
        color: #55463c !important;
    }
    
    div[data-testid="stMetricValue"] { color: #8b5a2b !important; font-weight: bold; }
    div[data-testid="stMetricLabel"] p { color: #55463c !important; }
    
    .main-title { color: #5c4033; font-size: 32px; font-weight: bold; text-align: center; margin-bottom: 5px; letter-spacing: 1px; }
    .subtitle { color: #8b6f5e; font-size: 16px; text-align: center; margin-bottom: 30px; font-style: italic; }
    
    .step-title { color: #8b5a2b; font-size: 22px; font-weight: bold; margin-top: 20px; margin-bottom: 15px; border-bottom: 2px solid #d2b48c; padding-bottom: 8px;}
    
    .fixed-box { background-color: #ffffff !important; color: #4a3b32 !important; padding: 25px; border: 1px solid #e8e0d2; border-radius: 16px; margin-bottom: 20px; box-shadow: 0 6px 15px rgba(139,90,43,0.05); }
    .fixed-box p, .fixed-box li, .fixed-box span, .fixed-box strong { color: #4a3b32 !important; font-size: 15px; line-height: 1.7; }
    .fixed-box h4 { color: #8b5a2b !important; margin-top: 0; font-weight: bold; font-size: 19px; margin-bottom: 15px; border-left: 4px solid #cfa375; padding-left: 10px; }
    
    .tips-box { background-color: #faf5ed !important; padding: 18px; border-left: 5px solid #d2b48c; border-radius: 8px; margin-top: 15px; color: #6e543c !important; font-size: 14px; box-shadow: 0 2px 4px rgba(0,0,0,0.02); }
    
    div.stButton > button:first-child { background-color: #8b5a2b !important; color: #ffffff !important; border-radius: 25px !important; border: none !important; padding: 12px 30px !important; font-weight: bold !important; font-size: 16px !important; box-shadow: 0 4px 10px rgba(139,90,43,0.2); transition: all 0.3s ease; }
    div.stButton > button:first-child:hover { background-color: #704723 !important; color: #ffffff !important; transform: translateY(-1px); }
    
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>div>textarea { color: #3d342e !important; background-color: #ffffff !important; border: 1px solid #d2b48c !important; border-radius: 8px !important; }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🌱 心境整理室</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">聽你說真心話，陪你梳理生命思緒的歇腳處</div>', unsafe_allow_html=True)

if 'step' not in st.session_state: st.session_state.step = 0
if 'form_data' not in st.session_state: st.session_state.form_data = {}

# ==========================================
# 第 0 步：歡迎與服務介紹頁面（完整還原文字版面）
# ==========================================
if st.session_state.step == 0:
    st.markdown(
        """
        <div class="fixed-box">
            <h4>☕ 💡 歡迎你前來。坐下來，給自己一杯茶的時間，卸下現實中的所有防備。</h4>
            <br>
            <h4>✨ 這裡，是一個完全獨立、沒有利害關係的思緒對話空間</h4>
            <p>在生活中，每個人心裡一定都有一些堆積很久、卻始終不敢對任何人說的真心話。為什麼我們越來越不敢對身邊的人坦白？</p>
            <ul>
                <li><strong>因為現實圈子的利害關係：</strong>現代人生活在錯綜複雜的人際網中，對熟人說了真正的內心話，就得提防彼此之間會不會有什麼利益牽扯或利害關係存在。</li>
                <li><strong>因為擔心隱私被到處亂說：</strong>畢竟都是現實生活中認識的親朋好友，再怎麼信任，也難免會隱隱擔心自己的脆弱哪天變成別人茶餘飯後的八卦。</li>
                <li><strong>因為親近之人的角色包袱：</strong>
                    <ul>
                        <li>跟父母伴侶說，怕他們聽了窮緊張、跟著操心。</li>
                        <li>跟朋友同事說，顧慮面子與人際眼光，怕丟臉。</li>
                        <li>跟晚輩孩子講，更是難以放下身段展現脆弱。</li>
                    </ul>
                </li>
            </ul>
            <p>如果你正處於這種「不知道該找誰說說心裡話、幫忙解決心中煩悶」的孤單狀態，或者正卡在人生的重大抉擇，希望有人能站在完全不一樣的角度給予建議——來到這裡，你完全不用擔心任何現實利益與流言誹語，可以百分之百放心地對笑長說出你的真話。</p>
            <br>
            <h4>🤝 笑長的陪伴風格與服務初衷</h4>
            <p>我是笑長。心境整理室的唯一目的，就是想用我個人的人生經歷與佛法體悟，來實質協助你面對心底的困境與煩惱。</p>
            <p>為了不浪費彼此的時間，並達到真正的幫助，在預約前我們必須達成以下共識：</p>
            <ol>
                <li><strong>我不會盲目地「百分之百不批判、不給建議」：</strong>如果只是敷衍地拍拍你、盲目地附和、做些流於形式的安慰，那就失去了我協助你梳理困境的本意。我會站在客觀、獨立的視角，適時給予你最真誠的引導與直言建議。</li>
                <li><strong>過程將融入個人佛法體悟與因果觀念：</strong>在陪伴與對話的過程中，我會運用個人的佛法體悟，從「因果」的視角來為你剖析煩惱的來龍去脈。這純粹是人生智慧的分享，你不需要有任何宗教壓力；但如果你本身對佛法或因果觀念完全無法接受，這個服務可能不太適合你。</li>
            </ol>
            <br>
            <h4>⚠️ 預約前的誠實提醒</h4>
            <p>心境整理室重視每一次對話的實質效果。如果您正尋找的是「純粹盲目的取暖」，或者「無法接受對話中出現個人佛法體悟與因果的敘述」，那麼笑長 的服務並不適合您，建議您可以尋求其他管道。</p>
            <br>
            <hr>
            <p><strong>💰 服務費用：</strong>每 30 分鐘新台幣 500 元（1 小時 1,000 元，依此類推）</p>
            <p><strong>🕒 開放時間：</strong>週四至週日 08:00 ~ 20:00（週一至週三公休）</p>
            <p><strong>💬 服務型態：</strong>LINE 文字對話 或 語音通話</p>
        </div>
        """, unsafe_allow_html=True
    )
    if st.button("🌱 開始線上預約"):
        st.session_state.step = 1
        st.rerun()

# ==========================================
# 第 1 步：基本資料收集
# ==========================================
elif st.session_state.step == 1:
    st.markdown('<div class="step-title">步驟 1：填寫基本聯繫資料</div>', unsafe_allow_html=True)
    
    cache_data = load_json_file(CACHE_PATH, {})
    line_id_input = st.text_input("💬 請輸入您的 LINE ID（老朋友輸入可自動帶入）：", value=st.session_state.form_data.get('line_id', ''))
    
    # 常客快取自動帶入
    if line_id_input in cache_data and not st.session_state.form_data.get('name'):
        st.session_state.form_data.update(cache_data[line_id_input])
        st.success("已自動帶入您的歷史聯繫資料！")

    name = st.text_input("👤 您的稱呼：", value=st.session_state.form_data.get('name', ''))
    gender = st.selectbox("🚻 性別：", ["請選擇", "男", "女", "不便透露"], index=["請選擇", "男", "女", "不便透露"].index(st.session_state.form_data.get('gender', '請選擇')))
    age = st.number_input("🎂 年齡：", min_value=18, max_value=100, value=int(st.session_state.form_data.get('age', 25)))
    
    city = st.selectbox("🏙️ 居住縣市：", list(TAIWAN_CITIES.keys()), index=list(TAIWAN_CITIES.keys()).index(st.session_state.form_data.get('city', '台北市')) if st.session_state.form_data.get('city') in TAIWAN_CITIES else 0)
    district_list = TAIWAN_CITIES.get(city, ["其他區域"])
    district = st.selectbox("🏡 鄉鎮市區：", district_list, index=district_list.index(st.session_state.form_data.get('district')) if st.session_state.form_data.get('district') in district_list else 0)
    
    phone = st.text_input("📞 手機號碼：", value=st.session_state.form_data.get('phone', ''))
    service_type = st.radio("💬 偏好的陪伴方式：", ["LINE 語音通話", "LINE 文字對話"], index=0 if st.session_state.form_data.get('service_type') == "LINE 語音通話" else 1)

    if st.button("下一步：選擇對話時段 ➔"):
        if not name or gender == "請選擇" or not phone or not line_id_input:
            st.error("請完整填寫稱呼、性別、電話與 LINE ID 喔！")
        else:
            st.session_state.form_data.update({
                "name": name, "gender": gender, "age": age, "city": city,
                "district": district, "phone": phone, "line_id": line_id_input, "service_type": service_type
            })
            st.session_state.step = 2
            st.rerun()

# ==========================================
# 第 2 步：選擇動態時段與費用計算
# ==========================================
elif st.session_state.step == 2:
    st.markdown('<div class="step-title">步驟 2：選擇諮詢日期與時長</div>', unsafe_allow_html=True)
    
    duration = st.selectbox("⏱️ 請選擇陪伴時長：", [30, 60, 90, 120], format_func=lambda x: f"{x} 分鐘 (NT$ {x * 100 // 6})")
    fee = (duration // 30) * 500
    st.info(f"💡 本次預估費用：NT$ {fee} 元")
    
    booking_date = st.date_input("📅 選擇預約日期 (公休日為週一至週三)：", min_value=datetime.now().date())
    
    if booking_date.weekday() in [0, 1, 2]:
        st.warning("⚠️ 週一、週二、週三為心境整理室公休日，請選擇週四至週日的日期喔！")
    else:
        # 動態產生可選時段 (08:00 ~ 20:00)
        available_slots = []
        booked_list = load_json_file(BOOKING_DB_PATH, [])
        
        start_hour = 8
        end_hour = 20
        
        for h in range(start_hour, end_hour):
            for m in [0, 30]:
                slot_time = datetime.strptime(f"{booking_date} {h:02d}:{m:02d}", "%Y-%m-%d %H:%M")
                slot_end = slot_time + timedelta(minutes=duration)
                
                # 過濾過期與衝突
                if slot_time < datetime.now():
                    continue
                    
                conflict = False
                for b in booked_list:
                    b_start = datetime.strptime(f"{b['date']} {b['start']}", "%Y-%m-%d %H:%M") - timedelta(minutes=30)
                    b_end = datetime.strptime(f"{b['date']} {b['end']}", "%Y-%m-%d %H:%M") + timedelta(minutes=30)
                    if not (slot_end <= b_start or slot_time >= b_end):
                        conflict = True
                        break
                
                if not conflict:
                    available_slots.append(slot_time.strftime("%H:%M"))
        
        if not available_slots:
            st.error("該日期已無合適的可預約時段，請嘗試選擇其他日期！")
        else:
            selected_start = st.selectbox("🕒 請選擇開始時間：", available_slots)
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("⬅️ 上一步"):
                    st.session_state.step = 1
                    st.rerun()
            with col2:
                if st.button("下一步：法律聲明與簽章 ➔"):
                    end_time_dt = datetime.strptime(f"{booking_date} {selected_start}", "%Y-%m-%d %H:%M") + timedelta(minutes=duration)
                    st.session_state.form_data.update({
                        "duration": duration, "fee": fee, "date": str(booking_date),
                        "start": selected_start, "end": end_time_dt.strftime("%H:%M")
                    })
                    st.session_state.step = 3
                    st.rerun()

# ==========================================
# 第 3 步：法律聲明與電子簽章
# ==========================================
elif st.session_state.step == 3:
    st.markdown('<div class="step-title">步驟 3：服務條款與非醫療聲明</div>', unsafe_allow_html=True)
    
    st.markdown(
        """
        <div class="fixed-box">
            <h4>📜 免責聲明與服務約定</h4>
            <ol>
                <li><strong>非醫療行為：</strong>「心境整理室」提供之服務為日常生活陪伴與思緒梳理，非醫療診斷、心理諮商或治療。</li>
                <li><strong>保密承諾：</strong>除違反法律規章或有即刻生命安全風險外，您的所有對話內容皆嚴格保密。</li>
                <li><strong>電子簽章：</strong>請輸入您的身分證真實姓名，表示您已閱讀並同意上述條款。</li>
            </ol>
        </div>
        """, unsafe_allow_html=True
    )
    
    agree = st.checkbox("我已詳閱並完全同意上述服務條款與免責聲明")
    real_name = st.text_input("🖋️ 請輸入身分證真實姓名（具法律效力之電子簽章）：")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ 上一步"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("下一步：上傳憑證完成預約 ➔"):
            if not agree or not real_name:
                st.error("請勾選同意條款並輸入真實姓名作為簽章喔！")
            else:
                st.session_state.form_data["real_name"] = real_name
                st.session_state.step = 4
                st.rerun()

# ==========================================
# 第 4 步：轉帳截圖上傳與完成預約（除錯與防堵遺失修復版）
# ==========================================
elif st.session_state.step == 4:
    st.markdown('<div class="step-title">步驟 4：付款憑證上傳與完成預約</div>', unsafe_allow_html=True)
    
    fee = st.session_state.form_data.get('fee', 500)
    st.markdown(
        f"""
        <div class="fixed-box">
            <h4>💳 銀行轉帳資訊</h4>
            <p><strong>轉帳金額：</strong><span style="color:#d9534f; font-size:20px; font-weight:bold;">NT$ {fee} 元</span></p>
            <p><strong>銀行代碼：</strong>822 (中國信託銀行)</p>
            <p><strong>轉帳帳號：</strong>1234-5678-9012-3456</p>
        </div>
        """, unsafe_allow_html=True
    )
    
    uploaded_file = st.file_uploader("📸 請上傳轉帳成功截圖憑證 (JPG / PNG)：", type=["jpg", "jpeg", "png"])
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⬅️ 上一步"):
            st.session_state.step = 3
            st.rerun()
    with col2:
        if st.button("✅ 確認送出預約"):
            if not uploaded_file:
                st.error("請先選擇並上傳轉帳截圖圖片喔！")
            else:
                # ✨ 使用 getvalue() 確保圖片位元資料穩定讀取，防範 Streamlit 重新讀取時清空
                file_bytes = uploaded_file.getvalue()
                customer_name = st.session_state.form_data.get('name', '客戶')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{customer_name}_{timestamp}.jpg"
                mime_type = uploaded_file.type or "image/jpeg"
                
                # 1. 確保儲存資料夾存在，寫入電腦實體圖片檔
                os.makedirs(UPLOAD_DIR, exist_ok=True)
                local_save_path = os.path.join(UPLOAD_DIR, filename)
                local_save_ok = False
                try:
                    with open(local_save_path, "wb") as f:
                        f.write(file_bytes)
                    local_save_ok = True
                except Exception as e_save:
                    st.warning(f"⚠️ 本地電腦/伺服器圖片儲存提醒：{str(e_save)}")
                    
                # 2. 上傳至 Google 雲端硬碟 (雙通道)
                with st.spinner("正將轉帳憑證同步寫入 Google 雲端硬碟中..."):
                    drive_success, drive_msg, drive_file_id = upload_to_google_drive(file_bytes, filename, mime_type)
                
                if drive_success:
                    st.success(f"【雲端同步結果】{drive_msg}")
                else:
                    st.warning(f"【備用提示】圖片寫入狀況：{drive_msg}\n(照片已備份於本地：{local_save_path})")
                
                # 3. 寫入預約資料庫 (記錄照片檔名與雲端 ID)
                booked_list = load_json_file(BOOKING_DB_PATH, [])
                new_booking = {
                    "name": st.session_state.form_data.get('name'),
                    "real_name": st.session_state.form_data.get('real_name'),
                    "gender": st.session_state.form_data.get('gender'),
                    "age": st.session_state.form_data.get('age'),
                    "city": st.session_state.form_data.get('city'),
                    "district": st.session_state.form_data.get('district'),
                    "phone": st.session_state.form_data.get('phone'),
                    "line_id": st.session_state.form_data.get('line_id'),
                    "service_type": st.session_state.form_data.get('service_type'),
                    "date": st.session_state.form_data.get('date'),
                    "start": st.session_state.form_data.get('start'),
                    "end": st.session_state.form_data.get('end'),
                    "fee": st.session_state.form_data.get('fee'),
                    "filename": filename,
                    "drive_file_id": drive_file_id,
                    "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                booked_list.append(new_booking)
                save_json_file(BOOKING_DB_PATH, booked_list)
                
                # 4. 自動寫入 Obsidian 05_客戶檔案/ 產生或更新筆記
                generate_obsidian_customer_note(new_booking)

                # 5. 更新常客快取
                cache_data = load_json_file(CACHE_PATH, {})
                cache_data[st.session_state.form_data.get('line_id')] = st.session_state.form_data
                save_json_file(CACHE_PATH, cache_data)
                
                # 6. LINE 即時推播給笑長
                push_msg = (
                    f"🎉【心境整理室 - 新預約成功通知】\n\n"
                    f"👤 稱呼：{new_booking['name']} ({new_booking['real_name']})\n"
                    f"📱 Line ID：{new_booking['line_id']}\n"
                    f"📞 電話：{new_booking['phone']}\n"
                    f"📅 時間：{new_booking['date']} {new_booking['start']} ~ {new_booking['end']}\n"
                    f"💰 費用：NT$ {new_booking['fee']}\n"
                    f"💬 方式：{new_booking['service_type']}\n\n"
                    f"※ 請笑長至後台或 Google 雲端硬碟核對轉帳憑證照片！🌱"
                )
                send_line_message(push_msg)
                
                st.session_state.step = 5
                st.rerun()

# ==========================================
# 第 5 步：完成預約頁面
# ==========================================
elif st.session_state.step == 5:
    st.balloons()
    st.markdown('<div class="step-title" style="text-align:center;">🎉 預約完成！我們到時見</div>', unsafe_allow_html=True)
    st.success("您的預約資訊與轉帳憑證已成功送出！")
    
    st.markdown(
        f"""
        <div class="fixed-box">
            <h4>📋 您的預約細節摘要</h4>
            <p><strong>預約稱呼：</strong>{st.session_state.form_data.get('name')}</p>
            <p><strong>對話時間：</strong>{st.session_state.form_data.get('date')} {st.session_state.form_data.get('start')} ~ {st.session_state.form_data.get('end')}</p>
            <p><strong>服務方式：</strong>{st.session_state.form_data.get('service_type')}</p>
            <p><strong>服務費用：</strong>NT$ {st.session_state.form_data.get('fee')} 元</p>
        </div>
        """, unsafe_allow_html=True
    )
    
    st.info("請點擊下方按鈕加入笑長官方 LINE，方便對話開始前聯繫喔！")
    st.markdown('<a href="https://line.me" target="_blank" style="display:block; text-align:center; padding:12px; background-color:#06C755; color:white; font-weight:bold; border-radius:25px; text-decoration:none; margin-bottom:20px;">🟢 加 LINE 好友聯繫笑長</a>', unsafe_allow_html=True)
    
    if st.button("🔄 返回首頁 / 再次預約"):
        st.session_state.step = 0
        st.session_state.form_data = {}
        st.rerun()

# ==========================================
# 🔒 笑長後台管理面板 (下方密碼解鎖區 + 自動連動刪除圖片)
# ==========================================
st.markdown("---")
with st.expander("🔑 笑長後台管理面板 (點擊展開)"):
    pwd = st.text_input("請輸入笑長專屬管理密碼：", type="password", key="admin_pwd_input")
    if pwd == ADMIN_PASSWORD:
        st.success("🔓 後台驗證成功！")
        
        # 🧪 雲端連線一鍵檢測工具
        st.markdown("---")
        st.markdown("### 🧪 Google 雲端連線實時檢測")
        if st.button("點擊測試 Google 雲端硬碟寫入狀態"):
            dummy_bytes = b"Test file content from Xiaochang"
            dummy_filename = f"測試連線_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with st.spinner("正在模擬測試上傳至 Google 雲端硬碟..."):
                t_ok, t_msg, t_id = upload_to_google_drive(dummy_bytes, dummy_filename, "text/plain")
            if t_ok:
                st.success(f"連線正常！{t_msg}")
            else:
                st.error(f"連線失敗！診斷報告如下：\n{t_msg}")
        st.markdown("---")

        booked_list = load_json_file(BOOKING_DB_PATH, [])
        st.markdown(f"### 📊 當前預約總筆數：{len(booked_list)} 筆")
        
        if not booked_list:
            st.info("目前尚無任何預約紀錄。")
        else:
            for idx, b in enumerate(booked_list):
                st.markdown(f"#### 筆數 #{idx+1}：{b.get('name')} ({b.get('date')} {b.get('start')}~{b.get('end')})")
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.write(f"- 真實姓名：{b.get('real_name')}")
                    st.write(f"- 地區：{b.get('city')} {b.get('district')}")
                    st.write(f"- 電話：{b.get('phone')}")
                    st.write(f"- Line ID：{b.get('line_id')}")
                    st.write(f"- 服務方式：{b.get('service_type')}")
                    st.write(f"- 費用：NT$ {b.get('fee')}")
                    
                    filename_to_del = b.get('filename')
                    img_path = os.path.join(UPLOAD_DIR, filename_to_del) if filename_to_del else ""
                    if img_path and os.path.exists(img_path):
                        st.image(img_path, caption=f"轉帳憑證：{filename_to_del}", width=280)
                    else:
                        st.warning("伺服器無本地快取，請至 Google 雲端硬碟檢視。")
                with col_b:
                    if st.button(f"🗑️ 刪除釋放此時段 (連動刪除圖片)", key=f"del_{idx}"):
                        filename_del = b.get('filename')
                        drive_id_del = b.get('drive_file_id')
                        
                        # 1. 刪除伺服器/本地圖片
                        if filename_del:
                            local_target = os.path.join(UPLOAD_DIR, filename_del)
                            if os.path.exists(local_target):
                                try:
                                    os.remove(local_target)
                                    st.info(f"已從伺服器物理刪除照片：{filename_del}")
                                except Exception as e_del:
                                    st.warning(f"刪除本地照片失敗：{str(e_del)}")
                                    
                        # 2. 連動刪除 Google 雲端硬碟照片
                        if drive_id_del:
                            d_ok, d_msg = delete_google_drive_file(drive_id_del)
                            if d_ok:
                                st.info(d_msg)
                            else:
                                st.warning(d_msg)
                        
                        # 3. 移除預約紀錄並儲存
                        booked_list.pop(idx)
                        save_json_file(BOOKING_DB_PATH, booked_list)
                        st.success("已成功刪除該筆預約與對應之轉帳截圖！")
                        st.rerun()
    elif pwd:
        st.error("密碼錯誤！")
