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
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy import func
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
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=5,
        max_overflow=10
    )
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
    odds = Column(Integer, default=-110)       # American odds for bookie's side
    amount = Column(Float)                      # Bookie's total risk amount
    status = Column(String, default="open")
    total_action = Column(Float, default=0.0)  # Bookie stake consumed so far
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
    game_id = Column(String, nullable=True)
    game = Column(String)
    type = Column(String)
    bookie_side = Column(String)
    bettor_side = Column(String)
    value = Column(Float)
    odds = Column(Integer, nullable=True, default=-110)        # American odds (bookie's side)
    amount = Column(Float)                                      # Bookie's stake portion (legacy compat)
    bookie_amount = Column(Float, nullable=True)               # Bookie's stake for this specific bet
    bettor_amount = Column(Float, nullable=True)               # Bettor's stake
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Prop(Base):
    __tablename__ = "props"
    id = Column(Integer, primary_key=True)
    bookie_id = Column(Integer)
    bookie_name = Column(String)
    game_id = Column(String, nullable=True)
    game = Column(String, nullable=True)
    sport = Column(String)
    player_name = Column(String)
    prop_type = Column(String)
    line = Column(Float)
    side = Column(String)
    odds = Column(Integer, nullable=True, default=-110)   # American odds
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
    odds = Column(Integer, nullable=True, default=-110)
    bookie_amount = Column(Float, nullable=True)
    bettor_amount = Column(Float, nullable=True)
    amount = Column(Float)
    status = Column(String, default="pending")
    winner = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Challenge(Base):
    __tablename__ = "challenges"
    id = Column(Integer, primary_key=True)
    challenger_id = Column(Integer)
    challenger_name = Column(String)
    challenged_id = Column(Integer)
    challenged_name = Column(String)
    game_id = Column(String)
    game = Column(String)
    sport = Column(String)
    type = Column(String)       # spread, moneyline, total
    side = Column(String)       # challenger's side
    value = Column(Float)
    odds = Column(Integer, default=-110)
    amount = Column(Float)      # challenger's stake (deducted on creation)
    message = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, accepted, declined, cancelled
    bet_id = Column(Integer, nullable=True)     # set when accepted → links to Bet
    created_at = Column(DateTime, default=datetime.utcnow)

class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True)
    follower_id = Column(Integer, index=True)
    followed_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class FriendRequest(Base):
    __tablename__ = "friend_requests"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, index=True)
    receiver_id = Column(Integer, index=True)
    status = Column(String, default="pending")   # pending | accepted | declined
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

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    type = Column(String)           # challenge_received, challenge_accepted, challenge_declined, bet_matched, bet_settled
    title = Column(String)
    body = Column(String)
    is_read = Column(Boolean, default=False)
    ref_id = Column(Integer, nullable=True)   # challenge_id or bet_id for deep-linking
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

GAMES = [
    {"id": "demo_1", "home": "Lakers",  "away": "Warriors", "sport": "NBA", "date": "2026-03-05", "commence_time": "2026-03-05T02:00:00Z"},
    {"id": "demo_2", "home": "Celtics", "away": "Heat",     "sport": "NBA", "date": "2026-03-05", "commence_time": "2026-03-05T00:00:00Z"},
    {"id": "demo_3", "home": "Nuggets", "away": "Clippers", "sport": "NBA", "date": "2026-03-06", "commence_time": "2026-03-06T01:00:00Z"},
    {"id": "demo_4", "home": "Bucks",   "away": "76ers",    "sport": "NBA", "date": "2026-03-06", "commence_time": "2026-03-06T23:00:00Z"},
    {"id": "demo_5", "home": "Suns",    "away": "Mavs",     "sport": "NBA", "date": "2026-03-07", "commence_time": "2026-03-07T02:00:00Z"},
]

FUTURES = [
    {"id": "f1", "market_name": "NBA Championship", "sport": "NBA", "options": ["Lakers", "Celtics", "Warriors"]},
    {"id": "f2", "market_name": "Super Bowl", "sport": "NFL", "options": ["Chiefs", "Bills", "49ers"]},
]

# ─── ODDS HELPERS ────────────────────────────────────────────────────────────

def bettor_stake_from_bookie(bookie_stake: float, odds: int) -> float:
    """
    Given bookie's stake and their American odds, return what bettor must risk.
    Bookie -110 for $110 → bettor risks $100 to win $110.
    Bookie +150 for $100 → bettor risks $150 to win $100.
    """
    if odds <= -100:
        return round(bookie_stake * (100 / abs(odds)), 2)
    else:  # positive odds
        return round(bookie_stake * (odds / 100), 2)

def bookie_portion_from_bettor(bettor_stake: float, odds: int) -> float:
    """
    Inverse: given bettor's chosen stake, how much of the bookie's line is consumed.
    """
    if odds <= -100:
        return round(bettor_stake * (abs(odds) / 100), 2)
    else:
        return round(bettor_stake * (100 / odds), 2)

def format_odds(odds: int) -> str:
    """Format American odds for display: -110 → '-110', +150 → '+150'."""
    return f"+{odds}" if odds > 0 else str(odds)

# ─── ODDS HELPERS END ─────────────────────────────────────────────────────────

