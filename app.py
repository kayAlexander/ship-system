import streamlit as st
import pandas as pd
import os
import hashlib
from datetime import datetime, date
import shutil
from filelock import FileLock
from dotenv import load_dotenv
import uuid
import time
import json
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
import tempfile

# ====================== 基础配置 ======================
load_dotenv()

st.set_page_config(
    page_title="🚢 船舶航次审批系统",
    layout="centered",
    initial_sidebar_state="collapsed",
    page_icon="🚢"
)

ENCRYPT_SALT = os.getenv("ENCRYPT_SALT", "ship_approval_2026")

# 船舶固定信息
SHIP_INFO = {
    "凡恒188": {"船籍港": "连云港", "最大载客人数": 17},
    "航瑞运维502": {"船籍港": "连云港", "最大载客人数": 18},
    "明德169": {"船籍港": "盐城", "最大载客人数": 17}
}

# 路径配置
CREW_BASE_DIR = "crew_base_data"
CREW_BASE_FILE = os.path.join(CREW_BASE_DIR, "crew_master_list.csv")
DATA_DIR = "ship_data"
DATA_FILES = {
    "ship_info": os.path.join(DATA_DIR, "ship_info.csv"),
    "crew_info": os.path.join(DATA_DIR, "crew_info.csv"),
    "check_info": os.path.join(DATA_DIR, "check_info.csv"),
    "approval_info": os.path.join(DATA_DIR, "approval_info.csv"),
    "first_sea_info": os.path.join(DATA_DIR, "first_sea_info.csv"),
    "photo_records": os.path.join(DATA_DIR, "photo_records.json")
}
PHOTO_DIR = "ship_photos"

# 无需上传照片的检查项
NO_PHOTO_ITEMS = [
    "船舶证书有效性", "消防设备", "救生设备",
    "油水储备", "应急演练记录", "天气海况确认"
]

# 所有检查项（含新增：是否已完成人员上船登记）
ALL_CHECK_ITEMS = [
    "船舶证书有效性", "船员证书有效性", "通讯设备", "消防设备", "救生设备",
    "航行设备", "动力设备", "油水储备", "货物绑扎", "乘员安全帽救生衣情况",
    "应急演练记录", "天气海况确认", "是否有人穿戴拖鞋", "是否有人第一次出海",
    "是否已完成人员上船登记"
]

# ====================== 初始化 ======================
def init_files():
    os.makedirs(CREW_BASE_DIR, exist_ok=True)
    if not os.path.exists(CREW_BASE_FILE):
        crew_df = pd.DataFrame({
            "船名": pd.Series(dtype=str), "船员姓名": pd.Series(dtype=str),
            "身份证号": pd.Series(dtype=str), "手机号": pd.Series(dtype=str), "是否有效": pd.Series(dtype=bool)
        })
        crew_df.to_csv(CREW_BASE_FILE, index=False, encoding="utf-8-sig")

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)

    for file_path in DATA_FILES.values():
        if not os.path.exists(file_path):
            if "ship_info" in file_path:
                df = pd.DataFrame(columns=[
                    "航次编号", "船名", "船籍港", "最大载客人数", "实际载客人数",
                    "出海任务", "出海携带货物", "拟计划回港时间", "出发港", "目的港",
                    "开航时间", "提交时间", "审核状态", "审核意见"
                ])
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            elif "crew_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "船员姓名", "身份证号", "手机号", "照片路径"])
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            elif "check_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "检查项名称", "检查结果", "照片路径"])
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            elif "approval_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "审核人", "审核时间", "审核状态", "审核意见"])
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            elif "first_sea_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "人数", "姓名", "电话", "身份证号"])
                df.to_csv(file_path, index=False, encoding="utf-8-sig")
            elif "photo_records" in file_path:
                # 修复：写入无BOM的UTF-8 JSON
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump({}, f)

init_files()

# ====================== 工具函数 ======================
def read_csv_with_lock(file_path):
    lock = FileLock(f"{file_path}.lock", timeout=10)
    with lock:
        time.sleep(0.05)
        dtype_spec = {}
        if "crew_master_list" in file_path:
            dtype_spec = {"船名": str, "船员姓名": str, "身份证号": str, "手机号": str, "是否有效": bool}
        return pd.read_csv(file_path, encoding="utf-8-sig", dtype=dtype_spec)

