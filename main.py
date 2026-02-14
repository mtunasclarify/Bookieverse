# main.py - BookieVerse with PostgreSQL - ALL FEATURES

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import hashlib
import jwt
from datetime import datetime, timedelta
import uvicorn
import os
import stripe
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import json

app = FastAPI(title="BookieVerse Complete")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = os.getenv("SECRET_KEY", "bookieverse-secret")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bookieverse.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

PROP_TYPES = {
    "NBA": ["Points", "Rebounds", "Assists", "3-Pointers Made"],
    "NFL": ["Passing Yards", "Rushing Yards", "Touchdowns"]
}

# Database
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    balance = Column(Float, default=1000.0)
    profit = Column(Float, default=0.0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    lines_created = Column(Integer, default=0)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Line(Base):
    __tablename__ = "lines"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    game_id = Column(String)
    game = Column(String)
    sport = Column(String)
    type = Column(String)
    side = Column(String)
    value = Column(Float)
    amount = Column(Float)
    status = Column(String, default="open")
    current_bettors = Column(Integer, default=0)
    max_bettors = Column(Integer, nullable=True)
    max_bet_per_user = Column(Float, nullable=True)
    max_total_action = Column(Float, nullable=True)
    is_private = Column(Boolean, default=False)
    group_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Bet(Base):
    __tablename__ = "bets"
    id = Column(Integer, primary_key=True)
    line_id = Column(Integer)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    bettor_id = Column(Integer)
    bettor_name = Column(String)
    game = Column(String)
    type = Column(String)
    bookie_side = Column(String)
    bettor_side = Column(String)
    value = Column(Float)
    amount = Column(Float)
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Prop(Base):
    __tablename__ = "props"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    sport = Column(String)
    player_name = Column(String)
    prop_type = Column(String)
    line = Column(Float)
    side = Column(String)
    amount = Column(Float)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)

class PropBet(Base):
    __tablename__ = "prop_bets"
    id = Column(Integer, primary_key=True)
    prop_id = Column(Integer)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    bettor_id = Column(Integer)
    bettor_name = Column(String)
    player_name = Column(String)
    prop_type = Column(String)
    line = Column(Float)
    bookie_side = Column(String)
    bettor_side = Column(String)
    amount = Column(Float)
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(Text, nullable=True)
    creator_id = Column(Integer)
    creator_name = Column(String)
    members = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

GAMES = [
    {"id": "demo_1", "home": "Lakers", "away": "Warriors", "sport": "NBA", "date": "2026-02-14"},
    {"id": "demo_2", "home": "Celtics", "away": "Heat", "sport": "NBA", "date": "2026-02-14"},
    {"id": "demo_3", "home": "Chiefs", "away": "Bills", "sport": "NFL", "date": "2026-02-15"},
]

FUTURES = [
    {"id": "f1", "market_name": "NBA Championship", "sport": "NBA", "options": ["Lakers", "Celtics", "Warriors"]},
    {"id": "f2", "market_name": "Super Bowl", "sport": "NFL", "options": ["Chiefs", "Bills", "49ers"]},
]

# Odds API Integration
def fetch_live_games():
    """Fetch real games from Odds API"""
    if not ODDS_API_KEY:
        return GAMES  # Return demo games if no API key
    
    try:
        # Fetch NBA games
        nba_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h,spreads,totals"
        nba_response = requests.get(nba_url, timeout=10)
        
        # Fetch NFL games
        nfl_url = f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/?apiKey={ODDS_API_KEY}&regions=us&markets=h2h,spreads,totals"
        nfl_response = requests.get(nfl_url, timeout=10)
        
        games = []
        
        # Process NBA games
        if nba_response.status_code == 200:
            nba_data = nba_response.json()
            for game in nba_data[:10]:  # Limit to 10 games
                games.append({
                    "id": game["id"],
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "sport": "NBA",
                    "date": game["commence_time"][:10],
                    "commence_time": game["commence_time"],
                    "status": "upcoming"
                })
        
        # Process NFL games
        if nfl_response.status_code == 200:
            nfl_data = nfl_response.json()
            for game in nfl_data[:10]:
                games.append({
                    "id": game["id"],
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "sport": "NFL",
                    "date": game["commence_time"][:10],
                    "commence_time": game["commence_time"],
                    "status": "upcoming"
                })
        
        return games if games else GAMES
    except Exception as e:
        print(f"Error fetching games: {e}")
        return GAMES

