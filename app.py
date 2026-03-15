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

# ====================== 基础配置 ======================
load_dotenv()

# 适配手机显示
st.set_page_config(
    page_title="🚢 船舶航次审批系统",
    layout="centered",  # 适配手机
    initial_sidebar_state="collapsed",
    page_icon="🚢"
)

# 加密配置
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
    "check_info": os.path.join(DATA_DIR, "check_info.csv"),  # 新增检查项存储文件
    "approval_info": os.path.join(DATA_DIR, "approval_info.csv"),
    "first_sea_info": os.path.join(DATA_DIR, "first_sea_info.csv")
}
PHOTO_DIR = "ship_photos"

# 无需上传照片的检查项
NO_PHOTO_ITEMS = [
    "船舶证书有效性", "消防设备", "救生设备", 
    "油水储备", "应急演练记录", "天气海况确认"
]

# 所有检查项列表（统一管理）
ALL_CHECK_ITEMS = [
    "船舶证书有效性", "船员证书有效性", "通讯设备", "消防设备", "救生设备",
    "航行设备", "动力设备", "油水储备", "货物绑扎", "乘员安全帽救生衣情况",
    "应急演练记录", "天气海况确认", "是否有人穿戴拖鞋", "是否有人第一次出海"
]

# ====================== 初始化函数 ======================
def init_files():
    # 初始化船员主名单
    os.makedirs(CREW_BASE_DIR, exist_ok=True)
    if not os.path.exists(CREW_BASE_FILE):
        crew_df = pd.DataFrame({
            "船名": pd.Series(dtype=str),
            "船员姓名": pd.Series(dtype=str),
            "身份证号": pd.Series(dtype=str),
            "手机号": pd.Series(dtype=str),
            "是否有效": pd.Series(dtype=bool)
        })
        crew_df.to_csv(CREW_BASE_FILE, index=False, encoding="utf-8-sig")
    
    # 初始化业务文件
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)
    for file_path in DATA_FILES.values():
        if not os.path.exists(file_path):
            if "ship_info" in file_path:
                df = pd.DataFrame(columns=[
                    "航次编号", "船名", "船籍港", "最大载客人数", "实际载客人数",
                    "出海任务", "出海携带货物", "拟计划回港时间",
                    "出发港", "目的港", "开航时间", "提交时间", "审核状态", "审核意见"
                ])
            elif "crew_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "船员姓名", "身份证号", "手机号", "照片路径"])
            elif "check_info" in file_path:  # 初始化检查项表
                df = pd.DataFrame(columns=["航次编号", "检查项名称", "检查结果", "照片路径"])
            elif "approval_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "审核人", "审核时间", "审核状态", "审核意见"])
            elif "first_sea_info" in file_path:
                df = pd.DataFrame(columns=["航次编号", "人数", "姓名", "电话", "身份证号"])
            df.to_csv(file_path, index=False, encoding="utf-8-sig")

init_files()

# ====================== 核心工具函数 ======================
def read_csv_with_lock(file_path):
    lock = FileLock(f"{file_path}.lock", timeout=10)
    with lock:
        time.sleep(0.1)
        dtype_spec = {}
        if "crew_master_list" in file_path:
            dtype_spec = {"船名": str, "船员姓名": str, "身份证号": str, "手机号": str, "是否有效": bool}
        return pd.read_csv(file_path, encoding="utf-8-sig", dtype=dtype_spec)

def write_csv_with_lock(df, file_path):
    lock = FileLock(f"{file_path}.lock", timeout=10)
    with lock:
        time.sleep(0.1)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")

def encrypt_data(raw_str):
    if isinstance(raw_str, int):
        raw_str = str(raw_str)
    return hashlib.sha256((str(raw_str).strip() + ENCRYPT_SALT).encode()).hexdigest() if raw_str else ""

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

def save_photo(photo_file, voyage_id, item_name):
    if not photo_file:
        return None
    voyage_dir = os.path.join(PHOTO_DIR, voyage_id)
    os.makedirs(voyage_dir, exist_ok=True)
    file_ext = photo_file.name.split('.')[-1] if '.' in photo_file.name else 'jpg'
    file_name = f"{item_name}_{uuid.uuid4()}.{file_ext}"
    photo_path = os.path.join(voyage_dir, file_name)
    with open(photo_path, "wb") as f:
        f.write(photo_file.getbuffer())
    return photo_path

