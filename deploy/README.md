# Running Funding Radar on a VPS

```
your browser ──HTTPS──▶ Caddy :443 ──▶ website 127.0.0.1:8787 ──▶ API 127.0.0.1:8000 ──▶ Supabase
```

Only Caddy is public. The website and the API listen on `127.0.0.1`, so they can't be reached from the internet
directly. The browser never calls the API itself; the website forwards requests to it.

Production sign-in cookies are `Secure`, so the site must be opened over **HTTPS** (or via `localhost`
through an SSH tunnel). Opening `http://VPS_IP:8787` directly signs you in and then bounces you back to the
sign-in page.

Assumes Ubuntu/Debian and the project at `/opt/funding-radar`. Replace `YOUR_USER` with your Linux user.

## 1. Copy the project

Copy the repository to `/opt/funding-radar`, using git or WinSCP. Leave out `venv/`, `node_modules/`, `dist/`
and `.wrangler/`. The `.env` files are not in git, so create them on the server (steps 2 and 3).

## 2. API

```bash
sudo apt install -y python3-venv
cd /opt/funding-radar
python3 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
nano backend/.env        # same values as your local backend/.env
backend/venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000   # test, then Ctrl+C
```

## 3. Website

Requires Node.js 22.13 or newer (for example from https://github.com/nodesource/distributions).

```bash
cd /opt/funding-radar/startup-dashboard
nano .env
#   SUPABASE_URL=https://<project>.supabase.co
#   SUPABASE_ANON_KEY=<anon key>
#   FASTAPI_URL=http://127.0.0.1:8000
npm ci
npm run build
npm start                # listens on 127.0.0.1:8787; test, then Ctrl+C
```

Run `npm run build` again after every frontend code change.

## 4. Keep both running (systemd)

Edit `YOUR_USER`, the paths, and the node path (`which node`) in the two `.service` files, then:

```bash
sudo cp deploy/funding-radar-api.service deploy/funding-radar-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now funding-radar-api funding-radar-web
systemctl status funding-radar-api funding-radar-web
journalctl -u funding-radar-web -f          # logs
```

## 5. Open it from your computer

**Option A: just you, no domain (SSH tunnel).** On your PC:

```powershell
ssh -L 8787:127.0.0.1:8787 YOUR_USER@VPS_IP
```

Keep that window open and browse to http://localhost:8787 in Chrome, Edge or Firefox.

**Option B: a real address for you and your team (domain + HTTPS).**

1. Point a domain or subdomain at the VPS with an `A` record to the VPS IP. A free DuckDNS name also works.
2. Install Caddy (https://caddyserver.com/docs/install), put your domain in `deploy/Caddyfile`, then run:
   ```bash
   sudo cp deploy/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
   ```
3. Open only SSH and web ports:
   ```bash
   sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
   ```
4. In Supabase, go to **Authentication → URL Configuration** and set **Site URL** to `https://your-domain`, so
   "Create account" confirmation emails link to the right place.

Then browse to `https://your-domain`.

## Website on Vercel, API on the VPS

Vercel runs the website, so it can't reach an API listening on the VPS's `127.0.0.1`. Give the API its own HTTPS
address instead. Every API route except `/health` requires a signed-in user.

1. On the VPS, do steps 2 and 4 for the API only (`funding-radar-api`).
2. Point a subdomain such as `api.your-domain` at the VPS, enable the API block in `deploy/Caddyfile`, and open
   ports 80 and 443 (step 5B, items 2 and 3).
3. In Vercel, go to **Project → Settings**:
   - **Root Directory:** `startup-dashboard`
   - **Environment Variables:** `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `FASTAPI_URL=https://api.your-domain`
   - Redeploy.
4. In Supabase, set **Site URL** to your Vercel address (step 5B, item 4).

`startup-dashboard/vercel.json` and `vite.config.ts` already handle the Vercel build itself.

## Updating

```bash
cd /opt/funding-radar && git pull
backend/venv/bin/pip install -r backend/requirements.txt && sudo systemctl restart funding-radar-api
cd startup-dashboard && npm ci && npm run build && sudo systemctl restart funding-radar-web
```
