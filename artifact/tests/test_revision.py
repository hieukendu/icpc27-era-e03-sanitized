"""Checks for statistical, accounting, annotation, and offline-replay invariants."""
from pathlib import Path
import io
import csv,hashlib,json,sys,unittest,tempfile,os
from unittest.mock import patch
import numpy as np
from scipy.stats import hypergeom
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from revision_analysis import finite_interval,syntactic,verify_frozen
class RevisionTests(unittest.TestCase):
 def test_missing_or_changed_input_fails_closed(self):
  from replay_revision import verify_inputs
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)
   with self.assertRaises(SystemExit):verify_inputs(p,{'absent.json':'bad'})
   (p/'present.json').write_text('changed')
   with self.assertRaises(SystemExit):verify_inputs(p,{'present.json':'bad'})
 def test_missing_model_cache_never_calls_network(self):
  import llm
  with tempfile.TemporaryDirectory() as tmp, patch.object(llm,'CACHE',tmp), patch.dict(os.environ,{'ATTEST_OFFLINE':'1'}), patch('urllib.request.urlopen') as network:
   with self.assertRaisesRegex(RuntimeError,'offline mode forbids model calls'):llm.llm('offline regression test')
   network.assert_not_called()
 def test_frozen_engine_and_annotations(self):verify_frozen()
 def test_pair_accounting(self):
  rs=list(csv.DictReader(io.StringIO((ROOT/'results/revision/planted_ledger.csv').read_text())))
  self.assertEqual(len(rs),151);self.assertEqual(len({r['pid'] for r in rs}),151)
  self.assertEqual(sum(r['selected']=='True' for r in rs),116)
  self.assertEqual(sum(r['exclusion_reason']=='original_not_supported' for r in rs),32)
  self.assertEqual(sum(r['exclusion_reason']=='known_label_error' for r in rs),3)
 def test_audit_interval_and_denominator(self):
  a=json.loads((ROOT/'results/revision/summary.json').read_text())['audit']
  self.assertTrue(a['sample_reproduced']);self.assertEqual((a['supported_population'],a['population_local_claims']),(315,822))
  self.assertAlmostEqual(a['fully_supported_share'],315/822*6/40)
  self.assertEqual(finite_interval(315,40,6),(20,91))
  # Verify coverage of confidence-set inversion for every population count in a small population.
  for K in range(21):
   coverage=sum(hypergeom.pmf(k,20,K,8) for k in range(9) if finite_interval(20,8,k)[0]<=K<=finite_interval(20,8,k)[1])
   self.assertGreaterEqual(coverage,.95-1e-12)
 def test_slot_pairs_preserve_text(self):
  anns=[json.loads(l) for l in (ROOT/'data/revision/corrected_slots.jsonl').read_text().splitlines()]
  outputs=[json.loads(l) for l in (ROOT/'results/revision/slot_ablation.jsonl').read_text().splitlines()]
  items=json.loads((ROOT/'results/planted_items.json').read_text())
  self.assertEqual(len(anns),246);self.assertEqual(len(outputs),246)
  self.assertEqual({(a['pid'],a['nominal_label']) for a in anns},{(a['pid'],a['nominal_label']) for a in outputs})
  for a in anns:
   self.assertEqual(a['original_sentence'],items[a['pid']]['true_text' if a['nominal_label'] else 'false_text'])
   self.assertEqual(a['original_sentence'],a['unresolved_remainder'])
  self.assertEqual(sum(not a['representable_target'] for a in anns),40)
 def test_baseline_preserves_receiver(self):
  f={'calls_full':['obj.run'],'params':['x']}
  self.assertTrue(syntactic({'type':'structural','subtype':'calls','slots':{'callee':'obj.run'}},f))
  self.assertFalse(syntactic({'type':'structural','subtype':'calls','slots':{'callee':'run'}},f))
  self.assertFalse(syntactic({'type':'structural','subtype':'calls','slots':{'callee':'other.run'}},f))
 def test_prevalence_identity(self):
  for r in csv.DictReader(io.StringIO((ROOT/'results/revision/prevalence_sensitivity.csv').read_text())):
   p,t,f=map(float,[r['false_claim_prevalence'],r['sensitivity'],r['false_positive_rate']])
   self.assertAlmostEqual(float(r['precision']),p*t/(p*t+(1-p)*f))
 def test_risk_bounds(self):
  for r in csv.DictReader(io.StringIO((ROOT/'results/revision/risk_coverage.csv').read_text())):
   self.assertLessEqual(float(r['finite_population_error_lower']),float(r['finite_population_error_upper']))
   self.assertAlmostEqual(float(r['coverage']),int(r['accepted'])/int(r['total']))
 def test_simulation_allocation(self):
  rows=list(csv.DictReader(io.StringIO((ROOT/'results/revision/simulation/allocation_example.csv').read_text())))
  for participant in ['1','2','3']:
   rs=[r for r in rows if r['participant']==participant]
   self.assertEqual(len({r['item'] for r in rs}),24)
   for condition in ['generic','scoped','links']:
    cs=[r for r in rs if r['condition']==condition]
    self.assertEqual(len(cs),8);self.assertEqual(sum(r['truth']=='TRUE' for r in cs),4)
    fs=[r for r in cs if r['truth']=='FALSE']
    self.assertEqual([sum(r['evidence']==k for r in fs) for k in ['partial','misleading','absent']],[2,1,1])
  for item in map(str,range(1,25)):
   self.assertEqual({r['condition'] for r in rows if r['item']==item},{'generic','scoped','links'})
 def test_simulation_results_if_available(self):
  p=ROOT/'results/revision/simulation/power_1000.csv'
  if not p.exists():self.skipTest('Full simulation still running')
  rows=list(csv.DictReader(io.StringIO(p.read_text())));self.assertEqual(len(rows),60)
  self.assertTrue(all(int(r['repetitions'])==1000 for r in rows))
  self.assertEqual({(int(r['n']),float(r['OR']),r['heterogeneity']) for r in rows},
   {(n,e,h) for n in [36,72,108,144,216] for e in [1,1.3,1.65,2.2] for h in ['low','central','high']})
  for i,r in enumerate(rows,1):
   draw_path=ROOT/f'results/revision/simulation/draws_{i:02d}_1000.csv'
   draws=list(csv.DictReader(io.StringIO(draw_path.read_text())))
   self.assertEqual(len(draws),1000)
   self.assertAlmostEqual(float(r['rejection_rate']),sum(float(d['reject']) for d in draws)/1000)
   self.assertAlmostEqual(float(r['convergence_failure_rate']),sum(float(d['failed']) for d in draws)/1000)
   self.assertTrue(all(d['reject']=='0' for d in draws if d['failed']=='1'))
   rate=float(r['rejection_rate'])
   self.assertAlmostEqual(float(r['mc_se']),(rate*(1-rate)/1000)**.5)
   singular=[float(d['singular']) for d in draws if d['singular']!='NA']
   self.assertAlmostEqual(float(r['singular_rate']),sum(singular)/len(singular))
  source=(ROOT/'src/simulate_badges.R').read_bytes()
  self.assertEqual(hashlib.sha256(source).hexdigest(),(p.parent/'source.sha256').read_text().strip())
if __name__=='__main__':unittest.main()
