"""Machine-check page boundaries and stale claim wording after compilation.
Visual inspection remains required; this cannot detect all layout defects.
"""
from pathlib import Path
import json,re,subprocess
ROOT=Path(__file__).resolve().parents[1]
def main():
 pdf=ROOT.parent/'manuscript/main.pdf'
 text=subprocess.check_output(['pdftotext','-layout',str(pdf),'-'],text=True)
 pages=text.split('\f')
 if not pages[-1].strip():pages.pop()
 assert len(pages)==5,f'Expected five pages; got {len(pages)}'
 header=re.search(r'R\s*E\s*F\s*E\s*R\s*E\s*N\s*C\s*E\s*S',pages[4],re.I)
 assert header and not pages[4][:header.start()].strip(),'Page 5 must begin with references'
 assert 'AI use and data availability' in pages[3],'Disclosure must be on page 4'
 assert 'AI use and data availability' not in pages[4],'Disclosure spills to page 5'
 assert 'CONCLUSION' not in pages[4].upper(),'Conclusion spills to reference page'
 for phrase in ['certifies','certified','no tool can check','held-out rounds']:
  assert phrase not in text.lower(),f'Stale claim terminology: {phrase}'
 log=(ROOT/'build/main.log').read_text(errors='replace')
 assert not re.search(r'Overfull \\[hv]box',log),'Overfull box in final PDF build'
 assert not re.search(r'(?:Reference|Citation).*undefined',log),'Unresolved reference/citation'
 p=ROOT/'results/revision/pdf_validation.json'
 p.write_text(json.dumps(dict(pages=5,main_text_max_page=4,references_start_page=5,
   disclosure_page=4,overfull_boxes=0,undefined_references=0,
   visual_review='Required separately; structural checks are not a substitute'),indent=2)+'\n')
 print('PDF structural checks passed: main text/disclosure through page 4; references only page 5.')
if __name__=='__main__':main()
