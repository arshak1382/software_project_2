import jwt
from jwt.exceptions import DecodeError, InvalidSignatureError, ExpiredSignatureError
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import User

SECRET_KEY = "my-secret-key-12345"
ALGORITHM = "HS256"
EXPIRE_MINUTES = 30

# پسوردهای ادمین و ادیتور
secret_password_admin = "rsehzerfhregwsgeh"
secret_password_editor = "kljj;jhlhbhjkhbkl"


def create_token(user_id: int, type_user: str) -> str:

    expire = datetime.now(timezone.utc) + timedelta(minutes=EXPIRE_MINUTES)
    
    payload = {"user_id": user_id , "exp": expire  ,  "iat": datetime.now(timezone.utc),  "type": type_user}
    
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    return token


def decode_token(token: str) -> dict:

    try:
        #دیباگ برسی اتمام زمان
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
 
        exp = payload.get("exp")
        if exp:

            exp_time = datetime.fromtimestamp(exp, tz=timezone.utc)
            now = datetime.now(timezone.utc)

            if exp_time < now:

                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="توکن منقضی شده است. لطفاً دوباره لاگین کنید")
            
            
            else:
                remaining = (exp_time - now).total_seconds()

        
        return payload
        
    except ExpiredSignatureError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توکن منقضی شده است. لطفاً دوباره لاگین کنید")
    

    except InvalidSignatureError:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="امضای توکن نامعتبر است"

        )
    except DecodeError as e:

        raise HTTPException( status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"توکن نامعتبر است: {str(e)}")
    


    except HTTPException:
        raise
    except Exception as e:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"خطا در اعتبارسنجی توکن: {str(e)}"

        )


def get_current_user(token: str, db: Session) -> User:

    payload = decode_token(token)
    user_id = payload.get("user_id")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="شناسه کاربرت در توکن یافت نشد"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="کاربری یافت نشد"


        )

    return user