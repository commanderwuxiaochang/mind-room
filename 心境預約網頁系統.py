import os
import json
import streamlit as st
import requests
import threading
import time
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
# ☁️ Google 雲端硬碟自動上傳核心函式 (雙通道智慧備援版)
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
                    return True, f"✅ 成功透過 GAS 小幫手寫入 Google 雲端硬碟 (檔案 ID: {res_json.get('file_id')})"
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
                return True, f"✅ 成功透過 GCP 機器人寫入 Google 雲端硬碟 (檔案 ID: {res_json.get('id')})"
            else:
                err_messages.append(f"GCP 拒絕寫入 (代碼 {response.status_code}): {response.text}")

        except Exception as e:
            err_messages.append(f"GCP API 連線異常: {str(e)}")

    if not err_messages:
        return False, "❌ 未設定任何雲端上傳金鑰 (請檢查 Secrets 的 gas_url 或 gcp_service_account)"
    else:
        return False, "❌ 雲端寫入失敗，原因如下：\n" + "\n".join(err_messages)

# 台灣行政區資料
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

# Background reminder daemon
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

# CSS Styling
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
# 第 0 步：歡迎與服務介紹頁面
# ==========================================
if st.session_state.step == 0:
    st.markdown(
        """
        <div class="fixed-box">
            <h4>☕ 歡迎前來，給自己一杯茶的時間</h4>
            <p>這是一個沒有現實利益牽扯、不擔心隱私外洩、沒有角色包袱的安心空間。</p>
            <p>我是笑長，在這裡我不給盲目的安慰，而是站在客觀獨立的角度，融合人生閱歷與佛法轉念智慧，陪你一同剖析煩惱的來龍去脈。</p>
            <br>
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
    
    # 常客快取帶入
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
# 第 4 步：轉帳截圖上傳與完成預約
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
                file_bytes = uploaded_file.read()
                customer_name = st.session_state.form_data.get('name', '客戶')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{customer_name}_{timestamp}.jpg"
                mime_type = uploaded_file.type or "image/jpeg"
                
                # 1. 儲存於 Streamlit 本地伺服器備份
                local_save_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    with open(local_save_path, "wb") as f:
                        f.write(file_bytes)
                except Exception:
                    pass
                    
                # 2. 上傳至 Google 雲端硬碟 (雙通道測試)
                with st.spinner("正將轉帳憑證同步寫入 Google 雲端硬碟中..."):
                    drive_success, drive_msg = upload_to_google_drive(file_bytes, filename, mime_type)
                
                if drive_success:
                    st.success(f"【雲端同步結果】{drive_msg}")
                else:
                    st.warning(f"【備用提示】照片已儲存於系統伺服器，但雲端回報：\n{drive_msg}")
                
                # 3. 寫入預約資料庫
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
                    "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                booked_list.append(new_booking)
                save_json_file(BOOKING_DB_PATH, booked_list)
                
                # 4. 更新常客快取
                cache_data = load_json_file(CACHE_PATH, {})
                cache_data[st.session_state.form_data.get('line_id')] = st.session_state.form_data
                save_json_file(CACHE_PATH, cache_data)
                
                # 5. LINE 即時推播給笑長
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
# 🔒 笑長後台管理面板 (下方密碼解鎖區)
# ==========================================
st.markdown("---")
with st.expander("🔑 笑長後台管理面板 (點擊展開)"):
    pwd = st.text_input("請輸入笑長專屬管理密碼：", type="password", key="admin_pwd_input")
    if pwd == ADMIN_PASSWORD:
        st.success("🔓 後台驗證成功！")
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
                    
                    img_path = os.path.join(UPLOAD_DIR, b.get('filename', ''))
                    if os.path.exists(img_path):
                        st.image(img_path, caption=f"轉帳憑證：{b.get('filename')}", width=280)
                    else:
                        st.warning("伺服器無本地快取，請至 Google 雲端硬碟檢視。")
                with col_b:
                    if st.button(f"🗑️ 刪除釋放此時段", key=f"del_{idx}"):
                        booked_list.pop(idx)
                        save_json_file(BOOKING_DB_PATH, booked_list)
                        st.success("已成功刪除該筆預約！")
                        st.rerun()
    elif pwd:
        st.error("密碼錯誤！")
