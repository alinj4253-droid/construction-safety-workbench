import hashlib
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from backend.app.monitor import router as monitor_router
from backend.app.dashboard import router as dashboard_router
from backend.app import db

MONITOR_BUILD=hashlib.sha256(b''.join((db.ROOT/path).read_bytes() for path in ('backend/app/monitor_service.py','backend/app/monitor.py','backend/app/dashboard.py','backend/vision/detector.py'))).hexdigest()[:16]

app=FastAPI(title='施工安全监控独立服务')
app.include_router(monitor_router)
app.include_router(dashboard_router)
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:8010','http://localhost:8010'],allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])

@app.get('/api/monitor-service/health')
def health():return {'code':0,'data':{'status':'ok','monitor_version':2,'build':MONITOR_BUILD},'message':'ok'}

@app.exception_handler(HTTPException)
async def http_error(request,exc):return JSONResponse({'code':exc.status_code,'data':None,'message':str(exc.detail)},status_code=exc.status_code)

@app.exception_handler(ValueError)
async def value_error(request,exc):return JSONResponse({'code':400,'data':None,'message':str(exc)},status_code=400)

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):return JSONResponse({'code':422,'data':None,'message':'输入格式有误'},status_code=422)
