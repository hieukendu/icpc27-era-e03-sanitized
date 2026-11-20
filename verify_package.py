from pathlib import Path
import hashlib,json,sys
r=Path(__file__).resolve().parent
m=json.loads((r/"MANIFEST.json").read_text())["files_sha256"]
bad=[n for n,h in m.items() if not (r/n).is_file() or hashlib.sha256((r/n).read_bytes()).hexdigest()!=h]
print("Verified",len(m),"files. Mismatches:",bad)
sys.exit(bool(bad))
