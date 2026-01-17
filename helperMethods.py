# Cleaned helperMethods.py
# Only contains strict unit-conversion helpers

# Convert bytes to Kilo bytes
def toKB(bytes):
    return int(bytes / 1024)

# Convert bytes to Mega bytes
def toMB(bytes):
    return toKB(toKB(bytes))