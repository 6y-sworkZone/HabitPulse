from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
from typing import List, Optional
from datetime import datetime, timedelta, date
import os
import shutil
import json
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def register_chinese_font():
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/Library/Fonts/Arial Unicode.ttf"
    ]
    
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('ChineseFont', path))
                return True
            except:
                continue
    return False

chinese_font_available = register_chinese_font()

from database import get_db, init_db, User, Habit, Checkin, ReminderLog, HabitGroup, GroupMember, GroupMessage
from auth import (
    get_password_hash, authenticate_user, create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES, Token, get_current_user, verify_password
)
from reminder import start_scheduler, shutdown_scheduler
from pydantic import BaseModel, EmailStr

app = FastAPI(title="HabitPulse")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/avatars", exist_ok=True)
os.makedirs("static/exports", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup_event():
    init_db()
    start_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    shutdown_scheduler()


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    avatar: str
    nickname: Optional[str]
    bio: Optional[str]
    webhook_url: Optional[str]
    webhook_type: str

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    nickname: Optional[str] = None
    bio: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = None


class HabitCreate(BaseModel):
    name: str
    target: str
    frequency: str
    reminder_time: Optional[str] = None
    icon: Optional[str] = None
    color: str = "#4CAF50"
    start_date: date


class HabitResponse(BaseModel):
    id: int
    name: str
    target: str
    frequency: str
    reminder_time: Optional[str]
    icon: Optional[str]
    color: str
    start_date: date
    is_archived: bool

    class Config:
        orm_mode = True


class CheckinCreate(BaseModel):
    habit_id: int
    checkin_date: date
    note: Optional[str] = None


class CheckinResponse(BaseModel):
    id: int
    habit_id: int
    checkin_date: date
    note: Optional[str]
    habit_name: str
    habit_color: str

    class Config:
        orm_mode = True


class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None


class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    creator_id: int
    creator_name: str

    class Config:
        orm_mode = True


class GroupMessageCreate(BaseModel):
    content: str


class GroupMessageResponse(BaseModel):
    id: int
    user_id: int
    username: str
    content: str
    created_at: datetime

    class Config:
        orm_mode = True


@app.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        nickname=user.username
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/login", response_model=Token)
async def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, username, password)
    if not user:
        db_user = db.query(User).filter(User.username == username).first()
        if db_user and db_user.is_deleted:
            if verify_password(password, db_user.hashed_password):
                db_user.is_deleted = False
                db_user.deleted_at = None
                db.commit()
                db.refresh(db_user)
                user = db_user
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/users/me/recover")
def recover_user(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user or not verify_password(password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not db_user.is_deleted:
        return {"message": "Account is not deleted"}
    
    db_user.is_deleted = False
    db_user.deleted_at = None
    db.commit()
    return {"message": "Account recovered successfully"}


@app.get("/users/me", response_model=UserResponse)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.put("/users/me", response_model=UserResponse)
def update_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    for field, value in user_update.dict(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@app.post("/users/me/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    ext = os.path.splitext(file.filename)[1]
    filename = f"avatar_{current_user.id}_{datetime.utcnow().timestamp()}{ext}"
    filepath = os.path.join("static/avatars", filename)
    
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    current_user.avatar = filename
    db.commit()
    return {"avatar": filename}


@app.delete("/users/me")
def delete_user(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_user.is_deleted = True
    current_user.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "Account scheduled for deletion in 30 days"}


@app.post("/habits", response_model=HabitResponse)
def create_habit(
    habit: HabitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reminder_time_obj = None
    if habit.reminder_time:
        reminder_time_obj = datetime.strptime(habit.reminder_time, "%H:%M").time()
    
    db_habit = Habit(
        user_id=current_user.id,
        name=habit.name,
        target=habit.target,
        frequency=habit.frequency,
        reminder_time=reminder_time_obj,
        icon=habit.icon,
        color=habit.color,
        start_date=habit.start_date
    )
    db.add(db_habit)
    db.commit()
    db.refresh(db_habit)
    return db_habit


@app.get("/habits", response_model=List[HabitResponse])
def get_habits(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Habit).filter(Habit.user_id == current_user.id)
    if not include_archived:
        query = query.filter(Habit.is_archived == False)
    return query.all()


@app.get("/habits/{habit_id}", response_model=HabitResponse)
def get_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    return habit


@app.put("/habits/{habit_id}", response_model=HabitResponse)
def update_habit(
    habit_id: int,
    habit_update: HabitCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    
    reminder_time_obj = None
    if habit_update.reminder_time:
        reminder_time_obj = datetime.strptime(habit_update.reminder_time, "%H:%M").time()
    
    habit.name = habit_update.name
    habit.target = habit_update.target
    habit.frequency = habit_update.frequency
    habit.reminder_time = reminder_time_obj
    habit.icon = habit_update.icon
    habit.color = habit_update.color
    habit.start_date = habit_update.start_date
    
    db.commit()
    db.refresh(habit)
    return habit


@app.post("/habits/{habit_id}/archive")
def archive_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit.is_archived = True
    db.commit()
    return {"message": "Habit archived"}


@app.post("/habits/{habit_id}/unarchive")
def unarchive_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    habit.is_archived = False
    db.commit()
    return {"message": "Habit unarchived"}


@app.delete("/habits/{habit_id}")
def delete_habit(
    habit_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habit = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    
    db.query(Checkin).filter(Checkin.habit_id == habit_id).delete()
    db.delete(habit)
    db.commit()
    return {"message": "Habit deleted"}


@app.post("/checkins", response_model=CheckinResponse)
def create_checkin(
    checkin: CheckinCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    seven_days_ago = date.today() - timedelta(days=7)
    if checkin.checkin_date < seven_days_ago:
        raise HTTPException(status_code=400, detail="Can only check in for the past 7 days")
    
    habit = db.query(Habit).filter(Habit.id == checkin.habit_id, Habit.user_id == current_user.id).first()
    if not habit:
        raise HTTPException(status_code=404, detail="Habit not found")
    
    existing = db.query(Checkin).filter(
        Checkin.habit_id == checkin.habit_id,
        Checkin.checkin_date == checkin.checkin_date
    ).first()
    
    if existing:
        existing.note = checkin.note
        db.commit()
        db.refresh(existing)
        return existing
    
    db_checkin = Checkin(
        user_id=current_user.id,
        habit_id=checkin.habit_id,
        checkin_date=checkin.checkin_date,
        note=checkin.note
    )
    db.add(db_checkin)
    db.commit()
    db.refresh(db_checkin)
    return db_checkin


@app.get("/checkins/today")
def get_today_checkins(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    today = date.today()
    habits = db.query(Habit).filter(
        Habit.user_id == current_user.id,
        Habit.is_archived == False,
        Habit.start_date <= today
    ).all()
    
    checkins = db.query(Checkin).filter(
        Checkin.user_id == current_user.id,
        Checkin.checkin_date == today
    ).all()
    
    checked_habit_ids = {c.habit_id for c in checkins}
    
    result = []
    for habit in habits:
        result.append({
            "habit": habit,
            "checked": habit.id in checked_habit_ids,
            "note": next((c.note for c in checkins if c.habit_id == habit.id), None)
        })
    
    return result


@app.get("/checkins/calendar")
def get_calendar_checkins(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    
    checkins = db.query(Checkin).join(Habit).filter(
        Checkin.user_id == current_user.id,
        Checkin.checkin_date >= start_date,
        Checkin.checkin_date <= end_date
    ).all()
    
    result = {}
    for c in checkins:
        day = c.checkin_date.day
        if day not in result:
            result[day] = []
        result[day].append({
            "habit_id": c.habit_id,
            "habit_name": c.habit.name,
            "color": c.habit.color,
            "note": c.note
        })
    
    return result


@app.get("/statistics/streak")
def get_streak_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habits = db.query(Habit).filter(
        Habit.user_id == current_user.id,
        Habit.is_archived == False
    ).all()
    
    if not habits:
        return {"current_streak": 0, "longest_streak": 0}
    
    habit_ids = [h.id for h in habits]
    checkins = db.query(Checkin.checkin_date).filter(
        Checkin.habit_id.in_(habit_ids)
    ).distinct().order_by(Checkin.checkin_date.desc()).all()
    
    checkin_dates = [c[0] for c in checkins]
    
    if not checkin_dates:
        return {"current_streak": 0, "longest_streak": 0}
    
    today = date.today()
    current_streak = 0
    check_date = today
    
    while check_date in checkin_dates:
        current_streak += 1
        check_date -= timedelta(days=1)
    
    longest_streak = 0
    streak = 1
    for i in range(1, len(checkin_dates)):
        if (checkin_dates[i-1] - checkin_dates[i]).days == 1:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 1
    
    longest_streak = max(longest_streak, current_streak)
    
    return {"current_streak": current_streak, "longest_streak": longest_streak}


@app.get("/statistics/completion")
def get_completion_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = date(today.year, today.month, 1)
    
    habits = db.query(Habit).filter(
        Habit.user_id == current_user.id,
        Habit.is_archived == False
    ).all()
    
    if not habits:
        return {"weekly": 0, "monthly": 0, "total": 0}
    
    habit_ids = [h.id for h in habits]
    
    def calculate_rate(start_date):
        days = (today - start_date).days + 1
        expected = len(habits) * days
        actual = db.query(Checkin).filter(
            Checkin.habit_id.in_(habit_ids),
            Checkin.checkin_date >= start_date
        ).count()
        return round((actual / expected * 100) if expected > 0 else 0, 1)
    
    earliest_date = db.query(func.min(Habit.start_date)).filter(
        Habit.user_id == current_user.id
    ).scalar() or today
    
    return {
        "weekly": calculate_rate(week_start),
        "monthly": calculate_rate(month_start),
        "total": calculate_rate(earliest_date)
    }


@app.get("/statistics/heatmap")
def get_heatmap_data(
    habit_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    today = date.today()
    one_year_ago = today - timedelta(days=365)
    
    query = db.query(Checkin.checkin_date, func.count(Checkin.id)).filter(
        Checkin.user_id == current_user.id,
        Checkin.checkin_date >= one_year_ago
    )
    
    if habit_id:
        query = query.filter(Checkin.habit_id == habit_id)
    
    checkins = query.group_by(Checkin.checkin_date).all()
    
    result = {str(d): cnt for d, cnt in checkins}
    return result


@app.get("/statistics/trend")
def get_trend_data(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    today = date.today()
    start_date = today - timedelta(days=days - 1)
    
    habits = db.query(Habit).filter(
        Habit.user_id == current_user.id,
        Habit.is_archived == False
    ).all()
    
    habit_ids = [h.id for h in habits] if habits else []
    
    result = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        count = db.query(Checkin).filter(
            Checkin.habit_id.in_(habit_ids),
            Checkin.checkin_date == d
        ).count()
        total = len(habits)
        completion_rate = round((count / total * 100) if total > 0 else 0, 1)
        result.append({"date": str(d), "count": count, "total": total, "rate": completion_rate})
    
    return result


@app.get("/data/export")
def export_data(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
    checkins = db.query(Checkin).filter(Checkin.user_id == current_user.id).all()
    
    data = {
        "exported_at": datetime.utcnow().isoformat(),
        "user": {
            "username": current_user.username,
            "email": current_user.email,
            "nickname": current_user.nickname,
            "bio": current_user.bio
        },
        "habits": [
            {
                "id": h.id,
                "name": h.name,
                "target": h.target,
                "frequency": h.frequency,
                "icon": h.icon,
                "color": h.color,
                "start_date": str(h.start_date),
                "is_archived": h.is_archived
            }
            for h in habits
        ],
        "checkins": [
            {
                "habit_id": c.habit_id,
                "checkin_date": str(c.checkin_date),
                "note": c.note
            }
            for c in checkins
        ]
    }
    
    filename = f"habit_pulse_export_{current_user.id}_{datetime.utcnow().strftime('%Y%m%d')}.json"
    filepath = os.path.join("static/exports", filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return FileResponse(filepath, filename=filename)


@app.post("/data/import")
def import_data(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    content = json.load(file.file)
    
    habit_mapping = {}
    for habit_data in content.get("habits", []):
        existing = db.query(Habit).filter(
            Habit.user_id == current_user.id,
            Habit.name == habit_data["name"]
        ).first()
        
        if existing:
            habit_mapping[habit_data["id"]] = existing.id
        else:
            new_habit = Habit(
                user_id=current_user.id,
                name=habit_data["name"],
                target=habit_data.get("target", ""),
                frequency=habit_data.get("frequency", "daily"),
                icon=habit_data.get("icon"),
                color=habit_data.get("color", "#4CAF50"),
                start_date=date.fromisoformat(habit_data["start_date"]),
                is_archived=habit_data.get("is_archived", False)
            )
            db.add(new_habit)
            db.flush()
            habit_mapping[habit_data["id"]] = new_habit.id
    
    imported_count = 0
    for checkin_data in content.get("checkins", []):
        new_habit_id = habit_mapping.get(checkin_data["habit_id"])
        if not new_habit_id:
            continue
        
        checkin_date = date.fromisoformat(checkin_data["checkin_date"])
        
        existing = db.query(Checkin).filter(
            Checkin.habit_id == new_habit_id,
            Checkin.checkin_date == checkin_date
        ).first()
        
        if existing:
            existing.note = checkin_data.get("note")
        else:
            new_checkin = Checkin(
                user_id=current_user.id,
                habit_id=new_habit_id,
                checkin_date=checkin_date,
                note=checkin_data.get("note")
            )
            db.add(new_checkin)
        imported_count += 1
    
    db.commit()
    return {"message": f"Imported {imported_count} checkins"}


@app.get("/data/report/pdf")
def export_pdf_report(
    year: int,
    month: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    
    habits = db.query(Habit).filter(Habit.user_id == current_user.id).all()
    checkins = db.query(Checkin).filter(
        Checkin.user_id == current_user.id,
        Checkin.checkin_date >= start_date,
        Checkin.checkin_date <= end_date
    ).all()
    
    filename = f"report_{year}_{month}_{current_user.id}.pdf"
    filepath = os.path.join("static/exports", filename)
    
    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    
    font_name = "ChineseFont" if chinese_font_available else "Helvetica"
    
    c.setFont(font_name, 20)
    c.drawString(50, height - 50, f"Habit Pulse 月度报告 - {year}年{month}月")
    
    c.setFont(font_name, 12)
    c.drawString(50, height - 80, f"用户: {current_user.nickname or current_user.username}")
    c.drawString(50, height - 100, f"期间: {start_date} 至 {end_date}")
    
    y = height - 150
    c.setFont(font_name, 14)
    c.drawString(50, y, "习惯列表:")
    y -= 25
    
    c.setFont(font_name, 11)
    for habit in habits:
        habit_checkins = [c for c in checkins if c.habit_id == habit.id]
        c.setFillColor(colors.HexColor(habit.color))
        c.circle(60, y, 5, fill=1)
        c.setFillColor(colors.black)
        c.drawString(75, y - 3, f"{habit.name}: {len(habit_checkins)} 次打卡")
        y -= 20
    
    y -= 20
    c.setFont(font_name, 14)
    c.drawString(50, y, "月度总结:")
    y -= 25
    
    total_days = (end_date - start_date).days + 1
    total_expected = len(habits) * total_days
    total_actual = len(checkins)
    completion_rate = (total_actual / total_expected * 100) if total_expected > 0 else 0
    
    c.setFont(font_name, 11)
    c.drawString(50, y, f"习惯总数: {len(habits)}")
    y -= 20
    c.drawString(50, y, f"打卡总数: {total_actual}")
    y -= 20
    c.drawString(50, y, f"完成率: {completion_rate:.1f}%")
    
    c.save()
    return FileResponse(filepath, filename=filename)


@app.post("/groups", response_model=GroupResponse)
def create_group(
    group: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db_group = HabitGroup(
        name=group.name,
        description=group.description,
        creator_id=current_user.id
    )
    db.add(db_group)
    db.flush()
    
    member = GroupMember(group_id=db_group.id, user_id=current_user.id)
    db.add(member)
    db.commit()
    db.refresh(db_group)
    
    result = GroupResponse(
        id=db_group.id,
        name=db_group.name,
        description=db_group.description,
        creator_id=db_group.creator_id,
        creator_name=current_user.username
    )
    return result


@app.get("/groups", response_model=List[GroupResponse])
def get_my_groups(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    memberships = db.query(GroupMember).filter(GroupMember.user_id == current_user.id).all()
    group_ids = [m.group_id for m in memberships]
    
    groups = db.query(HabitGroup).filter(HabitGroup.id.in_(group_ids)).all()
    result = []
    for g in groups:
        creator = db.query(User).filter(User.id == g.creator_id).first()
        result.append(GroupResponse(
            id=g.id,
            name=g.name,
            description=g.description,
            creator_id=g.creator_id,
            creator_name=creator.username if creator else ""
        ))
    return result


@app.post("/groups/{group_id}/invite")
def invite_to_group(
    group_id: int,
    username: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    group = db.query(HabitGroup).filter(HabitGroup.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a group member")
    
    invited_user = db.query(User).filter(User.username == username).first()
    if not invited_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    already_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == invited_user.id
    ).first()
    if already_member:
        raise HTTPException(status_code=400, detail="User already in group")
    
    member = GroupMember(group_id=group_id, user_id=invited_user.id)
    db.add(member)
    db.commit()
    return {"message": f"Invited {username} to group"}


@app.get("/groups/{group_id}/leaderboard")
def get_group_leaderboard(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a group member")
    
    members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    member_ids = [m.user_id for m in members]
    
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    
    leaderboard = []
    for user_id in member_ids:
        user = db.query(User).filter(User.id == user_id).first()
        count = db.query(Checkin).filter(
            Checkin.user_id == user_id,
            Checkin.checkin_date >= week_start
        ).count()
        leaderboard.append({
            "user_id": user_id,
            "username": user.username,
            "nickname": user.nickname,
            "avatar": user.avatar,
            "checkin_count": count
        })
    
    leaderboard.sort(key=lambda x: x["checkin_count"], reverse=True)
    return leaderboard


@app.get("/groups/{group_id}/messages", response_model=List[GroupMessageResponse])
def get_group_messages(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a group member")
    
    messages = db.query(GroupMessage).filter(
        GroupMessage.group_id == group_id
    ).order_by(GroupMessage.created_at.desc()).limit(50).all()
    
    result = []
    for m in messages:
        user = db.query(User).filter(User.id == m.user_id).first()
        result.append(GroupMessageResponse(
            id=m.id,
            user_id=m.user_id,
            username=user.username if user else "",
            content=m.content,
            created_at=m.created_at
        ))
    return result


@app.post("/groups/{group_id}/messages", response_model=GroupMessageResponse)
def post_group_message(
    group_id: int,
    message: GroupMessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a group member")
    
    db_message = GroupMessage(
        group_id=group_id,
        user_id=current_user.id,
        content=message.content
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    
    return GroupMessageResponse(
        id=db_message.id,
        user_id=db_message.user_id,
        username=current_user.username,
        content=db_message.content,
        created_at=db_message.created_at
    )


@app.get("/", response_class=HTMLResponse)
def get_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9527)
