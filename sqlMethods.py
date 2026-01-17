import sqlite3

DATABASE = 'database.db'

def getConnection():
    return sqlite3.connect(DATABASE)

# Create the table if it doesn't exist (Updated for TEXT IDs)
def createTable():
    conn = getConnection()
    c = conn.cursor()
    # Note: 'uid' is now TEXT to support 'dbid:...'
    c.execute('''CREATE TABLE IF NOT EXISTS files 
                 (uid TEXT, name TEXT, type TEXT, size REAL, path TEXT)''')
    conn.commit()
    conn.close()

def saveToDB(uid, names, types, sizes, paths):
    createTable() # Ensure table exists before writing
    conn = getConnection()
    c = conn.cursor()
    
    # 1. Clear old data for this user (to prevent duplicates on re-scan)
    c.execute("DELETE FROM files WHERE uid=?", (str(uid),))
    
    # 2. Bulk Insert (Much faster than a loop)
    # We zip the lists together to insert rows
    data_to_insert = []
    for i in range(len(names)):
        data_to_insert.append((str(uid), names[i], types[i], sizes[i], paths[i]))
        
    c.executemany("INSERT INTO files VALUES (?,?,?,?,?)", data_to_insert)
    
    conn.commit()
    conn.close()

def retrieveFromDB(uid, types, sizes, names, paths):
    conn = getConnection()
    c = conn.cursor()
    try:
        cursor = c.execute("SELECT * FROM files WHERE uid=?", (str(uid),))
        for row in cursor:
            # row: (uid, name, type, size, path)
            names.append(row[1])
            types.append(row[2])
            sizes.append(row[3])
            paths.append(row[4]) # <--- NEW: Capture the path
    except sqlite3.OperationalError:
        pass
    conn.close()

def searchInDB(uid, paths, sizes, keyword):
    conn = getConnection()
    c = conn.cursor()
    try:
        # standard SQL wildcard search
        cursor = c.execute("SELECT * FROM files WHERE uid=? AND name LIKE ?", (str(uid), '%' + keyword + '%'))
        for row in cursor:
            sizes.append(row[3])
            paths.append(row[4])
    except sqlite3.OperationalError:
        pass
    conn.close()

# --- Visualization Helpers (kept from original logic) ---

def getFileTypeSizes(names, sizes):
    # Aggregates sizes by file extension (e.g., .jpg, .docx)
    types_map = {}
    for i in range(len(names)):
        # Get extension
        if '.' in names[i]:
            ext = '.' + names[i].split('.')[-1].lower()
        else:
            ext = 'Unknown'
            
        if ext in types_map:
            types_map[ext] += sizes[i]
        else:
            types_map[ext] = sizes[i]
            
    return list(types_map.keys()), list(types_map.values())

def getColors(n):
    # Generates random hex colors for the chart
    import random
    colors = []
    for _ in range(n):
        color = "#%06x" % random.randint(0, 0xFFFFFF)
        colors.append(color)
    return colors