def check_game_scores():
    """Check scores and auto-settle bets"""
    if not ODDS_API_KEY:
        return
    
    try:
        # Fetch scores from Odds API
        scores_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/scores/?apiKey={ODDS_API_KEY}&daysFrom=1"
        response = requests.get(scores_url, timeout=10)
        
        if response.status_code == 200:
            scores_data = response.json()
            db = SessionLocal()
            
            for game_data in scores_data:
                if game_data.get("completed") and game_data.get("scores"):
                    game_id = game_data["id"]
                    scores = game_data["scores"]
                    
                    home_score = next((s["score"] for s in scores if s["name"] == game_data["home_team"]), None)
                    away_score = next((s["score"] for s in scores if s["name"] == game_data["away_team"]), None)
                    
                    if home_score and away_score:
                        # Find all bets for this game
                        bets = db.query(Bet).filter(Bet.game_id == game_id, Bet.status == "pending").all()
                        
                        for bet in bets:
                            # Auto-settle based on bet type
                            winner = determine_winner(bet, int(home_score), int(away_score))
                            if winner:
                                settle_bet(db, bet, winner)
            
            db.commit()
            db.close()
    except Exception as e:
        print(f"Error checking scores: {e}")

def determine_winner(bet, home_score, away_score):
    """Determine bet winner based on scores"""
    score_diff = home_score - away_score
    
    if bet.type == "spread":
        if bet.bookie_side == "home":
            adjusted = score_diff + bet.value
            return "bookie" if adjusted > 0 else "bettor"
        else:
            adjusted = score_diff - bet.value
            return "bookie" if adjusted < 0 else "bettor"
    elif bet.type == "moneyline":
        if bet.bookie_side == "home":
            return "bookie" if home_score > away_score else "bettor"
        else:
            return "bookie" if away_score > home_score else "bettor"
    elif bet.type == "total":
        total = home_score + away_score
        if bet.bookie_side == "over":
            return "bookie" if total > bet.value else "bettor"
        else:
            return "bookie" if total < bet.value else "bettor"
    return None

def settle_bet(db, bet, winner):
    """Auto-settle a bet"""
    payout = bet.amount * 2  # 0% rake
    
    bookie = db.query(User).filter(User.id == bet.bookie_id).first()
    bettor = db.query(User).filter(User.id == bet.bettor_id).first()
    
    if winner == "bookie":
        bookie.balance += payout
        bookie.profit += bet.amount
        bookie.wins += 1
        bettor.profit -= bet.amount
        bettor.losses += 1
    else:
        bettor.balance += payout
        bettor.profit += bet.amount
        bettor.wins += 1
        bookie.profit -= bet.amount
        bookie.losses += 1
    
    bet.status = "settled"
    bet.winner = winner

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(check_game_scores, 'interval', minutes=5)  # Check scores every 5 minutes
scheduler.start()

# Models
class UserCreate(BaseModel):
    username: str
    password: str

class LineCreate(BaseModel):
    game_id: str
    type: str
    side: str
    value: float
    amount: float
    max_bettors: Optional[int] = None
    max_bet_per_user: Optional[float] = None
    max_total_action: Optional[float] = None
    is_private: Optional[bool] = False
    group_id: Optional[int] = None

class PropCreate(BaseModel):
    sport: str
    player_name: str
    prop_type: str
    line: float
    side: str
    amount: float

