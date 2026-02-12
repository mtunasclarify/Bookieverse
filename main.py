# main.py - BookieVerse MEGA UPGRADE
# Features: Auto-Settlement, Cancel/Edit, Live Scores, Profiles/Ratings, Groups

from fastapi import FastAPI, HTTPException
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
import time

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

# Constants
HOURLY_CURRENCY = 5
STARTING_BALANCE = 1000
MAX_OFFLINE_HOURS = 72

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
    rating: int  # 1-5
    comment: Optional[str] = None

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
    """Calculate bookie's overall rating"""
    bookie_ratings = [r for r in ratings_db.values() if r["bookie_id"] == bookie_id]
    
    if not bookie_ratings:
        return {"average": 0, "count": 0}
    
    total = sum(r["rating"] for r in bookie_ratings)
    avg = total / len(bookie_ratings)
    
    return {"average": round(avg, 2), "count": len(bookie_ratings)}

def get_bookie_stats(bookie_id: str) -> dict:
    """Get detailed bookie statistics"""
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

# ==================== LIVE SCORES & AUTO-SETTLEMENT ====================

def fetch_live_scores():
    """Fetch live scores and auto-settle bets"""
    if not ODDS_API_KEY:
        return
    
    print("🔄 Fetching live scores...")
    
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
                
                # Update game status in games_db
                if game_id in games_db:
                    games_db[game_id]['status'] = 'live' if not game_score['completed'] else 'final'
                    games_db[game_id]['home_score'] = game_score.get('scores', [{}])[0].get('score')
                    games_db[game_id]['away_score'] = game_score.get('scores', [{}])[1].get('score')
                    
                    # Auto-settle if game is final
                    if game_score['completed']:
                        auto_settle_game(game_id, game_score)
        
        print(f"✅ Live scores updated")
                    
    except Exception as e:
        print(f"❌ Score fetch error: {e}")

def auto_settle_game(game_id: str, game_score: dict):
    """Automatically settle all bets for a completed game"""
    try:
        scores = game_score.get('scores', [])
        if len(scores) < 2:
            return
        
        home_score = int(scores[0].get('score', 0))
        away_score = int(scores[1].get('score', 0))
        
        # Find all pending bets for this game
        game_bets = [b for b in bets_db.values() 
                     if b.get("status") == "pending" 
                     and lines_db.get(b.get("line_id"), {}).get("game_id") == game_id]
        
        for bet in game_bets:
            line = lines_db.get(bet["line_id"])
            if not line:
                continue
            
            # Determine winner based on bet type
            winner = determine_bet_winner(bet, line, home_score, away_score)
            
            if winner:
                # Settle the bet
                settle_bet_automatically(bet["id"], winner)
        
        print(f"✅ Auto-settled {len(game_bets)} bets for game {game_id}")
        
    except Exception as e:
        print(f"❌ Auto-settle error: {e}")

def determine_bet_winner(bet: dict, line: dict, home_score: int, away_score: int) -> Optional[str]:
    """Determine who won the bet based on final score"""
    bet_type = line.get("type")
    value = line.get("value", 0)
    bookie_side = bet.get("bookie_side")
    
    score_diff = home_score - away_score  # Positive = home won
    
    if bet_type == "spread":
        # Bookie took home team
        if bookie_side == "home":
            adjusted_diff = score_diff + value  # value is negative for favorites
            return "bookie" if adjusted_diff > 0 else "bettor"
        else:  # Bookie took away
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
    """Auto-settle a bet with payout distribution"""
    bet = bets_db.get(bet_id)
    if not bet or bet["status"] != "pending":
        return
    
    rake = 0.05
    payout = bet["amount"] * 2 * (1 - rake)
    
    bookie = users_db.get(bet["bookie_id"])
    bettor = users_db.get(bet["bettor_id"])
    
    if not bookie or not bettor:
        return
    
    if winner == "bookie":
        bookie["balance"] += payout
        bookie["profit"] += (payout - bet["amount"])
        bookie["wins"] += 1
        bettor["profit"] -= bet["amount"]
        bettor["losses"] += 1
    else:
        bettor["balance"] += payout
        bettor["profit"] += (payout - bet["amount"])
        bettor["wins"] += 1
        bookie["profit"] -= bet["amount"]
        bookie["losses"] += 1
    
    bet["status"] = "settled"
    bet["winner"] = winner
    bet["settled_at"] = datetime.utcnow().isoformat()
    bet["auto_settled"] = True

