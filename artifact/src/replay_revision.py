"""Fail-closed offline replay of frozen observations and all manuscript analyses.

This replays analysis, not original model generation or behavioral execution.
"""
from pathlib import Path
import hashlib,json,os,runpy,socket,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def no_network(*args,**kwargs):raise RuntimeError('Network is disabled during offline replay')
def verify_inputs(root,manifest):
 for name,h in manifest.items():
  p=root/name
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
   raise SystemExit(f'Missing or changed frozen replay input: {name}')
def main():
 os.chdir(ROOT);os.environ['ATTEST_OFFLINE']='1'
 manifest=json.loads((ROOT/'data/revision/replay_inputs.json').read_text())
 verify_inputs(ROOT,manifest)
 socket.create_connection=no_network;socket.socket.connect=no_network;socket.socket.connect_ex=no_network
 from revision_analysis import verify_frozen
 verify_frozen()
 for script in ['analyze.py','revision_analysis.py']:
  runpy.run_path(str(ROOT/'src'/script),run_name='__main__')
 env=dict(os.environ)
 with (ROOT/'results/test_engine.log').open('w') as log:
  subprocess.run([sys.executable,'tests/test_engine.py'],check=True,stdout=log,env=env)
 for script in ['render.py','render_revision.py']:
  runpy.run_path(str(ROOT/'src'/script),run_name='__main__')
 subprocess.run([sys.executable,'tests/test_revision.py'],check=True,env=env)
 subprocess.run(['make','pdf',f'PY={sys.executable}'],check=True,env=env)
 subprocess.run([sys.executable,'src/verify_paper.py'],check=True,env=env)
 print('Offline replay complete: frozen observations, analyses, tests, and manuscript PDF.')
if __name__=='__main__':main()