# 船员管理函数
def get_crew_list(ship_name):
    df = read_csv_with_lock(CREW_BASE_FILE)
    return df[(df["船名"] == ship_name) & (df["是否有效"] == True)].reset_index(drop=True)

def add_crew(ship_name, crew_data):
    df = read_csv_with_lock(CREW_BASE_FILE)
    new_crews = []
    for crew in crew_data:
        name = crew["name"].strip()
        id_card = crew["id"].strip()
        phone = crew["phone"].strip()
        if name and id_card and phone and not ((df["船名"] == ship_name) & (df["身份证号"] == id_card)).any():
            new_crews.append({
                "船名": ship_name,
                "船员姓名": name,
                "身份证号": id_card,
                "手机号": phone,
                "是否有效": True
            })
    if new_crews:
        df = pd.concat([df, pd.DataFrame(new_crews)], ignore_index=True)
        write_csv_with_lock(df, CREW_BASE_FILE)

def delete_crew(ship_name, id_card):
    df = read_csv_with_lock(CREW_BASE_FILE)
    mask = (df["船名"] == ship_name) & (df["身份证号"] == id_card.strip())
    if mask.any():
        df.loc[mask, "是否有效"] = False
        write_csv_with_lock(df, CREW_BASE_FILE)
        return True
    return False

# ====================== 登录模块 ======================
def login_module():
    st.title("🚢 船舶航次审批系统")
    role = st.radio("选择角色", ["船方人员", "后台审批人员"], key="login_role")
    pwd = st.text_input("输入密码", type="password", key="login_pwd")
    
    # 🔐 公网强密码（可以后续自己改）
    SHIP_PWD = "Ship@20260315"  # 船方密码
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

