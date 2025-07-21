import pandas as pd
import mysql.connector
from werkzeug.security import generate_password_hash
import unicodedata

# --- CẤU HÌNH ---
DB_CONFIG = {
    'host': "localhost",
    'user': "root",
    'password': "",
    'database': "quanlysinhvien"
}
EXCEL_FILE_PATH = 'Danh_sach_sv_KTPM47.xlsx' # Tên file danh sách lớp

# --- HÀM HỖ TRỢ ---
def remove_accents(input_str):
    """Chuyển chuỗi có dấu thành không dấu"""
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])

def create_username(full_name, ma_sv, existing_usernames):
    """Tạo username theo quy tắc: ten + ma_sv, không dấu, không khoảng trắng"""
    # Chuyển tên thành không dấu và chữ thường
    no_accent_name = remove_accents(full_name).lower()
    parts = no_accent_name.split()
    
    # Lấy tên (từ cuối cùng trong họ tên)
    last_name = parts[-1] if parts else "user"
    
    # Tạo username cơ bản
    base_username = last_name + ma_sv

    # Xử lý trùng lặp (dù ít khả năng xảy ra với quy tắc này)
    username = base_username
    counter = 1
    while username in existing_usernames:
        username = f"{base_username}{counter}"
        counter += 1
    
    return username

# --- HÀM CHÍNH ---
def main():
    print("Bắt đầu quá trình tạo tài khoản...")
    
    try:
        # Đọc file Excel
        df = pd.read_excel(EXCEL_FILE_PATH)
        print(f"Đã đọc thành công {len(df)} sinh viên từ file Excel.")
        
        # Kết nối CSDL
        db = mysql.connector.connect(**DB_CONFIG)
        cursor = db.cursor()
        print("Kết nối cơ sở dữ liệu thành công.")
        
        # Làm rỗng bảng Users để tạo lại từ đầu
        print("Đang làm rỗng bảng Users...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute("TRUNCATE TABLE Users;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        print("Đã làm rỗng bảng Users thành công.")
        
        # Thêm tài khoản admin
        admin_username = "adminktpm47"
        admin_password = "adminktpm47@@"
        hashed_admin_password = generate_password_hash(admin_password, method='pbkdf2:sha256')
        
        cursor.execute(
            "INSERT INTO Users (username, password_hash, role, ma_sv) VALUES (%s, %s, %s, %s)",
            (admin_username, hashed_admin_password, 'admin', None) # admin không có ma_sv
        )
        print(f"  - Đã thêm tài khoản Admin: {admin_username} | Mật khẩu: {admin_password} | Vai trò: admin")

        # Lấy danh sách username hiện có (bao gồm cả admin vừa thêm)
        cursor.execute("SELECT username FROM Users")
        existing_usernames = {row[0] for row in cursor.fetchall()}
        
        users_to_insert = []
        
        # Lặp qua danh sách sinh viên để chuẩn bị dữ liệu
        for index, row in df.iterrows():
            full_name = str(row['ho_ten']).strip()
            ma_sv = str(row['ma_sv']).strip()
            
            # Tạo username và mật khẩu theo quy tắc mới
            username = create_username(full_name, ma_sv, existing_usernames)
            password = ma_sv # Mật khẩu là mã sinh viên
            hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
            
            # Phân quyền: tất cả sinh viên là viewer
            role = 'viewer'
            ma_sv_for_insert = ma_sv # Viewer có ma_sv
            users_to_insert.append((username, hashed_password, role, ma_sv_for_insert))
            
            existing_usernames.add(username)
            print(f"  - Đã chuẩn bị tài khoản: {username} | Mật khẩu: {password} | Vai trò: {role} | MSV: {ma_sv_for_insert}")

        # Thêm tất cả tài khoản sinh viên vào CSDL
        sql = "INSERT INTO Users (username, password_hash, role, ma_sv) VALUES (%s, %s, %s, %s)"
        cursor.executemany(sql, users_to_insert)
        db.commit()
        
        print(f"\nTHÀNH CÔNG! Đã thêm {len(users_to_insert)} tài khoản sinh viên mới vào cơ sở dữ liệu.")
        print(f"Tổng số tài khoản đã tạo: {len(users_to_insert) + 1} (bao gồm 1 admin và {len(users_to_insert)} sinh viên).")

    except FileNotFoundError:
        print(f"LỖI: Không tìm thấy file '{EXCEL_FILE_PATH}'. Vui lòng đảm bảo file này nằm cùng thư mục.")
    except Exception as e:
        print(f"Đã xảy ra lỗi: {e}")
    finally:
        if 'db' in locals() and db.is_connected():
            cursor.close()
            db.close()
            print("Đã đóng kết nối cơ sở dữ liệu.")

if __name__ == '__main__':
    main()