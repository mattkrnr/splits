# Splits

Personal fitness dashboard: Garmin runs, other activities and sleep, plus Fitbod lifting history.

- **App:** static page on GitHub Pages (`index.html`) with Google sign-in. Works on phone and desktop. On iPhone, add it to the home screen.
- **Data:** Supabase, in the shared **Personal** project, in tables prefixed `splits_`. Row-level security means each signed-in person sees only their own rows.
- **Garmin:** a GitHub Action (`.github/workflows/garmin-sync.yml`) pulls the last 3 days every morning. It uses a **sync token** that can only add your fitness rows. It can't read anything, and it can't touch other apps' tables.
- **Fitbod:** export the CSV in Fitbod and upload it in the app.

Everything stays within free tiers: GitHub Pages and Actions are free for public repos, and the data is a few MB.

## Setup

The database is already set up (see `supabase/migrations/`), and `config.js` already points at it.

### 1. Turn on GitHub Pages
In the repo, go to **Settings → Pages → Build and deployment**, choose *Deploy from a branch*, then `main` and `/ (root)`. The site goes live at `https://mattkrnr.github.io/splits/`.

### 2. Google sign-in (one time for the Personal project)
Skip to step 6 if Google sign-in is already set up on the Personal project for another app.

1. Go to console.cloud.google.com and create a project named **Personal apps**.
2. Open **Google Auth Platform** (the OAuth consent screen) and fill in an app name and your email. Audience: **External**. Leave it in **Testing**, and add your own Gmail under **Test users**. Only test users can sign in, which keeps everyone else out.
3. Go to **Clients → Create client**, choose **Web application**, and enter:
   - Authorized JavaScript origins: `https://mattkrnr.github.io`
   - Authorized redirect URIs: `https://lvaxrikegqknfkzrvmbr.supabase.co/auth/v1/callback`
4. Copy the **Client ID** and **Client secret**.
5. In Supabase (Personal project), go to **Authentication → Sign In / Providers → Google**. Turn it on, paste the client ID and secret, and save.
6. In Supabase, go to **Authentication → URL Configuration**. Under **Redirect URLs**, add `https://mattkrnr.github.io/splits/**`. If **Site URL** is still the default, set it to `https://mattkrnr.github.io`.

### 3. Sign in and make a sync token
Open the site, sign in with Google, go to the **Connect** tab, and tap **Create sync token**. Copy it right away, because it's shown only once.

### 4. Repo secrets
Go to **Settings → Secrets and variables → Actions → New repository secret** and add two secrets:

| Name | Value |
| --- | --- |
| `GARMIN_PERSONAL_API_KEY` | Your Garmin Personal API key (connect.garmin.com → Settings → Personal API) |
| `SPLITS_SYNC_TOKEN` | The token from step 3 |

### 5. First Garmin pull
Go to **Actions → Garmin sync → Run workflow**, set days to `365`, and run it. When it finishes, open the run and copy the lines that start with `activity fields` and `sleep fields` to Claude, to confirm the sleep mapping. These logs are public, so they contain only counts and field names, never your data.

### 6. On your phone
Open the site in Safari, then **Share → Add to Home Screen**.

## Things to know
- **Scheduled runs pause after 60 days without commits.** GitHub disables scheduled workflows in public repos when the repo has had no commits for 60 days. GitHub emails you first, and you re-enable it from the Actions tab.
- **The Garmin key expires** after the period you chose. Make a new key and update `GARMIN_PERSONAL_API_KEY`.
- **A new sync token replaces the old one.** If you make a new token, update `SPLITS_SYNC_TOKEN` right after.
- **Free Supabase projects pause after a week of low activity.** The daily sync writes every day, which should keep the Personal project awake.
- **If the Action can't reach Garmin** (Garmin may block cloud servers), run `garmin_pull.py` on your own computer or in a-Shell on iPhone and upload `garmin.json` from the Connect tab:
  ```
  python3 garmin_pull.py --save-key    # once
  python3 garmin_pull.py --days 90
  ```

## Data for analysis
Read these views, not the raw tables. They de-duplicate across Garmin and Fitbod, so nobody needs to know the rule:

| View | What it holds |
| --- | --- |
| `splits_activities_all` | Every Garmin activity, plus Fitbod runs that aren't on Garmin (`source` = `garmin` or `fitbod`) |
| `splits_strength_sets` | Fitbod sets without runs. `weight_lb` is per dumbbell; `multiplier` 2 = a pair, 0 = timed set |
| `splits_sleep_nights` | Garmin sleep per night (about the last year) |
| `splits_body_notes` | How your body feels: your words, area tags (`plantar_fascia`, `calves`, `it_band`, `hips`, ...), pain 0–10, and whether it was during/after a run or lift. `workouts` lists the linked workouts: `garmin:<activity id>` (matches `splits_activities_all.id` where `source = 'garmin'`), `fitbod_run:<start time>` and `fitbod_lift:<YYYY-MM-DD>` (a Fitbod session day) |

**Duplicate rule** (in `supabase/migrations/*_splits_dedup_views.sql`): Fitbod copies runs from the watch, often twice. A Fitbod run is the same run as a Garmin run if it starts within 15 minutes of it, or within 3 hours at a distance within 10%. Fitbod rows with the same start time and a distance within 2% count once. Exercise names are matched as whole words, so "Crunches" is not a run. The raw tables `splits_activities` and `splits_lift_sets` keep everything as imported.

## Weekly plan rules (Body tab and Today)
- **Equipment:** no gym, no pool, no easy bike access. Swaps are walks or the home session, never bike or swim.
- **Current level per area:** the latest note naming it in the last 7 days, easing 1 point every 2 days. A newer "feeling good" note eases it 1 more point. Decimal scores like 8.5/10 round to whole numbers.
- **Grouping:** foot = plantar fascia, calves, shins; hip = IT band, hips, knees.
- **Run days (Mon/Wed/Fri):**
  - Foot 6+: no running; do the home session, plus an easy walk only if the foot stays at 3/10 or less.
  - Hip 6+: an easy 30–45 min walk instead of running.
  - Worst level 4–5: a short flat run (1–2 mi) if your first steps feel 3/10 or less, otherwise a 30–40 min walk.
  - Worst level 1–3: an easy ~3 mi run on a flat or soft surface.
  - Nothing flagged: an easy ~3 mi run, with strides on Wednesday.
  - Less than 6 h of sleep shortens today's run.
- **Upper body Tue/Thu (Fitbod):** always kept. Skip leg work while the lower body is flagged.
- **After-work home session (30 min max, every day, optional on weekends):**
  - Blocks: foot & calf, hips (tight from sitting), and no-equipment leg strength.
  - Ordered by what hurts most and trimmed to fit 30 minutes.
  - Heel and leg loading only appears when the foot is calm enough.
- These are simple rules, not medical advice.