# ====================== 航次录入模块 ======================
def ship_info_input():
    st.subheader("📝 航次信息录入")
    
    # 1. 船舶选择
    ship_name = st.selectbox(
        "🔍 选择船舶", 
        list(SHIP_INFO.keys()), 
        key="ship_name",
        on_change=lambda: st.session_state.pop("preview_photos", None)
    )
    
    # 强制刷新船舶信息
    ship_data = SHIP_INFO[ship_name]
    port = ship_data["船籍港"]
    max_people = ship_data["最大载客人数"]
    
    # 2. 船舶基础信息
    st.markdown("### 🚢 船舶基础信息")
    col1, col2 = st.columns(2)
    with col1:
        st.text_input(
            "船籍港", 
            value=port, 
            disabled=True, 
            key=f"port_{ship_name}",
            help="船舶注册港口"
        )
    with col2:
        st.number_input(
            "最大载客人数（证书许可）", 
            value=max_people, 
            disabled=True, 
            key=f"max_people_{ship_name}",
            help="船舶证书许可的最大载客数量"
        )
    
    # 3. 实际载客人数（支持超员，仅提醒）
    actual_people = st.number_input(
        "👥 实际载客人数",
        min_value=1,
        value=1,
        key="actual_people",
        help="可输入超过最大限制的人数，系统仅提醒"
    )
    
    # 超员提醒
    if actual_people > max_people:
        st.error(f"⚠️ 警告：实际载客人数（{actual_people}人）已超过证书许可的最大人数（{max_people}人）！")
    else:
        st.success(f"✅ 实际载客人数（{actual_people}人）在证书许可范围内")
    
    # 4. 航次补充信息
    st.markdown("### 📋 航次任务信息")
    col1, col2 = st.columns(2)
    with col1:
        departure = st.text_input("出发港", key="departure", placeholder="例如：连云港码头")
        destination = st.text_input("目的港", key="destination", placeholder="例如：黄海作业区")
        sail_time = st.datetime_input("计划开航时间", key="sail_time")
    with col2:
        task = st.text_input("出海任务", key="task", placeholder="例如：海上作业、物资运输、巡查")
        cargo = st.text_input("出海携带货物", key="cargo", placeholder="例如：作业设备、生活物资、无")
        return_time = st.datetime_input("拟计划回港时间", key="return_time")
    
    # 5. 船员信息管理（带照片预览）
    st.markdown("### 👨‍✈️ 船员信息管理")
    crew_df = get_crew_list(ship_name)
    crew_data_list = []
    
    # 初始化照片预览缓存
    if "preview_photos" not in st.session_state:
        st.session_state["preview_photos"] = {}
    
    # 现有船员管理
    if not crew_df.empty:
        st.markdown("#### 现有船员（可删除离职人员）")
        for idx, row in crew_df.iterrows():
            crew_key = f"crew_{idx}"
            col1, col2, col3, col4 = st.columns([2, 3, 2, 3])
            
            with col1:
                st.write(f"**{row['船员姓名']}**")
            with col2:
                st.write(f"身份证：{desensitize_id(row['身份证号'])}")
            with col3:
                st.write(f"手机号：{desensitize_phone(row['手机号'])}")
            with col4:
                # 船员照片上传+实时预览
                photo_file = st.file_uploader(
                    "上传照片",
                    type=["jpg", "jpeg", "png"],
                    key=f"crew_photo_{idx}",
                    label_visibility="collapsed"
                )
                
                # 照片预览
                if photo_file:
                    st.session_state["preview_photos"][crew_key] = photo_file
                    st.image(
                        photo_file,
                        caption=f"{row['船员姓名']} 照片预览",
                        width=100,
                        use_column_width=False
                    )
                elif crew_key in st.session_state["preview_photos"]:
                    st.image(
                        st.session_state["preview_photos"][crew_key],
                        caption=f"{row['船员姓名']} 照片预览",
                        width=100,
                        use_column_width=False
                    )
            
            # 删除按钮
            if st.button(f"删除 {row['船员姓名']}", key=f"del_crew_{idx}", type="secondary"):
                if delete_crew(ship_name, row["身份证号"]):
                    st.success(f"✅ 已删除船员：{row['船员姓名']}")
                    st.rerun()
            
            # 收集船员数据
            crew_data_list.append({
                "name": row["船员姓名"],
                "id": row["身份证号"],
                "phone": row["手机号"],
                "photo": st.session_state["preview_photos"].get(crew_key)
            })
    
    # 新增船员（带照片预览）
    st.markdown("#### 添加新船员")
    if st.checkbox("➕ 新增船员", key="add_crew"):
        new_count = st.number_input("新增数量", min_value=1, max_value=5, value=1, key="new_crew_count")
        for i in range(new_count):
            st.markdown(f"##### 船员{i+1}")
            col1, col2 = st.columns(2)
            
            with col1:
                new_name = st.text_input("姓名", key=f"new_name_{i}", placeholder="请输入真实姓名")
                new_id = st.text_input("身份证号", key=f"new_id_{i}", placeholder="18位身份证号")
            with col2:
                new_phone = st.text_input("手机号", key=f"new_phone_{i}", placeholder="11位手机号")
                # 新增船员照片上传+预览
                new_photo = st.file_uploader(
                    "上传照片",
                    type=["jpg", "jpeg", "png"],
                    key=f"new_photo_{i}",
                    label_visibility="collapsed"
                )
                
                # 实时预览
                if new_photo:
                    st.session_state["preview_photos"][f"new_crew_{i}"] = new_photo
                    st.image(
                        new_photo,
                        caption="照片预览",
                        width=100,
                        use_column_width=False
                    )
            
            # 收集新增船员数据
            if new_name and new_id and new_phone:
                crew_data_list.append({
                    "name": new_name,
                    "id": new_id,
                    "phone": new_phone,
                    "photo": st.session_state["preview_photos"].get(f"new_crew_{i}")
                })
    
    # 6. 航次检查项（带照片预览）
    st.markdown("### ✅ 开航前检查")
    check_results = []
    first_sea_flag = False
    
    for item in ALL_CHECK_ITEMS:
        col1, col2, col3 = st.columns([3, 1, 3])
        with col1:
            st.write(f"**{item}**")
        with col2:
            if item == "是否有人第一次出海":
                res = st.selectbox("", ["是", "否"], key=f"check_{item}", index=1, label_visibility="collapsed")
                first_sea_flag = (res == "是")
            elif item == "是否有人穿戴拖鞋":
                res = st.selectbox("", ["是", "否"], key=f"check_{item}", index=0, label_visibility="collapsed")
            else:
                res = st.selectbox("", ["合格", "不合格"], key=f"check_{item}", label_visibility="collapsed")
        with col3:
            if item in NO_PHOTO_ITEMS + ["是否有人穿戴拖鞋", "是否有人第一次出海"]:
                st.write("无需上传照片")
                check_results.append({"item": item, "result": res, "photo": None})
            else:
                # 检查项照片上传+预览
                check_photo = st.file_uploader(
                    "上传照片",
                    type=["jpg", "jpeg", "png"],
                    key=f"check_photo_{item}",
                    label_visibility="collapsed"
                )
                
                # 实时预览
                if check_photo:
                    st.image(
                        check_photo,
                        caption="照片预览",
                        width=80,
                        use_column_width=False
                    )
                
                check_results.append({"item": item, "result": res, "photo": check_photo})
    
    # 7. 首次出海人员信息
    first_sea_data = []
    if first_sea_flag:
        st.markdown("### 🆕 首次出海人员信息")
        fs_count = st.number_input("首次出海人数", min_value=1, key="fs_count")
        for i in range(fs_count):
            col1, col2, col3 = st.columns(3)
            with col1:
                fs_name = st.text_input("姓名", key=f"fs_name_{i}")
            with col2:
                fs_phone = st.text_input("手机号", key=f"fs_phone_{i}")
            with col3:
                fs_id = st.text_input("身份证号", key=f"fs_id_{i}")
            first_sea_data.append({"name": fs_name, "phone": fs_phone, "id": fs_id})
    
    # 8. 提交审批
    if st.button("📤 提交审批", key="submit_btn", type="primary", use_container_width=True):
        # 基础校验
        valid = True
        
        # 船员信息校验
        if not crew_data_list:
            st.error("❌ 请至少录入1名船员信息")
            valid = False
        for idx, crew in enumerate(crew_data_list):
            if not crew["name"] or not crew["id"] or not crew["phone"]:
                st.error(f"❌ 船员{idx+1}信息不完整（姓名/身份证/手机号不能为空）")
                valid = False
            if len(str(crew["id"]).strip()) != 18:
                st.error(f"❌ 船员{crew['name']}身份证号格式错误（需18位）")
                valid = False
            if len(str(crew["phone"]).strip()) != 11:
                st.error(f"❌ 船员{crew['name']}手机号格式错误（需11位）")
                valid = False
        
        # 检查项照片校验
        for check in check_results:
            if not check["photo"] and check["item"] not in NO_PHOTO_ITEMS + ["是否有人穿戴拖鞋", "是否有人第一次出海"]:
                st.error(f"❌ {check['item']} 未上传照片，请补充")
                valid = False
        
        # 首次出海人员校验
        if first_sea_flag:
            for fs in first_sea_data:
                if not fs["name"] or not fs["phone"] or not fs["id"]:
                    st.error("❌ 首次出海人员信息不完整")
                    valid = False
        
        if not valid:
            return
        
        # 生成航次编号
        voyage_id = generate_voyage_id()
        submit_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 保存航次信息
        ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
        new_ship_row = pd.DataFrame({
            "航次编号": [voyage_id],
            "船名": [ship_name],
            "船籍港": [port],
            "最大载客人数": [max_people],
            "实际载客人数": [actual_people],
            "出海任务": [task.strip() if task else ""],
            "出海携带货物": [cargo.strip() if cargo else ""],
            "拟计划回港时间": [return_time.strftime("%Y-%m-%d %H:%M:%S")],
            "出发港": [departure.strip() if departure else ""],
            "目的港": [destination.strip() if destination else ""],
            "开航时间": [sail_time.strftime("%Y-%m-%d %H:%M:%S")],
            "提交时间": [submit_time],
            "审核状态": ["待审批"],
            "审核意见": [""]
        })
        ship_df = pd.concat([ship_df, new_ship_row], ignore_index=True)
        write_csv_with_lock(ship_df, DATA_FILES["ship_info"])
        
        # 保存船员信息
        crew_df = read_csv_with_lock(DATA_FILES["crew_info"])
        new_crew_rows = []
        for crew in crew_data_list:
            photo_path = save_photo(crew["photo"], voyage_id, crew["name"])
            new_crew_rows.append({
                "航次编号": voyage_id,
                "船员姓名": crew["name"],
                "身份证号": encrypt_data(crew["id"]),
                "手机号": encrypt_data(crew["phone"]),
                "照片路径": photo_path
            })
        crew_df = pd.concat([crew_df, pd.DataFrame(new_crew_rows)], ignore_index=True)
        write_csv_with_lock(crew_df, DATA_FILES["crew_info"])
        
        # 保存检查项信息（核心修复：新增检查项存储逻辑）
        check_df = read_csv_with_lock(DATA_FILES["check_info"])
        new_check_rows = []
        for check in check_results:
            photo_path = save_photo(check["photo"], voyage_id, check["item"])
            new_check_rows.append({
                "航次编号": voyage_id,
                "检查项名称": check["item"],
                "检查结果": check["result"],
                "照片路径": photo_path
            })
        check_df = pd.concat([check_df, pd.DataFrame(new_check_rows)], ignore_index=True)
        write_csv_with_lock(check_df, DATA_FILES["check_info"])
        
        # 保存首次出海信息
        if first_sea_flag:
            fs_df = read_csv_with_lock(DATA_FILES["first_sea_info"])
            new_fs_rows = []
            for fs in first_sea_data:
                new_fs_rows.append({
                    "航次编号": voyage_id,
                    "人数": fs_count,
                    "姓名": fs["name"],
                    "电话": encrypt_data(fs["phone"]),
                    "身份证号": encrypt_data(fs["id"])
                })
            fs_df = pd.concat([fs_df, pd.DataFrame(new_fs_rows)], ignore_index=True)
            write_csv_with_lock(fs_df, DATA_FILES["first_sea_info"])
        
        # 新增船员同步到主名单
        add_crew(ship_name, crew_data_list)
        
        # 提交成功提示
        st.success(f"""
        🎉 航次提交成功！
        - 航次编号：{voyage_id}
        - 船舶名称：{ship_name}
        - 提交时间：{submit_time}
        - 当前状态：待审批
        
        请等待管理员审批后执行开航任务！
        """)
        st.balloons()