# Odds API Integration
def fetch_live_games():
    """Fetch upcoming games from Odds API using the /events endpoint (0 quota cost).
    Falls back to demo data if no API key or on any error."""
    if not ODDS_API_KEY:
        return GAMES  # Return demo games if no API key

    try:
        games = []

        # Determine which sports are currently in season (Feb 2026: NBA yes, NFL no, MLB no yet)
        # Use /events endpoint — completely free (0 API quota consumed)
        active_sports = [
            ("basketball_nba", "NBA"),
        ]

        for sport_key, sport_label in active_sports:
            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events/?apiKey={ODDS_API_KEY}"
            try:
                resp = requests.get(url, timeout=10)
            except Exception as e:
                print(f"fetch_live_games: request error for {sport_key}: {e}")
                continue

            if resp.status_code != 200:
                print(f"fetch_live_games: {sport_key} returned {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
            if not isinstance(data, list):
                print(f"fetch_live_games: unexpected response for {sport_key}")
                continue

            for game in data:
                commence = game.get("commence_time", "")
                if not commence:
                    continue
                # Only include games that haven't started yet
                try:
                    game_dt = datetime.strptime(commence[:19], "%Y-%m-%dT%H:%M:%S")
                    if game_dt <= datetime.utcnow():
                        continue
                except ValueError:
                    pass
                games.append({
                    "id": game["id"],
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "sport": sport_label,
                    "date": commence[:10],
                    "commence_time": commence,
                    "status": "upcoming"
                })

        # Sort soonest first
        games.sort(key=lambda x: x["commence_time"])

        return games if games else GAMES

    except Exception as e:
        print(f"Error fetching games: {e}")
        return GAMES

def check_game_scores():
    """Check scores and auto-settle bets — covers NBA and NFL."""
    if not ODDS_API_KEY:
        return

    SPORT_ENDPOINTS = [
        "basketball_nba",
        "americanfootball_nfl",
    ]

    db = SessionLocal()
    try:
        for sport_key in SPORT_ENDPOINTS:
            scores_url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores/?apiKey={ODDS_API_KEY}&daysFrom=2"
            try:
                response = requests.get(scores_url, timeout=10)
            except Exception as e:
                print(f"Score fetch error for {sport_key}: {e}")
                continue

            if response.status_code != 200:
                print(f"Score API {sport_key} returned {response.status_code}")
                continue

            for game_data in response.json():
                if not (game_data.get("completed") and game_data.get("scores")):
                    continue

                game_id = game_data["id"]
                scores = game_data["scores"]

                home_raw = next((s["score"] for s in scores if s["name"] == game_data["home_team"]), None)
                away_raw = next((s["score"] for s in scores if s["name"] == game_data["away_team"]), None)

                if home_raw is None or away_raw is None:
                    continue

                try:
                    home_score = int(float(home_raw))
                    away_score = int(float(away_raw))
                except (ValueError, TypeError) as e:
                    print(f"Score parse error for game {game_id}: {e}")
                    continue

                bets = db.query(Bet).filter(Bet.game_id == game_id, Bet.status == "pending").all()
                if not bets:
                    continue

                line_ids = set(bet.line_id for bet in bets if bet.line_id)
                for bet in bets:
                    winner = determine_winner(bet, home_score, away_score)
                    if winner:
                        settle_bet(db, bet, winner)

                for line_id in line_ids:
                    line = db.query(Line).filter(Line.id == line_id).first()
                    if line and line.status not in ("settled", "refunded", "cancelled"):
                        refund_unmatched_line(db, line)
                        line.status = "settled"

        db.commit()
    except Exception as e:
        print(f"Error in check_game_scores: {e}")
        db.rollback()
    finally:
        db.close()

def determine_winner(bet, home_score, away_score):
    """Determine bet winner based on scores. Returns 'bookie', 'bettor', or 'push'."""
    score_diff = home_score - away_score
    
    if bet.type == "spread":
        if bet.bookie_side == "home":
            adjusted = score_diff + bet.value
            if adjusted > 0: return "bookie"
            if adjusted < 0: return "bettor"
            return "push"
        else:
            adjusted = score_diff - bet.value
            if adjusted < 0: return "bookie"
            if adjusted > 0: return "bettor"
            return "push"
    elif bet.type == "moneyline":
        if home_score == away_score: return "push"
        if bet.bookie_side == "home":
            return "bookie" if home_score > away_score else "bettor"
        else:
            return "bookie" if away_score > home_score else "bettor"
    elif bet.type == "total":
        total = home_score + away_score
        if total == bet.value: return "push"
        if bet.bookie_side == "over":
            return "bookie" if total > bet.value else "bettor"
        else:
            return "bookie" if total < bet.value else "bettor"
    return None

def settle_bet(db, bet, winner):
    """Auto-settle a bet. winner can be 'bookie', 'bettor', or 'push'."""
    # Use split amounts if available (odds-aware), fall back to legacy even-money
    b_amt = bet.bookie_amount if bet.bookie_amount is not None else bet.amount
    t_amt = bet.bettor_amount if bet.bettor_amount is not None else bet.amount
    total_pot = b_amt + t_amt

    bookie = db.query(User).filter(User.id == bet.bookie_id).first()
    bettor = db.query(User).filter(User.id == bet.bettor_id).first()

    if not bookie or not bettor:
        print(f"settle_bet: could not find bookie or bettor for bet {bet.id}")
        return

    if winner == "push":
        bookie.balance += b_amt
        bettor.balance += t_amt
    elif winner == "bookie":
        bookie.balance += total_pot
        bookie.profit += t_amt          # profit = what opponent risked
        bookie.wins += 1
        bettor.profit -= t_amt
        bettor.losses += 1
    else:  # bettor wins
        bettor.balance += total_pot
        bettor.profit += b_amt          # profit = what bookie risked
        bettor.wins += 1
        bookie.profit -= b_amt
        bookie.losses += 1

    bet.status = "settled"
    bet.winner = winner

    # Notify both parties
    if winner == "push":
        if bookie:
            push_notification(db, bookie.id, "bet_settled", "🤝 Bet pushed — refunded",
                f"{bet.game} · ${b_amt:.2f} returned", bet.id)
        if bettor:
            push_notification(db, bettor.id, "bet_settled", "🤝 Bet pushed — refunded",
                f"{bet.game} · ${t_amt:.2f} returned", bet.id)
    elif winner == "bookie":
        if bookie:
            push_notification(db, bookie.id, "bet_settled", f"🏆 You won! +${t_amt:.2f}",
                f"{bet.game} · {bet.type.upper()}", bet.id)
        if bettor:
            push_notification(db, bettor.id, "bet_settled", f"💸 You lost -${t_amt:.2f}",
                f"{bet.game} · {bet.type.upper()}", bet.id)
    else:
        if bettor:
            push_notification(db, bettor.id, "bet_settled", f"🏆 You won! +${b_amt:.2f}",
                f"{bet.game} · {bet.type.upper()}", bet.id)
        if bookie:
            push_notification(db, bookie.id, "bet_settled", f"💸 You lost -${b_amt:.2f}",
                f"{bet.game} · {bet.type.upper()}", bet.id)

def refund_unmatched_line(db, line):
    """When a line closes, refund any unmatched portion back to the bookie."""
    unmatched = line.amount - (line.total_action or 0)
    if unmatched > 0.01:  # avoid floating point noise
        bookie = db.query(User).filter(User.id == line.bookie_id).first()
        if bookie:
            bookie.balance += unmatched
            print(f"Refunded ${unmatched:.2f} unmatched funds to bookie {bookie.username}")

# ─── NOTIFICATION HELPERS ─────────────────────────────────────────────────────

def push_notification(db, user_id: int, type: str, title: str, body: str, ref_id: int = None):
    """Create a notification for a user. Fire-and-forget — never raises."""
    try:
        n = Notification(user_id=user_id, type=type, title=title, body=body, ref_id=ref_id)
        db.add(n)
        # No commit here — caller handles the commit
    except Exception as e:
        print(f"push_notification error: {e}")

# ─── NOTIFICATION HELPERS END ──────────────────────────────────────────────────

def expire_pregame_lines():
    """
    Cancel any open lines/props whose game has already started (commence_time passed).
    Refund the bookie's full unmatched stake. Runs every minute so the window is tight.
    """
    now = datetime.utcnow()
    all_games = fetch_live_games()

    # Build a set of game IDs that have already kicked off
    started_ids = {g["id"] for g in all_games if g.get("commence_time") and
                   datetime.strptime(g["commence_time"][:19], "%Y-%m-%dT%H:%M:%S") <= now}

    if not started_ids:
        return

    db = SessionLocal()
    try:
        # ── Lines ──────────────────────────────────────────────────────────────
        open_lines = db.query(Line).filter(
            Line.status == "open",
            Line.game_id.in_(started_ids)
        ).all()

        for line in open_lines:
            refund_unmatched_line(db, line)
            line.status = "expired"
            push_notification(
                db, line.bookie_id, "bet_settled",
                "⏰ Line expired — game started",
                f"{line.game} · Unmatched stake refunded",
                line.id
            )

        # ── Props (non-futures) ────────────────────────────────────────────────
        open_props = db.query(Prop).filter(
            Prop.status == "open",
            Prop.game_id.in_(started_ids)
        ).all()

        for prop in open_props:
            bookie = db.query(User).filter(User.id == prop.bookie_id).first()
            if bookie:
                bookie.balance += prop.amount
            prop.status = "expired"
            push_notification(
                db, prop.bookie_id, "bet_settled",
                "⏰ Prop expired — game started",
                f"{prop.player_name} {prop.prop_type} · ${prop.amount:.2f} refunded",
                prop.id
            )

        if open_lines or open_props:
            db.commit()
            print(f"[expire_pregame] Expired {len(open_lines)} lines, {len(open_props)} props for games: {started_ids}")

    except Exception as e:
        print(f"Error in expire_pregame_lines: {e}")
        db.rollback()
    finally:
        db.close()

# Initialize scheduler - started in app lifecycle to avoid duplicate workers
scheduler = BackgroundScheduler()
scheduler.add_job(check_game_scores,     'interval', minutes=5)
scheduler.add_job(expire_pregame_lines,  'interval', minutes=1)

@app.on_event("startup")
def start_scheduler():
    if not scheduler.running:
        scheduler.start()

@app.on_event("shutdown")
def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)

