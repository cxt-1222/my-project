import bcrypt


def _to_bytes(password: str) -> bytes:
    """密码转 bytes 并截断到 72 字节（bcrypt 上限）"""
    return password.encode("utf-8")[:72]


def get_password_hash(password: str) -> str:
    """明文密码 → bcrypt 哈希"""
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验：明文密码和数据库里的哈希是否匹配"""
    try:
        return bcrypt.checkpw(_to_bytes(plain_password), hashed_password.encode("utf-8"))
    except ValueError:
        return False