# ====================== 航次查询模块（新增驳回理由展示） ======================
def ship_voyage_query():
    st.subheader("🔍 航次查询")
    ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
    all_voyages = ship_df["航次编号"].tolist()
    
    if not all_voyages:
        st.info("📭 暂无航次记录")
        return
    
    selected_voyage = st.selectbox("选择航次编号", all_voyages, key="selected_voyage")
    voyage_info = ship_df[ship_df["航次编号"] == selected_voyage].iloc[0]
    
    # 航次基本信息
    st.markdown(f"### 📋 航次详情：{selected_voyage}")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**船舶名称**：{voyage_info['船名']}")
        st.write(f"**船籍港**：{voyage_info['船籍港']}")
        st.write(f"**最大载客人数**：{voyage_info['最大载客人数']}")
        st.write(f"**实际载客人数**：{voyage_info['实际载客人数']}")
    with col2:
        st.write(f"**出海任务**：{voyage_info['出海任务']}")
        st.write(f"**出海携带货物**：{voyage_info['出海携带货物']}")
        st.write(f"**出发港**：{voyage_info['出发港']}")
        st.write(f"**目的港**：{voyage_info['目的港']}")
    with col3:
        st.write(f"**开航时间**：{voyage_info['开航时间']}")
        st.write(f"**拟计划回港时间**：{voyage_info['拟计划回港时间']}")
        st.write(f"**提交时间**：{voyage_info['提交时间']}")
        # 显示审核状态+驳回理由
        status = voyage_info['审核状态']
        st.write(f"**审核状态**：{status}")
        opinion = voyage_info['审核意见']
        if opinion and status == "驳回":
            st.error(f"**驳回理由**：{opinion}")
        elif opinion and status == "通过":
            st.success(f"**审批意见**：{opinion}")
    
    # 检查项信息展示（核心修复）
    st.markdown("### ✅ 开航前检查结果")
    check_df = read_csv_with_lock(DATA_FILES["check_info"])
    check_info = check_df[check_df["航次编号"] == selected_voyage]
    
    if check_info.empty:
        st.info("暂无检查项记录")
    else:
        for _, check in check_info.iterrows():
            col1, col2, col3 = st.columns([3, 1, 2])
            with col1:
                st.write(f"**{check['检查项名称']}**")
            with col2:
                if check['检查结果'] == "合格" or check['检查结果'] == "否":
                    st.success(check['检查结果'])
                else:
                    st.error(check['检查结果'])
            with col3:
                if pd.notna(check["照片路径"]) and os.path.exists(check["照片路径"]):
                    st.image(
                        check["照片路径"],
                        caption="检查照片",
                        width=80,
                        use_column_width=False
                    )
    
    # 船员信息（带照片预览）
    st.markdown("### 👨‍✈️ 船员信息")
    crew_df = read_csv_with_lock(DATA_FILES["crew_info"])
    crew_info = crew_df[crew_df["航次编号"] == selected_voyage]
    
    for _, crew in crew_info.iterrows():
        col1, col2, col3, col4 = st.columns([2, 3, 3, 2])
        with col1:
            st.write(f"**{crew['船员姓名']}**")
        with col2:
            st.write(f"身份证：{desensitize_id(crew['身份证号'])}")
        with col3:
            st.write(f"手机号：{desensitize_phone(crew['手机号'])}")
        with col4:
            if pd.notna(crew["照片路径"]) and os.path.exists(crew["照片路径"]):
                st.image(
                    crew["照片路径"],
                    caption=f"{crew['船员姓名']} 照片",
                    width=100,
                    use_column_width=False
                )

