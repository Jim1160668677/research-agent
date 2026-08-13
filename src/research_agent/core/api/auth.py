"""认证 API - 注册/登录/登出/用户信息"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_db
from ..auth import (
    create_access_token,
    get_current_user,
)
from ..models.db import User
from ..models.schemas import UserCreate, UserResponse
from ...security import CryptoService

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not v or len(v) < 3:
            raise ValueError("用户名至少3个字符")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("密码至少8个字符")
        return v


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """Return the minimal state needed to choose setup or login UI."""
    result = await db.execute(select(User.id).limit(1))
    return {
        "initialized": result.scalar_one_or_none() is not None,
        "registration_enabled": True,
    }


@router.post("/setup", response_model=TokenResponse)
async def setup_first_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create the installation owner exactly once and sign them in.

    The desktop API binds only to loopback. This endpoint replaces the former
    generated password that was written to an invisible packaged console.
    """
    result = await db.execute(select(User.id).limit(1))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="系统已完成初始化",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=CryptoService.hash_password(body.password),
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
        ),
    )


@router.post("/register", response_model=TokenResponse)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """注册新用户并自动登录"""
    existing_user_result = await db.execute(select(User.id).limit(1))
    is_first_user = existing_user_result.scalar_one_or_none() is None
    # 检查用户名是否存在
    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被使用",
        )

    # 检查邮箱是否存在
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱已被注册",
        )

    # 创建用户
    user = User(
        username=body.username,
        email=body.email,
        hashed_password=CryptoService.hash_password(body.password),
        role="admin" if is_first_user else "researcher",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 自动登录
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    if not user or not CryptoService.verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
    return TokenResponse(
        access_token=token,
        user=UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            role=user.role,
        ),
    )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """登出 (客户端清除 Token)"""
    return {"message": "已登出"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户信息"""
    result = await db.execute(
        select(User).where(User.id == current_user["user_id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
    )


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改密码"""
    result = await db.execute(
        select(User).where(User.id == current_user["user_id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not CryptoService.verify_password(body.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="原密码错误",
        )

    user.hashed_password = CryptoService.hash_password(body.new_password)
    await db.commit()
    return {"message": "密码已更新"}


@router.post("/bootstrap")
async def bootstrap(
    db: AsyncSession = Depends(get_db),
):
    """首次启动引导 - 创建默认 admin 用户 (仅当无用户时)"""
    from ..models.db import UserProfile

    result = await db.execute(select(User).limit(1))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统已有用户，无需引导",
        )

    import secrets
    import string

    # 生成临时密码
    chars = string.ascii_letters + string.digits
    temp_password = ''.join(secrets.choice(chars) for _ in range(16))

    admin = User(
        username="admin",
        email="admin@research.local",
        hashed_password=CryptoService.hash_password(temp_password),
        role="admin",
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    # 创建用户档案
    profile = UserProfile(
        user_id=admin.id,
        research_fields=["计算机科学", "人工智能"],
    )
    db.add(profile)
    await db.commit()

    return {
        "username": "admin",
        "temporary_password": temp_password,
        "message": "请使用临时密码登录后立即修改",
    }
