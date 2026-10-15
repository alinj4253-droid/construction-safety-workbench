from __future__ import annotations
import hashlib
import secrets
from datetime import datetime,timedelta
from fastapi import Header,HTTPException
from backend.app import db

def digest(token):return hashlib.sha256(token.encode()).hexdigest()

def current_user(authorization:str=Header(default='')):
    token=authorization.removeprefix('Bearer ').strip()
    user=db.one('SELECT u.* FROM users u JOIN tokens t ON t.user_id=u.id WHERE t.token_hash=? AND t.expires_at>?',(digest(token),db.now())) if token else None
    if not user:raise HTTPException(401,'请登录或重新登录')
    user.pop('password_hash',None)
    return user

def require_operator(user):
    if user['role'] not in {'专职安全员','安全员'}:raise HTTPException(403,'当前身份可查看和督办；办理、签发与复查请使用安全员身份')

def login(username,password):
    user=db.one('SELECT * FROM users WHERE username=?',(username,))
    if not user or not db.password_ok(password,user['password_hash']):raise HTTPException(401,'账号或密码错误')
    token=secrets.token_urlsafe(40)
    with db.connect() as c:
        c.execute('INSERT INTO tokens VALUES(?,?,?)',(digest(token),user['id'],(datetime.now(db.TZ)+timedelta(hours=8)).isoformat(timespec='seconds')))
        db.audit(c,user['id'],'login','user',user['id'])
    user.pop('password_hash')
    return {'token':token,'user':user}
