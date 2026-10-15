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

def ok(data=None,message='ok'):return {'code':0,'data':data,'message':message}

@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield

app=FastAPI(title='施工安全管理工作台',version='1.0.0',lifespan=lifespan)
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