# ==================== GAME FETCHING ====================

def fetch_live_games():
    if not ODDS_API_KEY:
        load_demo_games()
        return
    
    print("🔄 Fetching live games...")
    new_games = {}
    
    try:
        for sport in SPORTS:
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
            params = {
                'apiKey': ODDS_API_KEY,
                'regions': 'us',
                'markets': 'h2h',
                'oddsFormat': 'american',
                'dateFormat': 'iso'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for game in data:
                game_id = game['id']
                home_team = game['home_team']
                away_team = game['away_team']
                commence_time = datetime.fromisoformat(game['commence_time'].replace('Z', '+00:00'))
                
                if commence_time > datetime.now(commence_time.tzinfo):
                    new_games[game_id] = {
                        'id': game_id,
                        'home': home_team,
                        'away': away_team,
                        'sport': 'NBA' if sport == 'basketball_nba' else 'NFL',
                        'date': commence_time.strftime('%Y-%m-%d'),
                        'time': commence_time.strftime('%I:%M %p'),
                        'commence_time': game['commence_time'],
                        'status': 'upcoming',
                        'home_score': None,
                        'away_score': None
                    }
        
        if new_games:
            games_db.clear()
            games_db.update(new_games)
            print(f"✅ Loaded {len(new_games)} live games")
        else:
            load_demo_games()
            
    except Exception as e:
        print(f"❌ Error: {e}")
        load_demo_games()

def load_demo_games():
    global games_db
    games_db = {
        'demo_1': {"id": 'demo_1', "home": "Lakers", "away": "Warriors", "sport": "NBA", "date": "2026-02-12", "time": "7:30 PM", "status": "upcoming", "home_score": None, "away_score": None},
        'demo_2': {"id": 'demo_2', "home": "Celtics", "away": "Heat", "sport": "NBA", "date": "2026-02-12", "time": "8:00 PM", "status": "upcoming", "home_score": None, "away_score": None},
        'demo_3': {"id": 'demo_3', "home": "Bucks", "away": "Nets", "sport": "NBA", "date": "2026-02-13", "time": "7:00 PM", "status": "upcoming", "home_score": None, "away_score": None},
    }

def load_default_futures():
    global futures_db
    futures_db = {
        'future_1': {'id': 'future_1', 'market_name': 'NBA Championship Winner', 'sport': 'NBA', 'close_date': '2026-06-01', 'settle_date': '2026-06-30', 'status': 'open', 'options': ['Lakers', 'Celtics', 'Warriors', 'Bucks', 'Nuggets']},
        'future_2': {'id': 'future_2', 'market_name': 'Super Bowl Winner', 'sport': 'NFL', 'close_date': '2026-02-05', 'settle_date': '2026-02-09', 'status': 'open', 'options': ['Chiefs', 'Bills', 'Eagles', 'Cowboys', '49ers']}
    }

# ==================== STARTUP ====================

@app.on_event("startup")
async def startup_event():
    fetch_live_games()
    load_default_futures()
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(fetch_live_games, 'interval', hours=1)
    scheduler.add_job(fetch_live_scores, 'interval', minutes=5)  # Check scores every 5 min
    scheduler.start()
    print("🚀 BookieVerse MEGA started - games refresh hourly, scores every 5 min")

# ==================== API ROUTES ====================

@app.get("/")
def home():
    return {
        "message": "🎯 BookieVerse MEGA - Full Featured",
        "app": "/app",
        "features": [
            "hourly_currency",
            "bookie_limits",
            "parlays",
            "futures",
            "auto_settlement",
            "cancel_edit_lines",
            "live_scores",
            "bookie_profiles",
            "ratings",
            "groups",
            "follows"
        ],
        "games": len(games_db),
        "users": len(users_db),
        "groups": len(groups_db)
    }

@app.post("/api/auth/register")
def register(user: UserCreate):
    if user.username in [u["username"] for u in users_db.values()]:
        raise HTTPException(400, "Username already exists")
    
    user_id = f"user_{len(users_db) + 1}"
    users_db[user_id] = {
        "id": user_id,
        "username": user.username,
        "password": hash_password(user.password),
        "balance": STARTING_BALANCE,
        "profit": 0,
        "wins": 0,
        "losses": 0,
        "lines_created": 0,
        "last_accrual": datetime.utcnow(),
        "total_earned": 0,
        "groups": []
    }
    
    token = create_token(user_id)
    return {"token": token, "user": {"id": user_id, "username": user.username, "balance": STARTING_BALANCE}}

@app.post("/api/auth/login")
def login(user: UserCreate):
    for uid, u in users_db.items():
        if u["username"] == user.username and u["password"] == hash_password(user.password):
            apply_hourly_currency(uid)
            token = create_token(uid)
            return {"token": token, "user": {"id": uid, "username": u["username"], "balance": u["balance"], "profit": u["profit"]}}
    raise HTTPException(401, "Invalid credentials")

@app.get("/api/games")
def get_games():
    return list(games_db.values())

@app.get("/api/futures")
def get_futures():
    return list(futures_db.values())

@app.get("/api/lines")
def get_lines(token: Optional[str] = None):
    """Get lines (filtered by user's groups if applicable)"""
    user_id = verify_token(token) if token else None
    user = users_db.get(user_id) if user_id else None
    
    all_lines = [l for l in lines_db.values() if l["status"] == "open"]
    
    # If user is logged in, include private lines from their groups
    if user:
        user_groups = user.get("groups", [])
        return [l for l in all_lines if not l.get("is_private") or l.get("group_id") in user_groups]
    
    # Public lines only for non-logged in users
    return [l for l in all_lines if not l.get("is_private")]

@app.post("/api/lines")
def create_line(line: LineCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    apply_hourly_currency(user_id)
    user = users_db[user_id]
    
    if user["balance"] < line.amount:
        raise HTTPException(400, "Insufficient balance")
    
    # Validate group access if private
    if line.is_private:
        if not line.group_id:
            raise HTTPException(400, "Private lines require a group_id")
        if line.group_id not in user.get("groups", []):
            raise HTTPException(403, "You're not in this group")
    
    if line.type == "future":
        market = futures_db.get(line.game_id)
        if not market:
            raise HTTPException(404, "Future market not found")
        game_display = market['market_name']
        sport = market.get('sport', 'FUTURE')
    else:
        game = games_db.get(line.game_id)
        if not game:
            raise HTTPException(404, "Game not found")
        game_display = f"{game['away']} @ {game['home']}"
        sport = game.get('sport', 'NBA')
    
    line_id = f"line_{len(lines_db) + 1}"
    lines_db[line_id] = {
        "id": line_id,
        "bookie_id": user_id,
        "bookie_name": user["username"],
        "game_id": line.game_id,
        "game": game_display,
        "sport": sport,
        "type": line.type,
        "side": line.side,
        "value": line.value,
        "amount": line.amount,
        "odds": -110,
        "status": "open",
        "max_bettors": line.max_bettors,
        "max_bet_per_user": line.max_bet_per_user,
        "max_total_action": line.max_total_action,
        "current_bettors": 0,
        "total_action": 0,
        "is_private": line.is_private or False,
        "group_id": line.group_id,
        "created_at": datetime.utcnow().isoformat()
    }
    
    user["balance"] -= line.amount
    user["lines_created"] += 1
    
    return {"message": "Line created", "line_id": line_id}

@app.delete("/api/lines/{line_id}")
def cancel_line(line_id: str, token: str):
    """Cancel an unmatched line and refund balance"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    line = lines_db.get(line_id)
    if not line:
        raise HTTPException(404, "Line not found")
    
    if line["bookie_id"] != user_id:
        raise HTTPException(403, "Not your line")
    
    if line["status"] != "open":
        raise HTTPException(400, "Can't cancel matched line")
    
    if line["current_bettors"] > 0:
        raise HTTPException(400, "Line has bets on it")
    
    # Refund balance
    user = users_db[user_id]
    user["balance"] += line["amount"]
    
    # Remove line
    line["status"] = "cancelled"
    
    return {"message": "Line cancelled", "refunded": line["amount"]}

@app.put("/api/lines/{line_id}")
def edit_line(line_id: str, updates: LineUpdate, token: str):
    """Edit an unmatched line"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    line = lines_db.get(line_id)
    if not line:
        raise HTTPException(404, "Line not found")
    
    if line["bookie_id"] != user_id:
        raise HTTPException(403, "Not your line")
    
    if line["status"] != "open":
        raise HTTPException(400, "Can't edit matched line")
    
    if line["current_bettors"] > 0:
        raise HTTPException(400, "Line has bets on it")
    
    # Update allowed fields
    if updates.value is not None:
        line["value"] = updates.value
    if updates.amount is not None:
        # Adjust balance
        user = users_db[user_id]
        balance_diff = updates.amount - line["amount"]
        if balance_diff > 0 and user["balance"] < balance_diff:
            raise HTTPException(400, "Insufficient balance for increase")
        user["balance"] -= balance_diff
        line["amount"] = updates.amount
    if updates.max_bettors is not None:
        line["max_bettors"] = updates.max_bettors
    
    return {"message": "Line updated", "line": line}

@app.post("/api/lines/take")
def take_line(take: TakeLine, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    apply_hourly_currency(user_id)
    
    line = lines_db.get(take.line_id)
    if not line or line["status"] != "open":
        raise HTTPException(404, "Line not available")
    
    if line["bookie_id"] == user_id:
        raise HTTPException(400, "Can't bet against your own line")
    
    user = users_db[user_id]
    
    # Check limits
    if line.get("max_bettors") and line["current_bettors"] >= line["max_bettors"]:
        raise HTTPException(400, f"Line full")
    if line.get("max_bet_per_user") and line["amount"] > line["max_bet_per_user"]:
        raise HTTPException(400, f"Exceeds max bet")
    if line.get("max_total_action") and line["total_action"] + line["amount"] > line["max_total_action"]:
        raise HTTPException(400, f"Exceeds total action limit")
    if user["balance"] < line["amount"]:
        raise HTTPException(400, "Insufficient balance")
    
    bet_id = f"bet_{len(bets_db) + 1}"
    bets_db[bet_id] = {
        "id": bet_id,
        "line_id": take.line_id,
        "bookie_id": line["bookie_id"],
        "bookie_name": line["bookie_name"],
        "bettor_id": user_id,
        "bettor_name": user["username"],
        "game": line["game"],
        "game_id": line["game_id"],
        "sport": line.get("sport", "NBA"),
        "type": line["type"],
        "bookie_side": line["side"],
        "bettor_side": "away" if line["side"] == "home" else "home",
        "value": line["value"],
        "amount": line["amount"],
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    
    user["balance"] -= line["amount"]
    line["status"] = "matched"
    line["current_bettors"] += 1
    line["total_action"] += line["amount"]
    
    return {"message": "Bet placed", "bet_id": bet_id}

@app.post("/api/parlays")
def create_parlay(parlay: ParlayCreate, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    apply_hourly_currency(user_id)
    
    if len(parlay.line_ids) < 2 or len(parlay.line_ids) > 10:
        raise HTTPException(400, "Parlay needs 2-10 legs")
    
    user = users_db[user_id]
    if user["balance"] < parlay.amount:
        raise HTTPException(400, "Insufficient balance")
    
    legs = []
    for line_id in parlay.line_ids:
        line = lines_db.get(line_id)
        if not line or line["status"] != "open":
            raise HTTPException(400, f"Line {line_id} not available")
        if line["bookie_id"] == user_id:
            raise HTTPException(400, "Can't bet against your own line in parlay")
        
        legs.append({
            "line_id": line_id,
            "game": line["game"],
            "game_id": line.get("game_id"),
            "type": line["type"],
            "side": line["side"],
            "value": line["value"],
            "status": "pending"
        })
        
        line["current_bettors"] += 1
        line["total_action"] += parlay.amount / len(parlay.line_ids)
    
    multiplier = 2.5 ** len(parlay.line_ids)
    potential_payout = parlay.amount * multiplier * 0.95
    
    parlay_id = f"parlay_{len(parlays_db) + 1}"
    parlays_db[parlay_id] = {
        "id": parlay_id,
        "bettor_id": user_id,
        "bettor_name": user["username"],
        "legs": legs,
        "amount": parlay.amount,
        "potential_payout": potential_payout,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat()
    }
    
    user["balance"] -= parlay.amount
    
    return {"message": "Parlay created", "parlay_id": parlay_id, "potential_payout": potential_payout}

@app.get("/api/bets")
def get_bets(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    apply_hourly_currency(user_id)
    
    user_bets = [b for b in bets_db.values() if b["bookie_id"] == user_id or b["bettor_id"] == user_id]
    user_parlays = [p for p in parlays_db.values() if p["bettor_id"] == user_id]
    
    return {"single_bets": user_bets, "parlays": user_parlays}

@app.post("/api/bets/{bet_id}/settle")
def settle_bet(bet_id: str, winner: str, token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    bet = bets_db.get(bet_id)
    if not bet:
        raise HTTPException(404, "Bet not found")
    
    if user_id not in [bet["bookie_id"], bet["bettor_id"]]:
        raise HTTPException(403, "Not authorized")
    
    if bet["status"] != "pending":
        raise HTTPException(400, "Bet already settled")
    
    settle_bet_automatically(bet_id, winner)
    
    return {"message": "Bet settled", "winner": winner}

# ==================== BOOKIE PROFILES & RATINGS ====================

@app.get("/api/bookie/{bookie_id}/profile")
def get_bookie_profile(bookie_id: str):
    """Get detailed bookie profile with stats and ratings"""
    stats = get_bookie_stats(bookie_id)
    if not stats:
        raise HTTPException(404, "Bookie not found")
    
    return stats

@app.post("/api/bookie/rate")
def rate_bookie(rating_data: RateBookie, token: str):
    """Rate a bookie after settling a bet"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    if rating_data.rating < 1 or rating_data.rating > 5:
        raise HTTPException(400, "Rating must be 1-5")
    
    # Check if user has bet with this bookie
    user_bets = [b for b in bets_db.values() 
                 if b["bettor_id"] == user_id 
                 and b["bookie_id"] == rating_data.bookie_id 
                 and b["status"] == "settled"]
    
    if not user_bets:
        raise HTTPException(400, "You haven't bet with this bookie")
    
    rating_id = f"rating_{len(ratings_db) + 1}"
    ratings_db[rating_id] = {
        "id": rating_id,
        "bookie_id": rating_data.bookie_id,
        "user_id": user_id,
        "rating": rating_data.rating,
        "comment": rating_data.comment,
        "created_at": datetime.utcnow().isoformat()
    }
    
    return {"message": "Rating submitted"}

@app.post("/api/bookie/{bookie_id}/follow")
def follow_bookie(bookie_id: str, token: str):
    """Follow a bookie to see their lines in feed"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    if bookie_id not in users_db:
        raise HTTPException(404, "Bookie not found")
    
    if bookie_id == user_id:
        raise HTTPException(400, "Can't follow yourself")
    
    # Check if already following
    existing = [f for f in follows_db.values() 
                if f["user_id"] == user_id and f["bookie_id"] == bookie_id]
    
    if existing:
        raise HTTPException(400, "Already following")
    
    follow_id = f"follow_{len(follows_db) + 1}"
    follows_db[follow_id] = {
        "id": follow_id,
        "user_id": user_id,
        "bookie_id": bookie_id,
        "created_at": datetime.utcnow().isoformat()
    }
    
    return {"message": "Now following"}

@app.delete("/api/bookie/{bookie_id}/follow")
def unfollow_bookie(bookie_id: str, token: str):
    """Unfollow a bookie"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    follow = None
    for f in follows_db.values():
        if f["user_id"] == user_id and f["bookie_id"] == bookie_id:
            follow = f
            break
    
    if not follow:
        raise HTTPException(404, "Not following this bookie")
    
    del follows_db[follow["id"]]
    
    return {"message": "Unfollowed"}

@app.get("/api/bookie/following")
def get_following(token: str):
    """Get bookies user is following"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user_follows = [f for f in follows_db.values() if f["user_id"] == user_id]
    following = []
    
    for follow in user_follows:
        stats = get_bookie_stats(follow["bookie_id"])
        if stats:
            following.append(stats)
    
    return following

# ==================== GROUPS ====================

@app.post("/api/groups")
def create_group(group_data: GroupCreate, token: str):
    """Create a private betting group"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user = users_db[user_id]
    
    group_id = f"group_{len(groups_db) + 1}"
    groups_db[group_id] = {
        "id": group_id,
        "name": group_data.name,
        "description": group_data.description,
        "creator_id": user_id,
        "creator_name": user["username"],
        "members": [user_id],
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Add group to user's groups
    if "groups" not in user:
        user["groups"] = []
    user["groups"].append(group_id)
    
    return {"message": "Group created", "group_id": group_id}

@app.post("/api/groups/invite")
def invite_to_group(invite: GroupInvite, token: str):
    """Invite someone to your group"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    group = groups_db.get(invite.group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    
    if user_id not in group["members"]:
        raise HTTPException(403, "You're not in this group")
    
    # Find invitee
    invitee = None
    for u in users_db.values():
        if u["username"] == invite.username:
            invitee = u
            break
    
    if not invitee:
        raise HTTPException(404, "User not found")
    
    if invitee["id"] in group["members"]:
        raise HTTPException(400, "User already in group")
    
    # Add to group
    group["members"].append(invitee["id"])
    if "groups" not in invitee:
        invitee["groups"] = []
    invitee["groups"].append(invite.group_id)
    
    return {"message": f"{invite.username} added to group"}

@app.get("/api/groups")
def get_user_groups(token: str):
    """Get user's groups"""
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    user = users_db[user_id]
    user_group_ids = user.get("groups", [])
    
    user_groups = []
    for group_id in user_group_ids:
        group = groups_db.get(group_id)
        if group:
            user_groups.append({
                **group,
                "member_count": len(group["members"]),
                "is_creator": group["creator_id"] == user_id
            })
    
    return user_groups

# ==================== OTHER ROUTES ====================

@app.get("/api/leaderboard")
def leaderboard():
    sorted_users = sorted(users_db.values(), key=lambda x: x["profit"], reverse=True)
    return sorted_users[:10]

@app.get("/api/user")
def get_user(token: str):
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(401, "Invalid token")
    
    apply_hourly_currency(user_id)
    user = users_db[user_id]
    
    now = datetime.utcnow()
    last_accrual = user.get("last_accrual", now)
    seconds_until_next = 3600 - ((now - last_accrual).total_seconds() % 3600)
    
    following_count = len([f for f in follows_db.values() if f["user_id"] == user_id])
    
    return {
        "id": user["id"],
        "username": user["username"],
        "balance": user["balance"],
        "profit": user["profit"],
        "wins": user["wins"],
        "losses": user["losses"],
        "lines_created": user["lines_created"],
        "total_earned": user.get("total_earned", 0),
        "hourly_rate": HOURLY_CURRENCY,
        "next_drop_seconds": int(seconds_until_next),
        "groups": user.get("groups", []),
        "following": following_count
    }

@app.get("/app", response_class=HTMLResponse)
def serve_app():
    with open("index.html", "r") as f:
        return f.read()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