def write_csv_with_lock(df, file_path):
    lock = FileLock(f"{file_path}.lock", timeout=10)
    with lock:
        time.sleep(0.05)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")

def encrypt_data(raw_str):
    if not raw_str: return ""
    return hashlib.sha256((str(raw_str).strip() + ENCRYPT_SALT).encode()).hexdigest()

def desensitize_id(id_str):
    """公网版身份证脱敏：只显示前6后4，中间隐藏"""
    id_str = str(id_str).strip()
    if len(id_str) == 18:
        return f"{id_str[:6]}**********{id_str[-4:]}"
    return "信息脱敏保护"

def desensitize_phone(phone_str):
    """公网版手机号脱敏：只显示前3后4"""
    phone_str = str(phone_str).strip()
    if len(phone_str) == 11:
        return f"{phone_str[:3]}****{phone_str[-4:]}"
    return "信息脱敏保护"

def generate_voyage_id():
    today = date.today().strftime("%Y%m%d")
    ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
    seq = len(ship_df[ship_df["航次编号"].str.startswith(f"V{today}", na=False)]) + 1
    return f"V{today}{seq:03d}"

# ====================== 多图管理（修复JSON BOM问题） ======================
def save_photo(photo_file, voyage_id, item_name, photo_type="check"):
    if not photo_file: return None
    voyage_dir = os.path.join(PHOTO_DIR, voyage_id)
    os.makedirs(voyage_dir, exist_ok=True)
    ext = photo_file.name.split('.')[-1] if '.' in photo_file.name else 'jpg'
    fname = f"{photo_type}_{item_name}_{uuid.uuid4()}.{ext}"
    path = os.path.join(voyage_dir, fname)
    with open(path, "wb") as f:
        f.write(photo_file.getbuffer())
    return path

