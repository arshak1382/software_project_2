"""
تست‌های کنترل دسترسی (RBAC) — نسخه‌ی خلاصه
فقط سناریوهای موفق/ناموفق دسترسی بین نقش‌ها (VIOWER / EDITOR / ADMIN)

نحوه‌ی استفاده: مثل فایل قبلی — کنار main.py قرار دهید و اجرا کنید:
    pytest test_access_control.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from database import Base, get_db
from auth_user import secret_password_admin, secret_password_editor

# ==================== تنظیم دیتابیس تست ====================

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app)


# ==================== تابع کمکی برای ساخت کاربر با نقش دلخواه ====================

def register_user(client, username, email, as_role="viewer"):
    """
    as_role: "viewer" | "editor" | "admin"
    نقش با استفاده از همان منطق پسورد مخفی برنامه تعیین می‌شود.
    """
    password = {
        "admin": secret_password_admin,
        "editor": secret_password_editor,
    }.get(as_role, "normal_pass_123")

    resp = client.post("/users/", json={
        "username": username,
        "email": email,
        "first_name": "تست",
        "last_name": "کاربر",
        "password": password,
    })
    assert resp.status_code == 201, f"ثبت‌نام ناموفق: {resp.text}"

    login_resp = client.post("/login/", json={"username": username, "password": password})
    assert login_resp.status_code == 200, f"لاگین ناموفق: {login_resp.text}"

    return login_resp.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ==================== سناریوهای دسترسی ====================

class TestViewerCannotDoAdminActions:
    """viewer تلاش می‌کند کارهای مخصوص ادمین را انجام دهد — همه باید رد شوند (403)"""

    def test_viewer_cannot_create_author(self, client):
        token = register_user(client, "viewer1", "viewer1@example.com", as_role="viewer")

        resp = client.post("/authors/", json={
            "first_name": "نویسنده",
            "last_name": "تست",
            "birth_date": "1990-01-01",
            "nationality": "ایرانی",
        }, headers=auth_header(token))

        assert resp.status_code == 403

    def test_viewer_cannot_delete_book(self, client):
        admin_token = register_user(client, "admin_del", "admin_del@example.com", as_role="admin")
        book_resp = client.post("/book_create/", json={
            "title": "کتاب تست",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 1,
        }, headers=auth_header(admin_token))
        book_id = book_resp.json()["id"]

        viewer_token = register_user(client, "viewer2", "viewer2@example.com", as_role="viewer")
        resp = client.delete(f"/books/{book_id}/", headers=auth_header(viewer_token))

        assert resp.status_code == 403

    def test_viewer_cannot_list_all_users(self, client):
        token = register_user(client, "viewer3", "viewer3@example.com", as_role="viewer")
        resp = client.get("/users/", headers=auth_header(token))
        assert resp.status_code == 403

    def test_viewer_cannot_change_own_role_to_admin(self, client):
        """مهم‌ترین تست امنیتی: viewer نباید بتواند از طریق /me/ خودش را ادمین کند"""
        token = register_user(client, "viewer4", "viewer4@example.com", as_role="viewer")
        resp = client.put("/me/", json={"role_ids": [1]}, headers=auth_header(token))
        assert resp.status_code == 403


class TestEditorPartialAccess:
    """editor به بعضی کارها دسترسی دارد (کتاب) ولی نه همه (نویسنده، کاربران)"""

    def test_editor_can_create_book(self, client):
        token = register_user(client, "editor1", "editor1@example.com", as_role="editor")
        resp = client.post("/book_create/", json={
            "title": "کتاب ویرایشگر",
            "publisher": "ناشر",
            "category": "علمی",
            "description": "توضیحات",
            "quantity": 3,
        }, headers=auth_header(token))
        assert resp.status_code == 201

    def test_editor_cannot_create_author(self, client):
        """ساخت نویسنده فقط مخصوص ادمین است، حتی editor هم نباید بتواند"""
        token = register_user(client, "editor2", "editor2@example.com", as_role="editor")
        resp = client.post("/authors/", json={
            "first_name": "نویسنده",
            "last_name": "تست",
            "birth_date": "1990-01-01",
            "nationality": "ایرانی",
        }, headers=auth_header(token))
        assert resp.status_code == 403

    def test_editor_cannot_delete_book(self, client):
        """حذف کتاب فقط مخصوص ادمین است، editor فقط می‌تواند بسازد/ویرایش کند"""
        admin_token = register_user(client, "admin_ed", "admin_ed@example.com", as_role="admin")
        book_resp = client.post("/book_create/", json={
            "title": "کتاب دیگر",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 1,
        }, headers=auth_header(admin_token))
        book_id = book_resp.json()["id"]

        editor_token = register_user(client, "editor3", "editor3@example.com", as_role="editor")
        resp = client.delete(f"/books/{book_id}/", headers=auth_header(editor_token))
        assert resp.status_code == 403


class TestAdminFullAccess:
    """ادمین باید بتواند همه‌ی این کارها را با موفقیت انجام دهد"""

    def test_admin_can_create_author(self, client):
        token = register_user(client, "admin_a", "admin_a@example.com", as_role="admin")
        resp = client.post("/authors/", json={
            "first_name": "نویسنده",
            "last_name": "ادمین",
            "birth_date": "1990-01-01",
            "nationality": "ایرانی",
        }, headers=auth_header(token))
        assert resp.status_code == 201

    def test_admin_can_delete_book(self, client):
        token = register_user(client, "admin_b", "admin_b@example.com", as_role="admin")
        book_resp = client.post("/book_create/", json={
            "title": "کتاب برای حذف",
            "publisher": "ناشر",
            "category": "رمان",
            "description": "توضیحات",
            "quantity": 1,
        }, headers=auth_header(token))
        book_id = book_resp.json()["id"]

        resp = client.delete(f"/books/{book_id}/", headers=auth_header(token))
        assert resp.status_code == 204

    def test_admin_can_list_all_users(self, client):
        token = register_user(client, "admin_c", "admin_c@example.com", as_role="admin")
        resp = client.get("/users/", headers=auth_header(token))
        assert resp.status_code == 200

    def test_admin_can_change_own_role(self, client):
        token = register_user(client, "admin_d", "admin_d@example.com", as_role="admin")
        roles = client.get("/roles/", headers=auth_header(token)).json()
        role_id = roles[0]["id"]

        resp = client.put("/me/", json={"role_ids": [role_id]}, headers=auth_header(token))
        assert resp.status_code == 200
