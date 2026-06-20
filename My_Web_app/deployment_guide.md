# AgriNex Cloud Deployment Guide

This guide details how to deploy the **AgriNex** backend web application and its PostgreSQL database to the cloud (specifically using **Render** or **Railway**), making it continuously available for the Android mobile application from anywhere.

---

## 📂 Deployment Architecture
- **Web App Service**: Python/Flask container running on Gunicorn, built automatically via `Dockerfile`.
- **Database Service**: PostgreSQL instance to store users, crop disease predictions, and GIS survey points.
- **Persistent Disk Storage**: Mounted volume (`/data`) to ensure crop images uploaded by field collectors are kept permanently.

---

## 🚀 Option A: Deploying on Render (Recommended)

### 1. Deploy the Database (PostgreSQL)
1. Go to the [Render Dashboard](https://dashboard.render.com/) and log in.
2. Click **New +** and select **PostgreSQL**.
3. Fill in the database details:
   - **Name**: `agrinex-db`
   - **Database Name**: `mygeoaidb`
   - **User**: `postgres`
4. Choose the **Free** tier (or paid for production).
5. Click **Create Database**.
6. Once created, copy the **Internal Database URL** (for connection between Render services) or **External Database URL** (for local testing/migration).

### 2. Deploy the Web Service
1. Push your backend code (`My_Web_app` folder) to a GitHub repository (private or public).
2. On Render, click **New +** and select **Web Service**.
3. Connect your GitHub repository.
4. Set the following configuration:
   - **Name**: `agrinex-platform`
   - **Region**: Choose the closest region to your users.
   - **Runtime**: `Docker` (Render will automatically detect the `Dockerfile`).
5. Scroll down to **Instance Type** and select **Free** (or a higher tier).
6. Click **Advanced** to set up Environment Variables and Disk Storage.

### 3. Add Environment Variables
Under the **Environment Variables** section, add:
* `DATABASE_URL`: Set this to the **Internal Database URL** of the PostgreSQL database created in Step 1.
* `SECRET_KEY`: Set this to a secure random string (e.g., `your_custom_secure_secret_2026`).
* `UPLOAD_FOLDER`: `/data/uploads` (This routes image uploads to the persistent disk).

### 4. Mount a Persistent Disk (Crucial for Image Storage)
To keep crop photos from disappearing when the service restarts:
1. In the Web Service settings, go to the **Disks** section.
2. Click **Add Disk**.
3. Set the following properties:
   - **Name**: `agrinex-uploads`
   - **Mount Path**: `/data`
   - **Size**: `1 GB` (or larger depending on your needs).
4. Click **Save**. Render will redeploy your web service and link this directory to a persistent SSD volume.

---

## 🚀 Option B: Deploying on Railway

### 1. Initialize Project & DB
1. Log in to [Railway](https://railway.app/).
2. Click **New Project** -> **Provision PostgreSQL**.
3. Railway will provision a database instance.

### 2. Deploy Web Service
1. Click **New** -> **GitHub Repo** and choose your repository.
2. Railway will automatically recognize the `Dockerfile` and start building.

### 3. Configure Variables & Volume
1. Under your service's **Variables** tab, click **New Variable**:
   - Reference the database by adding: `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (Railway automatically fills this).
   - Add `SECRET_KEY` = `your_custom_secure_secret_2026`.
   - Add `UPLOAD_FOLDER` = `/data/uploads`.
2. Under **Settings** -> **Volumes**:
   - Click **Add Volume**.
   - **Mount Path**: `/data`.
   - Click **Save**.

---

## 🔌 Connecting the Android Application

Once the web service is deployed, Render or Railway will give you a public URL (e.g., `https://agrinex-platform.onrender.com` or `https://agrinex.up.railway.app`).

1. Open `C:\Users\slama phone\Desktop\DL-Models\My_Mobile_app\app\src\main\java\com\example\agrinex\MainActivity.kt`.
2. Update the `DEFAULT_PRODUCTION_URL` constant with your deployed server's URL.
3. Build and package the release APK.
