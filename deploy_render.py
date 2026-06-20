import urllib.request
import json
import time
import os
import sys
import re
import subprocess

# Helper function to send API requests to Render
def send_request(url, method="GET", headers=None, data=None):
    if headers is None:
        headers = {}
    
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            if response.status in (200, 201, 202):
                return json.loads(res_body) if res_body else {}
            else:
                print(f"Error: Received status code {response.status}")
                print(res_body)
                return None
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        print(e.read().decode("utf-8"))
        return None
    except Exception as e:
        print(f"Connection Error: {e}")
        return None

def main():
    print("====================================================")
    print(" AgriNex Cloud Deployment and APK Compiler Tool")
    print("====================================================\n")
    
    # Read API Key
    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        api_key = input("Enter your Render API Key (from Account Settings): ").strip()
        if not api_key:
            print("Error: API Key is required.")
            sys.exit(1)
            
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    
    print("\n[1] Fetching owner ID (Workspace ID)...")
    owners = send_request("https://api.render.com/v1/owners?limit=20", headers=headers)
    if not owners or len(owners) == 0:
        print("Error: Could not retrieve workspaces. Check your API key.")
        sys.exit(1)
        
    # Pick first active workspace
    owner_id = owners[0]["owner"]["id"]
    owner_name = owners[0]["owner"]["name"]
    print(f"-> Using workspace: {owner_name} ({owner_id})")
    
    # Check if database already exists
    print("\n[2] Checking existing databases...")
    existing_dbs = send_request("https://api.render.com/v1/postgres?limit=20", headers=headers)
    db_id = None
    db_status = None
    
    if existing_dbs:
        for db in existing_dbs:
            if db["postgres"]["name"] == "agrinex-db" and db["postgres"]["status"] != "suspended":
                db_id = db["postgres"]["id"]
                db_status = db["postgres"]["status"]
                print(f"-> Found existing database: agrinex-db ({db_id}) in status: {db_status}")
                break
                
    if not db_id:
        print("\n-> Creating a new PostgreSQL database (Free plan)...")
        db_payload = {
            "name": "agrinex-db",
            "ownerId": owner_id,
            "plan": "free",
            "region": "oregon",
            "version": "15"
        }
        db_res = send_request("https://api.render.com/v1/postgres", method="POST", headers=headers, data=db_payload)
        if not db_res:
            print("Error: Could not create database.")
            sys.exit(1)
        if "postgres" in db_res:
            db_res = db_res["postgres"]
        db_id = db_res["id"]
        db_status = db_res["status"]
        print(f"-> Database provisioned! ID: {db_id}")
        
    # Poll database status until available
    while db_status != "available":
        print(f"-> Waiting for database to become available (current status: {db_status})...")
        time.sleep(10)
        db_info = send_request(f"https://api.render.com/v1/postgres/{db_id}", headers=headers)
        if db_info:
            db_status = db_info["status"]
            
    print("-> Database is available!")
    
    # Fetch Connection String
    print("\n[3] Retrieving internal connection parameters...")
    conn_info = send_request(f"https://api.render.com/v1/postgres/{db_id}/connection-info", headers=headers)
    if not conn_info or "internalConnectionString" not in conn_info:
        print("Error: Could not fetch connection string.")
        sys.exit(1)
        
    db_url = conn_info["internalConnectionString"]
    print("-> Retrieved internal connection string successfully.")
    
    # Check if web service already exists
    print("\n[4] Checking existing web services...")
    existing_svcs = send_request("https://api.render.com/v1/services?limit=50", headers=headers)
    svc_id = None
    svc_url = None
    
    if existing_svcs:
        for svc in existing_svcs:
            if svc["service"]["name"] == "agrinex-platform" and svc["service"]["suspended"] == "not_suspended":
                svc_id = svc["service"]["id"]
                # Find URL
                svc_url = svc["service"].get("url") or svc["service"].get("serviceDetails", {}).get("url")
                print(f"-> Found existing web service: agrinex-platform ({svc_id}) -> {svc_url}")
                break
                
    if not svc_id:
        print("\n-> Deploying a new Flask Web Service (Free plan, Docker)...")
        svc_payload = {
            "type": "web_service",
            "name": "agrinex-platform",
            "ownerId": owner_id,
            "repo": "https://github.com/kabdellaoui07/AgriNex-platform",
            "autoDeploy": "yes",
            "branch": "main",
            "rootDir": "My_Web_app",
            "envVars": [
                {
                    "key": "DATABASE_URL",
                    "value": db_url
                },
                {
                    "key": "SECRET_KEY",
                    "value": "agrocyber_secret_glass_key_2026"
                },
                {
                    "key": "UPLOAD_FOLDER",
                    "value": "static/uploads"
                }
            ],
            "serviceDetails": {
                "runtime": "docker",
                "plan": "free"
            }
        }
        svc_res = send_request("https://api.render.com/v1/services", method="POST", headers=headers, data=svc_payload)
        if not svc_res:
            print("Error: Could not create web service.")
            sys.exit(1)
        if "service" in svc_res:
            svc_res = svc_res["service"]
        svc_id = svc_res["id"]
        svc_url = svc_res.get("url") or svc_res.get("serviceDetails", {}).get("url")
        print(f"-> Web Service created! ID: {svc_id}")
        
    # Poll Web Service URL
    while not svc_url:
        print("-> Waiting for service to deploy and assign URL...")
        time.sleep(10)
        svc_info = send_request(f"https://api.render.com/v1/services/{svc_id}", headers=headers)
        if svc_info:
            if "service" in svc_info:
                svc_info = svc_info["service"]
            svc_url = svc_info.get("url") or svc_info.get("serviceDetails", {}).get("url")
            
    print(f"-> Web Service deployed! Public URL: {svc_url}")
    
    # Update MainActivity.kt
    print("\n[5] Updating Android application with the production URL...")
    main_activity_path = "My_Mobile_app/app/src/main/java/com/example/agrinex/MainActivity.kt"
    if not os.path.exists(main_activity_path):
        print(f"Error: {main_activity_path} not found. Are you running in the repository root?")
        sys.exit(1)
        
    with open(main_activity_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Replace defaultProductionUrl
    pattern = r'(val defaultProductionUrl = ")([^"]*)(")'
    new_content, count = re.subn(pattern, rf'\1{svc_url}\3', content)
    
    # Also replace setup screen public preset button URL
    preset_pattern = r'(onClick = \{ urlText = ")([^"]*)("\s*\},\s*colors = ButtonDefaults\.buttonColors\(containerColor = ForestGreenLight, contentColor = ForestGreenDark\),\s*contentPadding = PaddingValues\(horizontal = 8\.dp, vertical = 6\.dp\),\s*modifier = Modifier\.weight\(1f\)\.padding\(start = 4\.dp\)\s*\)\s*\{\s*Text\("Public")'
    new_content, preset_count = re.subn(preset_pattern, rf'\1{svc_url}\3', new_content)
    
    with open(main_activity_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print(f"-> Updated default production URL to {svc_url} (replaces count: {count}, presets: {preset_count})")
    
    # Compile APK
    print("\n[6] Building the final signed release APK...")
    java_home = "C:\\Users\\slama phone\\AppData\\Local\\Android\\Sdk\\openjdk-17\\jdk-17.0.19+10"
    os.environ["JAVA_HOME"] = java_home
    
    try:
        gradlew_path = ".\\gradlew.bat"
        print(f"-> Running Gradle assembleRelease in My_Mobile_app...")
        result = subprocess.run(
            f"{gradlew_path} assembleRelease",
            shell=True,
            cwd="My_Mobile_app",
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("-> Compilation successful!")
            apk_path = os.path.abspath("My_Mobile_app/app/build/outputs/apk/release/app-release.apk")
            print(f"-> Final APK Location: {apk_path}")
            print("\n====================================================")
            print(" DEPLOYMENT COMPLETE & APK COMPILED SUCCESSFULLY!")
            print(f" Production URL: {svc_url}")
            print("====================================================")
        else:
            print("Error during build compiling:")
            print(result.stderr)
            print(result.stdout)
    except Exception as e:
        print(f"Error executing build command: {e}")

if __name__ == "__main__":
    main()
