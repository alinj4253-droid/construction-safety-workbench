from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Depends,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from backend.app import db
from backend.app.security import current_user,login,digest
from backend.app.dashboard import router as dashboard_router
from backend.app.hazards import router as hazards_router
from backend.app.chat import router as chat_router
from backend.app.documents import router as documents_router
from backend.app.memory import router as memory_router
from backend.app.handle import router as handle_router

def ok(data=None,message='ok'):return {'code':0,'data':data,'message':message}

@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield

app=FastAPI(title='施工安全管理工作台',version='1.0.0',lifespan=lifespan)
app.include_router(dashboard_router)
app.include_router(hazards_router)
app.include_router(chat_router)
app.include_router(documents_router)
app.include_router(memory_router)
app.include_router(handle_router)
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:8010','http://localhost:8010'],allow_methods=['GET','POST','DELETE','PATCH'],allow_headers=['Authorization','Content-Type'])

@app.exception_handler(HTTPException)
async def http_error(request,exc):return JSONResponse({'code':exc.status_code,'data':None,'message':str(exc.detail)},status_code=exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):return JSONResponse({'code':422,'data':None,'message':'输入格式有误，请检查必填字段'},status_code=422)

@app.exception_handler(ValueError)
async def value_error(request,exc):return JSONResponse({'code':400,'data':None,'message':str(exc)},status_code=400)

class LoginInput(BaseModel):
    username:str
    password:str

@app.get('/api/health')
def health():return ok({'status':'ok','version':'1.0.0'})

@app.get('/api/auth/users')
def identities():return ok(db.rows('SELECT username,display_name,role,employee_no FROM users ORDER BY id'))

@app.post('/api/auth/login')
def auth_login(body:LoginInput):return ok(login(body.username,body.password))

@app.get('/api/auth/me')
def me(user=Depends(current_user)):return ok(user)

@app.post('/api/auth/logout')
def logout(request:Request,user=Depends(current_user)):
    with db.connect() as c:
        c.execute('DELETE FROM tokens WHERE token_hash=?',(digest(request.headers.get('authorization','').removeprefix('Bearer ').strip()),))
        db.audit(c,user['id'],'logout','user',user['id'])
    return ok()

@app.get('/')
def index():return FileResponse(db.ROOT/'frontend/index.html')

app.mount('/static',StaticFiles(directory=db.ROOT/'frontend'),name='static')
app.mount('/videos',StaticFiles(directory=db.ROOT/'videos'),name='videos')

@app.get('/favicon.ico',include_in_schema=False)
def favicon():return JSONResponse(None,status_code=204)

@app.get('/api/kb/sources/{sid:int}')
def source_detail(sid:int,user=Depends(current_user)):
    s=db.one('SELECT * FROM kb_sources WHERE id=?',(sid,))
    if not s:raise HTTPException(404,'资料不存在')
    s['chunks']=db.rows('SELECT * FROM kb_chunks WHERE source_id=? ORDER BY page,chunk_id LIMIT 100',(sid,))
    return ok(s)

@app.get('/api/kb/sources/{sid:int}/file')
def source_file(sid:int,user=Depends(current_user)):
    s=db.one('SELECT * FROM kb_sources WHERE id=?',(sid,))
    if not s:raise HTTPException(404,'资料不存在')
    path=(db.ROOT/s['file_path']).resolve()
    if not path.is_relative_to(db.ROOT.resolve()) or not path.is_file():raise HTTPException(404,'原文件不存在')
    return FileResponse(path,filename=path.name)
