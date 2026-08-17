from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from typing import Optional, List
from auth_user import decode_token, create_token, secret_password_admin, secret_password_editor
from database import engine, Base, get_db
import models
from models import User, UserRoleEnum, Role, Book, Author
from schemas import (
    UserCreate,
    UserResponse,
    Userlogin,
    BookCreate,
    BookResponse,
    AuthorCreate,
    AuthorResponse,
    LoginResponse,
    UserUpdate
)

print(" creating database ...")
Base.metadata.create_all(bind=engine)
print(" database created")

app = FastAPI(
    title="سامانه مدیریت کتابخانه",
    description="API برای مدیریت کتابخانه، کاربران و نقش‌ها",
    version="1.0.0"
)

security = HTTPBearer()

VIOWER = "VIOWER"
EDITOR = "EDITOR"
ADMIN = "ADMIN"

####################################امنیت توکن#########################

def get_current_user_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """دریافت کاربر فعلی از توکن"""
    try:

        token = credentials.credentials

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="توکن ارسال نشده است"
            )

        payload = decode_token(token)

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="شناسه کاربر در توکن یافت نشد"
            )

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="کاربر یافت نشد"
            )

        user_roles = [role.Role_of_user.value for role in user.roles]

        return user

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"خطا در احراز هویت: {str(e)}"
        )

########################################   لاگین   ################################################################
@app.post("/login/", response_model=LoginResponse)
def login_user(response: Userlogin, db: Session = Depends(get_db)):
    # پیدا کردن کاربر
    user_obj = db.query(User).filter(User.username == response.username).first()

    if not user_obj:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="نام کاربری یا رمز عبور اشتباه است"
        )

    if not user_obj.verify_password(response.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="نام کاربری یا رمز عبور اشتباه است"
        )

    # دریافت نقش کاربر از دیتابیس
    user_role = user_obj.roles[0].Role_of_user.value if user_obj.roles else VIOWER

    # ایجاد توکن با نقش واقعی کاربر
    access_token = create_token(user_obj.id, user_role)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user_obj)
    )

###########################################  ثبت نام    ##########################################################

@app.post("/users_create/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="نام کاربری یا ایمیل قبلاً ثبت شده است")

    if user.invite_code == secret_password_admin:
        role_enum = UserRoleEnum.ADMIN
    elif user.invite_code == secret_password_editor:
        role_enum = UserRoleEnum.EDITOR
    else:
        role_enum = UserRoleEnum.VIOWER

    new_user = User(
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        invite_code = user.invite_code
    )

    new_user.set_password(user.password)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    role = db.query(Role).filter(Role.Role_of_user == role_enum).first()

    if not role:
        role = Role(Role_of_user=role_enum)
        db.add(role)
        db.commit()
        db.refresh(role)

    new_user.roles.append(role)

    db.commit()
    db.refresh(new_user)

    return new_user

##############################################################################################################

@app.post("/book_create/", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
def create_book(
    book: BookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب ایجاد کنند"
        )

    new_book = Book(
        title=book.title,
        publisher=book.publisher,
        category=book.category,
        description=book.description,
        quantity=book.quantity
    )

    db.add(new_book)
    db.commit()
    db.refresh(new_book)

    if book.author_ids:
        authors = db.query(Author).filter(Author.id.in_(book.author_ids)).all()
        if authors:
            new_book.authors.extend(authors)
            db.commit()
            db.refresh(new_book)

    return new_book

@app.get("/books/", response_model=List[BookResponse])
def get_books(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token)
):
    books = db.query(Book).all()
    return books



@app.get("/books/{book_id}/", response_model=BookResponse)
def get_book(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token)
):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="کتاب یافت نشد"
        )
    return book

@app.put("/books/update/{book_id}/", response_model=BookResponse)
def update_book(
    book_id: int,
    book_update: BookCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب را ویرایش کنند"
        )

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="کتاب یافت نشد"
        )

    book.title = book_update.title
    book.publisher = book_update.publisher
    book.category = book_update.category
    book.description = book_update.description
    book.quantity = book_update.quantity

    if book_update.author_ids is not None:
        authors = db.query(Author).filter(Author.id.in_(book_update.author_ids)).all()
        book.authors = authors

    db.commit()
    db.refresh(book)

    return book


