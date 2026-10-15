"""Single-process startup recovery: interrupted jobs are visible and safely retryable."""
from backend.app import db

def recover_interrupted():
    with db.connect() as c:
        recovered={}
        for table,active,error in [
            ('handle_tasks',"'queued','drafting','rule_check','reviewing','rework'",'服务重启中断办理，已保存草稿和记录，请重新办理后再签发'),
            ('chat_runs',"'running'",'服务重启中断生成，已保存用户消息与部分结果，请重新提问'),
            ('monitor_runs',"'queued','running'",'服务重启中断检测，已有抓拍仍需人工确认，可重新运行片段')]:
            count=c.execute(f"UPDATE {table} SET status='error',error=? WHERE status IN ({active})",(error,)).rowcount
            if count:recovered[table]=count
        if recovered:db.audit(c,'system','recover_interrupted_jobs','system','startup',recovered)
    return recovered