def save_photo_records(voyage_id, item_name, paths, typ="check"):
    # 修复：兼容BOM头读取，增加异常捕获
    with open(DATA_FILES["photo_records"], "r", encoding="utf-8-sig") as f:
        try:
            r = json.load(f)
        except json.decoder.JSONDecodeError:
            r = {}
    key = f"{voyage_id}_{typ}_{item_name}"
    r[key] = paths
    # 修复：写入无BOM的UTF-8
    with open(DATA_FILES["photo_records"], "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)

def get_photo_records(voyage_id, item_name, typ="check"):
    if not os.path.exists(DATA_FILES["photo_records"]):
        return []
    # 修复：使用 utf-8-sig 读取，自动去除BOM，增加异常捕获
    with open(DATA_FILES["photo_records"], "r", encoding="utf-8-sig") as f:
        try:
            r = json.load(f)
        except json.decoder.JSONDecodeError:
            # 文件损坏时返回空列表
            return []
    return r.get(f"{voyage_id}_{typ}_{item_name}", [])

def delete_photo(path, voyage_id, item_name, typ="check"):
    if os.path.exists(path):
        os.remove(path)
    lst = get_photo_records(voyage_id, item_name, typ)
    if path in lst:
        lst.remove(path)
        save_photo_records(voyage_id, item_name, lst, typ)
    return True

# ====================== 船员管理 ======================
def get_crew_list(ship_name):
    df = read_csv_with_lock(CREW_BASE_FILE)
    return df[(df["船名"] == ship_name) & (df["是否有效"] == True)].reset_index(drop=True)

def add_crew(ship_name, crew_data):
    df = read_csv_with_lock(CREW_BASE_FILE)
    add = []
    for c in crew_data:
        name = c["name"].strip()
        cid = c["id"].strip()
        phone = c["phone"].strip()
        if name and cid and phone and not ((df["船名"] == ship_name) & (df["身份证号"] == cid)).any():
            add.append({"船名": ship_name, "船员姓名": name, "身份证号": cid, "手机号": phone, "是否有效": True})
    if add:
        df = pd.concat([df, pd.DataFrame(add)], ignore_index=True)
        write_csv_with_lock(df, CREW_BASE_FILE)

def delete_crew(ship_name, cid):
    df = read_csv_with_lock(CREW_BASE_FILE)
    mask = (df["船名"] == ship_name) & (df["身份证号"] == cid.strip())
    if mask.any():
        df.loc[mask, "是否有效"] = False
        write_csv_with_lock(df, CREW_BASE_FILE)
        return True
    return False

# ====================== 登录 ======================
def login_module():
    st.title("🚢 船舶航次审批系统")
    role = st.radio("选择角色", ["船方人员", "后台审批人员"], key="login_role")
    pwd = st.text_input("输入密码", type="password", key="login_pwd")
    
    # 🔐 公网强密码（你可以后续自己改，现在先按这个来）
    SHIP_PWD = "Ship@20260315"  # 船方密码（复杂且安全）
    ADMIN_PWD = "Admin@2026#123" # 管理员密码
    
    if st.button("登录", key="login_btn", use_container_width=True):
        if role == "船方人员" and pwd == SHIP_PWD:
            st.session_state["logged_in"] = True
            st.session_state["role"] = "ship"
            st.rerun()
        elif role == "后台审批人员" and pwd == ADMIN_PWD:
            st.session_state["logged_in"] = True
            st.session_state["role"] = "admin"
            st.rerun()
        else:
            st.error("❌ 密码错误，请重新输入")

# ====================== 航次录入 ======================
def ship_info_input():
    st.subheader("📝 航次信息录入")

    ship_name = st.selectbox("🔍 选择船舶", list(SHIP_INFO.keys()))
    port = SHIP_INFO[ship_name]["船籍港"]
    maxp = SHIP_INFO[ship_name]["最大载客人数"]

    st.markdown("### 🚢 船舶信息")
    c1, c2 = st.columns(2)
    with c1: st.text_input("船籍港", value=port, disabled=True)
    with c2: st.number_input("最大载客", value=maxp, disabled=True)

    actual = st.number_input("👥 实际载客人数", min_value=1)
    if actual > maxp:
        st.error(f"⚠️ 已超员：{actual}/{maxp}")

    st.markdown("### 📋 航次信息")
    c1, c2 = st.columns(2)
    with c1:
        dep = st.text_input("出发港")
        dest = st.text_input("目的港")
        sail = st.datetime_input("计划开航时间")
    with c2:
        task = st.text_input("出海任务")
        cargo = st.text_input("携带货物")
        ret = st.datetime_input("计划回港时间")

    # 船员
    st.markdown("### 👨‍✈️ 船员信息")
    crew_df = get_crew_list(ship_name)
    if "preview_photos" not in st.session_state:
        st.session_state.preview_photos = {}

    crew_list = []

    if not crew_df.empty:
        st.markdown("#### 现有船员")
        for i, row in crew_df.iterrows():
            name = row["船员姓名"]
            st.markdown(f"**{name}**")
            c1, c2, c3 = st.columns(3)
            with c1: st.write(f"身份证：{desensitize_id(row['身份证号'])}")
            with c2: st.write(f"手机：{desensitize_phone(row['手机号'])}")
            with c3:
                if st.button(f"删除 {name}", key=f"del{i}"):
                    delete_crew(ship_name, row["身份证号"])
                    st.rerun()

            photos = st.file_uploader(f"上传{name}照片", type=["png","jpg"], accept_multiple_files=True, key=f"cp{i}")
            paths = []
            if photos:
                cols = st.columns(4)
                for j, p in enumerate(photos):
                    with cols[j%4]:
                        st.image(p, width=80)
                        paths.append(save_photo(p, "temp", name, "crew"))

            exist = get_photo_records("temp", name, "crew")
            for j, p in enumerate(exist):
                cols = st.columns(4)
                with cols[j%4]:
                    st.image(p, width=80)
                    if st.button(f"删照片{j+1}", key=f"dc{i}{j}"):
                        delete_photo(p, "temp", name, "crew")
                        st.rerun()

            crew_list.append({
                "name": name, "id": row["身份证号"], "phone": row["手机号"],
                "photos": paths + exist
            })

    # 新增船员
    if st.checkbox("➕ 新增船员"):
        n = st.number_input("数量", 1,5,1)
        for i in range(n):
            st.markdown(f"新船员{i+1}")
            c1,c2 = st.columns(2)
            with c1:
                nn = st.text_input("姓名", key=f"nn{i}")
                cid = st.text_input("身份证", key=f"cid{i}")
            with c2:
                phone = st.text_input("手机号", key=f"phone{i}")
                ps = st.file_uploader("照片", accept_multiple_files=True, key=f"np{i}")
            ppaths = []
            if ps:
                for p in ps:
                    ppaths.append(save_photo(p, "temp", nn or f"new{i}", "crew"))
            if nn and cid and phone:
                crew_list.append({
                    "name": nn, "id": cid, "phone": phone, "photos": ppaths
                })

    # 开航检查（含新项）
    st.markdown("### ✅ 开航前检查")
    check_results = []
    first_sea = False

    for item in ALL_CHECK_ITEMS:
        st.markdown(f"**{item}**")
        c1, c2 = st.columns([1,3])
        res = "合格"
        with c1:
            if item == "是否有人第一次出海":
                res = st.selectbox("", ["是","否"], key=f"c_{item}", index=1)
                first_sea = (res == "是")
            elif item in ["是否有人穿戴拖鞋", "是否已完成人员上船登记"]:
                res = st.selectbox("", ["是","否"], key=f"c_{item}")
            else:
                res = st.selectbox("", ["合格","不合格"], key=f"c_{item}")

        with c2:
            if item in NO_PHOTO_ITEMS + ["是否有人穿戴拖鞋", "是否有人第一次出海"]:
                st.write("无需上传照片")
                check_results.append({"item": item, "result": res, "photos": []})
            else:
                st.markdown("📷 可传多张照片")
                uploads = st.file_uploader("", type=["png","jpg"], accept_multiple_files=True, key=f"cu_{item}")
                temps = []
                if uploads:
                    cols = st.columns(4)
                    for j,p in enumerate(uploads):
                        with cols[j%4]:
                            st.image(p, width=80)
                            temps.append(save_photo(p, "temp", item, "check"))
                exist_p = get_photo_records("temp", item, "check")
                for j,p in enumerate(exist_p):
                    cols = st.columns(4)
                    with cols[j%4]:
                        st.image(p, width=80)
                        if st.button(f"删除照片{j+1}", key=f"del_{item}_{j}"):
                            delete_photo(p, "temp", item, "check")
                            st.rerun()
                check_results.append({
                    "item": item, "result": res, "photos": temps + exist_p
                })

    # 首次出海
    first_data = []
    if first_sea:
        st.markdown("### 🆕 首次出海人员")
        cnt = st.number_input("人数", 1)
        for i in range(cnt):
            c1,c2,c3 = st.columns(3)
            with c1: n = st.text_input("姓名", key=f"f{i}")
            with c2: p = st.text_input("手机", key=f"fp{i}")
            with c3: c = st.text_input("身份证", key=f"fc{i}")
            first_data.append({"name":n,"phone":p,"id":c})

    # 提交
    if st.button("📤 提交审批", type="primary", use_container_width=True):
        ok = True
        if not crew_list:
            st.error("至少1名船员")
            ok=False
        for c in crew_list:
            if not c["name"] or not c["id"] or len(c["id"])!=18 or len(c["phone"])!=11:
                st.error(f"船员{c['name']}信息格式错误")
                ok=False
        for chk in check_results:
            if chk["item"] not in NO_PHOTO_ITEMS + ["是否有人穿戴拖鞋", "是否有人第一次出海"] and not chk["photos"]:
                st.error(f"{chk['item']} 必须上传照片")
                ok=False
        if first_sea:
            for f in first_data:
                if not f["name"] or not f["phone"] or not f["id"]:
                    st.error("首次出海信息不完整")
                    ok=False
        if not ok:
            return

        vid = generate_voyage_id()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 保存航次
        ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
        new_ship = pd.DataFrame({
            "航次编号": [vid], "船名": [ship_name], "船籍港": [port],
            "最大载客人数": [maxp], "实际载客人数": [actual],
            "出海任务": [task], "出海携带货物": [cargo],
            "拟计划回港时间": [ret.strftime("%Y-%m-%d %H:%M:%S")],
            "出发港": [dep], "目的港": [dest],
            "开航时间": [sail.strftime("%Y-%m-%d %H:%M:%S")],
            "提交时间": [now], "审核状态": ["待审批"], "审核意见": [""]
        })
        ship_df = pd.concat([ship_df, new_ship], ignore_index=True)
        write_csv_with_lock(ship_df, DATA_FILES["ship_info"])

        # 船员照片
        cdf = read_csv_with_lock(DATA_FILES["crew_info"])
        for c in crew_list:
            nps = []
            for p in c["photos"]:
                if p and "temp" in p:
                    np = p.replace("temp", vid)
                    os.makedirs(os.path.dirname(np), exist_ok=True)
                    shutil.move(p, np)
                    nps.append(np)
            save_photo_records(vid, c["name"], nps, "crew")
            cdf = pd.concat([cdf, pd.DataFrame([{
                "航次编号": vid, "船员姓名": c["name"],
                "身份证号": encrypt_data(c["id"]),
                "手机号": encrypt_data(c["phone"]),
                "照片路径": ",".join(nps)
            }])], ignore_index=True)
        write_csv_with_lock(cdf, DATA_FILES["crew_info"])

        # 检查项
        chk_df = read_csv_with_lock(DATA_FILES["check_info"])
        for ch in check_results:
            nps = []
            for p in ch["photos"]:
                if p and "temp" in p:
                    np = p.replace("temp", vid)
                    os.makedirs(os.path.dirname(np), exist_ok=True)
                    shutil.move(p, np)
                    nps.append(np)
            save_photo_records(vid, ch["item"], nps, "check")
            chk_df = pd.concat([chk_df, pd.DataFrame([{
                "航次编号": vid, "检查项名称": ch["item"],
                "检查结果": ch["result"], "照片路径": ",".join(nps)
            }])], ignore_index=True)
        write_csv_with_lock(chk_df, DATA_FILES["check_info"])

        # 首次出海
        if first_sea and first_data:
            fs_df = read_csv_with_lock(DATA_FILES["first_sea_info"])
            rows = []
            for f in first_data:
                rows.append({
                    "航次编号": vid, "人数": len(first_data), "姓名": f["name"],
                    "电话": encrypt_data(f["phone"]), "身份证号": encrypt_data(f["id"])
                })
            fs_df = pd.concat([fs_df, pd.DataFrame(rows)], ignore_index=True)
            write_csv_with_lock(fs_df, DATA_FILES["first_sea_info"])

        add_crew(ship_name, crew_list)

        st.success(f"""
🎉 提交成功！
航次编号：{vid}
船舶：{ship_name}
当前状态：待审批
请等待管理员审批后执行开航任务！
        """)
        st.balloons()

# ====================== 查询 ======================
def ship_voyage_query():
    st.subheader("🔍 航次查询")
    df = read_csv_with_lock(DATA_FILES["ship_info"])
    if df.empty:
        st.info("无记录")
        return
    vid = st.selectbox("选择航次", df["航次编号"])
    info = df[df["航次编号"]==vid].iloc[0]

    st.markdown(f"### 📋 {vid}")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.write(f"船名：{info['船名']}")
        st.write(f"船籍港：{info['船籍港']}")
        st.write(f"载客：{info['实际载客人数']}/{info['最大载客人数']}")
    with c2:
        st.write(f"任务：{info['出海任务']}")
        st.write(f"出发：{info['出发港']} → {info['目的港']}")
    with c3:
        st.write(f"开航：{info['开航时间']}")
        st.write(f"状态：{info['审核状态']}")
        if info["审核意见"]:
            if info["审核状态"] == "驳回":
                st.error(f"理由：{info['审核意见']}")
            else:
                st.success(f"意见：{info['审核意见']}")

    st.markdown("### ✅ 检查项")
    ckdf = read_csv_with_lock(DATA_FILES["check_info"])
    ck = ckdf[ckdf["航次编号"]==vid]
    for _, r in ck.iterrows():
        st.markdown(f"**{r['检查项名称']}**")
        if r["检查结果"] in ["合格","否"]:
            st.success(r["检查结果"])
        else:
            st.error(r["检查结果"])
        paths = r["照片路径"].split(",") if pd.notna(r["照片路径"]) else []
        cols = st.columns(4)
        for i,p in enumerate(paths):
            if p and os.path.exists(p):
                with cols[i%4]:
                    st.image(p, width=80)

    st.markdown("### 👨‍✈️ 船员")
    cdf = read_csv_with_lock(DATA_FILES["crew_info"])
    for _, r in cdf[cdf["航次编号"]==vid].iterrows():
        st.markdown(f"**{r['船员姓名']}**")
        st.write(f"身份证：{desensitize_id(r['身份证号'])}  手机：{desensitize_phone(r['手机号'])}")
        paths = r["照片路径"].split(",") if pd.notna(r["照片路径"]) else []
        cols = st.columns(4)
        for i,p in enumerate(paths):
            if p and os.path.exists(p):
                with cols[i%4]:
                    st.image(p, width=80)

# ====================== 审批日志生成 ======================
def generate_approval_pdf(voyage_id):
    """生成航次审批日志PDF（使用内置中文字体，永不报错 TTFError）"""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.fonts import addMapping
    import os
    import tempfile

    # ====================== 🔥 终极方案：内置中文字体，不需要任何外部 TTF 文件！======================
    # 这行代码直接解决 TTFError，不管本地/云端都 100% 运行
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    CHINESE_FONT = 'STSong-Light'

    # 获取航次基础信息
    ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
    ship_info = ship_df[ship_df["航次编号"] == voyage_id].iloc[0]

    # 获取审批信息
    approval_df = read_csv_with_lock(DATA_FILES["approval_info"])
    approval_info = approval_df[approval_df["航次编号"] == voyage_id].iloc[0] if not approval_df[approval_df["航次编号"] == voyage_id].empty else None

    # 获取船员信息
    crew_df = read_csv_with_lock(DATA_FILES["crew_info"])
    crew_info = crew_df[crew_df["航次编号"] == voyage_id]

    # 获取检查项信息
    check_df = read_csv_with_lock(DATA_FILES["check_info"])
    check_info = check_df[check_df["航次编号"] == voyage_id]

    # 创建临时PDF文件
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    doc = SimpleDocTemplate(temp_file.name, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    # 标题
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontName=CHINESE_FONT,
        fontSize=16,
        alignment=1,
        spaceAfter=30,
        textColor=colors.darkblue
    )
    elements.append(Paragraph(f"船舶航次审批日志 - {voyage_id}", title_style))

    # 航次基础信息
    normal_style = ParagraphStyle(
        'NormalCN',
        parent=styles['Normal'],
        fontName=CHINESE_FONT,
        fontSize=11,
        leading=14
    )
    elements.append(Paragraph("一、航次基础信息", normal_style))

    ship_data = [
        ["船名", ship_info.get("船名", "")],
        ["船籍港", ship_info.get("船籍港", "")],
        ["最大载客人数", str(ship_info.get("最大载客人数", ""))],
        ["实际载客人数", str(ship_info.get("实际载客人数", ""))],
        ["出海任务", ship_info.get("出海任务", "")],
        ["携带货物", ship_info.get("出海携带货物", "")],
        ["出发港", ship_info.get("出发港", "")],
        ["目的港", ship_info.get("目的港", "")],
        ["计划开航时间", ship_info.get("开航时间", "")],
        ["计划回港时间", ship_info.get("拟计划回港时间", "")],
        ["提交时间", ship_info.get("提交时间", "")]
    ]
    ship_table = Table(ship_data, colWidths=[150, 400])
    ship_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(ship_table)
    elements.append(Spacer(1, 20))

    # 审批信息
    if approval_info is not None:
        elements.append(Paragraph("二、审批信息", normal_style))
        approval_data = [
            ["审核人", approval_info.get("审核人", "")],
            ["审核时间", approval_info.get("审核时间", "")],
            ["审核状态", approval_info.get("审核状态", "")],
            ["审核意见", approval_info.get("审核意见", "")]
        ]
        approval_table = Table(approval_data, colWidths=[150, 400])
        approval_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgreen),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(approval_table)
        elements.append(Spacer(1, 20))

    # 船员信息
    elements.append(Paragraph("三、船员信息", normal_style))
    crew_data = [["姓名", "身份证号（脱敏）", "手机号（脱敏）"]]
    for _, row in crew_info.iterrows():
        crew_data.append([
            row.get("船员姓名", ""),
            desensitize_id(row.get("身份证号", "")),
            desensitize_phone(row.get("手机号", ""))
        ])
    crew_table = Table(crew_data, colWidths=[100, 200, 200])
    crew_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightyellow),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(crew_table)
    elements.append(Spacer(1, 20))

    # 检查项信息
    elements.append(Paragraph("四、开航前检查", normal_style))
    check_data = [["检查项", "检查结果"]]
    for _, row in check_info.iterrows():
        check_data.append([
            row.get("检查项名称", ""),
            row.get("检查结果", "")
        ])
    check_table = Table(check_data, colWidths=[300, 200])
    check_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightcoral),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(check_table)

    # 生成PDF
    doc.build(elements)
    return temp_file.name