@app.delete("/books/delete/{book_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب ایجاد کنند"
        )

    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="کتاب یافت نشد"
        )

    db.delete(book)
    db.commit()

    return None


@app.post("/authors/craete/", response_model=AuthorResponse, status_code=status.HTTP_201_CREATED)
def create_author(
    author: AuthorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب ایجاد کنند"
        )

    new_author = Author(
        first_name=author.first_name,
        last_name=author.last_name,
        birth_date=author.birth_date,
        nationality=author.nationality)

    db.add(new_author)
    db.commit()
    db.refresh(new_author)

    return new_author

@app.get("/authors/", response_model=List[AuthorResponse])
def get_authors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token)
):
    authors = db.query(Author).all()
    return authors

@app.get("/authors/{author_id}/", response_model=AuthorResponse)
def get_author(
    author_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token)
):
    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="نویسنده یافت نشد")
    return author


@app.put("/authors/update/{author_id}/", response_model=AuthorResponse)
def update_author(
    author_id: int,
    author_update: AuthorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب ایجاد کنند"
        )

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="نویسنده یافت نشد")

    author.first_name = author_update.first_name
    author.last_name = author_update.last_name
    author.birth_date = author_update.birth_date
    author.nationality = author_update.nationality

    db.commit()
    db.refresh(author)

    return author


@app.delete("/authors/delete/{author_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_author(
    author_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role not in (ADMIN, EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین و ویرایشگر می‌توانند کتاب ایجاد کنند"
        )

    author = db.query(Author).filter(Author.id == author_id).first()
    if not author:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="نویسنده یافت نشد"
        )

    db.delete(author)
    db.commit()

    return None



@app.get("/users/", response_model=List[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین می‌تواند لیست کاربران را ببیند")

    users = db.query(User).all()
    return users

@app.get("/users/{user_id}/", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین می‌تواند اطلاعات کاربران را ببیند"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="کاربر یافت نشد"
        )
    return user



@app.put("/me_update/", response_model=UserResponse)
def update_current_user(
    user_update: UserUpdate,
    db: Session = Depends(get_db),  current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    is_admin = current_role == ADMIN

    # بررسی یکتایی
    if user_update.username is not None and user_update.username != current_user.username:
        existing = db.query(User).filter(
            User.username == user_update.username,
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="این نام کاربری قبلاً استفاده شده است"
            )
        current_user.username = user_update.username

    # بررسی یکتایی
    if user_update.email is not None and user_update.email != current_user.email:
        existing = db.query(User).filter(
            User.email == user_update.email,
            User.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="این ایمیل قبلاً توسط کاربر دیگری استفاده شده است"
            )
        current_user.email = user_update.email

    if user_update.first_name is not None:
        current_user.first_name = user_update.first_name

    if user_update.last_name is not None:
        current_user.last_name = user_update.last_name

    if user_update.password is not None:
        current_user.set_password(user_update.password)

    # role_ids فقط توسط ادمین قابل تغییر است — حتی برای خودش
    if user_update.role_ids is not None:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="شما دسترسی تغییر نقش را ندارید"
            )
        roles = db.query(Role).filter(Role.id.in_(user_update.role_ids)).all()
        if len(roles) != len(user_update.role_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="یک یا چند شناسه نقش نامعتبر است"
            )
        current_user.roles = roles

    db.commit()
    db.refresh(current_user)

    return current_user

@app.delete("/users/delete/{user_id}/", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token), 
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    payload = decode_token(token)

    # بررسی دسترسی - فقط ADMIN و EDITOR
    current_role = payload.get("type")
    if current_role != ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="شما دسترسی لازم را ندارید. فقط ادمین می‌تواند کاربر را حذف کند"
        )

    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="شما نمی‌توانید خودتان را حذف کنید")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="کاربر یافت نشد"
        )

    db.delete(user)
    db.commit()

    return None

@app.get("/me/", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_user_from_token)
):
    return current_user

