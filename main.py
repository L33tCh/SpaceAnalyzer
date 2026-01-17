import os
import pickle
import dropbox
from dropbox import DropboxOAuth2Flow
from flask import Flask, request, session, redirect, render_template, url_for
from sqlMethods import saveToDB, retrieveFromDB, searchInDB, getFileTypeSizes, getColors
from helperMethods import toMB

# --- CONFIGURATION ---
APP_KEY = ''       # <--- PASTE YOUR KEY HERE
APP_SECRET = '' # <--- PASTE YOUR SECRET HERE
CHECKPOINT_FILE = "scan_checkpoint.pkl"

app = Flask(__name__)
app.secret_key = os.urandom(24)

def aggregate_folder_sizes(paths, sizes):
    folder_map = {}
    
    for path, size in zip(paths, sizes):
        # Only process files (folders have size 0 in our DB usually)
        if size > 0:
            # Dropbox paths look like: /Photos/Holiday/img.jpg
            # We want to add this file's size to:
            # 1. /Photos/Holiday
            # 2. /Photos
            
            # Split path into parts, ignoring empty start
            parts = path.split('/')[1:] 
            
            # Remove filename (last part)
            parts = parts[:-1]
            
            # Reconstruct cumulative paths
            current_path = ""
            for part in parts:
                current_path += "/" + part
                if current_path in folder_map:
                    folder_map[current_path] += size
                else:
                    folder_map[current_path] = size
                    
    # Convert to list [('/Photos', 1024), ...]
    return list(folder_map.items())

def human_readable_size(size_kb):
    if size_kb < 1024:
        return f"{size_kb:.0f} KB"
    elif size_kb < 1024 * 1024:
        return f"{size_kb / 1024:.1f} MB"
    else:
        return f"{size_kb / (1024 * 1024):.2f} GB"

# Helper: Get a distinct Dropbox client
def get_dbx():
    if 'oauth_token' in session:
        return dropbox.Dropbox(
            oauth2_refresh_token=session['oauth_token'].get('refresh_token'),
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            oauth2_access_token=session['oauth_token'].get('access_token')
        )
    return None

def spaceUsage():
    try:
        client = get_dbx() 
        if not client: return 0, 0
        
        usage = client.users_get_space_usage()
        used = usage.used
        
        if usage.allocation.is_individual():
            total = usage.allocation.get_individual().allocated
        else:
            total = usage.allocation.get_team().allocated
            
        return toMB(used), toMB(total - used)
    except Exception as e:
        print(f"Space Usage Error: {e}")
        return 0, 0

# --- ROUTES ---

@app.route('/')
def index():
    has_checkpoint = os.path.exists(CHECKPOINT_FILE)
    if 'oauth_token' in session:
        return render_template('index.html', logged_in=True, checkpoint_exists=has_checkpoint)
    return render_template('index.html', logged_in=False, checkpoint_exists=False)

@app.route('/login')
def login():
    flow = DropboxOAuth2Flow(
        consumer_key=APP_KEY,
        consumer_secret=APP_SECRET,
        redirect_uri=url_for('oauth_callback', _external=True),
        session=session,
        csrf_token_session_key='dropbox-auth-csrf-token',
        token_access_type='offline'
    )
    return redirect(flow.start())

