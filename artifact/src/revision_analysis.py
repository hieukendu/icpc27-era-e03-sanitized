"""Retrospective analyses over frozen inputs. No model calls, no engine changes."""
from pathlib import Path
import io
from collections import Counter, defaultdict
import csv, hashlib, json, random, re
import numpy as np
from scipy.stats import hypergeom
from discharge import discharge_claim
from explain import load_corpus, split_sentences

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/revision'
SEED=20261111
LABELS={'true':'slot-supported','false':'candidate refutation','consistent':'consistent',
        'unverifiable':'not checked','undischargeable':'outside evidence scope','lost':'extraction unmatched'}
def load(name):return [json.loads(l) for l in (ROOT/name).read_text().splitlines()]
def save(name,obj): (OUT/name).write_text(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
def jsonl(name,rows): (OUT/name).write_text(''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in rows))
def csvout(name,rows):
    if not rows:return
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def verify_frozen():
    frozen=json.loads((ROOT/'data/revision/frozen_engine.json').read_text())
    for p,h in frozen['files_sha256'].items():
        assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h, f'Frozen input changed: {p}'
    ann=ROOT/'data/revision/corrected_slots.jsonl'
    m=json.loads((ann.parent/'corrected_slots.freeze.json').read_text())
    assert hashlib.sha256(ann.read_bytes()).hexdigest()==m['sha256'],'Corrected annotations changed'
    assert hashlib.sha256((ROOT/'src/prepare_slot_diagnostic.py').read_bytes()).hexdigest()==m['generator_sha256'],'Annotation preparation source changed'

def finite_interval(N,n,k,alpha=.05):
    """Equal-tailed confidence set for the finite population success count."""
    K=np.arange(N+1)
    ok=(hypergeom.cdf(k,N,K,n)>=alpha/2)&(hypergeom.sf(k-1,N,K,n)>=alpha/2)
    candidates=K[ok];return int(candidates[0]),int(candidates[-1])

def syntactic(c,f):
    """Independent exact-string baseline; only named call sites and parameters.
    No receiver stripping, type inference, suffix match, data flow or refutations.
    """
    typ=c.get('type',c.get('ext_type')); sub=c.get('subtype',c.get('ext_subtype'));s=c.get('slots') or {}
    if typ!='structural':return False
    if sub=='calls':return s.get('callee') in f.get('calls_full',[])
    if sub=='parameter':return s.get('name') in f.get('params',[])
    return False

def policy(c,name,f):
    if name=='syntactic baseline':return syntactic(c,f)
    if c.get('outcome')!='true':return False
    typ=c.get('type2',c.get('type',c.get('ext_type')))
    if name=='exact structural':return typ=='structural' and c.get('rule') in {'calls-exact','param','imports-exact','raises-explicit','decorator','default'}
    if name=='structural + dataflow':return typ in {'structural','dataflow'}
    return True

def metrics(rows):
    t=[r for r in rows if r['label']];f=[r for r in rows if not r['label']]
    out={'pairs':len(t),'twins':len(rows),'functions':len({r['fid'] for r in rows}),
         'lost_twins':sum(r['outcome']=='lost' for r in rows),
         'original_side_supported':sum(r['outcome']=='true' for r in t),
         'mutated_side_refuted':sum(r['outcome']=='false' for r in f),
         'mutated_side_supported':sum(r['outcome']=='true' for r in f),
         'original_side_refuted':sum(r['outcome']=='false' for r in t)}
    out['nominal_refutation_sensitivity']=out['mutated_side_refuted']/len(f)
    out['nominal_false_positive_rate']=out['original_side_refuted']/len(t)
    return out

