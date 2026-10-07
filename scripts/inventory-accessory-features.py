"""Create a searchable, standalone inventory from an imported catalog.json."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from assets import accessory_options

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("catalog", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
rows = []
for entry in json.loads(args.catalog.read_text(encoding="utf-8")):
    if entry.get("unitType", "").startswith("physics_"):
        continue
    options = accessory_options(entry)
    if options["features"]:
        rows.append([entry.get("name", ""), entry.get("category", ""), entry.get("brand", ""), entry["path"], options["features"]])
rows.sort(key=lambda row: (row[0], row[2], row[3]))
counts = Counter(feature for row in rows for feature in row[4])
payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>S Garage special accessory inventory</title><style>
body{font:14px system-ui,sans-serif;background:#171b1f;color:#eef0f2;margin:24px;line-height:1.5}
main{max-width:1200px;margin:auto}h1{font-size:26px}p{max-width:85ch;color:#c6cbd0}
label{display:inline-flex;flex-direction:column;gap:6px;margin:0 12px 12px 0}input,select,button{font:inherit;background:#252c32;color:#eef0f2;border:1px solid #69747f;border-radius:6px;padding:8px}input{width:260px;max-width:70vw}
input:focus-visible,select:focus-visible,button:focus-visible{outline:2px solid #e9b15f;outline-offset:2px}
article{padding:14px 0;border-top:1px solid #48515a}article b{font-size:16px}article small{display:block;color:#c6cbd0}code{display:block;overflow-wrap:anywhere;color:#bdc9d6;font-size:12px}
#count{margin:6px 0 16px}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}
</style><main><h1>Special accessory inventory</h1>
<p>Installed catalog snapshot, generated __DATE__. Includes game, DLC and mounted mod definitions. Copies for each truck are listed separately. Feature counts overlap.</p>
<p><b>Editable:</b> confirmed standard name-plate text and independent colors on painted addons and paintable rims. Existing paint-job controls remain available. <b>Built-in:</b> physics, cloth, displays, horns, lighting, tanks, cables, animations and definition looks/variants are identified, not new editable save options.</p>
<p>Custom text detection covers the standard driver/co-driver plate models. A mod with its own text model may require additional support. Fixed-art logos and lightboxes are not classified as custom text. Attachment slots depend on exported geometry and are not exhaustively enumerated here.</p>
<label>Search name, truck or definition<input id="query" type="search"></label><label>Feature<select id="feature"><option value="">All special features</option></select></label>
<p id="count" role="status"></p><section id="results" aria-label="Matching parts"></section><button id="more">Show 100 more</button></main>
<script>const rows=__DATA__;const counts={};for(const r of rows)for(const f of r[4])counts[f]=(counts[f]||0)+1;
const feature=document.querySelector('#feature'),query=document.querySelector('#query'),results=document.querySelector('#results'),count=document.querySelector('#count'),more=document.querySelector('#more');
for(const [name,n] of Object.entries(counts).sort()){const o=document.createElement('option');o.value=name;o.textContent=name+' ('+n.toLocaleString()+')';feature.append(o)}
let limit=100;
function render(){const q=query.value.toLowerCase();const matches=rows.filter(r=>(!feature.value||r[4].includes(feature.value))&&r.slice(0,4).join(' ').toLowerCase().includes(q));results.replaceChildren();for(const r of matches.slice(0,limit)){const item=document.createElement('article');for(const [tag,value] of [['b',r[0]],['small',[r[1],r[2],r[4].join(', ')].filter(Boolean).join(' · ')],['code',r[3]]]){const e=document.createElement(tag);e.textContent=value;item.append(e)}results.append(item)}count.textContent=matches.length.toLocaleString()+' matching definitions · showing '+Math.min(limit,matches.length).toLocaleString();more.hidden=limit>=matches.length}
query.oninput=feature.onchange=()=>{limit=100;render()};more.onclick=()=>{limit+=100;render()};render();</script></html>"""
page = page.replace("__DATE__", datetime.now(timezone.utc).strftime("%Y-%m-%d UTC")).replace("__DATA__", payload)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(page, encoding="utf-8")
print(json.dumps({"definitions": len(rows), "features": counts, "output": str(args.output.resolve())}, indent=2))
