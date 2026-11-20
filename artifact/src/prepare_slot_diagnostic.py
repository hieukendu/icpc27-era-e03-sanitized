"""Materialize assistant-corrected target slots; never a gold or blinded annotation.

The explicit decisions below were made from paired text and source context before
running this ablation. Original-extraction slots seed the representation, so this
is an assistant-corrected diagnostic, not independent extraction validation.
Running again requires --replace; the analysis only consumes the frozen file.
"""
from pathlib import Path
import argparse, copy, difflib, hashlib, json, re
ROOT = Path(__file__).resolve().parents[1]
UNREP = {
 0:'Set/map denotes a collection type; no explicit constructor call assertion.',
 3:'Suppress is a natural-language verb, not an assertion of a suppress call.',
 12:'Property creation does not assert a call to the mutated identifier.',
 16:'All is a quantifier; the mutation replaces prose, not a callee.',
 18:'Defines a helper; a call slot cannot represent a definition.',
 31:'Defines a helper; a call slot cannot represent a definition.',
 33:'Passing a function to partial is not a direct call to that function.',
 47:'Analogy with zip describes behavior, not a zip call.',
 49:'Describes collection contents, not a parameter declaration.',
 53:'String specifies argument type; no parameter identifier is asserted.',
 56:'Array describes the argument role; mutation changes common nouns too.',
 64:'Conditional behavior of strict mode is not a parameter-declaration assertion.',
 65:'Iterable describes an input type; exact parameter name is ambiguous.',
 71:'Conditional behavior is not a parameter-declaration assertion.',
 72:'Square grid describes an input shape; parameter-name reading is ambiguous.',
 76:'String is a type, not a parameter name.',
 86:'String/second_string mutation changes a descriptive noun; endpoint ambiguous.',
 87:'First item is an iteration role, not an assertion of a variable named item.',
 108:'A numeric range is described without naming its induction variable.',
 116:'Flush and close require multiple receiver/call propositions, not one flow sink.',
}
# Explicit receiver or endpoint repairs. Other target slots retain original
# contextual grounding and apply the literal mutation to the FALSE-side text.
OVERRIDES = {
 2:{'callee':'poolmanager.clear'}, 6:{'callee':'_stream.read'},
 45:{'callee':'_stream.read'}, 79:{'source':'javaVersion.charAt(i)','sink':'num'},
 92:{'source':'declaredByRaw.getTypeParameters()','sink':'index'},
 96:{'source':'self._protected_args','sink':'return'},
 105:{'source':'trace_str','sink':'ret'},
 119:{'source':'tqdm_class.get_lock()','sink':'lock'},
}
QUALIFIERS = re.compile(r'\b(?:if|unless|only|always|never|not|without|each|every|all|first|then|finally|before|after|otherwise|recurs\w*|inner|nested|optional)\b',re.I)

def swaps(a,b):
    a=re.findall(r'[A-Za-z_]\w*|\S',a); b=re.findall(r'[A-Za-z_]\w*|\S',b)
    out={}
    for op,i,j,k,l in difflib.SequenceMatcher(None,a,b).get_opcodes():
        if op=='equal':continue
        if j-i!=l-k:return None
        for x,y in zip(a[i:j],b[k:l]):
            if x in out and out[x]!=y:return None
            out[x]=y
    return out

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--replace',action='store_true');args=parser.parse_args()
    path=ROOT/'data/revision/corrected_slots.jsonl'
    if path.exists() and not args.replace:raise SystemExit('Frozen annotations exist; refusing overwrite')
    original={r['cid']:r for r in map(json.loads,(ROOT/'results/discharge.jsonl').open())}
    items=json.load((ROOT/'results/planted_items.json').open());rows=[]
    for pid,it in enumerate(items):
        if it['kind']=='behavioural':continue
        base=original[it['orig_cid']]; replacements=swaps(it['true_text'],it['false_text'])
        for label in [True,False]:
            txt=it['true_text' if label else 'false_text']
            slots=copy.deepcopy(OVERRIDES.get(pid,base['slots']))
            reason=UNREP.get(pid,'')
            if replacements is None:reason='Mutation cannot be mapped unambiguously to identifier substitutions.'
            if not label and replacements:
                slots={k:re.sub(r'[A-Za-z_]\w*',lambda m:replacements.get(m[0],m[0]),v) if isinstance(v,str) else v for k,v in slots.items()}
            typ,sub=base['type'],base['subtype']
            if pid==100:
                typ,sub='structural','calls';slots={'callee':'self.on_miss' if label else 'self._get_link_and_move_to_front_of_ll'}
            rows.append(dict(pid=pid,fid=it['fid'],nominal_label=label,original_cid=it['orig_cid'],
                original_sentence=txt,type=typ,subtype=sub,slots=slots,
                representable_target=not bool(reason),unrepresentable_reason=reason,
                normalized_proposition={'predicate':sub,'arguments':slots},
                preserved_qualifiers=QUALIFIERS.findall(txt),
                unresolved_remainder=txt,
                scope='Only the selected slot relation; full sentence retained verbatim and not asserted entailed.',
                provenance='Tentative assistant coding, source-context informed, original-slot seeded; not independent or blinded.',
                annotation_note='Explicit repair' if pid in OVERRIDES or pid==100 else 'Literal target-slot reconstruction',
                sentence_truth='unknown; nominal planted label is not independent truth'))
    path.write_text(''.join(json.dumps(r,sort_keys=True,ensure_ascii=False)+'\n' for r in rows))
    (path.parent/'corrected_slots.freeze.json').write_text(json.dumps({'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'rows':len(rows),'pairs':len(rows)//2,'status':'Frozen before corrected-slot engine comparison; assistant-coded, not gold',
      'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2)+'\n')
    print('Frozen',len(rows),'twins;',sum(not r['representable_target'] for r in rows),'unrepresentable')
if __name__=='__main__':main()