@app.route('/oauth_callback')
def oauth_callback():
    try:
        flow = DropboxOAuth2Flow(
            consumer_key=APP_KEY,
            consumer_secret=APP_SECRET,
            redirect_uri=url_for('oauth_callback', _external=True),
            session=session,
            csrf_token_session_key='dropbox-auth-csrf-token',
            token_access_type='offline'
        )
        oauth_result = flow.finish(request.args)
        
        session['oauth_token'] = {
            'access_token': oauth_result.access_token,
            'refresh_token': oauth_result.refresh_token,
            'uid': oauth_result.account_id
        }
        session["userID"] = oauth_result.account_id
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Auth Error: {e}")
        return f"Auth error: {e}"

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/process')
def process():
    if 'oauth_token' not in session:
        return redirect(url_for('login'))
    
    # --- 1. DISPLAY LOGIC ---
    if request.args.get('analyze') is not None:
        names = []; types = []; sizes = []; paths = [] # <--- Added paths list
        
        # Call updated function with 'paths'
        retrieveFromDB(session["userID"], types, sizes, names, paths)
        
        used, free = spaceUsage()
        
        # --- File Types Chart Data ---
        types_list, totalSizes = getFileTypeSizes(names, sizes)
        colors = getColors(len(types_list))
        file_type_data = sorted(zip(totalSizes, colors, types_list), reverse=True)[:20]
        
        # --- NEW: Folder Size Logic ---
        folder_sizes = aggregate_folder_sizes(paths, sizes)
        
        # Sort by Size (Largest First) and take Top 15
        folder_sizes.sort(key=lambda x: x[1], reverse=True)
        top_folders = folder_sizes[:15]
        
        # Format for Template: (Name, Size, Color)
        # We reuse getColors to generate random colors for folders
        folder_colors = getColors(len(top_folders))
        folder_data = []
        for i, (path, size) in enumerate(top_folders):
            # Pass tuple: (Path, Size, Color)
            folder_data.append((path, size, folder_colors[i]))

        return render_template("analysis.html", 
                             used=used, free=free, 
                             rows=file_type_data, 
                             folder_rows=folder_data) # <--- Pass new data

    elif request.args.get('list') is not None:
        names = []; types = []; sizes = []; paths = []
        retrieveFromDB(session["userID"], types, sizes, names, paths)
        
        # Update sorting to handle the new path list (optional, but good for consistency)
        combined = list(zip(types, sizes, names))
        combined.sort(key=lambda x: x[1], reverse=True)
        
        final_data = []
        for t, s, n in combined:
            final_data.append((t, human_readable_size(s), n))
            
        return render_template("files.html", data=final_data)
    
    elif request.args.get('filesearch') is not None:
        return render_template("search.html")

    # --- 2. SCANNING LOGIC ---
    dbx = get_dbx()
    resume = False
    initial_entries = None
    
    if os.path.exists(CHECKPOINT_FILE):
        print("Found previous scan checkpoint. Resuming...")
        resume = True
    else:
        print("Starting fresh scan...")
        try:
            res = dbx.files_list_folder('')
            initial_entries = res.entries
            while res.has_more:
                res = dbx.files_list_folder_continue(res.cursor)
                initial_entries.extend(res.entries)
        except dropbox.exceptions.AuthError:
            return redirect(url_for('login'))

    names, types, sizes, paths = BFS_with_resume(dbx, initial_entries, resume=resume)

    saveToDB(session["userID"], names, types, sizes, paths)
    
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    return redirect(url_for('process', analyze='true'))

@app.route('/load-partial')
def load_partial():
    if not os.path.exists(CHECKPOINT_FILE):
        return "No checkpoint found. <a href='/'>Go Home</a>"

    print("Loading partial scan from checkpoint...")
    with open(CHECKPOINT_FILE, 'rb') as f:
        data = pickle.load(f)

    # Note: 'session["userID"]' relies on user being logged in. 
    # If session expired, this might fail, but @app.route('/login') handles that flow.
    if "userID" not in session:
         return redirect(url_for('login'))

    saveToDB(session["userID"], data['names'], data['types'], data['sizes'], data['paths'])
    return redirect(url_for('process', analyze='true'))

# --- SCANNING ENGINE ---
def BFS_with_resume(dbx, initial_entries=None, resume=False):
    names = []; types = []; sizes = []; paths = [];
    queue_paths = [] 
    
    if resume and os.path.exists(CHECKPOINT_FILE):
        print("[Resume] Loading checkpoint...")
        with open(CHECKPOINT_FILE, 'rb') as f:
            data = pickle.load(f)
            names = data['names']; types = data['types']; sizes = data['sizes']
            paths = data['paths']; queue_paths = data['queue']
            print(f"[Resume] Resumed with {len(names)} files.")
    else:
        if initial_entries:
            for entry in initial_entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    names.append(entry.name)
                    paths.append(entry.path_display)
                    sizes.append(entry.size / 1024)
                    types.append("File")
                elif isinstance(entry, dropbox.files.FolderMetadata):
                    types.append("Folder")
                    names.append(entry.name)
                    paths.append(entry.path_display)
                    sizes.append(0)
                    queue_paths.append(entry.path_lower)

    processed_count = 0
    while queue_paths:
        current_path = queue_paths.pop(0)
        processed_count += 1

        if processed_count % 100 == 0:
            print(f"Scanning... {len(names)} files found. (Queue: {len(queue_paths)})")
            with open(CHECKPOINT_FILE, 'wb') as f:
                pickle.dump({'names': names, 'types': types, 'sizes': sizes, 'paths': paths, 'queue': queue_paths}, f)

        try:
            result = dbx.files_list_folder(current_path)
            def process_batch(entries):
                for entry in entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        names.append(entry.name)
                        paths.append(entry.path_display)
                        sizes.append(entry.size / 1024)
                        types.append("File")
                    elif isinstance(entry, dropbox.files.FolderMetadata):
                        names.append(entry.name)
                        paths.append(entry.path_display)
                        sizes.append(0)
                        types.append("Folder")
                        queue_paths.append(entry.path_lower)

            process_batch(result.entries)
            while result.has_more:
                result = dbx.files_list_folder_continue(result.cursor)
                process_batch(result.entries)
        except dropbox.exceptions.ApiError as e:
            print(f"Skipping {current_path}: {e}")

    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    return names, types, sizes, paths

if __name__ == "__main__":
    app.run(debug=True)