import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ایمپورت همه مدل‌ها قبل از ایجاد جداول
from main import app
from database import Base, get_db
import models
from models import User, Role, Book, Author, UserRoleEnum
from auth_user import secret_password_admin, secret_password_editor

# ==================== تنظیم دیتابیس تست ====================

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db_session():
    """ایجاد نشست دیتابیس برای هر تست"""
    # ایجاد جداول
    Base.metadata.create_all(bind=engine)
    
    # ایجاد نشست
    db = TestingSessionLocal()
    try:
        # ایجاد نقش‌های اولیه
        admin_role = models.Role(Role_of_user=UserRoleEnum.ADMIN)
        editor_role = models.Role(Role_of_user=UserRoleEnum.EDITOR)
        viewer_role = models.Role(Role_of_user=UserRoleEnum.VIOWER)
        db.add_all([admin_role, editor_role, viewer_role])
        db.commit()
        
        yield db
    finally:
        db.close()
        # پاک کردن جداول بعد از تست
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """ایجاد کلاینت تست با دیتابیس جدید برای هر تست"""
    with TestClient(app) as test_client:
        yield test_client


# ==================== توابع کمکی ====================

def register_and_login(client, username, email, role="viewer", db_session=None):
    """ثبت‌نام و لاگین کاربر با نقش مشخص"""
    invite_code_map = {
        "admin": secret_password_admin,
        "editor": secret_password_editor,
        "viewer": "normal_code_123"
    }
    
    invite_code = invite_code_map.get(role, "normal_code_123")
    
    # ثبت‌نام
    resp = client.post("/users_create/", json={
        "username": username,
        "email": email,
        "first_name": "تست",
        "last_name": "کاربر",
        "password": invite_code,
        "invite_code": invite_code
    })
    
    if resp.status_code != 201:
        print(f" خطا در ثبت‌نام: {resp.status_code} - {resp.text}")
        return None
    
    # لاگین
    login_resp = client.post("/login/", json={
        "username": username,
        "password": invite_code
    })
    
    if login_resp.status_code != 200:
        print(f" خطا در لاگین: {login_resp.status_code} - {login_resp.text}")
        return None
    
    return login_resp.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ==================== تست‌ها ====================

class TestRoleAccess:
    """تست دسترسی بر اساس نقش‌ها"""
    
    def test_admin_can_create_book(self, client, db_session):
        """تست موفق: ادمین می‌تواند کتاب ایجاد کند"""
        token = register_and_login(client, "admin_test", "admin@test.com", role="admin")
        assert token is not None, "توکن دریافت نشد"
        
        resp = client.post("/book_create/", json={
            "title": "کتاب تست",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 5,
            "author_ids": []
        }, headers=auth_header(token))
        
        assert resp.status_code == 201
        assert resp.json()["title"] == "کتاب تست"
    
    def test_viewer_cannot_create_book(self, client, db_session):
        """تست رد دسترسی: viewer نمی‌تواند کتاب ایجاد کند"""
        token = register_and_login(client, "viewer_test", "viewer@test.com", role="viewer")
        assert token is not None
        
        resp = client.post("/book_create/", json={
            "title": "کتاب تست",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 5,
            "author_ids": []
        }, headers=auth_header(token))
        
        assert resp.status_code == 403
        assert "دسترسی لازم را ندارید" in resp.json()["detail"]
    
    def test_editor_can_create_book(self, client, db_session):
        """تست موفق: ویرایشگر می‌تواند کتاب ایجاد کند"""
        token = register_and_login(client, "editor_test", "editor@test.com", role="editor")
        assert token is not None
        
        resp = client.post("/book_create/", json={
            "title": "کتاب ویرایشگر",
            "publisher": "ناشر",
            "category": "علمی",
            "description": "توضیحات",
            "quantity": 3,
            "author_ids": []
        }, headers=auth_header(token))
        
        assert resp.status_code == 201
    
    def test_viewer_cannot_list_users(self, client, db_session):
        """تست رد دسترسی: viewer نمی‌تواند لیست کاربران را ببیند"""
        token = register_and_login(client, "viewer_list", "viewer_list@test.com", role="viewer")
        assert token is not None
        
        resp = client.get("/users/", headers=auth_header(token))
        assert resp.status_code == 403
    
    def test_admin_can_list_users(self, client, db_session):
        """تست موفق: ادمین می‌تواند لیست کاربران را ببیند"""
        token = register_and_login(client, "admin_list", "admin_list@test.com", role="admin")
        assert token is not None
        
        resp = client.get("/users/", headers=auth_header(token))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
    
    def test_viewer_cannot_delete_book(self, client, db_session):
        """تست رد دسترسی: viewer نمی‌تواند کتاب را حذف کند"""
        # ابتدا یک کتاب توسط ادمین ایجاد می‌کنیم
        admin_token = register_and_login(client, "admin_del", "admin_del@test.com", role="admin")
        assert admin_token is not None
        
        book_resp = client.post("/book_create/", json={
            "title": "کتاب برای حذف",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 1,
            "author_ids": []
        }, headers=auth_header(admin_token))
        assert book_resp.status_code == 201
        book_id = book_resp.json()["id"]
        
        # viewer سعی می‌کند کتاب را حذف کند
        viewer_token = register_and_login(client, "viewer_del", "viewer_del@test.com", role="viewer")
        assert viewer_token is not None
        
        resp = client.delete(f"/books/{book_id}/", headers=auth_header(viewer_token))
        assert resp.status_code == 403
    
    def test_editor_can_delete_book(self, client, db_session):
        """تست موفق: ویرایشگر می‌تواند کتاب را حذف کند"""
        # ابتدا یک کتاب توسط ادمین ایجاد می‌کنیم
        admin_token = register_and_login(client, "admin_ed_del", "admin_ed_del@test.com", role="admin")
        assert admin_token is not None
        
        book_resp = client.post("/book_create/", json={
            "title": "کتاب برای حذف توسط ویرایشگر",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 1,
            "author_ids": []
        }, headers=auth_header(admin_token))
        assert book_resp.status_code == 201
        book_id = book_resp.json()["id"]
        
        # ویرایشگر کتاب را حذف می‌کند
        editor_token = register_and_login(client, "editor_del", "editor_del@test.com", role="editor")
        assert editor_token is not None
        
        resp = client.delete(f"/books/{book_id}/", headers=auth_header(editor_token))
        assert resp.status_code == 204
    
    def test_viewer_cannot_change_role(self, client, db_session):
        """تست رد دسترسی: viewer نمی‌تواند نقش خود را تغییر دهد"""
        token = register_and_login(client, "viewer_role", "viewer_role@test.com", role="viewer")
        assert token is not None
        
        # دریافت role_id از دیتابیس
        admin_role = db_session.query(models.Role).filter(
            models.Role.Role_of_user == UserRoleEnum.ADMIN
        ).first()
        
        assert admin_role is not None, "نقش ادمین در دیتابیس وجود ندارد"
        role_id = admin_role.id
        
        # تلاش برای تغییر نقش
        resp = client.put("/me_update/", json={
            "role_ids": [role_id]
        }, headers=auth_header(token))
        
        assert resp.status_code == 403