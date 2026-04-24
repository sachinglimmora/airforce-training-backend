# Render Deployment Guide: Aegis Backend (Simple)

Don't worry about "Docker"—Render handles all the technical container stuff for you. You just need to connect your GitHub account and set up the settings below.

---

## 1. Setup the Database & Redis
1. **Create Database**: Go to **Dashboard** -> **New** -> **PostgreSQL**. Name it `aegis-db`.
2. **Create Redis**: Go to **Dashboard** -> **New** -> **Redis**. Name it `aegis-redis`.
3. Keep these tabs open; you'll need the **Internal URLs** in Step 2.

---

## 2. Connect your Code
1. Go to **Dashboard** -> **New** -> **Web Service**.
2. Select your GitHub repository.
3. **Important Settings**:
   - **Name**: `aegis-api`
   - **Region**: Choose one closest to you (e.g., Singapore or Oregon).
   - **Environment**: Select **Docker**. (Render will automatically find the file I updated for you).
   - **Dockerfile Path**: `server/docker/Dockerfile`
   - **Docker Context**: `server`

---

## 3. Set your Environment Variables
Click **Advanced** -> **Add Environment Variable**. This is the most important part!

| Key | Value | Where to find it |
| :--- | :--- | :--- |
| `ENV` | `production` | Just type this |
| `DATABASE_URL` | `postgres://...` | Copy from your Render Database tab |
| `REDIS_URL` | `redis://...` | Copy from your Render Redis tab |
| `CELERY_BROKER_URL` | `redis://...` | Same as Redis URL |
| `CELERY_RESULT_BACKEND` | `redis://...` | Same as Redis URL |
| `GEMINI_API_KEY` | `[YOUR_KEY]` | Your Google AI Key |
| `CORS_ALLOWED_ORIGINS` | `*` | Or your frontend URL if you have one |
| `JWT_PRIVATE_KEY_PATH` | `/app/etc/secrets/jwt_private.pem` | I've set this up for you |
| `JWT_PUBLIC_KEY_PATH` | `/app/etc/secrets/jwt_public.pem` | I've set this up for you |

---

## 4. Add Security Keys (Secret Files)
In the **Environment** tab on Render, scroll down to **Secret Files**:
1. Click **Add Secret File**.
2. Filename: `jwt_private.pem` -> Paste your private key content.
3. Click **Add Secret File** again.
4. Filename: `jwt_public.pem` -> Paste your public key content.

*Render will place these files in `/app/etc/secrets/` inside the server automatically.*

---

## 5. What happens next?
Once you click **Create Web Service**, Render will:
1. Build your "Docker" container automatically (you don't have to do anything).
2. Run your database migrations automatically (I added a script for this).
3. Start your API.

If you see a green "Live" badge, your API is ready!
