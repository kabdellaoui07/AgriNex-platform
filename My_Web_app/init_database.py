import os
import sys
import sqlite3
import struct
from datetime import datetime

# Import Flask app, DB, and models
from app import app, db, User, Prediction, Survey

def parse_gpkg_point(geom_bytes):
    if not geom_bytes:
        return None
    # Read header
    if len(geom_bytes) < 8:
        return None
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
    
    if len(wkb) < 5:
        return None
    byte_order = wkb[0]
    endian = '<' if byte_order == 1 else '>'
    geom_type = struct.unpack(f'{endian}I', wkb[1:5])[0]
    
    if geom_type == 1:
        if len(wkb) < 21:
            return None
        x, y = struct.unpack(f'{endian}dd', wkb[5:21])
        return x, y, 0.0
    elif geom_type == 1001 or geom_type == 21:
        if len(wkb) < 29:
            return None
        x, y, z = struct.unpack(f'{endian}ddd', wkb[5:29])
        return x, y, z
    else:
        raise ValueError(f"Unsupported geometry type: {geom_type}")

def init_database():
    print("--------------------------------------------------")
    print("AgriNex Local Database Initialization & Seeding")
    print("--------------------------------------------------")
    
    # Ensure instance folder exists for sqlite database if required
    os.makedirs('instance', exist_ok=True)
    
    with app.app_context():
        # 1. Create tables
        print("Creating all tables in SQLite (users, predictions, Survey)...")
        db.create_all()
        print("SQLAlchemy tables created successfully.")
        
        # 2. Seed users
        print("Checking default users...")
        if User.query.count() == 0:
            print("Seeding default users: admin/admin and collector/admin...")
            admin = User(username="admin", role="admin")
            admin.set_password("admin")
            
            collector = User(username="collector", role="collector")
            collector.set_password("admin")
            
            db.session.add(admin)
            db.session.add(collector)
            db.session.commit()
            print("Default users seeded successfully.")
        else:
            print("Users already exist in database.")

        # 3. Import Survey data from GPKG
        GPKG_PATH = r"C:\Users\slama phone\qyield\Projet pfe crop cereal\data.gpkg"
        if os.path.exists(GPKG_PATH):
            print(f"QGIS/Mergin Geopackage found at: {GPKG_PATH}")
            if Survey.query.count() == 0:
                print("Survey table is empty. Starting import...")
                
                try:
                    gpkg_conn = sqlite3.connect(GPKG_PATH)
                    gpkg_cur = gpkg_conn.cursor()
                    gpkg_cur.execute("SELECT fid, geom, Date, classe, Photo FROM Survey")
                    rows = gpkg_cur.fetchall()
                    print(f"Found {len(rows)} rows to import.")
                    
                    imported_count = 0
                    for row in rows:
                        fid, geom_bytes, date_val, classe, photo_path = row
                        coords = parse_gpkg_point(geom_bytes)
                        if not coords:
                            continue
                        
                        lon, lat, alt = coords
                        
                        dt = None
                        if date_val:
                            try:
                                date_clean = date_val.replace('Z', '').replace('T', ' ')
                                dt = datetime.fromisoformat(date_clean)
                            except Exception:
                                dt = None
                                
                        photo_filename = os.path.basename(photo_path) if photo_path else None
                        
                        # Instantiate SQLite Survey row
                        sv = Survey(
                            fid=fid,
                            geom=geom_bytes,
                            latitude=lat,
                            longitude=lon,
                            Date=dt,
                            classe=classe,
                            Photo=photo_filename
                        )
                        db.session.add(sv)
                        imported_count += 1
                        
                    db.session.commit()
                    print(f"Successfully imported {imported_count} survey points into database.db!")
                except Exception as e:
                    print(f"Error importing survey data: {e}")
                finally:
                    gpkg_conn.close()
            else:
                print(f"Survey table already contains {Survey.query.count()} points. Skipping import.")
        else:
            print(f"WARNING: GPKG file not found at {GPKG_PATH}. Cannot import training points.")
            
    print("--------------------------------------------------")
    print("Database initialization complete!")
    print("--------------------------------------------------")

if __name__ == "__main__":
    init_database()