class TakeLine(BaseModel):
    line_id: int

class TakeProp(BaseModel):
    prop_id: int

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def create_token(user_id: int) -> str:
    return jwt.encode({"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[int]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"]).get("user_id")
    except:
        return None

@app.get("/")
def home():
    return {"message": "🎯 BookieVerse", "app": "/app"}

@app.post("/api/auth/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    if len(user.password) < 6:
        raise HTTPException(400, "Password 6+ chars")
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(400, "Username taken")
    
    is_admin = db.query(User).count() == 0
    new_user = User(username=user.username, password=hash_password(user.password), is_admin=is_admin)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"token": create_token(new_user.id), "user": {"id": new_user.id, "username": new_user.username, "balance": new_user.balance}}

@app.post("/api/auth/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == user.username).first()
    if not u or u.password != hash_password(user.password):
        raise HTTPException(401, "Invalid credentials")
    return {"token": create_token(u.id), "user": {"id": u.id, "username": u.username, "balance": u.balance}}

@app.get("/api/games")
def get_games():
    return fetch_live_games()

@app.get("/api/futures")
def get_futures():
    return FUTURES

@app.get("/api/prop-types")
def get_prop_types():
    return PROP_TYPES

@app.get("/api/lines")
def get_lines(db: Session = Depends(get_db)):
    lines = db.query(Line).filter(Line.status == "open").all()
    return [{"id": l.id, "bookie_id": l.bookie_id, "bookie_name": l.bookie_name, "game": l.game, "sport": l.sport,
             "type": l.type, "side": l.side, "value": l.value, "amount": l.amount, "status": l.status,
             "current_bettors": l.current_bettors, "is_private": l.is_private} for l in lines]

@app.post("/api/lines")
def create_line(line: LineCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    game = next((g for g in GAMES if g["id"] == line.game_id), None)
    if not game:
        raise HTTPException(404, "Game not found")
    
    new_line = Line(bookie_id=user.id, bookie_name=user.username, game_id=line.game_id,
                   game=f"{game['away']} @ {game['home']}", sport=game["sport"],
                   type=line.type, side=line.side, value=line.value, amount=line.amount,
                   max_bettors=line.max_bettors, max_bet_per_user=line.max_bet_per_user,
                   max_total_action=line.max_total_action, is_private=line.is_private, group_id=line.group_id)
    user.balance -= line.amount
    user.lines_created += 1
    db.add(new_line)
    db.commit()
    db.refresh(new_line)
    return {"message": "Line created", "line_id": new_line.id}

@app.post("/api/lines/take")
def take_line(take: TakeLine, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    line = db.query(Line).filter(Line.id == take.line_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not available")
    if line.bookie_id == user_id:
        raise HTTPException(400, "Can't bet your own line")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    bet = Bet(line_id=line.id, bookie_id=line.bookie_id, bookie_name=line.bookie_name,
             bettor_id=user.id, bettor_name=user.username, game=line.game, type=line.type,
             bookie_side=line.side, bettor_side="away" if line.side == "home" else "home",
             value=line.value, amount=line.amount)
    line.status = "matched"
    line.current_bettors += 1
    user.balance -= line.amount
    db.add(bet)
    db.commit()
    return {"message": "Bet placed"}

@app.get("/api/props")
def get_props(db: Session = Depends(get_db)):
    props = db.query(Prop).filter(Prop.status == "open").all()
    return [{"id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name, "sport": p.sport,
             "player_name": p.player_name, "prop_type": p.prop_type, "line": p.line, "side": p.side,
             "amount": p.amount} for p in props]

@app.post("/api/props")
def create_prop(prop: PropCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance < prop.amount:
        raise HTTPException(400, "Insufficient balance")
    
    new_prop = Prop(bookie_id=user.id, bookie_name=user.username, sport=prop.sport,
                   player_name=prop.player_name, prop_type=prop.prop_type, line=prop.line,
                   side=prop.side, amount=prop.amount)
    user.balance -= prop.amount
    user.lines_created += 1
    db.add(new_prop)
    db.commit()
    return {"message": "Prop created"}

@app.post("/api/props/take")
def take_prop(take: TakeProp, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    prop = db.query(Prop).filter(Prop.id == take.prop_id, Prop.status == "open").first()
    if not prop:
        raise HTTPException(404, "Prop not available")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user.balance < prop.amount:
        raise HTTPException(400, "Insufficient balance")
    
    prop_bet = PropBet(prop_id=prop.id, bookie_id=prop.bookie_id, bookie_name=prop.bookie_name,
                      bettor_id=user.id, bettor_name=user.username, player_name=prop.player_name,
                      prop_type=prop.prop_type, line=prop.line, bookie_side=prop.side,
                      bettor_side="under" if prop.side == "over" else "over", amount=prop.amount)
    prop.status = "matched"
    user.balance -= prop.amount
    db.add(prop_bet)
    db.commit()
    return {"message": "Prop bet placed"}

@app.get("/api/bets")
def get_bets(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    bets = db.query(Bet).filter((Bet.bookie_id == user_id) | (Bet.bettor_id == user_id)).all()
    prop_bets = db.query(PropBet).filter((PropBet.bookie_id == user_id) | (PropBet.bettor_id == user_id)).all()
    
    return {
        "single_bets": [{"id": b.id, "bookie_id": b.bookie_id, "bookie_name": b.bookie_name,
                        "bettor_id": b.bettor_id, "bettor_name": b.bettor_name, "game": b.game,
                        "type": b.type, "bookie_side": b.bookie_side, "bettor_side": b.bettor_side,
                        "value": b.value, "amount": b.amount, "status": b.status, "winner": b.winner} for b in bets],
        "prop_bets": [{"id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name,
                      "bettor_id": p.bettor_id, "bettor_name": p.bettor_name, "player_name": p.player_name,
                      "prop_type": p.prop_type, "line": p.line, "bookie_side": p.bookie_side,
                      "bettor_side": p.bettor_side, "amount": p.amount, "status": p.status, "winner": p.winner} for p in prop_bets],
        "parlays": []
    }

@app.get("/api/groups")
def get_groups(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    groups = db.query(Group).all()
    result = []
    for g in groups:
        members = json.loads(g.members)
        if user_id in members:
            result.append({"id": g.id, "name": g.name, "description": g.description,
                          "creator_id": g.creator_id, "creator_name": g.creator_name,
                          "member_count": len(members), "is_creator": g.creator_id == user_id})
    return result

@app.post("/api/groups")
def create_group(group: GroupCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    
    new_group = Group(name=group.name, description=group.description,
                     creator_id=user.id, creator_name=user.username, members=json.dumps([user.id]))
    db.add(new_group)
    db.commit()
    return {"message": "Group created", "group_id": new_group.id}

@app.get("/api/leaderboard")
def leaderboard(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.profit.desc()).limit(10).all()
    return [{"id": u.id, "username": u.username, "balance": u.balance, "profit": u.profit,
             "wins": u.wins, "losses": u.losses} for u in users]

@app.get("/api/user")
def get_user(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return {"id": user.id, "username": user.username, "balance": user.balance, "profit": user.profit,
            "wins": user.wins, "losses": user.losses, "lines_created": user.lines_created, "is_admin": user.is_admin}

@app.get("/api/users/search")
def search_users(db: Session = Depends(get_db)):
    users = db.query(User).limit(50).all()
    return [{"id": u.id, "username": u.username, "wins": u.wins, "losses": u.losses, "profit": u.profit,
             "win_rate": round((u.wins / (u.wins + u.losses) * 100) if (u.wins + u.losses) > 0 else 0, 1),
             "rating": 0, "followers": 0} for u in users]

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    with open("index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
