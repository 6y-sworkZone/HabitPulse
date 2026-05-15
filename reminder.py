from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import requests
from database import SessionLocal, Habit, User, ReminderLog, Checkin

scheduler = BackgroundScheduler()

def cleanup_deleted_users():
    db = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=30)
        deleted_users = db.query(User).filter(
            User.is_deleted == True,
            User.deleted_at <= cutoff_date
        ).all()
        
        for user in deleted_users:
            db.query(Checkin).filter(Checkin.user_id == user.id).delete()
            db.query(ReminderLog).filter(ReminderLog.user_id == user.id).delete()
            db.query(Habit).filter(Habit.user_id == user.id).delete()
            db.delete(user)
        
        db.commit()
        if deleted_users:
            print(f"Cleaned up {len(deleted_users)} deleted accounts")
    finally:
        db.close()

def send_webhook_reminder(user, habit):
    if not user.webhook_url:
        return False
    
    message = f"⏰ 习惯提醒：{habit.name}\n目标：{habit.target}"
    
    try:
        if user.webhook_type == "dingtalk":
            payload = {
                "msgtype": "text",
                "text": {"content": message}
            }
        elif user.webhook_type == "feishu":
            payload = {
                "msg_type": "text",
                "content": {"text": message}
            }
        else:
            payload = {"message": message, "habit": habit.name}
        
        response = requests.post(user.webhook_url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Webhook error: {e}")
        return False

def check_reminders():
    db = SessionLocal()
    try:
        now = datetime.now()
        current_time = now.time()
        current_time_str = current_time.strftime("%H:%M")
        
        habits = db.query(Habit).filter(
            Habit.reminder_time.isnot(None),
            Habit.is_archived == False
        ).all()
        
        for habit in habits:
            reminder_time_str = habit.reminder_time.strftime("%H:%M")
            if reminder_time_str == current_time_str:
                user = db.query(User).filter(User.id == habit.user_id).first()
                if user:
                    success = send_webhook_reminder(user, habit)
                    log = ReminderLog(
                        user_id=user.id,
                        habit_id=habit.id,
                        message=f"Reminder sent for {habit.name}",
                        sent_at=now,
                        success=success
                    )
                    db.add(log)
                    db.commit()
    finally:
        db.close()

def start_scheduler():
    scheduler.add_job(check_reminders, 'cron', minute='*')
    scheduler.add_job(cleanup_deleted_users, 'cron', hour=2, minute=0)
    scheduler.start()
    print("Reminder scheduler started")

def shutdown_scheduler():
    scheduler.shutdown()
