import os, zlib, tkinter as tk
from tkinter.filedialog import askopenfilename

tk.Tk().withdraw()
path = askopenfilename(filetypes=[("PKG Files", "*.pkg"), ("All Files", "*.*")])
if not path: exit()

d = open(path, 'rb').read()
if d[:4] != b'pkg\x00': exit(print("Invalid PKG!"))

out_dir = f"Extracted_{os.path.basename(path).replace('.','_')}"
os.makedirs(out_dir, exist_ok=True)

# Grab the first filename from the Global Header (Offset 48 to 80)
name = d[48:80].split(b'\x00')[0].decode('ascii', 'ignore').strip() or "f0.bin"

# Read the file count (Offset 8 to 12) and loop through the TOC
for i in range(int.from_bytes(d[8:12], 'little')):
    e = d[80+i*52 : 132+i*52] # Grab the 52-byte entry
    
    # Size is Compressed Size (bytes 8-12) OR Uncompressed Size (bytes 4-8)
    sz = int.from_bytes(e[8:12], 'little') or int.from_bytes(e[4:8], 'little')
    off = int.from_bytes(e[12:16], 'little')
    
    if sz and 0 < off < len(d):
        fd = d[off : off+sz]
        safe_name = "".join(c for c in name if c.isalnum() or c in "._-/\\")
        
        # Inline if/else to check for GZIP magic, decompress, and fallback on failure
        try: out_data = zlib.decompressobj(31).decompress(fd) if fd[:3] == b'\x1f\x8b\x08' else fd
        except: out_data = fd
        
        with open(os.path.join(out_dir, safe_name), 'wb') as f: f.write(out_data)
        print(f"[+] Extracted: {safe_name}")
        
    # Queue up the filename for the NEXT file (bytes 20-52)
    name = e[20:52].split(b'\x00')[0].decode('ascii', 'ignore').strip() or f"f{i+1}.bin"

input(f"\n[!] Success! Extracted to {out_dir}\nPress Enter to exit...")