def prevalence(rows,cohort):
    grouped=defaultdict(list)
    for r in rows:grouped[r['fid']].append(r)
    groups=[grouped[k] for k in sorted(grouped)];rng=np.random.default_rng(SEED)
    base=metrics(rows); boots=[]
    for _ in range(2000):
        b=metrics([r for i in rng.integers(0,len(groups),len(groups)) for r in groups[i]])
        boots.append((b['nominal_refutation_sensitivity'],b['nominal_false_positive_rate']))
    res=[]
    for p in [.01,.05,.1,.25,.5]:
        t,f=base['nominal_refutation_sensitivity'],base['nominal_false_positive_rate'];den=p*t+(1-p)*f
        vals=[p*t/(p*t+(1-p)*f) for t,f in boots if p*t+(1-p)*f>0]
        res.append(dict(cohort=cohort,false_claim_prevalence=p,sensitivity=t,false_positive_rate=f,
           precision=p*t/den if den else None,ci_lo=float(np.quantile(vals,.025)) if len(vals)>=1900 else None,
           ci_hi=float(np.quantile(vals,.975)) if len(vals)>=1900 else None,
           undefined_bootstraps=2000-len(vals),bootstrap_reps=2000,
           status='Nominal planted labels; synthetic prevalence sensitivity; assistant labels not independent'))
    return res

