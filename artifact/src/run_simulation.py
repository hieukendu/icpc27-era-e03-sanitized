"""Guard resumable simulation caches against source changes."""
from pathlib import Path
import argparse,hashlib,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--cores',type=int,default=12);a=p.parse_args()
 src=ROOT/'src/simulate_badges.R';mark=ROOT/'results/revision/simulation/source.sha256'
 h=hashlib.sha256(src.read_bytes()).hexdigest()
 if mark.exists() and mark.read_text().strip()!=h:raise SystemExit('Simulation source changed; use a new results directory, do not reuse scenario caches')
 mark.parent.mkdir(parents=True,exist_ok=True);mark.write_text(h+'\n')
 subprocess.run(['Rscript',str(src),'1000',str(a.cores)],cwd=ROOT,check=True)
if __name__=='__main__':main()
