from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import mysql.connector
import pandas as pd
import os
from collections import OrderedDict

app = Flask(__name__)
app.secret_key = 'day_la_mot_khoa_bi_mat_rat_an_toan'

# --- CẤU HÌNH UPLOAD FILE ---
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- CẤU HÌNH FLASK-LOGIN ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Vui lòng đăng nhập để truy cập trang này."
login_manager.login_message_category = "info"

# --- KẾT NỐI DATABASE ---
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="quanlysinhvien"
)
cursor = db.cursor(dictionary=True)

# --- LỚP USER CHO FLASK-LOGIN ---
class User(UserMixin):
    def __init__(self, id, username, role, ma_sv=None):
        self.id = id
        self.username = username
        self.role = role
        self.ma_sv = ma_sv

@login_manager.user_loader
def load_user(user_id):
    if not db.is_connected():
        db.reconnect()
    cursor.execute("SELECT * FROM Users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()
    if user_data:
        return User(id=user_data['id'], username=user_data['username'], role=user_data['role'], ma_sv=user_data['ma_sv'])
    return None

# --- DECORATOR ĐỂ KIỂM TRA VAI TRÒ ADMIN ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash("Bạn không có quyền truy cập trang này.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- HÀM HỖ TRỢ TÍNH TOÁN LẠI ĐIỂM RÈN LUYỆN ---
def update_drl_score(ma_sv, hoc_ky, submission_id = None):
    print(f"++++++++++++++ Here hoc ky {hoc_ky}, submission_id = {submission_id}")
    """Tính toán và cập nhật tổng điểm rèn luyện cho một sinh viên trong một học kỳ."""
    if not db.is_connected(): db.reconnect()
    state = "đã duyệt"
    if submission_id is not None:
        state = "chờ duyệt"
    
    query = f"""
        SELECT SUM(hd.diem) as total_activity_score 
            FROM DangKyHoatDong dkhd 
            JOIN HoatDong hd ON dkhd.hoat_dong_id = hd.id 
            WHERE dkhd.ma_sv = '{ma_sv}' 
            AND hd.hoc_ky LIKE '%{hoc_ky}%' 
            AND dkhd.trang_thai = 'đã duyệt';
    """
    print(query)
    cursor.execute(query)
    result = cursor.fetchone()
    
    # Approve the submission if submission_id is provided
    if submission_id is not None:
        cursor.execute("UPDATE DangKyHoatDong SET trang_thai = 'đã duyệt' WHERE id = %s", (submission_id,))
        # Re-run the query to get the updated total_activity_score after approval
        cursor.execute(query)
        result = cursor.fetchone()

    print(f"result = {result}")
    activity_bonus_score = result['total_activity_score'] if result['total_activity_score'] else 0
    print(f"activity_bonus_score = {activity_bonus_score}")

    cursor.execute("SELECT id, diem_co_ban, diem_tru FROM DiemRenLuyen WHERE ma_sv = %s AND hoc_ky = %s", (ma_sv, hoc_ky))
    drl_record = cursor.fetchone()
    print(f"drl_record = {drl_record}")
    print("------------------------------------------------------")

    if drl_record:
        # Update diem_cong_hoat_dong and recalculate total diem
        diem_co_ban = drl_record['diem_co_ban'] if drl_record['diem_co_ban'] else 0
        diem_tru = drl_record['diem_tru'] if drl_record['diem_tru'] else 0
        total_score = diem_co_ban + activity_bonus_score - diem_tru
        cursor.execute("UPDATE DiemRenLuyen SET diem_cong_hoat_dong = %s, diem = %s WHERE id = %s", 
                       (activity_bonus_score, total_score, drl_record['id']))
    else:
        # If no existing DRL record, create one with initial scores
        total_score = activity_bonus_score # Assuming base and deduction are 0 for new records
        cursor.execute("INSERT INTO DiemRenLuyen (ma_sv, hoc_ky, diem_cong_hoat_dong, diem) VALUES (%s, %s, %s, %s)", 
                       (ma_sv, hoc_ky, activity_bonus_score, total_score))
    db.commit()

# ========== CÁC ROUTE XÁC THỰC ==========
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if not db.is_connected(): db.reconnect()
        cursor.execute("SELECT * FROM Users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        if user_data and check_password_hash(user_data['password_hash'], password):
            user = User(id=user_data['id'], username=user_data['username'], role=user_data['role'], ma_sv=user_data['ma_sv'])
            login_user(user)
            flash('Đăng nhập thành công!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Bạn đã đăng xuất.', 'info')
    return redirect(url_for('login'))

# ========== SINH VIÊN ==========
@app.route('/')
@login_required
def index():
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT ma_sv, ho_ten FROM sinhvien ORDER BY ma_sv")
    students = cursor.fetchall()
    return render_template("index.html", students=students)

@app.route('/sinhvien/<ma_sv>')
@login_required
def student_details(ma_sv):
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT * FROM sinhvien WHERE ma_sv = %s", (ma_sv,))
    student = cursor.fetchone()
    if not student:
        flash('Không tìm thấy sinh viên!', 'warning')
        return redirect(url_for('index'))
    query_diem = """
        SELECT m.hoc_ky, m.ten_mon_hoc, m.so_tin_chi, d.diem_qua_trinh, d.diem_thi, m.he_so_qua_trinh, m.he_so_thi
        FROM Diem d
        JOIN MonHoc m ON d.ma_mon_hoc = m.ma_mon_hoc
        WHERE d.ma_sv = %s
        ORDER BY m.hoc_ky, m.ten_mon_hoc
    """
    cursor.execute(query_diem, (ma_sv,))
    academic_scores = cursor.fetchall()
    scores_by_semester = OrderedDict()
    for record in academic_scores:
        hoc_ky = record['hoc_ky']
        if hoc_ky not in scores_by_semester:
            scores_by_semester[hoc_ky] = {'scores': [], 'total_credit_points': 0, 'total_credits': 0, 'gpa': 0}
        diem_tb = (record['diem_qua_trinh'] * record['he_so_qua_trinh']) + (record['diem_thi'] * record['he_so_thi'])
        record['diem_trung_binh'] = diem_tb
        so_tin_chi = record.get('so_tin_chi', 0)
        scores_by_semester[hoc_ky]['scores'].append(record)
        scores_by_semester[hoc_ky]['total_credit_points'] += diem_tb * so_tin_chi
        scores_by_semester[hoc_ky]['total_credits'] += so_tin_chi
    for hoc_ky, data in scores_by_semester.items():
        if data['total_credits'] > 0:
            data['gpa'] = data['total_credit_points'] / data['total_credits']
    
    # Updated query to fetch all DRL columns
    cursor.execute("SELECT id, hoc_ky, diem_co_ban, diem_cong_hoat_dong, diem_tru, diem AS tong_diem FROM DiemRenLuyen WHERE ma_sv = %s ORDER BY hoc_ky DESC", (ma_sv,))
    training_scores = cursor.fetchall()
    
    return render_template("student_details.html", student=student, scores_by_semester=scores_by_semester, training_scores=training_scores)

@app.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add():
    if request.method == 'POST':
        ma_sv = request.form['ma_sv']
        ho_ten = request.form['ho_ten']
        ngay_sinh = request.form['ngay_sinh']
        gioi_tinh = request.form['gioi_tinh']
        lop = request.form['lop']
        try:
            if not db.is_connected(): db.reconnect()
            cursor.execute("INSERT INTO sinhvien (ma_sv, ho_ten, ngay_sinh, gioi_tinh, lop) VALUES (%s, %s, %s, %s, %s)", 
                           (ma_sv, ho_ten, ngay_sinh, gioi_tinh, lop))
            db.commit()
            flash('Thêm sinh viên thành công!', 'success')
        except mysql.connector.Error as err:
            flash(f"Lỗi: {err}", "danger")
        return redirect(url_for('index'))
    return render_template("add.html")

@app.route('/edit/<ma_sv>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit(ma_sv):
    if not db.is_connected(): db.reconnect()
    if request.method == 'POST':
        ho_ten = request.form['ho_ten']
        ngay_sinh = request.form['ngay_sinh']
        gioi_tinh = request.form['gioi_tinh']
        lop = request.form['lop']
        cursor.execute("UPDATE sinhvien SET ho_ten=%s, ngay_sinh=%s, gioi_tinh=%s, lop=%s WHERE ma_sv=%s",
                       (ho_ten, ngay_sinh, gioi_tinh, lop, ma_sv))
        db.commit()
        flash('Cập nhật thông tin sinh viên thành công!', 'success')
        return redirect(url_for('student_details', ma_sv=ma_sv))
    cursor.execute("SELECT * FROM sinhvien WHERE ma_sv=%s", (ma_sv,))
    sv = cursor.fetchone()
    return render_template("edit.html", sv=sv)

@app.route('/delete/<ma_sv>')
@login_required
@admin_required
def delete(ma_sv):
    try:
        if not db.is_connected(): db.reconnect()
        cursor.execute("DELETE FROM sinhvien WHERE ma_sv=%s", (ma_sv,))
        db.commit()
        flash(f'Đã xóa thành công sinh viên {ma_sv} và tất cả điểm liên quan.', 'success')
    except mysql.connector.Error as err:
        flash(f"Lỗi: {err}", "danger")
    return redirect(url_for('index'))

@app.route('/upload_excel', methods=['POST'])
@login_required
@admin_required
def upload_excel():
    if 'excel_file' not in request.files:
        flash('Không có tệp nào được chọn', 'danger')
        return redirect(url_for('index'))
    file = request.files['excel_file']
    if file.filename == '':
        flash('Chưa chọn tệp Excel nào', 'warning')
        return redirect(url_for('index'))
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            df = pd.read_excel(file, dtype=str)
            for index, row in df.iterrows():
                ma_sv = row['ma_sv'].strip()
                ho_ten = row['ho_ten'].strip()
                ngay_sinh = pd.to_datetime(row['ngay_sinh']).strftime('%Y-%m-%d') 
                gioi_tinh = row['gioi_tinh'].strip()
                lop = row['lop'].strip()
                if not db.is_connected(): db.reconnect()
                cursor.execute(
                    "INSERT INTO sinhvien (ma_sv, ho_ten, ngay_sinh, gioi_tinh, lop) VALUES (%s, %s, %s, %s, %s)",
                    (ma_sv, ho_ten, ngay_sinh, gioi_tinh, lop)
                )
            db.commit()
            flash('Dữ liệu sinh viên từ file Excel đã được thêm thành công!', 'success')
        except Exception as e:
            db.rollback()
            flash(f'Đã xảy ra lỗi khi xử lý file sinh viên: {e}', 'danger')
    else:
        flash('Định dạng tệp không hợp lệ. Vui lòng chọn file .xlsx hoặc .xls', 'danger')
    return redirect(url_for('index'))

# ========== MÔN HỌC ==========
@app.route('/monhoc')
@login_required
def monhoc():
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT * FROM MonHoc ORDER BY hoc_ky, ten_mon_hoc")
    all_mon_hoc = cursor.fetchall()
    grouped_mon_hoc = OrderedDict()
    for mon in all_mon_hoc:
        hoc_ky = mon['hoc_ky']
        if hoc_ky not in grouped_mon_hoc:
            grouped_mon_hoc[hoc_ky] = []
        grouped_mon_hoc[hoc_ky].append(mon)
    return render_template("monhoc.html", grouped_mon_hoc=grouped_mon_hoc)

@app.route('/add_monhoc', methods=['GET', 'POST'])
@login_required
@admin_required
def add_monhoc():
    if request.method == 'POST':
        ma_mon_hoc = request.form['ma_mon_hoc']
        ten_mon_hoc = request.form['ten_mon_hoc']
        so_tin_chi = int(request.form['so_tin_chi'])
        hoc_ky = request.form['hoc_ky']
        he_so_qua_trinh = float(request.form['he_so_qua_trinh'])
        he_so_thi = float(request.form['he_so_thi'])
        if round(he_so_qua_trinh + he_so_thi, 1) != 1.0:
            flash('Tổng hai hệ số phải bằng 1.0', 'danger')
        else:
            try:
                if not db.is_connected(): db.reconnect()
                cursor.execute("INSERT INTO MonHoc (ma_mon_hoc, ten_mon_hoc, so_tin_chi, hoc_ky, he_so_qua_trinh, he_so_thi) VALUES (%s, %s, %s, %s, %s, %s)",
                               (ma_mon_hoc, ten_mon_hoc, so_tin_chi, hoc_ky, he_so_qua_trinh, he_so_thi))
                db.commit()
                flash('Thêm môn học thành công!', 'success')
                return redirect(url_for('monhoc'))
            except mysql.connector.Error as err:
                flash(f"Lỗi: {err}", "danger")
    return render_template("add_monhoc.html")

@app.route('/edit_monhoc/<ma_mon_hoc>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_monhoc(ma_mon_hoc): # Đảm bảo tham số ở đây là ma_mon_hoc
    if not db.is_connected(): db.reconnect()
    # Sửa lỗi ở đây: Sử dụng ma_mon_hoc thay vì id
    cursor.execute("SELECT hoc_ky FROM MonHoc WHERE ma_mon_hoc = %s", (ma_mon_hoc,)) # Sửa HoatDong thành MonHoc
    old_activity = cursor.fetchone()
    old_hoc_ky = old_activity['hoc_ky'] if old_activity else None
    if request.method == 'POST':
        ten_mon_hoc = request.form['ten_mon_hoc']
        so_tin_chi = int(request.form['so_tin_chi'])
        hoc_ky = request.form['hoc_ky']
        he_so_qua_trinh = float(request.form['he_so_qua_trinh'])
        he_so_thi = float(request.form['he_so_thi'])
        if round(he_so_qua_trinh + he_so_thi, 1) != 1.0:
            flash('Tổng hai hệ số phải bằng 1.0', 'danger')
        else:
            cursor.execute("UPDATE MonHoc SET ten_mon_hoc=%s, so_tin_chi=%s, hoc_ky=%s, he_so_qua_trinh=%s, he_so_thi=%s WHERE ma_mon_hoc=%s",
                           (ten_mon_hoc, so_tin_chi, hoc_ky, he_so_qua_trinh, he_so_thi, ma_mon_hoc))
            db.commit()
            flash('Cập nhật môn học thành công!', 'success')
            return redirect(url_for('monhoc'))
    cursor.execute("SELECT * FROM MonHoc WHERE ma_mon_hoc=%s", (ma_mon_hoc,))
    mon = cursor.fetchone()
    return render_template("edit_monhoc.html", mon=mon)

@app.route('/delete_monhoc/<ma_mon_hoc>')
@login_required
@admin_required
def delete_monhoc(ma_mon_hoc):
    try:
        if not db.is_connected(): db.reconnect()
        cursor.execute("DELETE FROM MonHoc WHERE ma_mon_hoc=%s", (ma_mon_hoc,))
        db.commit()
        flash('Xóa môn học thành công!', 'success')
    except mysql.connector.Error as err:
        flash(f"Lỗi: Không thể xóa môn học này vì đã có điểm được nhập.", "danger")
    return redirect(url_for('monhoc'))

@app.route('/upload_monhoc_excel', methods=['POST'])
@login_required
@admin_required
def upload_monhoc_excel():
    if 'excel_file' not in request.files:
        flash('Không có tệp nào được chọn', 'danger')
        return redirect(url_for('monhoc'))
    file = request.files['excel_file']
    if file.filename == '':
        flash('Chưa chọn tệp Excel nào', 'warning')
        return redirect(url_for('monhoc'))
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            df = pd.read_excel(file, dtype=str)
            monhoc_to_insert = []
            for index, row in df.iterrows():
                he_so_qua_trinh = float(row['he_so_qua_trinh'])
                he_so_thi = float(row['he_so_thi'])
                if round(he_so_qua_trinh + he_so_thi, 1) != 1.0:
                    flash(f"Lỗi ở dòng {index + 2} trong file Excel: Tổng hệ số của môn '{row['ten_mon_hoc']}' không bằng 1.0.", 'danger')
                    return redirect(url_for('monhoc'))
                monhoc_to_insert.append(row)
            for row in monhoc_to_insert:
                ma_mon_hoc = row['ma_mon_hoc'].strip()
                ten_mon_hoc = row['ten_mon_hoc'].strip()
                so_tin_chi = int(row['so_tin_chi'])
                hoc_ky = row['hoc_ky'].strip()
                he_so_qua_trinh = float(row['he_so_qua_trinh'])
                he_so_thi = float(row['he_so_thi'])
                if not db.is_connected(): db.reconnect()
                cursor.execute(
                    "INSERT INTO MonHoc (ma_mon_hoc, ten_mon_hoc, so_tin_chi, hoc_ky, he_so_qua_trinh, he_so_thi) VALUES (%s, %s, %s, %s, %s, %s)",
                    (ma_mon_hoc, ten_mon_hoc, so_tin_chi, hoc_ky, he_so_qua_trinh, he_so_thi)
                )
            db.commit()
            flash('Dữ liệu môn học từ file Excel đã được thêm thành công!', 'success')
        except Exception as e:
            db.rollback()
            flash(f'Đã xảy ra lỗi khi xử lý file môn học: {e}', 'danger')
    else:
        flash('Định dạng tệp không hợp lệ. Vui lòng chọn file .xlsx hoặc .xls', 'danger')
    return redirect(url_for('monhoc'))

# ========== ĐIỂM HỌC TẬP ==========
@app.route('/diem', methods=['GET'])
@login_required

def diem():
    if not db.is_connected(): db.reconnect()
    
    selected_hoc_ky = request.args.get('hoc_ky')
    selected_ma_mon_hoc = request.args.get('ma_mon_hoc') 
    
    query = """
        SELECT d.id, sv.ma_sv, sv.ho_ten, mh.ma_mon_hoc, mh.ten_mon_hoc, d.diem_qua_trinh, d.diem_thi, mh.hoc_ky, mh.so_tin_chi,
               mh.he_so_qua_trinh, mh.he_so_thi
        FROM Diem d
        JOIN sinhvien sv ON d.ma_sv = sv.ma_sv
        JOIN MonHoc mh ON d.ma_mon_hoc = mh.ma_mon_hoc
    """
    conditions = []
    params = []

    if selected_hoc_ky:
        conditions.append("mh.hoc_ky = %s")
        params.append(selected_hoc_ky)
        
    if selected_ma_mon_hoc: 
        conditions.append("mh.ma_mon_hoc = %s")
        params.append(selected_ma_mon_hoc)
        
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY mh.hoc_ky DESC, mh.ten_mon_hoc, sv.ma_sv"

    cursor.execute(query, params)
    diems = cursor.fetchall()

    warning_students_and_subjects = set() # Set to store (ma_sv, ma_mon_hoc) pairs for students who failed
    for diem in diems:
        diem_tb = (diem['diem_qua_trinh'] * diem['he_so_qua_trinh']) + \
                  (diem['diem_thi'] * diem['he_so_thi'])
        diem['diem_trung_binh'] = diem_tb
        if diem_tb < 4.0: # Check for failing grade
            warning_students_and_subjects.add((diem['ma_sv'], diem['ma_mon_hoc']))

    # Lấy danh sách tất cả các học kỳ có trong MonHoc (vì Diem liên kết với MonHoc)
    cursor.execute("SELECT DISTINCT hoc_ky FROM MonHoc ORDER BY hoc_ky DESC")
    all_hoc_kies = [row['hoc_ky'] for row in cursor.fetchall()]

    # Lấy danh sách môn học dựa trên học kỳ đã chọn (nếu có)
    all_mon_hocs_for_dropdown = []
    if selected_hoc_ky:
        cursor.execute("SELECT DISTINCT ma_mon_hoc, ten_mon_hoc, hoc_ky FROM MonHoc WHERE hoc_ky = %s ORDER BY ten_mon_hoc", (selected_hoc_ky,))
        all_mon_hocs_for_dropdown = cursor.fetchall()
    else: 
        cursor.execute("SELECT DISTINCT ma_mon_hoc, ten_mon_hoc, hoc_ky FROM MonHoc ORDER BY ten_mon_hoc")
        all_mon_hocs_for_dropdown = cursor.fetchall()

    # Lấy danh sách cảnh báo học tập (sinh viên có điểm trung bình < 4.0)
    # Logic này luôn chạy và truyền warning_list để hiển thị.
    warning_query = """
        SELECT sv.ho_ten, sv.ma_sv, mh.ten_mon_hoc, mh.hoc_ky, mh.ma_mon_hoc,
               (d.diem_qua_trinh * mh.he_so_qua_trinh) + (d.diem_thi * mh.he_so_thi) AS diem_trung_binh
        FROM Diem d
        JOIN sinhvien sv ON d.ma_sv = sv.ma_sv
        JOIN MonHoc mh ON d.ma_mon_hoc = mh.ma_mon_hoc
        WHERE ((d.diem_qua_trinh * mh.he_so_qua_trinh) + (d.diem_thi * mh.he_so_thi)) < 4.0
    """
    warning_params = []
    if selected_hoc_ky: # Nếu có lọc theo học kỳ, chỉ hiển thị cảnh báo cho học kỳ đó
        warning_query += " AND mh.hoc_ky = %s"
        warning_params.append(selected_hoc_ky)
    if selected_ma_mon_hoc: # Nếu có lọc theo môn học, chỉ hiển thị cảnh báo cho môn học đó
        warning_query += " AND mh.ma_mon_hoc = %s"
        warning_params.append(selected_ma_mon_hoc)
    warning_query += " ORDER BY diem_trung_binh DESC"
    
    cursor.execute(warning_query, warning_params)
    warning_list = cursor.fetchall()

    return render_template('diem.html', 
                           diems=diems, 
                           all_hoc_kies=all_hoc_kies, 
                           all_mon_hocs_for_dropdown=all_mon_hocs_for_dropdown,
                           selected_hoc_ky=selected_hoc_ky,
                           selected_ma_mon_hoc=selected_ma_mon_hoc, 
                           warning_list=warning_list,
                           warning_students_and_subjects=warning_students_and_subjects) # Truyền set cảnh báo



@app.route('/add_diem', methods=['GET', 'POST'])
@login_required
@admin_required
def add_diem():
    if not db.is_connected(): db.reconnect()
    if request.method == 'POST':
        ma_sv = request.form['ma_sv']
        ma_mon_hoc = request.form['ma_mon_hoc']
        diem_qua_trinh = float(request.form['diem_qua_trinh'])
        diem_thi = float(request.form['diem_thi'])
        cursor.execute("SELECT id FROM Diem WHERE ma_sv = %s AND ma_mon_hoc = %s", (ma_sv, ma_mon_hoc))
        if cursor.fetchone():
            flash(f"Lỗi: Sinh viên {ma_sv} đã có điểm cho môn học này.", 'danger')
        else:
            try:
                cursor.execute("INSERT INTO Diem (ma_sv, ma_mon_hoc, diem_qua_trinh, diem_thi) VALUES (%s, %s, %s, %s)",
                               (ma_sv, ma_mon_hoc, diem_qua_trinh, diem_thi))
                db.commit()
                flash('Thêm điểm thành công!', 'success')
                return redirect(url_for('diem'))
            except mysql.connector.Error as err:
                flash(f"Lỗi: {err}", "danger")
    cursor.execute("SELECT * FROM MonHoc ORDER BY ten_mon_hoc")
    mon_hoc_list = cursor.fetchall()
    return render_template("add_diem.html", mon_hoc_list=mon_hoc_list)

@app.route('/edit_diem/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_diem(id):
    if not db.is_connected(): db.reconnect()
    if request.method == 'POST':
        ma_mon_hoc = request.form['ma_mon_hoc']
        diem_qua_trinh = float(request.form['diem_qua_trinh'])
        diem_thi = float(request.form['diem_thi'])
        cursor.execute("UPDATE Diem SET ma_mon_hoc=%s, diem_qua_trinh=%s, diem_thi=%s WHERE id=%s",
                       (ma_mon_hoc, diem_qua_trinh, diem_thi, id))
        db.commit()
        flash('Cập nhật điểm thành công!', 'success')
        return redirect(url_for('diem'))
    cursor.execute("SELECT * FROM Diem WHERE id=%s", (id,))
    record = cursor.fetchone()
    cursor.execute("SELECT * FROM MonHoc ORDER BY ten_mon_hoc")
    mon_hoc_list = cursor.fetchall()
    return render_template("edit_diem.html", record=record, mon_hoc_list=mon_hoc_list)

@app.route('/delete_diem/<int:id>')
@login_required
@admin_required
def delete_diem(id):
    if not db.is_connected(): db.reconnect()
    cursor.execute("DELETE FROM Diem WHERE id=%s", (id,))
    db.commit()
    flash('Xóa điểm thành công!', 'success')
    return redirect(url_for('diem'))

@app.route('/upload_diem_excel', methods=['POST'])
@login_required
@admin_required
def upload_diem_excel():
    if 'excel_file' not in request.files:
        flash('Không có tệp nào được chọn', 'danger')
        return redirect(url_for('diem'))
    file = request.files['excel_file']
    if file.filename == '':
        flash('Chưa chọn tệp Excel nào', 'warning')
        return redirect(url_for('diem'))
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            df = pd.read_excel(file)
            df['diem_qua_trinh'].fillna(0, inplace=True)
            df['diem_thi'].fillna(0, inplace=True)
            warnings = []
            for index, row in df.iterrows():
                ma_sv = str(int(row['ma_sv']))
                ma_mon_hoc = str(int(row['ma_mon_hoc']))
                if not db.is_connected(): db.reconnect()
                cursor.execute("SELECT id FROM Diem WHERE ma_sv = %s AND ma_mon_hoc = %s", (ma_sv, ma_mon_hoc))
                if cursor.fetchone():
                    warnings.append(f"Dòng {index + 2} (SV: {ma_sv}, Môn: {ma_mon_hoc})")
                    continue
                diem_qua_trinh = float(row['diem_qua_trinh'])
                diem_thi = float(row['diem_thi'])
                cursor.execute(
                    "INSERT INTO Diem (ma_sv, ma_mon_hoc, diem_qua_trinh, diem_thi) VALUES (%s, %s, %s, %s)",
                    (ma_sv, ma_mon_hoc, diem_qua_trinh, diem_thi)
                )
            db.commit()
            if warnings:
                flash(f"Đã thêm điểm thành công. Các bản ghi sau bị bỏ qua vì đã tồn tại: {', '.join(warnings)}.", 'warning')
            else:
                flash('Dữ liệu điểm từ file Excel đã được thêm thành công!', 'success')
        except mysql.connector.IntegrityError as err:
            db.rollback()
            if err.errno == 1452:
                flash(f"Lỗi ở dòng {index + 2} trong file Excel: Mã sinh viên '{ma_sv}' hoặc Mã môn học '{ma_mon_hoc}' không tồn tại trong hệ thống. Vui lòng kiểm tra lại.", 'danger')
            else:
                flash(f'Lỗi cơ sở dữ liệu: {err}', 'danger')
        except Exception as e:
            db.rollback()
            flash(f'Đã xảy ra lỗi không xác định khi xử lý file điểm: {e}', 'danger')
    else:
        flash('Định dạng tệp không hợp lệ. Vui lòng chọn file .xlsx hoặc .xls', 'danger')
    return redirect(url_for('diem'))

# ========== ĐIỂM RÈN LUYỆN ==========
@app.route('/diemrenluyen', methods=['GET']) # Thêm methods=['GET'] để nhận tham số
@login_required
def diemrenluyen():
    if not db.is_connected(): db.reconnect()
    
    selected_hoc_ky = request.args.get('hoc_ky') # Lấy tham số hoc_ky từ URL
    
    query = """
        SELECT 
            drl.id, drl.ma_sv, sv.ho_ten, drl.hoc_ky, 
            drl.diem_co_ban, drl.diem_cong_hoat_dong, drl.diem_tru, drl.diem AS tong_diem
        FROM DiemRenLuyen drl
        JOIN sinhvien sv ON drl.ma_sv = sv.ma_sv
    """
    params = []
    
    if selected_hoc_ky:
        query += " WHERE drl.hoc_ky = %s"
        params.append(selected_hoc_ky)
        
    query += " ORDER BY drl.hoc_ky DESC, drl.ma_sv" # Sắp xếp theo học kỳ giảm dần

    cursor.execute(query, params)
    diemrenluyen = cursor.fetchall()

    # Lấy danh sách tất cả các học kỳ có trong DiemRenLuyen để tạo bộ lọc
    cursor.execute("SELECT DISTINCT hoc_ky FROM DiemRenLuyen ORDER BY hoc_ky DESC")
    all_hoc_kies = [row['hoc_ky'] for row in cursor.fetchall()]

    return render_template("diemrenluyen.html", 
                           diemrenluyen=diemrenluyen, 
                           all_hoc_kies=all_hoc_kies, 
                           selected_hoc_ky=selected_hoc_ky)

@app.route('/diemrenluyen/details/<int:drl_id>')
@login_required
def drl_details(drl_id):
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT drl.id, drl.ma_sv, drl.hoc_ky, drl.diem_co_ban, drl.diem_cong_hoat_dong, drl.diem_tru, drl.diem AS tong_diem FROM DiemRenLuyen drl WHERE drl.id = %s", (drl_id,))
    drl_summary = cursor.fetchone()
    if not drl_summary:
        flash('Không tìm thấy bản ghi điểm rèn luyện.', 'warning')
        return redirect(url_for('diemrenluyen'))
    cursor.execute("SELECT ho_ten FROM sinhvien WHERE ma_sv = %s", (drl_summary['ma_sv'],))
    student = cursor.fetchone()
    query = """
        SELECT hd.ten_hoat_dong, hd.diem
        FROM DangKyHoatDong dkhd
        JOIN HoatDong hd ON dkhd.hoat_dong_id = hd.id
        WHERE dkhd.ma_sv = %s AND hd.hoc_ky = %s AND dkhd.trang_thai = 'đã duyệt'
    """
    cursor.execute(query, (drl_summary['ma_sv'], drl_summary['hoc_ky']))
    activities = cursor.fetchall()
    return render_template("diemrenluyen_details.html", 
                           drl_summary=drl_summary, 
                           student=student,
                           activities=activities)

@app.route('/add_diemrenluyen', methods=['GET', 'POST'])
@login_required
@admin_required
def add_diemrenluyen():
    if request.method == 'POST':
        ma_sv = request.form['ma_sv']
        hoc_ky = request.form['hoc_ky']
        diem_co_ban = int(request.form['diem_co_ban']) if request.form['diem_co_ban'] else 0
        diem_tru = int(request.form['diem_tru']) if request.form['diem_tru'] else 0

        try:
            if not db.is_connected(): db.reconnect()
            # Check if a record already exists for the student and semester
            cursor.execute("SELECT id, diem_cong_hoat_dong FROM DiemRenLuyen WHERE ma_sv = %s AND hoc_ky = %s", (ma_sv, hoc_ky))
            existing_record = cursor.fetchone()

            if existing_record:
                # Update existing record
                diem_cong_hoat_dong = existing_record['diem_cong_hoat_dong'] if existing_record['diem_cong_hoat_dong'] else 0
                total_diem = diem_co_ban + diem_cong_hoat_dong - diem_tru
                cursor.execute(
                    "UPDATE DiemRenLuyen SET diem_co_ban = %s, diem_tru = %s, diem = %s WHERE id = %s",
                    (diem_co_ban, diem_tru, total_diem, existing_record['id'])
                )
            else:
                # Insert new record
                total_diem = diem_co_ban - diem_tru # activity bonus score is 0 for a new manual entry
                cursor.execute(
                    "INSERT INTO DiemRenLuyen (ma_sv, hoc_ky, diem_co_ban, diem_tru, diem) VALUES (%s, %s, %s, %s, %s)",
                    (ma_sv, hoc_ky, diem_co_ban, diem_tru, total_diem)
                )
            db.commit()
            flash('Thêm/Cập nhật điểm rèn luyện thành công!', 'success')
            return redirect(url_for('diemrenluyen'))
        except mysql.connector.Error as err:
            flash(f"Lỗi: {err}", "danger")
    
    # Fetch all students for the dropdown
    cursor.execute("SELECT ma_sv, ho_ten FROM sinhvien ORDER BY ho_ten")
    students = cursor.fetchall()
    return render_template("add_diemrenluyen.html", students=students)

@app.route('/edit_diemrenluyen/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_diemrenluyen(id):
    if not db.is_connected(): db.reconnect()
    if request.method == 'POST':
        hoc_ky = request.form['hoc_ky']
        diem_co_ban = int(request.form['diem_co_ban']) if request.form['diem_co_ban'] else 0
        diem_tru = int(request.form['diem_tru']) if request.form['diem_tru'] else 0

        # Fetch existing record to get diem_cong_hoat_dong
        cursor.execute("SELECT ma_sv, hoc_ky, diem_cong_hoat_dong FROM DiemRenLuyen WHERE id = %s", (id,))
        existing_drl = cursor.fetchone()
        
        if existing_drl:
            diem_cong_hoat_dong = existing_drl['diem_cong_hoat_dong'] if existing_drl['diem_cong_hoat_dong'] else 0
            total_diem = diem_co_ban + diem_cong_hoat_dong - diem_tru
            cursor.execute(
                "UPDATE DiemRenLuyen SET hoc_ky=%s, diem_co_ban=%s, diem_tru=%s, diem=%s WHERE id=%s",
                (hoc_ky, diem_co_ban, diem_tru, total_diem, id)
            )
            db.commit()
            flash('Cập nhật điểm rèn luyện thành công!', 'success')
            return redirect(url_for('diemrenluyen'))
        else:
            flash('Không tìm thấy bản ghi điểm rèn luyện để cập nhật.', 'danger')
            return redirect(url_for('diemrenluyen'))
    
    cursor.execute("SELECT * FROM DiemRenLuyen WHERE id=%s", (id,))
    record = cursor.fetchone()
    if not record:
        flash('Không tìm thấy bản ghi điểm rèn luyện.', 'warning')
        return redirect(url_for('diemrenluyen'))
    return render_template("edit_diemrenluyen.html", record=record)

@app.route('/delete_diemrenluyen/<int:id>')
@login_required
@admin_required
def delete_diemrenluyen(id):
    if not db.is_connected(): db.reconnect()
    cursor.execute("DELETE FROM DiemRenLuyen WHERE id=%s", (id,))
    db.commit()
    flash('Xóa điểm rèn luyện thành công!', 'success')
    return redirect(url_for('diemrenluyen'))

@app.route('/upload_diemrenluyen_excel', methods=['POST'])
@login_required
@admin_required
def upload_diemrenluyen_excel():
    if 'excel_file' not in request.files:
        flash('Không có tệp nào được chọn', 'danger')
        return redirect(url_for('diemrenluyen'))
    file = request.files['excel_file']
    if file.filename == '':
        flash('Chưa chọn tệp Excel nào', 'warning')
        return redirect(url_for('diemrenluyen'))
    if file and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
        try:
            df = pd.read_excel(file, dtype=str)
            for index, row in df.iterrows():
                ma_sv = row['ma_sv'].strip()
                hoc_ky = row['hoc_ky'].strip()
                diem_co_ban = int(row['diem_co_ban']) if 'diem_co_ban' in row and pd.notna(row['diem_co_ban']) else 0
                diem_tru = int(row['diem_tru']) if 'diem_tru' in row and pd.notna(row['diem_tru']) else 0
                
                if not db.is_connected(): db.reconnect()

                # Check if record already exists
                cursor.execute("SELECT id, diem_cong_hoat_dong FROM DiemRenLuyen WHERE ma_sv = %s AND hoc_ky = %s", (ma_sv, hoc_ky))
                existing_record = cursor.fetchone()

                if existing_record:
                    diem_cong_hoat_dong = existing_record['diem_cong_hoat_dong'] if existing_record['diem_cong_hoat_dong'] else 0
                    total_diem = diem_co_ban + diem_cong_hoat_dong - diem_tru
                    cursor.execute(
                        "UPDATE DiemRenLuyen SET diem_co_ban = %s, diem_tru = %s, diem = %s WHERE id = %s",
                        (diem_co_ban, diem_tru, total_diem, existing_record['id'])
                    )
                else:
                    total_diem = diem_co_ban - diem_tru # Initial total_diem for new record
                    cursor.execute(
                        "INSERT INTO DiemRenLuyen (ma_sv, hoc_ky, diem_co_ban, diem_tru, diem) VALUES (%s, %s, %s, %s, %s)",
                        (ma_sv, hoc_ky, diem_co_ban, diem_tru, total_diem)
                    )
            db.commit()
            flash('Dữ liệu điểm rèn luyện từ file Excel đã được thêm/cập nhật thành công!', 'success')
        except Exception as e:
            db.rollback()
            flash(f'Đã xảy ra lỗi khi xử lý file điểm rèn luyện: {e}', 'danger')
    else:
        flash('Định dạng tệp không hợp lệ. Vui lòng chọn file .xlsx hoặc .xls', 'danger')
    return redirect(url_for('diemrenluyen'))

# ========== XÉT ĐIỂM RÈN LUYỆN ==========
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/hoatdong')
@login_required
@admin_required
def hoatdong():
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT * FROM HoatDong ORDER BY hoc_ky, ten_hoat_dong")
    activities = cursor.fetchall()
    return render_template("hoatdong.html", activities=activities)

@app.route('/add_hoatdong', methods=['GET', 'POST'])
@login_required
@admin_required
def add_hoatdong():
    if request.method == 'POST':
        ten_hoat_dong = request.form['ten_hoat_dong']
        diem = int(request.form['diem'])
        hoc_ky = request.form['hoc_ky']
        try:
            if not db.is_connected(): db.reconnect()
            cursor.execute("INSERT INTO HoatDong (ten_hoat_dong, diem, hoc_ky) VALUES (%s, %s, %s)",
                           (ten_hoat_dong, diem, hoc_ky))
            db.commit()
            flash('Thêm hoạt động thành công!', 'success')
            return redirect(url_for('hoatdong'))
        except mysql.connector.Error as err:
            flash(f"Lỗi: {err}", "danger")
    return render_template("add_hoatdong.html")

@app.route('/edit_hoatdong/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_hoatdong(id):
    if not db.is_connected(): db.reconnect()
    cursor.execute("SELECT hoc_ky FROM HoatDong WHERE id = %s", (id,))
    old_activity = cursor.fetchone()
    old_hoc_ky = old_activity['hoc_ky'] if old_activity else None
    if request.method == 'POST':
        ten_hoat_dong = request.form['ten_hoat_dong']
        diem = int(request.form['diem'])
        hoc_ky = request.form['hoc_ky']
        try:
            cursor.execute("UPDATE HoatDong SET ten_hoat_dong = %s, diem = %s, hoc_ky = %s WHERE id = %s",
                           (ten_hoat_dong, diem, hoc_ky, id))
            cursor.execute("""
                SELECT DISTINCT ma_sv FROM DangKyHoatDong 
                WHERE hoat_dong_id = %s AND trang_thai = 'đã duyệt'
            """, (id,))
            students_to_update = cursor.fetchall()
            for student in students_to_update:
                if old_hoc_ky:
                    update_drl_score(student['ma_sv'], old_hoc_ky)
                if old_hoc_ky != hoc_ky:
                    update_drl_score(student['ma_sv'], hoc_ky)
            db.commit()
            flash('Cập nhật hoạt động thành công! Điểm rèn luyện của các sinh viên liên quan đã được tự động tính lại.', 'success')
            return redirect(url_for('hoatdong'))
        except mysql.connector.Error as err:
            flash(f"Lỗi: {err}", "danger")
    cursor.execute("SELECT * FROM HoatDong WHERE id = %s", (id,))
    activity = cursor.fetchone()
    return render_template("edit_hoatdong.html", activity=activity)

@app.route('/delete_hoatdong/<int:id>')
@login_required
@admin_required
def delete_hoatdong(id):
    try:
        if not db.is_connected(): db.reconnect()
        cursor.execute("DELETE FROM HoatDong WHERE id = %s", (id,))
        db.commit()
        flash('Xóa hoạt động thành công!', 'success')
    except mysql.connector.Error as err:
        flash(f"Lỗi: Không thể xóa hoạt động này vì đã có sinh viên đăng ký.", "danger")
    return redirect(url_for('hoatdong'))

@app.route('/xetdiem')
@login_required
def xetdiem():
    if not db.is_connected(): db.reconnect()
    if current_user.role == 'admin':
        query = """
            SELECT dkhd.*, sv.ho_ten, hd.ten_hoat_dong, hd.diem, hd.hoc_ky
            FROM DangKyHoatDong dkhd
            JOIN sinhvien sv ON dkhd.ma_sv = sv.ma_sv
            JOIN HoatDong hd ON dkhd.hoat_dong_id = hd.id
            WHERE dkhd.trang_thai = 'chờ duyệt'
            ORDER BY sv.ho_ten
        """
        cursor.execute(query)
        pending_submissions = cursor.fetchall()
        submissions_by_student = OrderedDict()
        for sub in pending_submissions:
            ma_sv = sub['ma_sv']
            if ma_sv not in submissions_by_student:
                submissions_by_student[ma_sv] = {'ho_ten': sub['ho_ten'], 'submissions': []}
            submissions_by_student[ma_sv]['submissions'].append(sub)
        return render_template("xetdiem_admin.html", submissions_by_student=submissions_by_student)
    else:
        cursor.execute("SELECT * FROM HoatDong ORDER BY hoc_ky, ten_hoat_dong")
        activities = cursor.fetchall()
        ma_sv = current_user.ma_sv
        query = """
            SELECT dkhd.*, hd.ten_hoat_dong, hd.diem, hd.hoc_ky
            FROM DangKyHoatDong dkhd
            JOIN HoatDong hd ON dkhd.hoat_dong_id = hd.id
            WHERE dkhd.ma_sv = %s
            ORDER BY dkhd.ngay_dang_ky DESC
        """
        cursor.execute(query, (ma_sv,))
        my_submissions = cursor.fetchall()
        return render_template("xetdiem_viewer.html", activities=activities, my_submissions=my_submissions)

@app.route('/xetdiem/dangky', methods=['POST'])
@login_required
def submit_activity():
    if current_user.role != 'viewer':
        flash('Chỉ sinh viên mới có thể nộp minh chứng.', 'danger')
        return redirect(url_for('xetdiem'))
    if not current_user.ma_sv:
        flash(f"Lỗi: Tài khoản '{current_user.username}' của bạn không được liên kết với Mã Sinh viên. Vui lòng liên hệ Admin.", 'danger')
        return redirect(url_for('xetdiem'))
    if 'minh_chung' not in request.files:
        flash('Không có tệp minh chứng nào được tải lên.', 'danger')
        return redirect(url_for('xetdiem'))
    file = request.files['minh_chung']
    hoat_dong_id = request.form['hoat_dong_id']
    if file.filename == '':
        flash('Chưa chọn tệp minh chứng.', 'warning')
        return redirect(url_for('xetdiem'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        ma_sv = current_user.ma_sv
        try:
            if not db.is_connected(): db.reconnect()
            cursor.execute("INSERT INTO DangKyHoatDong (ma_sv, hoat_dong_id, minh_chung_url) VALUES (%s, %s, %s)",
                           (ma_sv, hoat_dong_id, filename))
            db.commit()
            flash('Nộp minh chứng thành công! Vui lòng chờ duyệt.', 'success')
        except mysql.connector.Error as err:
            flash(f"Lỗi: {err}", "danger")
    else:
        flash('Định dạng tệp không hợp lệ. Chỉ chấp nhận png, jpg, jpeg, gif.', 'danger')
    return redirect(url_for('xetdiem'))

@app.route('/xetdiem/approve/<int:submission_id>')
@login_required
@admin_required
def approve_submission(submission_id):
    try:
        if not db.is_connected(): db.reconnect()
        query = """
            SELECT dkhd.ma_sv, hd.hoc_ky
            FROM DangKyHoatDong dkhd
            JOIN HoatDong hd ON dkhd.hoat_dong_id = hd.id
            WHERE dkhd.id = %s
        """
        cursor.execute(query, (submission_id,))
        submission_data = cursor.fetchone()
        if submission_data:
            update_drl_score(submission_data['ma_sv'], submission_data['hoc_ky'], submission_id)
            db.commit()
            flash('Đã duyệt thành công và cập nhật tổng điểm rèn luyện.', 'success')
        else:
            flash('Không tìm thấy minh chứng để duyệt.', 'warning')
    except mysql.connector.Error as err:
        db.rollback()
        flash(f"Lỗi khi duyệt: {err}", "danger")
    return redirect(url_for('xetdiem'))

# ========== CHẠY APP ==========
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
