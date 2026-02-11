# 🚀 GitHub → Render Deployment Guide

## Files You Have

- `main.py` - Backend API
- `index.html` - Frontend UI
- `requirements.txt` - Dependencies
- `README.md` - Documentation
- `.gitignore` - Git ignore rules

---

## Step 1: Create GitHub Repo (5 minutes)

### Option A: GitHub Website (Easiest)

1. Go to **https://github.com**
2. Sign in (or create account)
3. Click **"+"** (top right) → **"New repository"**
4. Name: **bookieverse**
5. Make it **Public**
6. **DON'T** add README (you already have one)
7. Click **"Create repository"**

### Option B: GitHub Desktop (If you prefer GUI)

1. Download GitHub Desktop
2. File → New Repository → "bookieverse"
3. Drag all 5 files into the repo folder
4. Commit & Publish

### Option C: Command Line (If you're comfortable)

```bash
# Create a new folder
mkdir bookieverse
cd bookieverse

# Copy all your files into this folder
# Then:

git init
git add .
git commit -m "Initial commit - BookieVerse P2P Sportsbook"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/bookieverse.git
git push -u origin main
```

---

## Step 2: Deploy to Render (5 minutes)

### 2.1 Sign Up

1. Go to **https://render.com**
2. Click **"Get Started"**
3. Sign up with **GitHub** (easiest)
4. Authorize Render to access your repos

### 2.2 Create Web Service

1. Click **"New +"** (top right)
2. Select **"Web Service"**
3. Click **"Connect account"** if needed
4. Find your **bookieverse** repo → Click **"Connect"**

### 2.3 Configure Settings

You'll see a form. Fill it out:

**Basic Settings:**
- **Name:** `bookieverse` (or whatever you want)
- **Region:** Choose closest to you
- **Branch:** `main`
- **Root Directory:** Leave blank
- **Runtime:** `Python 3`

**Build Settings:**
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Plan:**
- Select **"Free"** (first option)

### 2.4 Deploy!

1. Scroll down, click **"Create Web Service"**
2. Wait 2-3 minutes while it builds
3. You'll see logs scrolling - this is normal
4. When it says **"Live"** with a green dot → You're done!

---

## Step 3: Test Your App (2 minutes)

### 3.1 Get Your URL

At the top of the Render dashboard, you'll see:
```
https://bookieverse-XXXX.onrender.com
```

Copy that URL.

### 3.2 Open Your App

Add `/app` to the end:
```
https://bookieverse-XXXX.onrender.com/app
```

Open that in your browser.

### 3.3 Test It

1. You should see purple gradient login screen
2. Type any username
3. Click "Enter BookieVerse"
4. Should see $10,000 balance

**IT WORKS!** 🎉

---

## Step 4: Share with Friends (1 minute)

Text your friends:

```
Check out my P2P sportsbook app!
Everyone is their own bookie.

https://bookieverse-XXXX.onrender.com/app

Try it out and let me know what you think!
```

---

## Troubleshooting

### "Build failed"

**Check the logs.** Common issues:

1. **Missing requirements.txt**
   - Make sure you uploaded ALL 5 files to GitHub
   
2. **Wrong start command**
   - Should be: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Check for typos
   
3. **Python version**
   - Render uses Python 3.7+ by default
   - Our code works with all versions

### "Application error"

**Your app is running but crashing:**

1. Click **"Logs"** tab in Render
2. Look for error messages
3. Usually it's a missing file or typo

### "Site not loading"

**Did you add `/app` to the URL?**

- Wrong: `https://bookieverse.onrender.com`
- Right: `https://bookieverse.onrender.com/app`

### "Free tier sleep"

Render free tier **sleeps after 15 min of inactivity**.

First load after sleep takes 30 seconds. This is normal!

**Upgrade to $7/mo** to remove sleep (do this later when you have users).

---

## Next Steps

### This Week:
- [x] Deploy to Render
- [ ] Get 5-10 friends to test
- [ ] Collect feedback
- [ ] Fix any bugs they find

### Next Week:
- [ ] Add PostgreSQL database (Render makes this easy)
- [ ] Connect sports data API
- [ ] Add auto-settlement
- [ ] Better mobile UI

### Month 2:
- [ ] Launch publicly (Twitter, Reddit)
- [ ] Get 100+ users
- [ ] Add premium features
- [ ] Start monetization

---

## Updating Your App

Made changes to your code? Push to GitHub and Render auto-deploys:

```bash
# Make your changes, then:
git add .
git commit -m "Added new feature"
git push

# Render automatically detects the push and redeploys!
# Takes 2-3 minutes
```

Or use GitHub website:
1. Go to your repo
2. Click on a file
3. Click edit (pencil icon)
4. Make changes
5. Click "Commit changes"
6. Render auto-deploys!

---

## Render Dashboard

**Useful tabs:**

- **Logs:** See what's happening (errors, requests)
- **Metrics:** CPU, memory usage
- **Environment:** Add SECRET_KEY or other variables
- **Settings:** Change build/start commands

---

## Cost Breakdown

**Free Tier:**
- 750 hours/month (enough for 24/7 for 31 days!)
- Sleeps after 15 min inactivity
- Wakes up on request (30 sec delay)
- Perfect for testing

**Paid Tier ($7/mo):**
- Never sleeps
- Faster
- Better support
- Upgrade when you have real users

---

## FAQ

**Q: Can I use a custom domain?**
A: Yes! In Render Settings → Custom Domain. Free on all tiers.

**Q: How do I add a database?**
A: Render dashboard → New → PostgreSQL. Connects automatically.

**Q: What if I get a lot of traffic?**
A: Free tier handles ~100 concurrent users. Upgrade to $7/mo for more.

**Q: Can I see who's using my app?**
A: Check Logs tab. Or add Google Analytics to index.html.

**Q: How do I add more games?**
A: Edit `main.py`, find `games_db`, add more games. Push to GitHub.

---

## Success Checklist

- [ ] Files uploaded to GitHub
- [ ] Repo is public
- [ ] Connected repo to Render
- [ ] Build succeeded (green checkmark)
- [ ] App shows "Live"
- [ ] Opened `/app` URL
- [ ] Can create account
- [ ] Can see $10,000 balance
- [ ] Shared URL with friends

**All checked? You're live! 🚀**

---

## Need Help?

1. Check Render logs first
2. Google the error message
3. Check GitHub issues: github.com/YOUR_USERNAME/bookieverse/issues
4. Ask in Render community: community.render.com

---

**Total Time: 15 minutes from files to live app.**

Let's go! 🎯