# ====================== 审批（含已审批查询+高清照片） ======================
def admin_approval():
    st.subheader("📋 后台审批管理")
    
    # 切换待审批/已审批
    view_mode = st.radio("查看模式", ["待审批航次", "已审批航次"], key="view_mode")
    
    if "show_full" not in st.session_state:
        st.session_state.show_full = False

    pwd = st.sidebar.text_input("管理员密码", type="password")
    if st.sidebar.button("验证"):
        if pwd == "Admin@2026#123":  # 统一管理员密码
            st.session_state.show_full = True
            st.sidebar.success("✅ 已验证")
        else:
            st.sidebar.error("密码错误")

    df = read_csv_with_lock(DATA_FILES["ship_info"])
    
    # 筛选航次
    if view_mode == "待审批航次":
        target_df = df[df["审核状态"]=="待审批"]
    else:
        target_df = df[df["审核状态"].isin(["通过", "驳回"])]
    
    if target_df.empty:
        st.info(f"无{view_mode}记录")
        return

    vid = st.selectbox("选择航次", target_df["航次编号"])
    info = target_df[target_df["航次编号"]==vid].iloc[0]

    st.markdown(f"### {vid}")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.write(f"船名：{info['船名']}")
        st.write(f"载客：{info['实际载客人数']}/{info['最大载客人数']}")
    with c2:
        st.write(f"任务：{info['出海任务']}")
        st.write(f"路线：{info['出发港']} → {info['目的港']}")
    with c3:
        st.write(f"提交：{info['提交时间']}")
        st.write(f"状态：{info['审核状态']}")
        if info["审核意见"]:
            st.write(f"意见：{info['审核意见']}")

    # 检查项（高清照片）
    st.markdown("### ✅ 检查项")
    ckdf = read_csv_with_lock(DATA_FILES["check_info"])
    for _, r in ckdf[ckdf["航次编号"]==vid].iterrows():
        st.markdown(f"**{r['检查项名称']}**")
        if r["检查结果"] in ["合格","否"]:
            st.success(r["检查结果"])
        else:
            st.error(r["检查结果"])
        
        # 高清照片展示
        paths = r["照片路径"].split(",") if pd.notna(r["照片路径"]) else []
        if paths and paths[0]:
            # 主照片（高清）
            main_photo = paths[0]
            if os.path.exists(main_photo):
                st.image(main_photo, caption=f"{r['检查项名称']} - 高清原图", use_column_width=True)
            
            # 其他照片（缩略图+高清查看）
            if len(paths) > 1:
                st.markdown("#### 其他照片")
                cols = st.columns(4)
                for i,p in enumerate(paths[1:]):
                    if p and os.path.exists(p):
                        with cols[i%4]:
                            st.image(p, width=80)
                            # 高清查看按钮
                            if st.button(f"查看高清{i+1}", key=f"hd_{r['检查项名称']}_{i}"):
                                st.image(p, caption=f"高清照片{i+1}", use_column_width=True)

    # 船员（高清照片）
    st.markdown("### 👨‍✈️ 船员")
    cdf = read_csv_with_lock(DATA_FILES["crew_info"])
    crew_master = get_crew_list(info["船名"])
    for _, r in cdf[cdf["航次编号"]==vid].iterrows():
        st.markdown(f"**{r['船员姓名']}**")
        if st.session_state.show_full:
            match = crew_master[crew_master["船员姓名"]==r["船员姓名"]]
            cid = match.iloc[0]["身份证号"] if not match.empty else desensitize_id(r["身份证号"])
            phone = match.iloc[0]["手机号"] if not match.empty else desensitize_phone(r["手机号"])
            st.write(f"身份证：{cid}   手机：{phone}")
        else:
            st.write(f"身份证：{desensitize_id(r['身份证号'])}   手机：{desensitize_phone(r['手机号'])}")
        
        # 高清照片展示
        paths = r["照片路径"].split(",") if pd.notna(r["照片路径"]) else []
        if paths and paths[0]:
            main_photo = paths[0]
            if os.path.exists(main_photo):
                st.image(main_photo, caption=f"{r['船员姓名']} - 高清原图", use_column_width=True)
            
            if len(paths) > 1:
                st.markdown("#### 其他照片")
                cols = st.columns(4)
                for i,p in enumerate(paths[1:]):
                    if p and os.path.exists(p):
                        with cols[i%4]:
                            st.image(p, width=80)
                            if st.button(f"查看高清{i+1}", key=f"hd_crew_{r['船员姓名']}_{i}"):
                                st.image(p, caption=f"高清照片{i+1}", use_column_width=True)

    # 审批操作（仅待审批航次显示）
    if view_mode == "待审批航次":
        st.markdown("### 审批操作")
        act = st.radio("审批结果", ["通过","驳回"], key=f"approval_{vid}")
        opinion = st.text_area("审批意见/理由", key=f"opinion_{vid}")
        if st.button("确认审批", type="primary", use_container_width=True):
            if not opinion:
                st.error("请填写审批意见")
                return
            
            # 更新航次状态
            df.loc[df["航次编号"]==vid, "审核状态"] = act
            df["审核意见"] = df["审核意见"].astype(object)
            df.loc[df["航次编号"]==vid, "审核意见"] = opinion
            write_csv_with_lock(df, DATA_FILES["ship_info"])

            # 记录审批日志
            log = read_csv_with_lock(DATA_FILES["approval_info"])
            log = pd.concat([log, pd.DataFrame([{
                "航次编号": vid, "审核人": "管理员", "审核时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "审核状态": act, "审核意见": opinion
            }])], ignore_index=True)
            write_csv_with_lock(log, DATA_FILES["approval_info"])

            st.success(f"✅ {vid} 已{act}")
            st.rerun()
    
    # 生成审批日志PDF（所有航次都可生成）
    st.markdown("### 日志管理")
    if st.button("📄 生成审批日志PDF", use_container_width=True):
        with st.spinner("正在生成PDF..."):
            pdf_path = generate_approval_pdf(vid)
            with open(pdf_path, "rb") as f:
                st.download_button(
                    label="下载审批日志",
                    data=f,
                    file_name=f"{vid}_审批日志.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
        os.unlink(pdf_path)  # 删除临时文件
        st.success("PDF生成完成！")

# ====================== 主程序 ======================
def main():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        login_module()
        return

    st.title("🚢 船舶航次审批系统")
    if st.session_state.role == "ship":
        t1, t2 = st.tabs(["📝 航次录入", "🔍 航次查询"])
        with t1: ship_info_input()
        with t2: ship_voyage_query()
    else:
        admin_approval()

    if st.sidebar.button("🚪 退出登录"):
        st.session_state.logged_in = False
        st.rerun()

if __name__ == "__main__":
    main()