# Models
class UserCreate(BaseModel):
    username: str
    password: str

class LineCreate(BaseModel):
    game_id: str
    type: str
    side: str
    value: float
    odds: int = -110
    amount: float
    max_bettors: Optional[int] = None
    max_bet_per_user: Optional[float] = None
    max_total_action: Optional[float] = None
    is_private: Optional[bool] = False
    group_id: Optional[int] = None

class LineUpdate(BaseModel):
    odds: Optional[int] = None          # Change the odds
    add_amount: Optional[float] = None  # Add more stake to the line
    max_bet_per_user: Optional[float] = None
    max_bettors: Optional[int] = None

class PropCreate(BaseModel):
    game_id: str
    sport: str
    player_name: str
    prop_type: str
    line: float
    side: str
    odds: int = -110
    amount: float

class TakeLine(BaseModel):
    line_id: int
    amount: Optional[float] = None  # Bettor can specify amount

class TakeProp(BaseModel):
    prop_id: int

class ChallengeCreate(BaseModel):
    challenged_username: str
    game_id: str
    type: str
    side: str
    value: float
    odds: int = -110
    amount: float
    message: Optional[str] = None

class ChallengeAction(BaseModel):
    challenge_id: int

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class InviteBody(BaseModel):
    username: str

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
    try:
        print(f"=== REGISTER ATTEMPT: {user.username} ===")
        
        if len(user.password) < 6:
            print("Password too short")
            raise HTTPException(400, "Password 6+ chars")
        
        # Check if username exists
        print(f"Checking if {user.username} exists...")
        existing = db.query(User).filter(User.username == user.username).first()
        print(f"Existing user found: {existing is not None}")
        
        if existing:
            print(f"User {user.username} already exists!")
            raise HTTPException(400, "Username taken")
        
        print("Counting total users...")
        user_count = db.query(User).count()
        is_admin = user_count == 0
        print(f"Total users: {user_count}, Will be admin: {is_admin}")
        
        print("Creating new user...")
        new_user = User(username=user.username, password=hash_password(user.password), is_admin=is_admin)
        db.add(new_user)
        
        print("Committing to database...")
        db.commit()
        db.refresh(new_user)
        
        print(f"User created successfully! ID: {new_user.id}")
        return {
            "token": create_token(new_user.id), 
            "user": {
                "id": new_user.id, 
                "username": new_user.username, 
                "balance": new_user.balance,
                "profit": new_user.profit,
                "wins": new_user.wins,
                "losses": new_user.losses,
                "lines_created": new_user.lines_created,
                "is_admin": new_user.is_admin
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"!!! REGISTRATION ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(500, f"Database error: {str(e)}")

@app.post("/api/auth/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == user.username).first()
    if not u or u.password != hash_password(user.password):
        raise HTTPException(401, "Invalid credentials")
    return {
        "token": create_token(u.id), 
        "user": {
            "id": u.id, 
            "username": u.username, 
            "balance": u.balance,
            "profit": u.profit,
            "wins": u.wins,
            "losses": u.losses,
            "lines_created": u.lines_created,
            "is_admin": u.is_admin
        }
    }

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
    lines = db.query(Line).filter(Line.status == "open", (Line.is_private == False) | (Line.is_private == None)).all()
    result = []
    for l in lines:
        odds = l.odds if l.odds is not None else -110
        available_bookie = l.amount - (l.total_action or 0)
        available_for_bettor = bettor_stake_from_bookie(available_bookie, odds)
        result.append({
            "id": l.id, "bookie_id": l.bookie_id, "bookie_name": l.bookie_name,
            "game": l.game, "sport": l.sport, "type": l.type, "side": l.side,
            "value": l.value, "odds": odds, "amount": l.amount, "status": l.status,
            "total_action": l.total_action, "current_bettors": l.current_bettors,
            "max_bet_per_user": l.max_bet_per_user, "is_private": l.is_private,
            "available_for_bettor": round(available_for_bettor, 2)
        })
    return result

@app.post("/api/lines")
def create_line(line: LineCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.balance < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    all_games = fetch_live_games()
    game = next((g for g in all_games if g["id"] == line.game_id), None)
    if not game:
        raise HTTPException(404, "Game not found")
    
    new_line = Line(bookie_id=user.id, bookie_name=user.username, game_id=line.game_id,
                   game=f"{game['away']} @ {game['home']}", sport=game["sport"],
                   type=line.type, side=line.side, value=line.value, odds=line.odds,
                   amount=line.amount, max_bettors=line.max_bettors,
                   max_bet_per_user=line.max_bet_per_user,
                   max_total_action=line.max_total_action,
                   is_private=line.is_private, group_id=line.group_id)
    user.balance -= line.amount
    user.lines_created += 1
    db.add(new_line)
    db.commit()
    db.refresh(new_line)
    return {"message": "Line created", "line_id": new_line.id}

@app.get("/api/lines/mine")
def get_my_lines(token: str, db: Session = Depends(get_db)):
    """Get all open lines posted by the authenticated bookie."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    lines = db.query(Line).filter(Line.bookie_id == user_id, Line.status == "open").order_by(Line.created_at.desc()).all()
    result = []
    for l in lines:
        odds = l.odds if l.odds is not None else -110
        unmatched = l.amount - (l.total_action or 0)
        available_for_bettor = bettor_stake_from_bookie(unmatched, odds)
        result.append({
            "id": l.id, "game": l.game, "sport": l.sport, "type": l.type,
            "side": l.side, "value": l.value, "odds": odds,
            "amount": l.amount, "total_action": l.total_action or 0,
            "unmatched": round(unmatched, 2),
            "available_for_bettor": round(available_for_bettor, 2),
            "current_bettors": l.current_bettors or 0,
            "max_bet_per_user": l.max_bet_per_user,
            "max_bettors": l.max_bettors,
            "is_private": l.is_private,
        })
    return result

@app.patch("/api/lines/{line_id}")
def update_line(line_id: int, update: LineUpdate, token: str, db: Session = Depends(get_db)):
    """Bookie adjusts odds, adds stake, or changes limits on their open line."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    line = db.query(Line).filter(Line.id == line_id, Line.bookie_id == user_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not found or not yours")

    if update.odds is not None:
        if update.odds == 0 or (-100 < update.odds < 100):
            raise HTTPException(400, "Odds must be ≤ -100 or ≥ +100")
        line.odds = update.odds

    if update.add_amount is not None and update.add_amount > 0:
        user = db.query(User).filter(User.id == user_id).first()
        if user.balance < update.add_amount:
            raise HTTPException(400, f"Insufficient balance. You have ${user.balance:.2f}")
        user.balance -= update.add_amount
        line.amount += update.add_amount

    if update.max_bet_per_user is not None:
        line.max_bet_per_user = update.max_bet_per_user if update.max_bet_per_user > 0 else None

    if update.max_bettors is not None:
        line.max_bettors = update.max_bettors if update.max_bettors > 0 else None

    db.commit()
    odds = line.odds if line.odds is not None else -110
    unmatched = line.amount - (line.total_action or 0)
    return {
        "message": "Line updated",
        "odds": odds,
        "amount": line.amount,
        "unmatched": round(unmatched, 2),
        "available_for_bettor": round(bettor_stake_from_bookie(unmatched, odds), 2)
    }

@app.delete("/api/lines/{line_id}")
def pull_line(line_id: int, token: str, db: Session = Depends(get_db)):
    """Bookie pulls their line — unmatched stake is refunded."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    line = db.query(Line).filter(Line.id == line_id, Line.bookie_id == user_id, Line.status == "open").first()
    if not line:
        raise HTTPException(404, "Line not found or not yours")

    refund_unmatched_line(db, line)
    line.status = "cancelled"
    db.commit()

    unmatched = line.amount - (line.total_action or 0)
    refunded = max(0, unmatched)
    return {"message": f"Line pulled. ${refunded:.2f} refunded to your balance."}

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
    if not user:
        raise HTTPException(404, "User not found")

    odds = line.odds if line.odds is not None else -110

    # Available bookie stake remaining on this line
    available_bookie = line.amount - (line.total_action or 0)
    if available_bookie <= 0:
        raise HTTPException(400, "Line is fully filled")

    # Max bettor can wager = bettor equivalent of available bookie stake
    max_bettor_stake = bettor_stake_from_bookie(available_bookie, odds)

    # Bettor's desired stake (they enter how much THEY want to risk)
    bettor_stake = take.amount if take.amount else max_bettor_stake
    bettor_stake = min(bettor_stake, max_bettor_stake)

    # Enforce max_bet_per_user (in bettor stake terms)
    if line.max_bet_per_user:
        already_bet = db.query(func.sum(Bet.bettor_amount)).filter(
            Bet.line_id == line.id,
            Bet.bettor_id == user_id
        ).scalar() or 0
        remaining = line.max_bet_per_user - already_bet
        if remaining <= 0:
            raise HTTPException(400, f"You've reached the max bet limit of ${line.max_bet_per_user}")
        bettor_stake = min(bettor_stake, remaining)

    # Enforce max_bettors
    if line.max_bettors:
        unique_bettors = db.query(Bet.bettor_id).filter(Bet.line_id == line.id).distinct().count()
        if unique_bettors >= line.max_bettors:
            user_has_bet = db.query(Bet).filter(
                Bet.line_id == line.id, Bet.bettor_id == user_id
            ).first()
            if not user_has_bet:
                raise HTTPException(400, f"Max of {line.max_bettors} bettors reached")

    if bettor_stake < 0.01:
        raise HTTPException(400, "Bet amount is too small")
    if user.balance < bettor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${bettor_stake:.2f}")

    # Corresponding bookie stake consumed for this bettor wager
    bookie_portion = bookie_portion_from_bettor(bettor_stake, odds)

    # Determine bettor's side
    if line.side in ("home", "away"):
        bettor_side = "away" if line.side == "home" else "home"
    elif line.side == "over":
        bettor_side = "under"
    elif line.side == "under":
        bettor_side = "over"
    else:
        bettor_side = line.side

    bet = Bet(
        line_id=line.id,
        bookie_id=line.bookie_id,
        bookie_name=line.bookie_name,
        bettor_id=user.id,
        bettor_name=user.username,
        game_id=line.game_id,
        game=line.game,
        type=line.type,
        bookie_side=line.side,
        bettor_side=bettor_side,
        value=line.value,
        odds=odds,
        amount=bookie_portion,          # legacy field = bookie portion
        bookie_amount=bookie_portion,
        bettor_amount=bettor_stake
    )

    line.total_action = (line.total_action or 0) + bookie_portion
    line.current_bettors = db.query(Bet.bettor_id).filter(Bet.line_id == line.id).distinct().count() + 1

    if line.total_action >= line.amount:
        line.status = "matched"

    user.balance -= bettor_stake

    db.add(bet)
    db.flush()

    # Notify bookie their line was taken
    push_notification(db, line.bookie_id, "bet_matched",
        f"🎯 @{user.username} took your line",
        f"{line.game} · {line.type.upper()} · ${bettor_stake:.2f} matched",
        bet.id)

    db.commit()

    return {
        "message": "Bet placed",
        "bettor_stake": bettor_stake,
        "bookie_stake": bookie_portion,
        "to_win": bookie_portion,
        "odds": format_odds(odds)
    }

@app.get("/api/props")
def get_props(db: Session = Depends(get_db)):
    props = db.query(Prop).filter(
        Prop.status == "open",
        ~Prop.game_id.startswith("future_")
    ).all()
    return [{"id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name,
             "game_id": p.game_id, "game": p.game, "sport": p.sport,
             "player_name": p.player_name, "prop_type": p.prop_type, "line": p.line, "side": p.side,
             "odds": p.odds if p.odds is not None else -110,
             "amount": p.amount} for p in props]

@app.post("/api/props")
def create_prop(prop: PropCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.balance < prop.amount:
        raise HTTPException(400, "Insufficient balance")

    # Look up game name from game_id — futures use a "future_" prefix, bypass live lookup
    if prop.game_id.startswith("future_"):
        game_name = f"Futures: {prop.player_name} ({prop.prop_type})"
    else:
        all_games = fetch_live_games()
        game = next((g for g in all_games if g["id"] == prop.game_id), None)
        if not game:
            raise HTTPException(404, "Game not found")
        game_name = f"{game['away']} @ {game['home']}"

    new_prop = Prop(bookie_id=user.id, bookie_name=user.username,
                   game_id=prop.game_id, game=game_name,
                   sport=prop.sport, player_name=prop.player_name,
                   prop_type=prop.prop_type, line=prop.line,
                   side=prop.side, odds=prop.odds, amount=prop.amount)
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
    if prop.bookie_id == user_id:
        raise HTTPException(400, "Can't bet your own prop")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    odds = prop.odds if prop.odds is not None else -110
    if odds == 0 or (-100 < odds < 100):
        odds = -110  # fallback safety

    # Bettor stake is the mirror of the bookie stake at these odds
    bettor_stake = bettor_stake_from_bookie(prop.amount, odds)

    if user.balance < bettor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${bettor_stake:.2f}")

    prop_bet = PropBet(prop_id=prop.id, bookie_id=prop.bookie_id, bookie_name=prop.bookie_name,
                      bettor_id=user.id, bettor_name=user.username, player_name=prop.player_name,
                      prop_type=prop.prop_type, line=prop.line, bookie_side=prop.side,
                      bettor_side="under" if prop.side == "over" else "over",
                      odds=odds,
                      bookie_amount=prop.amount,
                      bettor_amount=bettor_stake,
                      amount=prop.amount)
    prop.status = "matched"
    user.balance -= bettor_stake
    db.add(prop_bet)
    db.commit()
    return {"message": "Prop bet placed", "bettor_stake": bettor_stake, "bookie_stake": prop.amount}

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
                        "value": b.value, "odds": b.odds or -110, "amount": b.amount,
                        "bookie_amount": b.bookie_amount or b.amount,
                        "bettor_amount": b.bettor_amount or b.amount,
                        "status": b.status, "winner": b.winner} for b in bets],
        "prop_bets": [{"id": p.id, "bookie_id": p.bookie_id, "bookie_name": p.bookie_name,
                      "bettor_id": p.bettor_id, "bettor_name": p.bettor_name, "player_name": p.player_name,
                      "prop_type": p.prop_type, "line": p.line, "bookie_side": p.bookie_side,
                      "bettor_side": p.bettor_side, "odds": p.odds or -110,
                      "bookie_amount": p.bookie_amount or p.amount,
                      "bettor_amount": p.bettor_amount or p.amount,
                      "amount": p.amount, "status": p.status, "winner": p.winner} for p in prop_bets],
        "parlays": []
    }

@app.post("/api/challenges")
def create_challenge(challenge: ChallengeCreate, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenger = db.query(User).filter(User.id == user_id).first()
    if not challenger:
        raise HTTPException(404, "User not found")

    challenged = db.query(User).filter(User.username == challenge.challenged_username).first()
    if not challenged:
        raise HTTPException(404, f"User @{challenge.challenged_username} not found")
    if challenged.id == user_id:
        raise HTTPException(400, "Can't challenge yourself")

    if challenger.balance < challenge.amount:
        raise HTTPException(400, "Insufficient balance")

    # Validate odds
    if challenge.odds == 0 or (-100 < challenge.odds < 100):
        raise HTTPException(400, "Odds must be -100 or lower, or +100 or higher")

    all_games = fetch_live_games()
    game = next((g for g in all_games if g["id"] == challenge.game_id), None)
    if not game:
        raise HTTPException(404, "Game not found")

    new_challenge = Challenge(
        challenger_id=challenger.id,
        challenger_name=challenger.username,
        challenged_id=challenged.id,
        challenged_name=challenged.username,
        game_id=challenge.game_id,
        game=f"{game['away']} @ {game['home']}",
        sport=game["sport"],
        type=challenge.type,
        side=challenge.side,
        value=challenge.value,
        odds=challenge.odds,
        amount=challenge.amount,
        message=challenge.message
    )
    challenger.balance -= challenge.amount
    db.add(new_challenge)
    db.flush()
    push_notification(db, challenged.id, "challenge_received",
        f"⚔️ Challenge from @{challenger.username}",
        f"{challenge.type.upper()} · {challenge.side} · ${challenge.amount} stake",
        new_challenge.id)
    db.commit()
    db.refresh(new_challenge)
    return {"message": "Challenge sent!", "challenge_id": new_challenge.id}

@app.get("/api/challenges")
def get_challenges(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    incoming = db.query(Challenge).filter(
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).order_by(Challenge.created_at.desc()).all()

    outgoing = db.query(Challenge).filter(
        Challenge.challenger_id == user_id
    ).order_by(Challenge.created_at.desc()).limit(20).all()

    def fmt(c, role):
        odds = c.odds if c.odds else -110
        if odds <= -100:
            bettor_stake = round(c.amount * (100 / abs(odds)), 2)
        else:
            bettor_stake = round(c.amount * (odds / 100), 2)
        return {
            "id": c.id, "challenger_name": c.challenger_name,
            "challenged_name": c.challenged_name,
            "game": c.game, "sport": c.sport, "type": c.type,
            "side": c.side, "value": c.value, "odds": odds,
            "amount": c.amount, "bettor_stake": bettor_stake,
            "message": c.message, "status": c.status,
            "bet_id": c.bet_id, "role": role,
            "created_at": c.created_at.isoformat()
        }

    return {
        "incoming": [fmt(c, "challenged") for c in incoming],
        "outgoing": [fmt(c, "challenger") for c in outgoing]
    }

@app.post("/api/challenges/accept")
def accept_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found or already resolved")

    acceptor = db.query(User).filter(User.id == user_id).first()
    if not acceptor:
        raise HTTPException(404, "User not found")

    odds = challenge.odds if challenge.odds else -110
    if odds <= -100:
        acceptor_stake = round(challenge.amount * (100 / abs(odds)), 2)
    else:
        acceptor_stake = round(challenge.amount * (odds / 100), 2)

    if acceptor.balance < acceptor_stake:
        raise HTTPException(400, f"Insufficient balance. Need ${acceptor_stake:.2f}")

    # Determine opponent sides
    ch_side = challenge.side
    if ch_side in ("home", "away"):
        opp_side = "away" if ch_side == "home" else "home"
    elif ch_side == "over":
        opp_side = "under"
    elif ch_side == "under":
        opp_side = "over"
    else:
        opp_side = ch_side

    # Create a real Bet — plugs straight into the settlement pipeline
    bet = Bet(
        line_id=None,
        bookie_id=challenge.challenger_id,
        bookie_name=challenge.challenger_name,
        bettor_id=acceptor.id,
        bettor_name=acceptor.username,
        game_id=challenge.game_id,
        game=challenge.game,
        type=challenge.type,
        bookie_side=ch_side,
        bettor_side=opp_side,
        value=challenge.value,
        odds=odds,
        amount=challenge.amount,
        bookie_amount=challenge.amount,
        bettor_amount=acceptor_stake
    )
    acceptor.balance -= acceptor_stake
    db.add(bet)
    db.flush()

    challenge.status = "accepted"
    challenge.bet_id = bet.id

    # Notify challenger their challenge was accepted
    push_notification(db, challenge.challenger_id, "challenge_accepted",
        f"✅ @{acceptor.username} accepted your challenge!",
        f"{challenge.game} · {challenge.type.upper()} · Bet #{bet.id} is live",
        bet.id)
    db.commit()
    return {"message": "Challenge accepted! Bet is live.", "bet_id": bet.id}

@app.post("/api/challenges/decline")
def decline_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenged_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found")
    # Refund challenger
    challenger = db.query(User).filter(User.id == challenge.challenger_id).first()
    if challenger:
        challenger.balance += challenge.amount
    challenge.status = "declined"
    push_notification(db, challenge.challenger_id, "challenge_declined",
        f"❌ @{challenge.challenged_name} declined your challenge",
        f"{challenge.game} · Stake of ${challenge.amount} refunded",
        challenge.id)
    db.commit()
    return {"message": "Challenge declined. Challenger refunded."}

@app.post("/api/challenges/cancel")
def cancel_challenge(action: ChallengeAction, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    challenge = db.query(Challenge).filter(
        Challenge.id == action.challenge_id,
        Challenge.challenger_id == user_id,
        Challenge.status == "pending"
    ).first()
    if not challenge:
        raise HTTPException(404, "Challenge not found or cannot be cancelled")
    challenger = db.query(User).filter(User.id == user_id).first()
    if challenger:
        challenger.balance += challenge.amount
    challenge.status = "cancelled"
    db.commit()
    return {"message": "Challenge cancelled. Stake refunded."}

@app.get("/api/notifications")
def get_notifications(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    notifs = db.query(Notification).filter(
        Notification.user_id == user_id
    ).order_by(Notification.created_at.desc()).limit(30).all()
    return [{"id": n.id, "type": n.type, "title": n.title, "body": n.body,
             "is_read": n.is_read, "ref_id": n.ref_id,
             "created_at": n.created_at.isoformat()} for n in notifs]

@app.post("/api/notifications/read")
def mark_notifications_read(token: str, notif_id: Optional[int] = None, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    q = db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read == False)
    if notif_id:
        q = q.filter(Notification.id == notif_id)
    q.update({"is_read": True})
    db.commit()
    return {"message": "Marked as read"}

@app.post("/api/groups/{group_id}/invite")
def invite_to_group(group_id: int, body: InviteBody, token: str, db: Session = Depends(get_db)):
    """Group creator invites another user by username."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id != user_id:
        raise HTTPException(403, "Only the group owner can invite members")
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username required")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, f"User @{username} not found")
    members = json.loads(group.members)
    if target.id in members:
        raise HTTPException(400, f"@{username} is already in this group")
    members.append(target.id)
    group.members = json.dumps(members)
    push_notification(db, target.id, "group_invite",
        f"👥 Added to group: {group.name}",
        f"@{db.query(User).filter(User.id==user_id).first().username} added you to the group \"{group.name}\"",
        ref_id=group.id)
    db.commit()
    return {"message": f"@{username} added to {group.name}"}

@app.post("/api/groups/{group_id}/leave")
def leave_group(group_id: int, token: str, db: Session = Depends(get_db)):
    """Leave a group (creator can't leave — must delete instead)."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id == user_id:
        raise HTTPException(400, "You're the owner — delete the group instead")
    members = json.loads(group.members)
    if user_id not in members:
        raise HTTPException(400, "You're not in this group")
    members.remove(user_id)
    group.members = json.dumps(members)
    db.commit()
    return {"message": f"Left group {group.name}"}

@app.delete("/api/groups/{group_id}")
def delete_group(group_id: int, token: str, db: Session = Depends(get_db)):
    """Creator deletes the group."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "Group not found")
    if group.creator_id != user_id:
        raise HTTPException(403, "Only the owner can delete this group")
    db.delete(group)
    db.commit()
    return {"message": "Group deleted"}

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
    db.refresh(new_group)
    return {"message": "Group created", "group_id": new_group.id}

@app.post("/api/follow/{username}")
def follow_user(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user_id:
        raise HTTPException(400, "Can't follow yourself")
    existing = db.query(Follow).filter(Follow.follower_id == user_id, Follow.followed_id == target.id).first()
    if existing:
        raise HTTPException(400, "Already following")
    db.add(Follow(follower_id=user_id, followed_id=target.id))
    db.commit()
    return {"message": f"Now following @{username}"}

@app.delete("/api/follow/{username}")
def unfollow_user(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    follow = db.query(Follow).filter(Follow.follower_id == user_id, Follow.followed_id == target.id).first()
    if not follow:
        raise HTTPException(404, "Not following")
    db.delete(follow)
    db.commit()
    return {"message": f"Unfollowed @{username}"}

@app.get("/api/following")
def get_following(token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
    followed_ids = [f.followed_id for f in follows]
    users = db.query(User).filter(User.id.in_(followed_ids)).all() if followed_ids else []
    # Get open lines count per followed user
    result = []
    for u in users:
        open_lines = db.query(Line).filter(Line.bookie_id == u.id, Line.status == "open").count()
        result.append({
            "id": u.id, "username": u.username, "wins": u.wins, "losses": u.losses,
            "profit": u.profit, "open_lines": open_lines,
            "win_rate": round((u.wins / (u.wins + u.losses) * 100) if (u.wins + u.losses) > 0 else 0, 1)
        })
    return result

# ─── FRIEND REQUESTS ─────────────────────────────────────────────────────────

@app.post("/api/friends/request/{username}")
def send_friend_request(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user_id:
        raise HTTPException(400, "Can't friend yourself")
    # Already friends?
    existing = db.query(FriendRequest).filter(
        ((FriendRequest.sender_id == user_id) & (FriendRequest.receiver_id == target.id)) |
        ((FriendRequest.sender_id == target.id) & (FriendRequest.receiver_id == user_id))
    ).first()
    if existing:
        if existing.status == "accepted":
            raise HTTPException(400, "Already friends")
        if existing.status == "pending":
            raise HTTPException(400, "Request already sent")
        # declined — allow re-request by updating
        existing.status = "pending"
        existing.sender_id = user_id
        existing.receiver_id = target.id
        db.commit()
        return {"message": f"Friend request sent to @{username}"}
    req = FriendRequest(sender_id=user_id, receiver_id=target.id)
    db.add(req)
    sender = db.query(User).filter(User.id == user_id).first()
    push_notification(db, target.id, "friend_request",
        f"👋 Friend request from @{sender.username}",
        f"@{sender.username} wants to be friends", ref_id=user_id)
    db.commit()
    return {"message": f"Friend request sent to @{username}"}

@app.post("/api/friends/accept/{request_id}")
def accept_friend_request(request_id: int, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    req = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        raise HTTPException(404, "Request not found")
    req.status = "accepted"
    receiver = db.query(User).filter(User.id == user_id).first()
    push_notification(db, req.sender_id, "friend_accepted",
        f"🤝 @{receiver.username} accepted your friend request",
        "You're now friends!", ref_id=user_id)
    db.commit()
    return {"message": "Friend request accepted"}

@app.post("/api/friends/decline/{request_id}")
def decline_friend_request(request_id: int, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    req = db.query(FriendRequest).filter(
        FriendRequest.id == request_id,
        FriendRequest.receiver_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        raise HTTPException(404, "Request not found")
    req.status = "declined"
    db.commit()
    return {"message": "Request declined"}

@app.delete("/api/friends/{username}")
def remove_friend(username: str, token: str, db: Session = Depends(get_db)):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(404, "User not found")
    req = db.query(FriendRequest).filter(
        FriendRequest.status == "accepted",
        ((FriendRequest.sender_id == user_id) & (FriendRequest.receiver_id == target.id)) |
        ((FriendRequest.sender_id == target.id) & (FriendRequest.receiver_id == user_id))
    ).first()
    if not req:
        raise HTTPException(404, "Not friends")
    db.delete(req)
    db.commit()
    return {"message": f"Removed @{username} from friends"}

@app.get("/api/friends")
def get_friends(token: str, db: Session = Depends(get_db)):
    """Returns: accepted friends, pending incoming requests, pending outgoing requests."""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")

    all_reqs = db.query(FriendRequest).filter(
        (FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)
    ).all()

    friends, incoming, outgoing = [], [], []
    for r in all_reqs:
        other_id = r.receiver_id if r.sender_id == user_id else r.sender_id
        other = db.query(User).filter(User.id == other_id).first()
        if not other:
            continue
        obj = {
            "request_id": r.id,
            "id": other.id, "username": other.username,
            "wins": other.wins, "losses": other.losses, "profit": other.profit,
            "win_rate": round((other.wins/(other.wins+other.losses)*100) if (other.wins+other.losses)>0 else 0, 1)
        }
        if r.status == "accepted":
            friends.append(obj)
        elif r.status == "pending":
            if r.receiver_id == user_id:
                incoming.append(obj)
            else:
                outgoing.append(obj)

    return {"friends": friends, "incoming": incoming, "outgoing": outgoing}

# Update users/search to include friendship status
@app.get("/api/users/search")
def search_users(token: str = None, db: Session = Depends(get_db)):
    user_id = verify_token(token) if token else None
    users = db.query(User).order_by(User.profit.desc()).all()

    # Build friendship map for current user
    friend_map = {}  # other_user_id -> status string
    if user_id:
        reqs = db.query(FriendRequest).filter(
            (FriendRequest.sender_id == user_id) | (FriendRequest.receiver_id == user_id)
        ).all()
        for r in reqs:
            other = r.receiver_id if r.sender_id == user_id else r.sender_id
            if r.status == "accepted":
                friend_map[other] = "friends"
            elif r.status == "pending":
                friend_map[other] = "outgoing" if r.sender_id == user_id else "incoming"

        follows = db.query(Follow).filter(Follow.follower_id == user_id).all()
        follow_set = {f.followed_id for f in follows}
    else:
        follow_set = set()

    result = []
    for u in users:
        if user_id and u.id == user_id:
            continue
        result.append({
            "id": u.id, "username": u.username, "wins": u.wins,
            "losses": u.losses, "profit": u.profit,
            "is_following": u.id in follow_set,
            "friend_status": friend_map.get(u.id, "none"),  # none|outgoing|incoming|friends
            "request_id": next((r.id for r in (reqs if user_id else [])
                               if (r.sender_id==u.id and r.receiver_id==user_id) or
                                  (r.sender_id==user_id and r.receiver_id==u.id)), None)
        })
    return result

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

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    base = os.path.dirname(os.path.abspath(__file__))
    for name in ["index.html", "FRESH_index.html"]:
        path = os.path.join(base, name)
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read()
    return HTMLResponse("<h1>index.html not found</h1>", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