def main():
    OUT.mkdir(parents=True,exist_ok=True);verify_frozen()
    claims=load('results/discharge.jsonl');byid={c['cid']:c for c in claims}
    facts={r['fid']:r for r in load('results/facts.jsonl')};corpus={r['fid']:r for r in load_corpus()}
    planted=load('results/planted.jsonl');items=json.loads((ROOT/'results/planted_items.json').read_text())
    audit={int(r['pid']):r for r in csv.DictReader(io.StringIO((ROOT/'data/planted_audit.csv').read_text()))}
    pairs=defaultdict(dict)
    for r in planted:
        assert r['label'] not in pairs[r['pid']]
        pairs[r['pid']][r['label']]=r
    assert len(pairs)==len(items)==151 and all(set(p)=={True,False} for p in pairs.values())
    ledger=[];selected=set();known_errors=set()
    for pid,it in enumerate(items):
        au=audit.get(pid,{}); eligible=byid[it['orig_cid']]['outcome']=='true'
        error=au.get('decision')=='label_error'
        if error:known_errors.add(pid)
        if eligible and not error:selected.add(pid)
        t,f=pairs[pid][True],pairs[pid][False]
        ledger.append(dict(pid=pid,fid=it['fid'],kind=it['kind'],original_cid=it['orig_cid'],
            original_current_outcome=byid[it['orig_cid']]['outcome'],original_eligible=eligible,
            label_status=au.get('decision','not_audited'),label_note=au.get('note',''),
            label_provenance='assistant-only; inherited nominal labels otherwise',
            audited_side=('original' if 'TRUE twin' in au.get('note','') else 'mutated') if au else 'neither',
            audit_side_basis='Legacy free-text note identifies the single original-side audit; other targeted audits are mutated-side',
            selected=eligible and not error,exclusion_reason='original_not_supported' if not eligible else ('known_label_error' if error else ''),
            original_text=it['true_text'],mutated_text=it['false_text'],
            original_matched=t['matched'],mutated_matched=f['matched'],
            original_outcome=t['outcome'],mutated_outcome=f['outcome']))
    csvout('planted_ledger.csv',ledger)
    cohorts={'all_frozen_nominal':planted,'without_known_label_errors':[r for r in planted if r['pid'] not in known_errors],
             'selected_original_supported':[r for r in planted if r['pid'] in selected]}
    S={'status':'Retrospective/exploratory; all semantic audit labels tentative assistant coding',
       'planted_flow':{'frozen_pairs':151,'original_not_supported':sum(not r['original_eligible'] for r in ledger),
         'eligible_label_error':sum(r['original_eligible'] and r['label_status']=='label_error' for r in ledger),
         'selected_pairs':len(selected),'audit_pair_count':len(audit),'known_label_error_pairs':len(known_errors)},
       'cohorts':{k:metrics(v) for k,v in cohorts.items()}}
    csvout('planted_cohorts.csv',[dict(cohort=k,**v) for k,v in S['cohorts'].items()])
    csvout('prevalence_sensitivity.csv',[r for k,v in cohorts.items() for r in prevalence(v,k)])
    # Recover the exact probability sample; never multiply by true+false share.
    local=[c for c in claims if c['explainer']!='frontier']
    frame=[c for c in local if c['outcome']=='true'];ta=list(csv.DictReader(io.StringIO((ROOT/'data/true_audit.csv').read_text())))
    ids={r['cid'] for r in ta};assert len(ids)==len(ta)==40
    drawn={r['cid'] for r in random.Random(20261110).sample(frame,40)}
    assert drawn==ids,'Audit sampling frame/seed mismatch'
    k=sum(r['decision']=='pure' for r in ta);lo,hi=finite_interval(len(frame),40,k)
    S['audit']={'population_local_claims':len(local),'supported_population':len(frame),'sample_size':40,
        'seed':20261110,'sample_reproduced':True,'full_support_labels':k,'partial_or_unrelated_labels':40-k,
        'fully_supported_share':len(frame)/len(local)*k/40,'ci_lo':lo/len(local),'ci_hi':hi/len(local),
        'population_full_count_ci':[lo,hi],
        'interval_scope':'95% exact finite-population sampling interval conditional on corpus and tentative labels; no semantic-label uncertainty included'}
    csvout('audit_frame.csv',[dict(cid=c['cid'],fid=c['fid'],explainer=c['explainer'],sampled=c['cid'] in ids) for c in frame])
    # One-to-one records, including unrepresentable targets. No new model call.
    annotations=load('data/revision/corrected_slots.jsonl');ab=[]
    for a in annotations:
        raw=pairs[a['pid']][a['nominal_label']]
        if a['representable_target']:
            c=dict(cid=f"corrected:{a['pid']}:{int(a['nominal_label'])}",type=a['type'],type2=a['type'],
                   subtype=a['subtype'],slots=a['slots'],text=a['original_sentence'])
            oc,ev,scope,rule=discharge_claim(c,facts[a['fid']],corpus[a['fid']],{})
        else:oc,ev,scope,rule='unrepresentable',a['unrepresentable_reason'],a['scope'],'unrepresentable'
        ab.append(dict(pid=a['pid'],fid=a['fid'],nominal_label=a['nominal_label'],
            extracted_outcome=raw['outcome'],corrected_outcome=oc,corrected_rule=rule,corrected_evidence=ev,
            extracted_slots=raw.get('slots'),corrected_slots=a['slots'],representable_target=a['representable_target'],
            original_sentence=a['original_sentence'],unresolved_remainder=a['unresolved_remainder'],
            status='Assistant-corrected target only; not gold sentence truth'))
    jsonl('slot_ablation.jsonl',ab)
    counts=Counter((r['extracted_outcome'],r['corrected_outcome']) for r in ab)
    csvout('slot_transitions.csv',[dict(extracted=x,corrected=y,twins=n) for (x,y),n in sorted(counts.items())])
    S['ablation']={'twins':len(ab),'pairs':len(ab)//2,'unrepresentable':sum(not r['representable_target'] for r in ab),
      'extraction_lost':sum(r['extracted_outcome']=='lost' for r in ab),
      'changed':sum(r['extracted_outcome']!=r['corrected_outcome'] for r in ab),
      'mutated_extracted_supported':sum(not r['nominal_label'] and r['extracted_outcome']=='true' for r in ab),
      'mutated_corrected_supported':sum(not r['nominal_label'] and r['corrected_outcome']=='true' for r in ab),
      'status':'Corrected targets; unrepresentable items retained; nominal labels, not independent truth'}
    # Risk/coverage: distinguish nominal sentence truth, scope alignment and unknown slot validity.
    policies=['syntactic baseline','exact structural','structural + dataflow','all supported']
    risks=[];aud={r['cid']:r for r in ta}
    for name in policies:
        accepted=[c for c in local if policy(c,name,facts[c['fid']])]
        sampled=[c for c in accepted if c['cid'] in aud]
        errors=sum(aud[c['cid']]['decision']!='pure' for c in sampled)
        n=len(accepted);unk=n-len(sampled)
        within_frame=all(c['outcome']=='true' for c in accepted)
        risk_ci=finite_interval(n,len(sampled),errors) if n and sampled and within_frame else (None,None)
        risks.append(dict(dataset='local_scope_audit',policy=name,total=len(local),accepted=n,coverage=n/len(local),
           labeled=len(sampled),observed_error_count=errors,unknown=unk,
           observed_error_rate=errors/len(sampled) if sampled else None,
           scope_error_ci_lo=risk_ci[0]/n if risk_ci[0] is not None else None,
           scope_error_ci_hi=risk_ci[1]/n if risk_ci[1] is not None else None,
           finite_population_error_lower=errors/n if n else None,finite_population_error_upper=(errors+unk)/n if n else None,
           slot_evidence_error_lower=0 if n else None,slot_evidence_error_upper=1 if n else None,
           status='Scope mismatch is not sentence falsehood. Slot evidence correctness not independently labeled.'))
        # Planted result is a nominal sentence-label diagnostic; uncertain labels stay unknown.
        acc=[c for c in planted if policy(c,name,facts[c['fid']])];n=len(acc)
        unknown=sum(c['pid'] in known_errors for c in acc)
        bad=sum(not c['label'] and c['pid'] not in known_errors for c in acc)
        risks.append(dict(dataset='all_frozen_planted_nominal',policy=name,total=len(planted),accepted=n,coverage=n/len(planted),
           labeled=n-unknown,observed_error_count=bad,unknown=unknown,
           observed_error_rate=bad/(n-unknown) if n>unknown else None,
           scope_error_ci_lo=None,scope_error_ci_hi=None,
           finite_population_error_lower=bad/n if n else None,finite_population_error_upper=(bad+unknown)/n if n else None,
           slot_evidence_error_lower=0 if n else None,slot_evidence_error_upper=1 if n else None,
           status='Nominal sentence-label risk only; known label-error pairs unknown; remaining labels also unvalidated.'))
    csvout('risk_coverage.csv',risks);S['risk_coverage']=risks
    # Original explanation retained, distinct from extractor paraphrase and evidence claim.
    explanations={(e['explainer'],e['fid']):e['text'] for e in load('results/explanations.jsonl')}
    contracts=[]
    for c in claims:
        text=c['text'];explanation=explanations[(c['explainer'],c['fid'])]
        source_sentences=[];start=0
        for i,sentence in enumerate(split_sentences(explanation)):
            offset=explanation.find(sentence,start)
            assert offset>=0
            source_sentences.append(dict(index=i,start=offset,end=offset+len(sentence),text=sentence))
            start=offset+len(sentence)
        contracts.append(dict(cid=c['cid'],fid=c['fid'],original_explanation=explanation,extracted_claim_text=text,
           original_sentences=source_sentences,
           matching_source_sentence_indices=[s['index'] for s in source_sentences if text in s['text']],
           source_alignment_status='Verbatim matches only; paraphrases retain all original sentence spans without inferred alignment',
           verbatim_in_explanation=text in explanation,normalized_proposition={'predicate':c['subtype'],'arguments':c['slots']},
           raw_outcome=c['outcome'],outcome_label=LABELS[c['outcome']],evidence=c['evidence'],scope=c['scope'],rule=c['rule'],
           unresolved_remainder=text,sentence_truth='unassessed',
           scope_note='The whole text remains unassessed beyond the indicated slot; no assertion that other clauses are covered.'))
    jsonl('claim_contracts.jsonl',contracts)
    save('summary.json',S)
    print(json.dumps({k:S[k] for k in ['planted_flow','audit','ablation']},indent=2))
if __name__=='__main__':main()