# ====================== 后台审批模块（新增检查项展示） ======================
def admin_approval():
    st.subheader("📋 后台审批")
    
    # 权限验证
    if "show_full_info" not in st.session_state:
        st.session_state["show_full_info"] = False
    
    st.sidebar.subheader("🔒 权限验证")
    pwd = st.sidebar.text_input("管理员密码", type="password", key="admin_pwd")
    if st.sidebar.button("验证", use_container_width=True):
        if pwd == "admin123":
            st.session_state["show_full_info"] = True
            st.sidebar.success("✅ 验证成功")
        else:
            st.session_state["show_full_info"] = False
            st.sidebar.error("❌ 密码错误")
    
    # 待审批航次
    ship_df = read_csv_with_lock(DATA_FILES["ship_info"])
    pending_voyages = ship_df[ship_df["审核状态"] == "待审批"]
    
    if pending_voyages.empty:
        st.info("📭 暂无待审批航次")
        return
    
    selected_voyage = st.selectbox("选择待审批航次", pending_voyages["航次编号"], key="admin_voyage")
    voyage_info = pending_voyages[pending_voyages["航次编号"] == selected_voyage].iloc[0]
    
    # 航次信息展示
    st.markdown(f"### 📋 航次详情：{selected_voyage}")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.write(f"**船舶名称**：{voyage_info['船名']}")
        st.write(f"**船籍港**：{voyage_info['船籍港']}")
        st.write(f"**最大载客人数**：{voyage_info['最大载客人数']}")
        st.write(f"**实际载客人数**：{voyage_info['实际载客人数']}")
    with col2:
        st.write(f"**出海任务**：{voyage_info['出海任务']}")
        st.write(f"**出海携带货物**：{voyage_info['出海携带货物']}")
        st.write(f"**出发港**：{voyage_info['出发港']}")
        st.write(f"**目的港**：{voyage_info['目的港']}")
    with col3:
        st.write(f"**开航时间**：{voyage_info['开航时间']}")
        st.write(f"**拟计划回港时间**：{voyage_info['拟计划回港时间']}")
        st.write(f"**提交时间**：{voyage_info['提交时间']}")
    
    # 检查项信息展示（核心修复：审批页显示所有检查项）
    st.markdown("### ✅ 开航前检查结果")
    check_df = read_csv_with_lock(DATA_FILES["check_info"])
    check_info = check_df[check_df["航次编号"] == selected_voyage]
    
    if check_info.empty:
        st.info("暂无检查项记录")
    else:
        for _, check in check_info.iterrows():
            col1, col2, col3 = st.columns([3, 1, 2])
            with col1:
                st.write(f"**{check['检查项名称']}**")
            with col2:
                if check['检查结果'] == "合格" or check['检查结果'] == "否":
                    st.success(check['检查结果'])
                else:
                    st.error(check['检查结果'])
            with col3:
                if pd.notna(check["照片路径"]) and os.path.exists(check["照片路径"]):
                    st.image(
                        check["照片路径"],
                        caption="检查照片",
                        width=80,
                        use_column_width=False
                    )
    
    # 船员信息（带完整照片预览）
    st.markdown("### 👨‍✈️ 船员信息")
    crew_df = read_csv_with_lock(DATA_FILES["crew_info"])
    crew_info = crew_df[crew_df["航次编号"] == selected_voyage]
    crew_master_df = get_crew_list(voyage_info['船名'])
    
    for _, crew in crew_info.iterrows():
        col1, col2, col3, col4 = st.columns([2, 3, 3, 2])
        with col1:
            st.write(f"**{crew['船员姓名']}**")
        with col2:
            if st.session_state["show_full_info"]:
                match = crew_master_df[crew_master_df["船员姓名"] == crew["船员姓名"]]
                st.write(f"身份证：**{match.iloc[0]['身份证号'] if not match.empty else desensitize_id(crew['身份证号'])}**")
            else:
                st.write(f"身份证：{desensitize_id(crew['身份证号'])}")
        with col3:
            if st.session_state["show_full_info"]:
                match = crew_master_df[crew_master_df["船员姓名"] == crew["船员姓名"]]
                st.write(f"手机号：**{match.iloc[0]['手机号'] if not match.empty else desensitize_phone(crew['手机号'])}**")
            else:
                st.write(f"手机号：{desensitize_phone(crew['手机号'])}")
        with col4:
            if pd.notna(crew["照片路径"]) and os.path.exists(crew["照片路径"]):
                st.image(
                    crew["照片路径"],
                    caption=f"{crew['船员姓名']} 照片",
                    width=100,
                    use_column_width=False
                )
    
    # 审批操作
    st.markdown("### ✅ 审批操作")
    action = st.radio("审批结果", ["通过", "驳回"], key="approval_action")
    opinion = st.text_area("审批意见/驳回理由", key="approval_opinion", placeholder="请输入审批意见（必填）")
    
    if st.button("确认审批", key="confirm_approval", type="primary", use_container_width=True):
        if not opinion:
            st.error("❌ 审批意见不能为空")
            return
        
        # 更新航次状态和审批意见
        ship_df.loc[ship_df["航次编号"] == selected_voyage, "审核状态"] = action
        ship_df.loc[ship_df["航次编号"] == selected_voyage, "审核意见"] = opinion
        write_csv_with_lock(ship_df, DATA_FILES["ship_info"])
        
        # 记录审批日志
        approval_df = read_csv_with_lock(DATA_FILES["approval_info"])
        approval_df = pd.concat([approval_df, pd.DataFrame({
            "航次编号": [selected_voyage],
            "审核人": ["管理员"],
            "审核时间": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            "审核状态": [action],
            "审核意见": [opinion]
        })], ignore_index=True)
        write_csv_with_lock(approval_df, DATA_FILES["approval_info"])
        
        st.success(f"🎉 航次{selected_voyage}审批完成！状态：{action}")
        st.rerun()

# ====================== 主程序 ======================
def main():
    st.cache_data.clear()
    
    # 初始化会话状态
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False
    
    # 登录验证
    if not st.session_state["logged_in"]:
        login_module()
        return
    
    # 主界面
    st.title("🚢 船舶航次审批系统")
    
    if st.session_state["role"] == "ship":
        tab1, tab2 = st.tabs(["📝 航次录入", "🔍 航次查询"])
        with tab1:
            ship_info_input()
        with tab2:
            ship_voyage_query()
    else:
        admin_approval()
    
    # 退出登录
    if st.sidebar.button("🚪 退出登录", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state.pop("preview_photos", None)
        st.session_state.pop("show_full_info", None)
        st.rerun()

if __name__ == "__main__":
    main()