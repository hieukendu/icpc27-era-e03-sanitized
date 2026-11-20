"""Render the scoped vocabulary and revision results without changing raw codes."""
from pathlib import Path
import io
import csv,json
ROOT=Path(__file__).resolve().parents[1];GEN=ROOT.parent/'manuscript/generated'
def main():
 s=json.loads((ROOT/'results/revision/summary.json').read_text());a=s['audit'];ab=s['ablation']
 m={'RevFullShare':f"{100*a['fully_supported_share']:.1f}",'RevFullLo':f"{100*a['ci_lo']:.1f}",'RevFullHi':f"{100*a['ci_hi']:.1f}",
 'RevLocalClaims':a['population_local_claims'],'RevSupported':a['supported_population'],
 'RevAblPairs':ab['pairs'],'RevAblTwins':ab['twins'],'RevAblUnrep':ab['unrepresentable'],
 'RevAblLost':ab['extraction_lost'],'RevAblBefore':ab['mutated_extracted_supported'],'RevAblAfter':ab['mutated_corrected_supported']}
 prev=list(csv.DictReader(io.StringIO((ROOT/'results/revision/prevalence_sensitivity.csv').read_text())))
 for p,n in [('0.01','One'),('0.05','Five'),('0.1','Ten'),('0.25','Quarter'),('0.5','Half')]:
  r=next(r for r in prev if r['cohort']=='selected_original_supported' and r['false_claim_prevalence']==p)
  m['RevPrec'+n]=f"{100*float(r['precision']):.1f}"
 for name in ['tab_typology.tex','tab_profile.tex','fig_outcomes.tex']:
  p=GEN/name;t=p.read_text()
  t=t.replace('T true, F false','SS slot-supported, CR candidate refutation').replace('& T & F &','& SS & CR &')
  t=t.replace('Decided share (true+false)','Outcome share (SS+CR)').replace('Decided \\%','SS+CR \\%')
  t=t.replace('false share among decided claims','candidate-refutation share among SS+CR outcomes').replace('False \\%','CR \\%')
  t=t.replace('Local, held-out r3--5','Local, later r3--5').replace('held-out','later rounds')
  t=t.replace('addlegendentry{true}','addlegendentry{slot-supported}').replace('addlegendentry{false}','addlegendentry{candidate ref.}')
  t=t.replace('addlegendentry{unverifiable}','addlegendentry{not checked}').replace('addlegendentry{undischargeable}','addlegendentry{outside scope}')
  t=t.replace('width=0.74\\columnwidth','width=0.66\\columnwidth')
  t=t.replace('width=0.66\\columnwidth, height=5.2cm, bar width=3.0pt','width=0.96\\columnwidth, height=5.5cm, bar width=3.8pt')
  t=t.replace('yticklabel style={font=\\scriptsize}, xticklabel style={font=\\scriptsize}, label style={font=\\scriptsize}','yticklabel style={font=\\footnotesize}, xticklabel style={font=\\footnotesize}, label style={font=\\footnotesize}')
  t=t.replace('legend style={font=\\scriptsize, at={(1.02,0.5)}, anchor=west, legend columns=1, draw=none}','legend style={font=\\footnotesize, at={(0.5,-0.23)}, anchor=north, legend columns=2, draw=none}')
  t=t.replace('\\attest{} outcomes by claim type (S/D/B/P/R) and explainer, as a share of all claims of that explainer.','Supported outcomes concentrate in syntax and flow. Bars show outcomes by claim kind and explainer, as a share of all claims from that explainer; S/D/B/P/R are defined in Table~\\ref{tab:contract}.')
  t=t.replace('Supported outcomes concentrate in syntax and flow. Bars show outcomes by claim kind and explainer, as a share of all claims from that explainer; S/D/B/P/R are defined in Table~\\ref{tab:contract}.',"Claim composition and outcomes. Coder, Qwen and Haiku denote the three explainers; S/D/B/P/R denote the kinds in Table~\\ref{tab:contract}. Segment widths show each category's share of the explainer's total claims.")
  t=t.replace('addlegendentry{candidate ref.}','addlegendentry{candidate refutation}')
  t=t.replace('Coder, Qwen and Haiku denote the three explainers; S/D/B/P/R denote the kinds in Table~\\ref{tab:contract}.','Coder = Qwen2.5-Coder-14B; Qwen = Qwen2.5-14B; Haiku = Claude Haiku 5.5. S/D/B/P/R denote the kinds in Table~\\ref{tab:contract}.')
  t=t.replace('Coder = Qwen2.5-Coder-14B; Qwen = Qwen2.5-14B; Haiku = Claude Haiku 5.5.', 'Coder = Qwen2.5-Coder-14B, Qwen = Qwen2.5-14B and Haiku = Claude Haiku 5.5.')
  if name=='fig_outcomes.tex':
   t=t.replace('width=0.96\\columnwidth','width=0.90\\columnwidth')
   kinds={'S':'structure','D':'data flow','B':'behaviour','P':'purpose','R':'rationale'}
   for model in ['Coder','Qwen','Haiku']:
    for code,word in kinds.items():t=t.replace(model+'-'+code,model+': '+word)
   t=t.replace('S/D/B/P/R denote the kinds in Table~\\ref{tab:contract}. ', '')
  t=t.replace("Segment widths are percentages of each explainer's total claims, not success rates within a kind.", "Segment widths show each category's share of the explainer's total claims.")
  p.write_text(t)
 rows=[]
 for label,key in [('All frozen (nominal)','all_frozen_nominal'),('No known label errors','without_known_label_errors'),('Original supported','selected_original_supported')]:
  c=s['cohorts'][key];n=c['pairs'];rows.append(f"{label} & {n} & {c['lost_twins']}/{2*n} & {c['mutated_side_refuted']}/{n} & {c['mutated_side_supported']}/{n} \\\\")
 (GEN/'tab_planted_revision.tex').write_text(r'''\begin{table}[t]
\centering\caption{Planted pairs: original and altered statements. Unmatched counts failed extractions over both twins. Candidate refutation and slot support count altered twins only. Construction (nominal) truth labels are unvalidated.}
\label{tab:planted}\footnotesize\setlength{\tabcolsep}{3pt}
\begin{tabular}{@{}lrrrr@{}}\toprule
Pair set & Pairs & Unmatched & \shortstack{Candidate\\refutation} & \shortstack{Slot\\support} \\\midrule
'''+ '\n'.join(rows)+r'''
\bottomrule\end{tabular}\end{table}
''')
 (GEN/'tab_planted.tex').write_text('% Compatibility filename; original numerical tables remain in historical results.\n'+r'\input{generated/tab_planted_revision.tex}'+'\n')
 risks=[r for r in s['risk_coverage'] if r['dataset']=='local_scope_audit']
 names={'syntactic baseline':'Exact syntax baseline','exact structural':'Exact structural support','structural + dataflow':'Structural + flow support','all supported':'All supported outcomes'}
 body=[f"{names[r['policy']]} & {100*r['coverage']:.1f} & {r['observed_error_count']}/{r['labeled']} " + r"\\" for r in risks]
 (GEN/'tab_risk.tex').write_text(r"\begin{table}[t]\centering\caption{Policy coverage among all 822 local claims. Audit mismatch counts partial/unrelated judgments over audited accepted claims. Sentence truth requires separate assessment.}\label{tab:risk}\footnotesize\begin{tabular}{@{}lrr@{}}\toprule Policy & Coverage \% & Audit mismatch \\\midrule"+'\n'+'\n'.join(body)+r"\bottomrule\end{tabular}\end{table}"+'\n')
 sim=ROOT/'results/revision/simulation/power_1000.csv'
 if sim.exists():
  rows=list(csv.DictReader(io.StringIO(sim.read_text())))
  for n in [36,72,108,144,216]:
   rr=[float(r['rejection_rate']) for r in rows if int(r['n'])==n and float(r['OR'])==1.65]
   # alphabetic command suffixes only
   tag={36:'Small',72:'Medium',108:'Large',144:'Larger',216:'Largest'}[n]
   m['RevPower'+tag]=f"{min(rr):.2f} to {max(rr):.2f}"
  null=[float(r['rejection_rate']) for r in rows if float(r['OR'])==1]
  m['RevNullRange']=f"{min(null):.3f} to {max(null):.3f}"
  fail=[float(r['convergence_failure_rate']) for r in rows];sing=[float(r['singular_rate']) for r in rows]
  m['RevFailureRange']=f"{100*min(fail):.1f} to {100*max(fail):.1f}"
  m['RevSingularRange']=f"{100*min(sing):.1f} to {100*max(sing):.1f}"
  m['RevSimulationStatus']='completed'
 else:
  for name in ['RevPowerSmall','RevPowerMedium','RevPowerLarge','RevPowerLarger','RevPowerLargest','RevNullRange','RevFailureRange','RevSingularRange']:m[name]='pending'
  m['RevSimulationStatus']='pending'
 (GEN/'revision_macros.tex').write_text('% Generated; do not edit.\n'+''.join(f'\\newcommand{{\\{k}}}{{{v}}}\n' for k,v in sorted(m.items())))
if __name__=='__main__':main()
