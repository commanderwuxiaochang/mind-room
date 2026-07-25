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
# ☁️ Google 雲端硬碟自動上傳核心函式 (防錯除錯強化版)
# ==========================================
def upload_to_google_drive(file_bytes, filename, mime_type):
    """將客戶上傳的轉帳憑證強制寫入 Google 雲端硬碟指定資料夾"""
    try:
        if "gcp_service_account" not in st.secrets or "drive_folder_id" not in st.secrets:
            return False, "Streamlit Secrets 設定缺失：未設定 gcp_service_account 或 drive_folder_id"
        
        service_account_info = dict(st.secrets["gcp_service_account"])
        if "private_key" in service_account_info:
            service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
            
        folder_id = st.secrets["drive_folder_id"]
        scopes = ['https://www.googleapis.com/auth/drive']
        
        creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=scopes)
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        access_token = creds.token
        
        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        
        import json as py_json
        metadata = {
            "name": filename,
            "parents": [folder_id]
        }
        
        import uuid
        boundary = 'foo_bar_baz_' + uuid.uuid4().hex
        
        body = (
            f'--{boundary}\r\n'
            f'Content-Type: application/json; charset=UTF-8\r\n\r\n'
            f'{py_json.dumps(metadata)}\r\n'
            f'--{boundary}\r\n'
            f'Content-Type: {mime_type if mime_type else "image/jpeg"}\r\n\r\n'
        ).encode('utf-8') + file_bytes + f'\r\n--{boundary}--\r\n'.encode('utf-8')
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}"
        }
        
        response = requests.post(upload_url, headers=headers, data=body)
        if response.status_code == 200:
            res_json = response.json()
            return True, res_json.get('id', 'success')
        else:
            return False, f"HTTP {response.status_code} 雲端拒絕：{response.text}"

    except Exception as e:
        return False, f"程式執行異常: {str(e)}"

