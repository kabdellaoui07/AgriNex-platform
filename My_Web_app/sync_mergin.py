import sqlite3
import psycopg
import struct
import os
import shutil
from datetime import datetime

# Paths
GPKG_PATH = r"C:\Users\slama phone\qyield\Projet pfe crop cereal\data.gpkg"
MERGIN_DIR = r"C:\Users\slama phone\qyield\Projet pfe crop cereal"
DEST_UPLOAD_DIR = r"C:\Users\slama phone\Desktop\DL-Models\My_app\static\uploads"

PG_CONN_STRING = "postgresql://postgres:admin@localhost:5432/mygeoaidb"

def parse_gpkg_point(geom_bytes):
    if not geom_bytes:
        return None
    # Read header
    magic = geom_bytes[0:2]
    if magic != b'GP':
        raise ValueError("Not a GeoPackage geometry")
    
    version = geom_bytes[2]
    flags = geom_bytes[3]
    srid = struct.unpack('<i' if (flags & 1) else '>i', geom_bytes[4:8])[0]
    
    envelope_type = (flags & 0x0E) >> 1
    if envelope_type == 0:
        env_size = 0
    elif envelope_type == 1:
        env_size = 32
    elif envelope_type == 2:
        env_size = 48
    elif envelope_type == 3:
        env_size = 64
    else:
        raise ValueError(f"Invalid envelope type: {envelope_type}")
        
    wkb_offset = 8 + env_size
    wkb = geom_bytes[wkb_offset:]
    
    # Read WKB
    byte_order = wkb[0]
    endian = '<' if byte_order == 1 else '>'
    geom_type = struct.unpack(f'{endian}I', wkb[1:5])[0]
    
    # Check if geom_type is 1 (POINT) or 1001 (POINTZ) or 21 (POINTZ in some variants)
    if geom_type == 1:
        x, y = struct.unpack(f'{endian}dd', wkb[5:21])
        return x, y, 0.0
    elif geom_type == 1001 or geom_type == 21:
        x, y, z = struct.unpack(f'{endian}ddd', wkb[5:29])
        return x, y, z
    else:
        raise ValueError(f"Unsupported geometry type: {geom_type}")

def main():
    print("Starting synchronization...")
    os.makedirs(DEST_UPLOAD_DIR, exist_ok=True)
    
    # 1. Connect to GPKG
    gpkg_conn = sqlite3.connect(GPKG_PATH)
    gpkg_cur = gpkg_conn.cursor()
    gpkg_cur.execute("SELECT fid, geom, Date, classe, Photo FROM Survey")
    rows = gpkg_cur.fetchall()
    print(f"Found {len(rows)} rows in Mergin GPKG 'Survey' table.")
    
    # 2. Connect to PostgreSQL
    pg_conn = psycopg.connect(PG_CONN_STRING)
    pg_cur = pg_conn.cursor()
    
    # 3. Clear existing Survey table in PostgreSQL
    print("Clearing public.\"Survey\" table in PostgreSQL...")
    pg_cur.execute("TRUNCATE TABLE public.\"Survey\" RESTART IDENTITY;")
    
    # 4. Insert rows and copy images
    imported_count = 0
    copied_count = 0
    
    for row in rows:
        fid, geom_bytes, date_val, classe, photo_path = row
        coords = parse_gpkg_point(geom_bytes)
        
        if not coords:
            print(f"Skipping row {fid}: No valid geometry.")
            continue
            
        lon, lat, alt = coords
        
        # Parse date
        dt = None
        if date_val:
            try:
                date_clean = date_val.replace('Z', '').replace('T', ' ')
                dt = datetime.fromisoformat(date_clean)
            except Exception as e:
                print(f"Warning parsing date '{date_val}' for row {fid}: {e}")
                dt = None
        
        # Copy photo if exists
        photo_filename = None
        if photo_path:
            photo_filename = os.path.basename(photo_path)
            src_photo = os.path.join(MERGIN_DIR, photo_filename)
            
            if os.path.exists(src_photo):
                dest_photo = os.path.join(DEST_UPLOAD_DIR, photo_filename)
                if not os.path.exists(dest_photo):
                    shutil.copy2(src_photo, dest_photo)
                    copied_count += 1
            else:
                # Handle Snapchat- prefix mismatch (replaces Snapchat- with img-)
                if photo_filename.startswith("Snapchat-"):
                    alt_filename = photo_filename.replace("Snapchat-", "img-")
                    alt_src = os.path.join(MERGIN_DIR, alt_filename)
                    if os.path.exists(alt_src):
                        dest_photo = os.path.join(DEST_UPLOAD_DIR, photo_filename)
                        if not os.path.exists(dest_photo):
                            shutil.copy2(alt_src, dest_photo)
                            copied_count += 1
                            print(f"Mapped Snapchat image: {alt_filename} -> {photo_filename}")
                else:
                    found = False
                    for f in os.listdir(MERGIN_DIR):
                        if f.lower() == photo_filename.lower():
                            shutil.copy2(os.path.join(MERGIN_DIR, f), os.path.join(DEST_UPLOAD_DIR, f))
                            photo_filename = f
                            copied_count += 1
                            found = True
                            break
                    if not found:
                        print(f"Warning: Photo '{photo_filename}' not found in Mergin directory for row {fid}.")
        
        # Insert into PostgreSQL
        pg_cur.execute(
            """
            INSERT INTO public."Survey" (fid, geom, "Date", classe, "Photo")
            VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s, %s), 4326), %s, %s, %s)
            """,
            (fid, lon, lat, alt, dt, classe, photo_filename)
        )
        imported_count += 1
        
    pg_conn.commit()
    pg_conn.close()
    gpkg_conn.close()
    
    print(f"Synchronization complete!")
    print(f"Imported {imported_count} points into PostgreSQL.")
    print(f"Copied {copied_count} new images to static/uploads.")

if __name__ == "__main__":
    main()
