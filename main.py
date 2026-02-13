# main.py - BookieVerse with Stripe Shop + User Search + Auto-Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List
import hashlib
import jwt
from datetime import datetime, timedelta
import uvicorn
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import stripe

app = FastAPI(title="BookieVerse - Full Featured P2P Sportsbook")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "bookieverse-secret-change-in-production")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Initialize Stripe
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Constants
HOURLY_CURRENCY = 5
STARTING_BALANCE = 1000
MAX_OFFLINE_HOURS = 72

# Credit Packages (in cents for Stripe)
CREDIT_PACKAGES = {
    "small": {"amount": 299, "credits": 300, "name": "$2.99 - 300 Credits"},
    "medium": {"amount": 499, "credits": 500, "name": "$4.99 - 500 Credits"},
    "large": {"amount": 999, "credits": 1100, "name": "$9.99 - 1,100 Credits (+10%)"},
    "xl": {"amount": 1999, "credits": 2400, "name": "$19.99 - 2,400 Credits (+20%)"},
    "mega": {"amount": 4999, "credits": 6500, "name": "$49.99 - 6,500 Credits (+30%)"}
}

# In-memory storage
users_db = {}
lines_db = {}
bets_db = {}
games_db = {}
futures_db = {}
parlays_db = {}
groups_db = {}
ratings_db = {}
follows_db = {}
purchases_db = {}

SPORTS = ['basketball_nba', 'americanfootball_nfl']

# ==================== PYDANTIC MODELS ====================

class UserCreate(BaseModel):
    username: str
    password: str = "demo123"

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
    group_id: Optional[str] = None

class LineUpdate(BaseModel):
    value: Optional[float] = None
    amount: Optional[float] = None
    max_bettors: Optional[int] = None

class TakeLine(BaseModel):
    line_id: str

class ParlayCreate(BaseModel):
    line_ids: List[str]
    amount: float

class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None

class GroupInvite(BaseModel):
    group_id: str
    username: str

class RateBookie(BaseModel):
    bookie_id: str
    rating: int
    comment: Optional[str] = None

class CreditPurchase(BaseModel):
    package: str  # small, medium, large, xl, mega

# ==================== HELPER FUNCTIONS ====================

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("user_id")
    except:
        return None

def apply_hourly_currency(user_id: str):
    user = users_db.get(user_id)
    if not user:
        return
    
    now = datetime.utcnow()
    last_accrual = user.get("last_accrual")
    
    if not last_accrual:
        user["last_accrual"] = now
        return
    
    hours_passed = (now - last_accrual).total_seconds() / 3600
    hours_passed = min(hours_passed, MAX_OFFLINE_HOURS)
    currency_to_add = int(hours_passed) * HOURLY_CURRENCY
    
    if currency_to_add > 0:
        user["balance"] += currency_to_add
        user["last_accrual"] = now
        user["total_earned"] = user.get("total_earned", 0) + currency_to_add

def get_bookie_rating(bookie_id: str) -> dict:
    bookie_ratings = [r for r in ratings_db.values() if r["bookie_id"] == bookie_id]
    
    if not bookie_ratings:
        return {"average": 0, "count": 0}
    
    total = sum(r["rating"] for r in bookie_ratings)
    avg = total / len(bookie_ratings)
    
    return {"average": round(avg, 2), "count": len(bookie_ratings)}

def get_bookie_stats(bookie_id: str) -> dict:
    user = users_db.get(bookie_id)
    if not user:
        return {}
    
    bookie_lines = [l for l in lines_db.values() if l["bookie_id"] == bookie_id]
    bookie_bets = [b for b in bets_db.values() if b["bookie_id"] == bookie_id and b["status"] == "settled"]
    
    total_lines = len(bookie_lines)
    active_lines = len([l for l in bookie_lines if l["status"] == "open"])
    
    wins = len([b for b in bookie_bets if b.get("winner") == "bookie"])
    losses = len([b for b in bookie_bets if b.get("winner") == "bettor"])
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    rating_data = get_bookie_rating(bookie_id)
    followers = len([f for f in follows_db.values() if f["bookie_id"] == bookie_id])
    
    return {
        "id": bookie_id,
        "username": user["username"],
        "total_lines_created": total_lines,
        "active_lines": active_lines,
        "settled_bets": len(bookie_bets),
        "win_rate": round(win_rate, 1),
        "wins": wins,
        "losses": losses,
        "rating": rating_data["average"],
        "rating_count": rating_data["count"],
        "followers": followers,
        "profit": user["profit"]
    }

def is_game_started(game_id: str) -> bool:
    """Check if a game has started"""
    game = games_db.get(game_id)
    if not game:
        return False
    
    # If game has status 'live' or 'final', it has started
    if game.get('status') in ['live', 'final']:
        return True
    
    # Check commence_time
    if game.get('commence_time'):
        try:
            commence_time = datetime.fromisoformat(game['commence_time'].replace('Z', '+00:00'))
            return datetime.now(commence_time.tzinfo) >= commence_time
        except:
            pass
    
    return False

# ==================== LIVE SCORES & AUTO-SETTLEMENT ====================

def fetch_live_scores():
    if not ODDS_API_KEY:
        return
    
    try:
        for sport in SPORTS:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/scores/"
            params = {
                'apiKey': ODDS_API_KEY,
                'daysFrom': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            scores = response.json()
            
            for game_score in scores:
                game_id = game_score['id']
                
                if game_id in games_db:
                    games_db[game_id]['status'] = 'live' if not game_score['completed'] else 'final'
                    games_db[game_id]['home_score'] = game_score.get('scores', [{}])[0].get('score')
                    games_db[game_id]['away_score'] = game_score.get('scores', [{}])[1].get('score')
                    
                    if game_score['completed']:
                        auto_settle_game(game_id, game_score)
                    
    except Exception as e:
        print(f"❌ Score fetch error: {e}")

def auto_settle_game(game_id: str, game_score: dict):
    try:
        scores = game_score.get('scores', [])
        if len(scores) < 2:
            return
        
        home_score = int(scores[0].get('score', 0))
        away_score = int(scores[1].get('score', 0))
        
        game_bets = [b for b in bets_db.values() 
                     if b.get("status") == "pending" 
                     and lines_db.get(b.get("line_id"), {}).get("game_id") == game_id]
        
        for bet in game_bets:
            line = lines_db.get(bet["line_id"])
            if not line:
                continue
            
            winner = determine_bet_winner(bet, line, home_score, away_score)
            
            if winner:
                settle_bet_automatically(bet["id"], winner)
        
    except Exception as e:
        print(f"❌ Auto-settle error: {e}")

def determine_bet_winner(bet: dict, line: dict, home_score: int, away_score: int) -> Optional[str]:
    bet_type = line.get("type")
    value = line.get("value", 0)
    bookie_side = bet.get("bookie_side")
    
    score_diff = home_score - away_score
    
    if bet_type == "spread":
        if bookie_side == "home":
            adjusted_diff = score_diff + value
            return "bookie" if adjusted_diff > 0 else "bettor"
        else:
            adjusted_diff = score_diff - value
            return "bookie" if adjusted_diff < 0 else "bettor"
    
    elif bet_type == "moneyline":
        if bookie_side == "home":
            return "bookie" if home_score > away_score else "bettor"
        else:
            return "bookie" if away_score > home_score else "bettor"
    
    elif bet_type == "total":
        total_points = home_score + away_score
        if bookie_side == "over":
            return "bookie" if total_points > value else "bettor"
        else:
            return "bookie" if total_points < value else "bettor"
    
    return None

def settle_bet_automatically(bet_id: str, winner: str):