# 台灣行政區資料
TAIWAN_CITIES = {
    "台北市": ["中正區", "大同區", "中山區", "松山區", "大安區", "萬華區", "信義區", "士林區", "北投區", "內湖區", "南港區", "文山區"],
    "新北市": ["板橋區", "三重區", "中和區", "永和區", "新莊區", "新店區", "樹林區", "鶯歌區", "三峽區", "淡水區", "汐止區", "瑞芳區", "土城區", "蘆洲區", "五股區", "泰山區", "林口區", "深坑區", "石碇區", "坪林區", "三芝區", "石門區", "八里區", "平溪區", "雙溪區", "貢寮區", "金山區", "萬里區", "烏來區"],
    "桃園市": ["桃園區", "中壢區", "大溪區", "楊梅區", "蘆竹區", "大園區", "龜山區", "八德區", "龍潭區", "平鎮區", "新屋區", "觀音區", "復興區"],
    "台中市": ["中區", "東區", "南區", "西區", "北區", "北屯區", "西屯區", "南屯區", "太平區", "大里區", "霧峰區", "烏日區", "豐原區", "後里區", "石岡區", "東勢區", "和平區", "新社區", "潭子區", "大雅區", "神岡區", "大肚區", "沙鹿區", "龍井區", "梧棲區", "清水區", "大甲區", "外埔區", "大安區"],
    "台南市": ["中西區", "東區", "南區", "北區", "安平區", "安南區", "永康區", "歸仁區", "新化區", "左鎮區", "玉井區", "楠西區", "南化區", "仁德區", "關廟區", "龍崎區", "官田區", "麻豆區", "佳里區", "西港區", "七股區", "將軍區", "學甲區", "北門區", "新營區", "後壁區", "白河區", "東山區", "六甲區", "下營區", "柳營區", "鹽水區", "善化區", "大內區", "山上區", "新市區", "安定區"],
    "高雄市": ["新興區", "前金區", "苓雅區", "鹽埕區", "鼓山區", "旗津區", "前鎮區", "三民區", "楠梓區", "小港區", "左營區", "仁武區", "大社區", "岡山區", "路竹區", "阿蓮區", "田寮區", "燕巢區", "橋頭區", "梓官區", "彌陀區", "永安區", "湖內區", "鳳山區", "大寮區", "林園區", "鳥松區", "大樹區", "旗山區", "美濃區", "六龜區", "內門區", "杉林區", "甲仙區", "桃源區", "那瑪夏區", "茂林區", "茄萣區"],
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

# ==========================================
# 背景智慧追蹤：前一小時自動提醒笑長
# ==========================================
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

# ==========================================
# 溫馨療癒系網頁視覺與字體 (CSS)
# ==========================================
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
    st.markdown('<div style="text-align: center; margin-bottom: 25px; color: #6e543c;">☕ 💡 歡迎你前來。坐下來，給自己一杯茶的時間，卸下現實中的所有防備。</div>', unsafe_allow_html=True)

    st.markdown("""<div class="fixed-box">
<h4>✨ 這裡，是一個完全獨立、沒有利害關係的思緒對話空間</h4>
<p>在生活中，每個人心裡一定都有一些堆積很久、卻始終不敢對任何人說的真心話。為什麼我們越來越不敢對身邊的人坦白？</p>
<ul>
    <li style="margin-bottom: 8px;"><strong>因為現實圈子的利害關係</strong>：現代人生活在錯綜複雜的人際網中，對熟人說了真正的內心話，就得提防彼此之間會不會有什麼利益牽扯或利害關係存在。</li>
    <li style="margin-bottom: 8px;"><strong>因為擔心隱私被到處亂說</strong>：畢竟都是現實生活中認識的親朋好友，再怎麼信任，也難免會隱隱擔心自己的脆弱哪天變成別人茶餘飯後的八卦。</li>
    <li style="margin-bottom: 8px;"><strong>因為親近之人的角色包袱</strong>：
        <ul>
            <li>跟父母伴侶說，怕他們聽了窮緊張、跟著操心。</li>
            <li>跟朋友同事說，顧慮面子與人際眼光，怕丟臉。</li>
            <li>跟晚輩孩子講，更是難以放下身段展現脆弱。</li>
        </ul>
    </li>
</ul>
<p style="margin-top: 15px; border-top: 1px dashed #e8e0d2; padding-top: 15px;">如果你正處於這種「不知道該找誰說說心裡話、幫忙解決心中煩悶」的孤單狀態，或者正卡在人生的重大抉擇，希望有人能站在完全不一樣的角度給予建議——<strong>來到這裡，你完全不用擔心任何現實利益與流言誹語，可以百分之百放心地對笑長說出你的真話。</strong></p>
</div>

<div class="fixed-box">
<h4>🤝 笑長的陪伴風格與服務初衷</h4>
<p>我是笑長。心境整理室的唯一目的，就是想用我<strong>個人的人生經歷與佛法體悟</strong>，來實質協助你面對心底的困境與煩惱。</p>
<p>為了不浪費彼此的時間，並達到真正的幫助，在預約前我們必須達成以下共識：</p>
<ol>
    <li style="margin-bottom: 10px;"><strong>我不會盲目地「百分之百不批判、不給建議」</strong>：如果只是敷衍地拍拍你、盲目地附和、做些流於形式的安慰，那就失去了我協助你梳理困境的本意。我會站在客觀、獨立的視角，適時給予你最真誠的引導與直言建議。</li>
    <li><strong>過程將融入個人佛法體悟與因果觀念</strong>：在陪伴與對話的過程中，我會運用個人的佛法體悟，從「因果」的視角來為你剖析煩惱的來龍去脈。這純粹是人生智慧的分享，你不需要有任何宗教壓力；但如果你本身對佛法或因果觀念完全無法接受，這個服務可能不太適合你。</li>
</ol>
</div>

<div class="fixed-box" style="border: 1px solid #e11d48; background-color: #fff5f5 !important;">
<h4 style="color: #e11d48 !important; border-left: 4px solid #e11d48;">⚠️ 預約前的誠實提醒</h4>
<p style="color: #4a3b32 !important;">心境整理室重視每一次對話的實質效果。如果您正尋找的是「純粹盲目的取暖」，或者「無法接受對話中出現個人佛法體悟與因果的敘述」，那麼笑長的服務並不適合您，建議您可以尋求其他管道。</p>
</div>""", unsafe_allow_html=True)
    
    if st.button("我認同笑長理念，開始預約 ➔", use_container_width=True):
        st.session_state.step = 1
        st.rerun()

# ==========================================
# 第一步：基本個資與服務方式選擇
# ==========================================
elif st.session_state.step == 1:
    st.markdown('<div class="step-title">第一步：填寫基本聯絡資料</div>', unsafe_allow_html=True)
    
    q1 = st.text_input("1. 希望笑長怎麼稱呼你/妳呢？", value=st.session_state.form_data.get('name', ''))
    gender_options = ["男", "女"]
    default_gender = st.session_state.form_data.get('gender', "男")
    q2 = st.selectbox("2. 性別是？", gender_options, index=gender_options.index(default_gender) if default_gender in gender_options else 0)
    
    q3 = st.text_input("3. 實際真實年齡？", value=st.session_state.form_data.get('age', ''))
    
    city_options = list(TAIWAN_CITIES.keys())
    default_city = st.session_state.form_data.get('city', "台北市")
    if default_city not in city_options: default_city = "台北市"
    chosen_city = st.selectbox("4. 目前居住城市（縣市第一層）", city_options, index=city_options.index(default_city))
    
    district_options = TAIWAN_CITIES[chosen_city]
    default_district = st.session_state.form_data.get('district', district_options[0])
    if default_district not in district_options: default_district = district_options[0]
    chosen_district = st.selectbox("└ 請選擇區域/鄉鎮（第二層）", district_options, index=district_options.index(default_district))
    
    q5 = st.text_input("5. 請提供手機號碼", value=st.session_state.form_data.get('phone', ''))
    q6 = st.text_input("6. 請提供 Line ID", value=st.session_state.form_data.get('line_id', ''))
    
    service_options = ["Line文字服務", "Line語音服務"]
    default_service = st.session_state.form_data.get('service_type', "Line文字服務")
    q7 = st.selectbox("7. 請選擇本次期望的服務方式：", service_options, index=service_options.index(default_service) if default_service in service_options else 0)
    st.markdown('<p style="color: #dc2626; font-size: 13px; font-weight: bold; margin-top: -5px; margin-bottom: 20px;">⚠️ 備註說明：一旦確認選擇此服務方式，在本次服務期間內即不得變更服務方式。</p>', unsafe_allow_html=True)
    
    col_btn1, col_btn2 = st.columns([2, 3])
    with col_btn1:
        check_click = st.button("🔍 檢查歷史個資")
    
    st.markdown("""<div class="tips-box">
<strong>💡 溫馨提示（老朋友免重填）：</strong><br>
如果您先前已預約過陪伴服務，只需在第 6 點填入您的 <strong>Line ID</strong> 並點擊「檢查歷史個資」，系統會自動載入您的基本資料喔！
</div>""", unsafe_allow_html=True)
    
    if check_click and q6.strip():
        history = load_json_file(CACHE_PATH, {}).get(q6.strip())
        if history:
            st.session_state.form_data.update({
                'name': history.get('name', ''), 'gender': history.get('gender', '男'),
                'age': history.get('age', ''), 'city': history.get('city', '台北市'),
                'district': history.get('district', ''), 'phone': history.get('phone', ''), 'line_id': q6.strip()
            })
            st.success("🎉 偵測成功！已自動填妥您的歷史資料！")
            st.rerun()
        else:
            st.warning("查無此 Line ID 的歷史紀錄。初次預約送出後，下次就能自動載入囉！")

    st.markdown("<br>", unsafe_allow_html=True)
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("返回服務介紹"):
            st.session_state.step = 0
            st.rerun()
    with col_nav2:
        if st.button("下一步：選擇時間", use_container_width=True):
            if not q1 or not q3 or not q5.strip() or not q6.strip():
                st.error("❌ 請完整填寫所有基本欄位資訊（包含手機號碼與 Line ID）。")
            else:
                st.session_state.form_data.update({
                    'name': q1, 'gender': q2, 'age': q3,
                    'city': chosen_city, 'district': chosen_district,
                    'phone': q5.strip(), 'line_id': q6.strip(), 'service_type': q7
                })
                st.session_state.step = 2
                st.rerun()

# ==========================================
# 第二步：動態時段選擇
# ==========================================
elif st.session_state.step == 2:
    st.markdown('<div class="step-title">第二步：選擇您有空的時間</div>', unsafe_allow_html=True)
    
    st.markdown("""<div class="fixed-box">
<h4>💰 心境整理室 收費與服務時間</h4>
<ul>
    <li><strong>服務費用：</strong>每 30 分鐘 / 500 元</li>
    <li><strong>開放時間：</strong>星期四 至 星期日 (08:00 ~ 20:00)</li>
    <li><strong>休息公休：</strong>星期一 至 星期三 休息</li>
</ul>
</div>""", unsafe_allow_html=True)
    
    duration_options = {"30分鐘": 30, "1小時": 60, "1.5小時": 90, "2小時": 120}
    chosen_dur_label = st.selectbox("請選擇預約服務時長：", list(duration_options.keys()))
    duration_mins = duration_options[chosen_dur_label]
    total_price = int((duration_mins / 30) * 500)
    st.session_state.form_data['duration_label'] = chosen_dur_label
    st.session_state.form_data['total_price'] = total_price
    
    st.metric(label="📊 本次服務預計總金額", value=f"NT$ {total_price} 元")
    
    try:
        import pytz
        tw_tz = pytz.timezone('Asia/Taipei')
        now_dt = datetime.now(tw_tz)
    except:
        now_dt = datetime.now()

    selected_date = st.date_input("請選擇預約日期：", min_value=now_dt.date())
    weekday_num = selected_date.weekday()
    
    if weekday_num in [0, 1, 2]:
        st.error("❌ 溫馨提示：星期一至星期三為笑長公休休息日，請選擇【星期四至星期日】的日期範圍。")
        chosen_time = None
    else:
        booked_list = load_json_file(BOOKING_DB_PATH, [])
        date_str = selected_date.strftime("%Y-%m-%d")
        day_bookings = [b for b in booked_list if b['date'] == date_str]
        
        available_slots = []
        start_time_current = datetime.strptime("08:00", "%H:%M")
        end_time_limit = datetime.strptime("20:00", "%H:%M")
        earliest_allowed_dt = now_dt.replace(tzinfo=None) + timedelta(minutes=30)
        
        while start_time_current + timedelta(minutes=duration_mins) <= end_time_limit:
            p_start = start_time_current
            p_end = start_time_current + timedelta(minutes=duration_mins)
            slot_dt = datetime.combine(selected_date, p_start.time())
            
            is_too_soon_or_past = False
            if selected_date == now_dt.date() and slot_dt < earliest_allowed_dt:
                is_too_soon_or_past = True
            
            conflict = False
            for b in day_bookings:
                e_start = datetime.strptime(b['start'], "%H:%M")
                e_end = datetime.strptime(b['end'], "%H:%M")
                if not (p_end + timedelta(minutes=30) <= e_start or p_start >= e_end + timedelta(minutes=30)):
                    conflict = True
                    break
            
            if not conflict and not is_too_soon_or_past:
                available_slots.append(p_start.strftime("%H:%M"))
            
            start_time_current += timedelta(minutes=30)
            
        if not available_slots:
            st.warning("⚠️ 該日期此時段的空檔不足，或剩餘時段已過期，請選擇其他日期或縮短服務時長。")
            chosen_time = None
        else:
            chosen_time = st.selectbox("請選擇對話開始時間：", available_slots)
            
        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("返回上一步"):
                st.session_state.step = 1
                st.rerun()
        with col2:
            if st.button("下一步：閱讀法律免責聲明"):
                if not chosen_time:
                    st.error("❌ 請選擇一個有效的預約時間段。")
                else:
                    st.session_state.form_data.update({
                        'booking_date': date_str,
                        'booking_start': chosen_time,
                        'booking_end': (datetime.strptime(chosen_time, "%H:%M") + timedelta(minutes=duration_mins)).strftime("%H:%M")
                    })
                    st.session_state.step = 3
                    st.rerun()

# ==========================================
# 第三步：閱讀條款與電子簽章
# ==========================================
elif st.session_state.step == 3:
    st.markdown('<div class="step-title">第三步：閱讀服務條款與免責聲明</div>', unsafe_allow_html=True)
    
    st.markdown("""<div class="fixed-box" style="height: 320px; overflow-y: scroll; border: 1px solid #d2b48c;">
<h4 style="margin-top:0;">【心境整理室 服務條款、風格共識與法律免責聲明】</h4>
<p>歡迎您預約心境整理室。為了保障雙方權益並確保服務符合台灣現行法規，請務必詳閱以下條款：</p>

<p>1. <strong>服務性質之明確界定（非醫療行為）</strong>：<br>
本服務完全定位為「日常生活陪伴、客觀聆聽與人生經驗分享」。笑長<strong>並非</strong>台灣醫療法規所稱之精神科醫師、臨床心理師或諮商心理師。本服務<strong>絕對不包含、亦無法取代</strong>任何專業的醫療行為、心理諮商、心理治療、精神疾病診斷或藥物治療建議。</p>

<p>2. <strong>溝通風格與共識（雙向真誠交流）</strong>：<br>
心境整理室重視的是真實且有建設性的思緒梳理。笑長在對話中不會流於形式地盲目附和或敷衍取暖，而是會結合自身的人生閱歷與佛法體悟，從因果智慧的視角，為您提供不同角度的客觀建議。</p>

<p>3. <strong>求助管道之重要提醒（非醫療承諾）</strong>：<br>
本服務無法提供<strong>任何</strong>精神官能症狀治療或重大情緒危機介入。若您目前正面臨重度精神困擾、自我傷害或傷害他人等強烈意圖與危機，請務必尋求正規醫療院所或專業心理諮商機構協助。</p>

<p>4. <strong>個人自主行為責任與免責</strong>：<br>
對話過程中涉及之所有佛法體悟、因果觀念或生活建議，僅供您參考。最終之日常抉擇與個人行為責任，仍由預約人本人完全自主決定、承擔與負責。</p>
</div>""", unsafe_allow_html=True)
    
    sig_name = st.text_input("✍️ 請在此輸入您的【身分證上完整的真實姓名】（作為具法律效力的電子簽章）：", value=st.session_state.form_data.get('signature', ''))
    legal_agree = st.checkbox("我已詳細閱讀、充分理解並完全同意上述所有服務共識與免責聲明，並保證填寫資訊屬實。")
    
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("返回上一步"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("我同意條款，前往付款"):
            if not sig_name.strip():
                st.error("❌ 您必須輸入身分證上完整的真實姓名以完成電子簽章。")
            elif not legal_agree:
                st.error("❌ 您必須勾選同意方塊方可繼續。")
            else:
                st.session_state.form_data['signature'] = sig_name.strip()
                st.session_state.step = 4
                st.rerun()

# ==========================================
# 第四步：轉帳付款驗證與 Google 雲端自動同步
# ==========================================
elif st.session_state.step == 4:
    st.markdown('<div class="step-title">第四步：轉帳付款驗證</div>', unsafe_allow_html=True)
    
    st.markdown(f"""<div class="fixed-box">
<h4>🏦 中國信託 轉帳帳戶資訊</h4>
<p><strong>銀行代碼：</strong>822 (中國信託)</p>
<p><strong>匯款帳號：</strong>8645-4006-3853</p>
<p><strong>本次應轉帳總金額：</strong><span style="color:#8b5a2b; font-size:18px; font-weight:bold;">NT$ {st.session_state.form_data.get('total_price', 500)} 元</span></p>
</div>""", unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("請上傳您的轉帳成功截圖照片", type=["png", "jpg", "jpeg", "heic", "HEIC"])
    pay_note = st.text_area("付款說明或備註（例如：您的轉帳帳號後五碼）：", value=st.session_state.form_data.get('pay_note', ''))
    
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("返回修改條款"):
            st.session_state.step = 3
            st.rerun()
    with col2:
        if st.button("送出預訂資料，等待款項確認", use_container_width=True):
            if uploaded_file is None:
                st.error("❌ 錯誤：您必須上傳轉帳成功截圖，才能送出預訂。")
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_filename = f"{timestamp}_{st.session_state.form_data['name']}_{uploaded_file.name}"
                
                # 1. 本機/雲端伺服器備份儲存
                full_save_path = os.path.normpath(os.path.join(UPLOAD_DIR, safe_filename))
                try:
                    with open(full_save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                except Exception as local_err:
                    print(f"本地儲存提醒: {local_err}")
                
                # 2. 自動同步上傳至 Google 雲端硬碟共用資料夾
                file_bytes = uploaded_file.getvalue()
                mime_type = uploaded_file.type or "image/jpeg"
                drive_success, drive_msg = upload_to_google_drive(file_bytes, safe_filename, mime_type)
                
                if drive_success:
                    st.toast("⚡ 付款截圖已成功自動寫入 Google 雲端硬碟！", icon="✅")
                else:
                    st.error(f"⚠️ 雲端硬碟備份提示: {drive_msg}")
                
                st.session_state.form_data['saved_receipt_path'] = full_save_path
                st.session_state.form_data['receipt_name'] = safe_filename
                st.session_state.form_data['pay_note'] = pay_note if pay_note.strip() else "無特別說明"
                
                # 寫入快取與暫存資料庫
                c_cache = load_json_file(CACHE_PATH, {})
                c_cache[st.session_state.form_data['line_id']] = {
                    "name": st.session_state.form_data['name'], "gender": st.session_state.form_data['gender'],
                    "age": st.session_state.form_data['age'], "city": st.session_state.form_data['city'],
                    "district": st.session_state.form_data['district'], "phone": st.session_state.form_data['phone']
                }
                save_json_file(CACHE_PATH, c_cache)
                
                b_db = load_json_file(BOOKING_DB_PATH, [])
                b_db.append({
                    "date": st.session_state.form_data['booking_date'],
                    "start": st.session_state.form_data['booking_start'],
                    "end": st.session_state.form_data['booking_end'],
                    "name": st.session_state.form_data['name'],
                    "service_type": st.session_state.form_data['service_type'],
                    "line_id": st.session_state.form_data['line_id'],
                    "phone": st.session_state.form_data['phone'],
                    "reminder_sent": False,
                    "receipt_name": safe_filename
                })
                save_json_file(BOOKING_DB_PATH, b_db)
                
                preorder_cache = load_json_file(PREORDER_TEMP_PATH, [])
                preorder_cache.append({
                    "name": st.session_state.form_data['name'],
                    "amount": str(st.session_state.form_data['total_price']),
                    "method": "銀行轉帳",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                save_json_file(PREORDER_TEMP_PATH, preorder_cache)
                
                # 自動更新 Obsidian 客戶資料卡 md 檔
                record_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c_name = st.session_state.form_data['name'].strip()
                existing_md_files = []
                if os.path.exists(CLIENT_FILES_DIR):
                    try: existing_md_files = [f for f in os.listdir(CLIENT_FILES_DIR) if f.endswith('.md')]
                    except: pass
                
                target_md_filename = None
                client_id_str = None

                for f_name in existing_md_files:
                    if f_name.endswith(f" {c_name}.md") or f_name == f"{c_name}.md":
                        target_md_filename = f_name
                        if f_name.startswith("[") and "]" in f_name:
                            client_id_str = f_name[1:f_name.index("]")]
                        break

                if not client_id_str:
                    max_id = 0
                    for f_name in existing_md_files:
                        if f_name.startswith("[C") and "]" in f_name:
                            try:
                                num = int(f_name[2:f_name.index("]")])
                                if num > max_id: max_id = num
                            except: pass
                    client_id_str = f"C{max_id + 1:04d}"

                if not target_md_filename:
                    target_md_filename = f"[{client_id_str}] {c_name}.md"

                full_md_path = os.path.normpath(os.path.join(CLIENT_FILES_DIR, target_md_filename))

                existing_body = ""
                if os.path.exists(full_md_path):
                    try:
                        with open(full_md_path, "r", encoding="utf-8") as mf:
                            raw_txt = mf.read()
                            if raw_txt.startswith("---") and "---" in raw_txt[3:]:
                                second_dash_pos = raw_txt.find("---", 3)
                                existing_body = raw_txt[second_dash_pos + 3:].strip()
                            else:
                                existing_body = raw_txt.strip()
                    except: pass

                booking_history_block = f"""
### 🗓️ 線上網頁預約紀錄（同步時間：{record_time}）
* **預約時段：** {st.session_state.form_data['booking_date']} {st.session_state.form_data['booking_start']} ~ {st.session_state.form_data['booking_end']} ({st.session_state.form_data['duration_label']})
* **服務方式：** {st.session_state.form_data['service_type']}
* **預計費用：** NT$ {st.session_state.form_data['total_price']} 元
* **付款備註/轉帳後五碼：** {st.session_state.form_data['pay_note']}
* **轉帳憑證檔名：** `{st.session_state.form_data['receipt_name']}`
* **手機號碼：** {st.session_state.form_data['phone']}
* **電子簽章正名：** {st.session_state.form_data['signature']} (已同意法律條款)

---
"""

                yaml_header = f"""---
ID: {client_id_str}
客戶姓名: {c_name}
檔案建立日期: {datetime.now().strftime('%Y/%m/%d')}
真實姓名: {st.session_state.form_data['signature']}
性別: {st.session_state.form_data['gender']}
稱呼方式: {c_name}
戶籍地: 未提供
居住地: {st.session_state.form_data['city']}{st.session_state.form_data['district']}
最高學歷: 未提供
職業: 未提供
手機: {st.session_state.form_data['phone']}
電子郵件: 未提供
Line ID: {st.session_state.form_data['line_id']}
生日: 未提供
---
"""

                if existing_body:
                    new_full_content = yaml_header + "\n" + booking_history_block + "\n" + existing_body
                else:
                    new_full_content = yaml_header + f"\n# 👤 客戶全紀錄主檔：{c_name} ({client_id_str})\n\n" + booking_history_block

                try:
                    with open(full_md_path, "w", encoding="utf-8") as mf:
                        mf.write(new_full_content)
                except Exception as md_err:
                    print(f"Markdown 寫入提醒: {md_err}")

                # 推播 LINE 給笑長
                boss_msg = (
                    f"🎉【心境整理室 - 新客戶線上預約通知】\n\n"
                    f"👤 客戶稱呼：{st.session_state.form_data['name']} ({st.session_state.form_data['gender']}，{st.session_state.form_data['age']}歲)\n"
                    f"✍️ 正式簽名：{st.session_state.form_data['signature']}\n"
                    f"📍 居住區域：{st.session_state.form_data['city']}{st.session_state.form_data['district']}\n"
                    f"📱 手機號碼：{st.session_state.form_data['phone']}\n"
                    f"💬 Line ID：{st.session_state.form_data['line_id']}\n"
                    f"🛠️ 服務方式：{st.session_state.form_data['service_type']}\n\n"
                    f"📅 預約時段：{st.session_state.form_data['booking_date']} {st.session_state.form_data['booking_start']} ~ {st.session_state.form_data['booking_end']} ({st.session_state.form_data['duration_label']})\n"
                    f"💰 預計費用：NT$ {st.session_state.form_data['total_price']} 元\n"
                    f"📝 付款備註：{st.session_state.form_data['pay_note']}\n"
                    f"🖼️ 憑證檔名：{safe_filename}\n\n"
                    f"🌱 請笑長記得於服務開始前，提前開啟 LINE 主動聯繫對方喔！"
                )
                send_line_message(boss_msg)
                st.session_state.step = 5
                st.rerun()

# ==========================================
# 第五步：預約成功結案頁面
# ==========================================
elif st.session_state.step == 5:
    st.balloons()
    st.markdown('<div class="step-title" style="text-align: center; color: #166534;">🎉 恭喜您！已成功完成線上預約！</div>', unsafe_allow_html=True)
    
    st.markdown(f"""<div class="fixed-box" style="border: 2px solid #22c55e;">
<h4>📋 您的預約資訊摘要</h4>
<ul>
    <li><strong>預約稱呼：</strong>{st.session_state.form_data.get('name')}</li>
    <li><strong>服務方式：</strong>{st.session_state.form_data.get('service_type')}</li>
    <li><strong>預約日期：</strong>{st.session_state.form_data.get('booking_date')}</li>
    <li><strong>預約時間：</strong>{st.session_state.form_data.get('booking_start')} ~ {st.session_state.form_data.get('booking_end')} ({st.session_state.form_data.get('duration_label')})</li>
    <li><strong>預計費用：</strong>NT$ {st.session_state.form_data.get('total_price')} 元</li>
</ul>
<p style="margin-top: 15px;">已將您的預約紀錄同步送出。笑長會在核對轉帳憑證後，於預約時間前透過 LINE 與您聯繫！</p>
</div>""", unsafe_allow_html=True)
    
    st.markdown('<div style="text-align: center; margin-top: 20px;"><a href="https://lin.ee/77h6NpL" target="_blank" style="background-color: #06C755; color: white; padding: 14px 28px; border-radius: 30px; text-decoration: none; font-weight: bold; font-size: 18px; display: inline-block;">💬 點擊加入心境整理室官方 LINE 好友</a></div>', unsafe_allow_html=True)
    st.markdown("<br><br>", unsafe_allow_html=True)
    
    if st.button("返回預約首頁"):
        st.session_state.step = 0
        st.session_state.form_data = {}
        st.rerun()

# ==========================================
# 🔐 笑長專屬後台管理區塊
# ==========================================
st.markdown("<br><hr><br>", unsafe_allow_html=True)
with st.expander("🔐 笑長專屬後台管理區（點擊展開）"):
    input_pwd = st.text_input("請輸入笑長管理密碼：", type="password")
    if input_pwd == ADMIN_PASSWORD:
        st.success("🔓 密碼正確，已解鎖笑長後台管理控制台！")
        
        booked_db = load_json_file(BOOKING_DB_PATH, [])
        st.write(f"📊 目前已佔用預約時段總筆數：{len(booked_db)} 筆")
        
        if booked_db:
            for idx, item in enumerate(booked_db):
                st.markdown(f"**[{idx+1}] {item['date']} ({item['start']}~{item['end']})** - {item['name']} | {item.get('service_type', '未設定')} | 憑證：`{item.get('receipt_name', '無')}`")
                
                # 顯示圖片預覽與刪除按鈕
                rec_path = os.path.normpath(os.path.join(UPLOAD_DIR, item.get('receipt_name', '')))
                if os.path.exists(rec_path):
                    st.image(rec_path, width=250)
                
                if st.button(f"🗑️ 刪除此筆預約並釋放時段 #{idx+1}"):
                    # 1. 刪除資料庫條目
                    deleted_item = booked_db.pop(idx)
                    save_json_file(BOOKING_DB_PATH, booked_db)
                    
                    # 2. 同步刪除實體付款圖片
                    if os.path.exists(rec_path):
                        try: os.remove(rec_path)
                        except: pass
                        
                    st.success(f"✅ 已成功釋放 {deleted_item['date']} {deleted_item['start']} 時段！")
                    st.rerun()
                st.markdown("---")
        else:
            st.info("目前尚無任何預約時段紀錄。")
