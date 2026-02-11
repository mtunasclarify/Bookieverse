# 🎯 BookieVerse - P2P Sportsbook

## What is This?

A peer-to-peer sportsbook where **users are their own bookies**. Set your own lines, take action from others, compete for profit. We take 5% rake on every settled bet.

**Demo:** [Your Render URL will go here]

## Features

- 🏦 **Be the Bookie** - Set your own spreads, moneylines, totals
- 🎯 **Take Action** - Bet against other users' lines
- 📊 **Track Performance** - Win/loss records, profit/loss tracking
- 🏆 **Leaderboard** - Compete for top profit
- 💰 **$10,000 Play Money** - Start betting immediately

## Quick Deploy to Render (FREE)

### Step 1: Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bookieverse.git
git push -u origin main
```

### Step 2: Deploy on Render

1. Go to **https://render.com**
2. Sign up with GitHub
3. Click **"New +"** → **"Web Service"**
4. Connect your **bookieverse** repository
5. Settings:
   - **Name:** bookieverse
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Click **"Create Web Service"**

### Step 3: It's Live!

Your app will be at: `https://bookieverse-XXXX.onrender.com/app`

---

## Local Development

### Prerequisites

- Python 3.8+
- pip

### Setup

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/bookieverse.git
cd bookieverse

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

Open http://localhost:8000/app

---

## Project Structure

```
bookieverse/
├── main.py              # FastAPI backend + API routes
├── index.html           # Frontend UI
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

---

## API Endpoints

### Authentication
- `POST /api/auth/register` - Create new account
- `POST /api/auth/login` - Login

### Lines
- `GET /api/lines` - Get all open lines
- `POST /api/lines` - Create a new line (requires auth)
- `POST /api/lines/take` - Take a line (requires auth)

### Bets
- `GET /api/bets` - Get user's bets (requires auth)
- `POST /api/bets/{bet_id}/settle` - Settle a bet (requires auth)

### Other
- `GET /api/games` - Get available games
- `GET /api/leaderboard` - Get top users by profit
- `GET /api/user` - Get current user info (requires auth)

Full API docs at: `/docs`

---

## Environment Variables

Optional environment variables:

```bash
SECRET_KEY=your-secret-key-here
PORT=8000
```

---

## Tech Stack

- **Backend:** FastAPI (Python)
- **Frontend:** Vanilla JavaScript + HTML/CSS
- **Database:** In-memory (for beta testing)
- **Hosting:** Render.com (free tier)

---

## Roadmap

### Phase 1: Beta Testing (This Week) ✅
- [x] Core betting functionality
- [x] User accounts
- [x] Leaderboard
- [x] Deploy to Render

### Phase 2: Production (Next Week)
- [ ] PostgreSQL database
- [ ] Real sports data API
- [ ] Auto-settlement system
- [ ] Mobile responsive improvements

### Phase 3: Scale (Month 2)
- [ ] Mobile app (React Native)
- [ ] Push notifications
- [ ] Advanced analytics
- [ ] Tournament system

---

## Contributing

1. Fork the repo
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - feel free to use this for your own projects!

---

## Support

- **Issues:** https://github.com/YOUR_USERNAME/bookieverse/issues
- **Twitter:** @yourhandle
- **Email:** your@email.com

---

## Acknowledgments

Built with ❤️ by [Your Name]

Inspired by the idea that everyone should be able to be their own bookie.

---

## Legal

This is a **play money** betting platform for entertainment purposes only. No real money gambling is involved. Users receive virtual currency ($10,000 play money) to bet with.

If you plan to add real money betting, consult with legal counsel about gambling licenses in your jurisdiction.
