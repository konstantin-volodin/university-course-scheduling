"""Render an instance, or a solved schedule, as a standalone HTML page.

    scheduler report config.yaml -o instance.html
    scheduler report config.yaml --result result.json -o schedule.html

Both pages are one self-contained file: no build step, no template engine.
The data is embedded as JSON and the page draws itself, so the file keeps
working after the repo moves.
"""

from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from typing import Any

from .instance import OFF_CAMPUS, PART_TIMER

__all__ = ["instance_page", "schedule_page"]

_DISPLAY = '"Helvetica Neue",Arial,sans-serif'
_SANS = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif'
_MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'

_CSS = """
:root{
  /* brand -- University of Ottawa visual identity */
  --garnet:#8F001A; --garnet-deep:#6B0014; --garnet-wash:#F5E6E9;
  --grey-warm:#80746C; --grey-light:#ACA39A;
  --charcoal:#2D2D2C; --polar:#F2F2F2; --sage:#67796C; --white:#FFFFFF;
  /* roles */
  --ground:var(--polar); --surface:var(--white); --sunk:var(--polar);
  --ink:var(--charcoal); --muted:#5C554F; --faint:var(--grey-warm);
  --line:#DEDAD5; --line-strong:#C6BFB8; --focus:var(--garnet);
  /* semantic -- one meaning per colour, on both pages */
  --deficit:var(--garnet);      /* the shortfall, the part-time hires */
  --satisfied:var(--grey-warm); /* the quantities that already exist */
  --ok:var(--sage);             /* passing checks only */
  /* space */
  --s1:4px; --s2:8px; --s3:12px; --s4:16px;
  --s5:24px; --s6:32px; --s7:48px; --s8:72px;
}
*{box-sizing:border-box}
html{color-scheme:light}
body{background:var(--ground);color:var(--ink);font-family:__SANS__;
  font-size:17px;line-height:1.6;
  margin:0;padding:0 clamp(16px,5vw,64px) var(--s8);-webkit-font-smoothing:antialiased}
.wrap{max-width:1400px;margin:0 auto}
a{color:var(--garnet);text-decoration:underline;text-underline-offset:2px}
/* masthead: a garnet rule, not a garnet slab */
header{background:var(--surface);border-top:5px solid var(--garnet);
  border-bottom:1px solid var(--line);
  margin:var(--s5) 0 0;padding:var(--s8) var(--s6) var(--s7)}
h1{font-family:__DISPLAY__;font-weight:700;font-size:clamp(2.4rem,5.2vw,3.75rem);
  line-height:1.02;margin:0 0 var(--s5);letter-spacing:-.015em;text-wrap:balance;max-width:16ch}
.eyebrow{font-size:.6875rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint);margin:0 0 var(--s5)}
/* summary band */
.stats{display:flex;flex-wrap:wrap;gap:0;margin:0;
  background:var(--surface);border:1px solid var(--line);border-top:0}
.stat{flex:1 1 150px;padding:var(--s6) var(--s5);border-left:1px solid var(--line);
  display:flex;flex-direction:column}
.stat:first-child{border-left:0}
.stat .n{font-family:__DISPLAY__;font-size:clamp(2rem,4vw,2.75rem);font-weight:700;
  font-variant-numeric:tabular-nums;line-height:1;letter-spacing:-.03em}
/* margin-top:auto puts every label on one bottom line, however it wraps, so
   the deficit cell's underscore sits level with its neighbours' floors */
.stat .l{font-size:.6875rem;font-weight:600;letter-spacing:.11em;text-transform:uppercase;
  color:var(--faint);margin-top:auto;padding-top:var(--s3);line-height:1.4;max-width:22ch}
/* the deficit is the only garnet cell, and it double-encodes with a rule */
.stat.pt{box-shadow:inset 0 -3px 0 var(--deficit)}
.stat.pt .n{color:var(--deficit)}
.stat.pt .l{color:var(--garnet-deep)}
.controls{display:flex;flex-wrap:wrap;gap:var(--s6);align-items:flex-end;
  margin:var(--s7) 0 var(--s5)}
.ctl{display:flex;flex-direction:column;gap:var(--s2)}
.ctl-label{font-size:.6875rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint)}
.seg{display:inline-flex;border:1px solid var(--line-strong);background:var(--surface)}
.seg button{font-family:inherit;font-size:.9375rem;padding:7px 14px;border:0;
  background:transparent;color:var(--muted);cursor:pointer;border-left:1px solid var(--line)}
.seg button:first-child{border-left:0}
.seg button:hover{background:var(--polar)}
.seg button[aria-pressed="true"]{background:var(--garnet);color:var(--white);font-weight:600}
.seg button:focus-visible{outline:2px solid var(--focus);outline-offset:-2px}
.seg button .n{font-family:__MONO__;font-size:.75rem;opacity:.75;margin-left:5px}
.count{font-size:.9375rem;color:var(--faint);padding-bottom:8px;margin:0}
.count b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.gridwrap{overflow:auto;max-height:min(72vh,720px);border:1px solid var(--line);
  background:var(--surface)}
.gridwrap:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
table{border-collapse:collapse;width:100%;min-width:920px}
th,td{border-right:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:top}
th:last-child,td:last-child{border-right:0}
tbody tr:last-child td{border-bottom:0}
thead th{background:var(--polar);padding:var(--s3);text-align:left;
  font-size:.6875rem;font-weight:600;letter-spacing:.12em;
  text-transform:uppercase;color:var(--faint);position:sticky;top:0;z-index:2}
.rowhead{background:var(--polar);width:118px;padding:var(--s3);white-space:nowrap;
  font-size:.6875rem;font-weight:600;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);text-align:left}
.rowhead .cnt{display:block;margin-top:2px;font-family:__MONO__;font-size:.8125rem;
  color:var(--faint);letter-spacing:0;font-variant-numeric:tabular-nums;font-weight:400}
td.cell{padding:var(--s3);min-width:152px}
/* an empty cell is a finding, not whitespace */
td.cell.empty{background:repeating-linear-gradient(135deg,transparent 0 7px,#EDE9E4 7px 8px)}
/* no nested scroll: the region scrolls, a cell never hides its own contents */
.cellinner{display:flex;flex-direction:column;gap:var(--s3)}
/* a cell mixes 2-3 timeslots; the slot is the real event, so group by it */
.grp-h{font-family:__MONO__;font-size:.6875rem;letter-spacing:.04em;
  color:var(--muted);margin-bottom:4px}
.grp-h .dbl{color:var(--garnet-deep)}
/* one column rhythm, so chips line up down the cell instead of ragging */
.grp-c{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:4px}
/* Night carries 175 of the 426 sections, so a cell there runs 15 rows deep and
   the band dwarfs the other three. Show a group's first few and let it open. */
.grp:not(.open) .chip.over{display:none}
.more{margin-top:5px;font:inherit;font-size:.6875rem;font-weight:600;letter-spacing:.08em;
  text-transform:uppercase;background:transparent;border:0;padding:2px 0;cursor:pointer;
  color:var(--garnet);text-decoration:underline;text-underline-offset:2px}
.more:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
/* a chip carries staffing on its left edge and fill, never on the text colour */
.chip{font-family:__MONO__;font-size:.75rem;font-weight:400;padding:3px 8px;
  cursor:pointer;border:0;display:flex;align-items:center;
  gap:6px;line-height:1.35;white-space:nowrap;overflow:hidden;
  background:var(--white);color:var(--ink);border-left:3px solid var(--grey-light)}
/* the flag is the edge, not a fill: whichever way the filter tips, the grid
   stays mostly white with flags in it -- the same logic as the room footnote */
.chip.pt{border-left:3px solid var(--garnet)}
.chip:hover{background:var(--polar)}
.chip:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.chip .room{font-size:.6875rem;color:var(--muted)}
.chip.dim{opacity:.3}
/* the picked chip has to gain something, not just survive the others fading */
.chip.sel{outline:2px solid var(--garnet);outline-offset:1px;background:var(--garnet-wash)}
.detail{position:sticky;bottom:0;z-index:3;background:var(--surface);
  border:1px solid var(--line-strong);border-top:3px solid var(--garnet);
  padding:var(--s4) var(--s5);display:flex;flex-wrap:wrap;gap:var(--s6);align-items:center}
.detail[hidden]{display:none}
.detail dl{margin:0;display:flex;flex-direction:column;gap:2px}
.detail dt{font-size:.6875rem;font-weight:600;letter-spacing:.14em;
  text-transform:uppercase;color:var(--faint)}
.detail dd{margin:0;font-family:__MONO__;font-size:.875rem;font-weight:500;
  font-variant-numeric:tabular-nums}
.detail .close{margin-left:auto;background:transparent;border:1px solid var(--line-strong);
  color:var(--muted);padding:6px 16px;cursor:pointer;font-family:inherit;font-size:.9375rem}
.detail .close:focus-visible{outline:2px solid var(--focus);outline-offset:1px}
.legend{display:flex;flex-wrap:wrap;gap:var(--s5);margin:var(--s4) 0 0;
  font-size:.9375rem;color:var(--muted);align-items:center}
.key{display:inline-flex;align-items:center;gap:var(--s2)}
.sw{width:14px;height:14px;border:1px solid var(--line-strong)}
.sw.f{background:var(--white);border-left:3px solid var(--grey-warm)}
.sw.p{background:var(--white);border-left:3px solid var(--garnet)}
.stages{border-collapse:collapse;font-size:.9375rem;margin-top:2px;min-width:0}
.stages td{border:0;padding:3px 14px 3px 0;color:var(--muted)}
.stages td.v{font-family:__MONO__;font-variant-numeric:tabular-nums;
  color:var(--ink);font-weight:500;text-align:right}
.stages td.st{font-size:.6875rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase}
.ok{color:var(--ok)}
.early{color:var(--deficit)}
/* instance page */
.sect{margin:var(--s8) 0 0}
.sect h2{font-family:__DISPLAY__;font-size:clamp(1.5rem,2.6vw,1.95rem);font-weight:600;
  margin:0 0 var(--s3);letter-spacing:-.015em}
.sect .lead{color:var(--muted);font-size:1.0625rem;margin:0 0 var(--s5);max-width:65ch}
.panel{border:1px solid var(--line);background:var(--surface);padding:var(--s6)}
.bars{display:flex;flex-direction:column;gap:var(--s4)}
.bar{display:grid;grid-template-columns:150px 1fr 132px;gap:var(--s4);align-items:center}
.bar .nm{font-size:.6875rem;font-weight:600;color:var(--muted);
  text-align:right;text-transform:uppercase;letter-spacing:.1em;line-height:1.35}
.bar .track{background:#E7E3DE;height:22px;overflow:hidden}
.bar .fill{height:100%;background:var(--satisfied)}
.bar .fill.pt{background:var(--deficit)}
.bar .vl{font-size:.8125rem;color:var(--muted)}
.bar .vl .num{font-family:__MONO__;font-variant-numeric:tabular-nums;color:var(--ink)}
.hist{display:flex;align-items:flex-end;gap:5px;height:150px;padding-top:8px}
.hist .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
  gap:5px;height:100%}
.hist .hb{width:100%;background:var(--satisfied);min-height:2px}
.hist .hl{font-family:__MONO__;font-size:.6875rem;color:var(--faint);
  font-variant-numeric:tabular-nums}
.hist .hv{font-family:__MONO__;font-size:.75rem;color:var(--ink);font-weight:500;
  font-variant-numeric:tabular-nums}
.slotgrid td{padding:6px}
.slot{display:inline-flex;flex-direction:column;gap:1px;border:1px solid var(--line-strong);
  background:var(--white);color:var(--ink);padding:6px 8px;min-width:112px;
  font-family:__MONO__;font-size:.8125rem;font-weight:500}
.slot .meta{font-family:__SANS__;font-size:.75rem;font-weight:400;color:var(--faint);
  letter-spacing:0}
.slot.dbl{border-style:dashed;border-color:var(--garnet)}
.slot.dbl .id{color:var(--garnet-deep)}
.cap{width:100%;border-collapse:collapse;font-size:.9375rem;min-width:0}
.cap th,.cap td{border:0;border-bottom:1px solid var(--line);padding:8px 10px;text-align:left}
.cap th{font-size:.6875rem;font-weight:600;letter-spacing:.12em;
  text-transform:uppercase;color:var(--faint)}
.cap td{font-family:__MONO__;font-size:.8125rem}
.cap td.n{font-variant-numeric:tabular-nums;text-align:right}
.cap tr:last-child td{border-bottom:0}
.two{display:grid;gap:var(--s5);grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
@media (max-width:900px){
  .bar{grid-template-columns:1fr}
  .bar .nm{text-align:left}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""
_CSS = (
    _CSS.replace("__SANS__", _SANS)
    .replace("__MONO__", _MONO)
    .replace("__DISPLAY__", _DISPLAY)
)



def _doc(title: str, body: str, data: Any, script: str) -> str:
    """Wrap a page body into a complete, self-contained HTML document."""
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{body}\n"
        f"<script>\nconst DATA={_json_for_script(data)};\n</script>\n"
        f"<script>\n{script}\n</script>\n</body>\n</html>\n"
    )


def _json_for_script(data: Any) -> str:
    """Encode data without allowing it to close the surrounding script tag."""
    return (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


# --------------------------------------------------------------------------- #
# shared payload readers
# --------------------------------------------------------------------------- #

def _pairs(rows: Any) -> list[tuple[Any, Any]]:
    """``[["a","b"], {"a": 1}]`` -> ``[("a","b"), ("a",1)]`` — both shapes occur.

    Keys are usually ids, but ``section_attendance`` keys on the 4-tuple, so
    neither side is narrowed to ``str`` here.
    """
    out: list[tuple[Any, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            if "key" in row:
                out.append((row["key"], row.get("value")))
            else:
                out.extend(row.items())
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append((row[0], row[1] if len(row) == 2 else list(row[1:])))
    return out


def _slot_days(payload: Any) -> dict[str, list[str]]:
    days: dict[str, list[str]] = defaultdict(list)
    for slot, day in _pairs(payload.get("timeslot_dow_subset")):
        days[slot].append(day)
    return dict(days)


def _slot_len(payload: Any) -> dict[str, str]:
    # block type is the meeting length in hours; "3.0" is the double block.
    return {s: ("double" if str(b) == "3.0" else "single")
            for s, b in _pairs(payload.get("timeslot_block_subset"))}


def _slot_tod(payload: Any) -> dict[str, str]:
    return dict(_pairs(payload.get("timeslot_tod_subset")))


def _order(payload: Any, key: str, fallback: list[str]) -> list[str]:
    got = [str(x) for x in payload.get(key) or []]
    ranked = [f for f in fallback if f in got]
    return ranked + [g for g in got if g not in ranked]


_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TODS = ["Morning", "Afternoon", "Evening", "Night"]


# --------------------------------------------------------------------------- #
# the solved schedule
# --------------------------------------------------------------------------- #

_SCHEDULE_BODY = """<div class="wrap">
<header>
  <p class="eyebrow">{eyebrow}</p>
  <h1>{heading}</h1>
</header>
<div class="stats" id="stats"></div>
<div class="controls">
  <div class="ctl"><span class="ctl-label" id="lbl-sem">Semester</span>
    <div class="seg" role="group" aria-labelledby="lbl-sem" id="semseg"></div></div>
  <div class="ctl"><span class="ctl-label" id="lbl-staff">Staffing</span>
    <div class="seg" role="group" aria-labelledby="lbl-staff" id="staffseg">
      <button data-staff="all" aria-pressed="true">All</button>
      <button data-staff="fac" aria-pressed="false">Named faculty</button>
      <button data-staff="pt" aria-pressed="false">Part-timers</button>
    </div></div>
  <div class="ctl"><span class="ctl-label" id="lbl-room">Room</span>
    <div class="seg" role="group" aria-labelledby="lbl-room" id="roomseg">
      <button data-room="all" aria-pressed="true">All</button>
      <button data-room="on" aria-pressed="false">On campus only</button>
    </div></div>
  <p class="count" id="count"></p>
</div>
<div class="gridwrap" id="gridwrap" tabindex="0" role="region" aria-label="Schedule grid">
  <table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
</div>
<div class="detail" id="detail" hidden></div>
<div class="legend">
  <span class="key"><span class="sw f"></span> Named faculty</span>
  <span class="key"><span class="sw p"></span> Part-time</span>
  <span class="key">Room shown after section</span>
</div>
<div class="sect">
  <h2>Solve stages</h2>
  <div class="panel"><table class="stages" id="stagetable"></table></div>
</div>
</div>"""

_SCHEDULE_JS = """
(function(){
  function esc(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g,function(char){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  var R=DATA.assignments, DAYS=DATA.days, TODS=DATA.timesOfDay;
  var SEMS=DATA.semesters, ROOMS=DATA.rooms;
  var state={sem:SEMS[0],staff:"all",room:"all",pick:null};
  var CAP=6;  // chips shown per slot group before it has to be opened

  var totalPT=R.filter(function(r){return r.professor===null}).length;
  var profs={}; R.forEach(function(r){ if(r.professor!==null) profs[r.professor]=1; });
  [["",R.length,"sections"],
   ["",R.length-totalPT,"named-faculty sections"],
   ["pt",totalPT,"part-time sections"],
   ["",Object.keys(profs).length,"professors"],
   ["",R.filter(function(r){return r.room!==null}).length,"on campus"],
   ["",DATA.summary.unscheduled,"unscheduled"]
  ].forEach(function(s){
    var d=document.createElement("div"); d.className="stat "+s[0];
    d.innerHTML='<div class="n"></div><div class="l"></div>';
    d.querySelector(".n").textContent=s[1]; d.querySelector(".l").textContent=s[2];
    document.getElementById("stats").appendChild(d);
  });

  document.getElementById("stagetable").innerHTML=DATA.stages.map(function(s){
    var early=!s.proven;
    return '<tr><td>'+esc(s.name.replace(/^./,function(c){return c.toUpperCase()}))+'</td>'+
      '<td class="v">'+s.value.toFixed(2)+'</td>'+
      '<td class="v">'+Math.round(s.seconds)+'s</td>'+
      '<td class="st '+(early?"early":"ok")+'">'+(early?"stopped early":"proven")+'</td></tr>';
  }).join("");

  document.getElementById("semseg").innerHTML=SEMS.map(function(s){
    var n=R.filter(function(r){return r.semester===s}).length;
    return '<button data-sem="'+esc(s)+'" aria-pressed="'+(s===state.sem)+'">'+esc(s)+
      ' <span class="n">'+n+'</span></button>';
  }).join("");
  document.getElementById("head").innerHTML='<td style="width:118px"></td>'+
    DAYS.map(function(d){return '<th scope="col">'+esc(d)+'</th>'}).join("");

  function visible(r){
    if(r.semester!==state.sem) return false;
    if(state.staff==="fac" && r.professor===null) return false;
    if(state.staff==="pt" && r.professor!==null) return false;
    if(state.room==="on" && r.room===null) return false;
    return true;
  }
  function render(){
    var rows=R.filter(visible), byCell={};
    rows.forEach(function(r){ r.days.forEach(function(d){
      var k=d+"|"+r.timeOfDay; (byCell[k]=byCell[k]||[]).push(r);
    }); });
    document.getElementById("body").innerHTML=TODS.map(function(tod){
      var n=rows.filter(function(r){return r.timeOfDay===tod}).length;
      return '<tr><th scope="row" class="rowhead">'+esc(tod)+'<span class="cnt">'+n+'</span></th>'+
        DAYS.map(function(d){
          var list=(byCell[d+"|"+tod]||[]).slice().sort(function(a,b){
            return String(a.course).localeCompare(String(b.course),undefined,{numeric:true}) ||
                   String(a.section).localeCompare(String(b.section),undefined,{numeric:true});
          });
          if(!list.length) return '<td class="cell empty"></td>';
          var bySlot={};
          list.forEach(function(r){ (bySlot[r.slot]=bySlot[r.slot]||[]).push(r); });
          return '<td class="cell"><div class="cellinner">'+
            Object.keys(bySlot).sort().map(function(slot){
              var g=bySlot[slot], f=g[0];
              return '<div class="grp"><div class="grp-h'+
                (f.length==="double"?' dbl':'')+'">'+esc(slot)+'</div>'+
                '<div class="grp-c">'+g.map(function(r,gi){
                  var pt=r.professor===null;
                  return '<button class="chip'+(pt?' pt':'')+(gi>=CAP?' over':'')+
                    '" data-row="'+r.id+'" title="'+
                    esc((pt?'Part-timer':'Prof '+r.professor)+' \\u00b7 course '+r.course+
                      ' \\u00b7 '+r.slot)+'">'+
                    '<span>'+esc(r.label)+'</span>'+
                    (r.room?'<span class="room">'+esc(r.room)+'</span>':'')+'</button>';
                }).join("")+'</div>'+
                (g.length>CAP
                  ? '<button class="more" data-n="'+(g.length-CAP)+'">+'+(g.length-CAP)+
                    ' more</button>'
                  : "")+'</div>';
            }).join("")+'</div></td>';
        }).join("")+'</tr>';
    }).join("");
    var pt=rows.filter(function(r){return r.professor===null}).length;
    document.getElementById("count").innerHTML='<b>'+rows.length+'</b> sections shown \\u00b7 <b>'+
      (rows.length-pt)+'</b> faculty \\u00b7 <b>'+pt+'</b> part-time';
    if(state.pick && !rows.some(function(r){return String(r.id)===state.pick})) hideDetail();
    else if(state.pick) markPick();
  }
  function markPick(){
    Array.prototype.forEach.call(document.querySelectorAll(".chip"),function(c){
      var mine=c.dataset.row===state.pick;
      c.classList.toggle("dim", state.pick!==null && !mine);
      c.classList.toggle("sel", state.pick!==null && mine);
    });
  }
  function hideDetail(){
    state.pick=null;
    document.getElementById("detail").hidden=true;
    Array.prototype.forEach.call(document.querySelectorAll(".chip"),function(c){
      c.classList.remove("dim"); c.classList.remove("sel");
    });
  }
  function showDetail(rowId){
    var r=R.filter(function(x){return String(x.id)===rowId})[0];
    if(!r) return;
    state.pick=rowId;
    var f=[["Course",r.course],["Section",r.section],
      ["Professor",r.professor===null?"part-timer":r.professor],
      ["Meets",r.days.join(" + ")+" \\u00b7 "+r.timeOfDay],
      ["Slot",r.slot+" ("+r.length+")"],
      ["Room",r.room?r.room+" \\u00b7 "+ROOMS[r.room]+" seats":"off campus"],
      ["Students",r.students===null?"\\u2014":r.students]];
    var d=document.getElementById("detail");
    d.innerHTML=f.map(function(x){
      return '<dl><dt>'+x[0]+'</dt><dd>'+esc(x[1])+'</dd></dl>';
    }).join("")+'<button class="close" id="closebtn" title="Clear (Esc)">Clear</button>';
    d.hidden=false;
    document.getElementById("closebtn").onclick=hideDetail;
    markPick();
  }
  document.addEventListener("click",function(e){
    var more=e.target.closest?e.target.closest(".more"):null;
    if(more){
      var grp=more.parentNode, open=grp.classList.toggle("open");
      more.textContent=open?"show fewer":"+"+more.dataset.n+" more";
      return;
    }
    var chip=e.target.closest?e.target.closest(".chip"):null;
    if(chip){ chip.classList.contains("sel")?hideDetail():showDetail(chip.dataset.row); return; }
    var b=e.target.closest?e.target.closest("#semseg button,#staffseg button,#roomseg button"):null;
    if(!b) return;
    Array.prototype.forEach.call(b.parentNode.children,function(x){
      x.setAttribute("aria-pressed",String(x===b));
    });
    if(b.dataset.sem) state.sem=b.dataset.sem;
    if(b.dataset.staff) state.staff=b.dataset.staff;
    if(b.dataset.room) state.room=b.dataset.room;
    render();
  });
  document.addEventListener("keydown",function(e){ if(e.key==="Escape") hideDetail(); });
  render();
})();
"""


def schedule_page(payload: Any, result: Any, *, title: str = "Solved Schedule") -> str:
    """The solved schedule as a week grid, one per semester."""
    days_of = _slot_days(payload)
    len_of = _slot_len(payload)
    students = {
        tuple(str(part) for part in key): value
        for key, value in _pairs(payload.get("section_attendance"))
        if isinstance(key, (list, tuple)) and len(key) == 4
    }
    rooms = {str(k): v for k, v in _pairs(payload.get("classroom_cap"))}

    rows = []
    for row_id, a in enumerate(result.get("assignments", [])):
        slot = a.get("timeslot_id")
        room = a.get("classroom_id")
        prof = a.get("professor_id")
        course = str(a.get("course_id"))
        section = str(a.get("section_id"))
        semester = str(a.get("semester_id"))
        time_of_day = str(a.get("time_of_day_id"))
        rows.append(
            {
                "id": row_id,
                "professor": None if prof in (None, PART_TIMER) else prof,
                "course": course,
                "section": section,
                "semester": semester,
                "slot": slot,
                "room": None if room in (None, OFF_CAMPUS) else room,
                "timeOfDay": time_of_day,
                "days": days_of.get(slot, []),
                "length": len_of.get(slot, "single"),
                "students": students.get((course, section, semester, time_of_day)),
                "label": _section_label(course, section),
            }
        )

    summary = result.get("summary") or {}
    data = {
        "assignments": rows,
        "rooms": rooms,
        "days": _order(payload, "day_of_week_set", _DAYS),
        "timesOfDay": _order(payload, "time_of_day_set", _TODS),
        "semesters": [str(s) for s in payload.get("semester_set") or []],
        "summary": {"unscheduled": summary.get("unscheduled", 0)},
        "stages": result.get("stages") or [],
    }
    body = _SCHEDULE_BODY.format(
        eyebrow=html.escape(
            f"{len(rows)} sections · solver: {result.get('solver', 'n/a')} "
            f"· status: {result.get('status', 'n/a')}"
        ),
        heading=html.escape(title),
    )
    return _doc(title, body, data, _SCHEDULE_JS)


def _section_label(course: Any, section: Any) -> str:
    """Return a section label without repeating a course already in its id."""
    course_id = str(course)
    section_id = str(section)
    if section_id == course_id or section_id.startswith(f"{course_id}-"):
        return section_id
    return f"{course_id}-{section_id}"


# --------------------------------------------------------------------------- #
# the instance behind it
# --------------------------------------------------------------------------- #

_INSTANCE_BODY = """<div class="wrap">
<header>
  <p class="eyebrow">{eyebrow}</p>
  <h1>{heading}</h1>
</header>
<div class="stats" id="stats"></div>

<div class="sect">
  <h2>Capacity</h2>
  <div class="panel"><div class="bars" id="supply"></div></div>
</div>

<div class="sect">
  <h2>Timeslots</h2>
  <div class="gridwrap" tabindex="0" role="region" aria-label="Available timeslots">
    <table class="slotgrid"><thead><tr id="slothead"></tr></thead>
      <tbody id="slotbody"></tbody></table>
  </div>
</div>

<div class="sect">
  <h2>Demand</h2>
  <div class="two">
    <div class="panel"><div class="bars" id="bysem"></div></div>
    <div class="panel"><div class="bars" id="bytod"></div></div>
  </div>
</div>

<div class="sect">
  <h2>Faculty</h2>
  <div class="two">
    <div class="panel">
      <div class="ctl-label" style="margin-bottom:12px">Teaching load, professors per value</div>
      <div class="hist" id="loadhist"></div>
    </div>
    <div class="panel"><div class="bars" id="perms"></div></div>
  </div>
</div>

<div class="sect">
  <h2>Rooms</h2>
  <div class="two">
    <div class="panel"><table class="cap" id="roomtable"></table></div>
    <div class="panel">
      <div class="ctl-label" style="margin-bottom:12px">Section size, sections per band</div>
      <div class="hist" id="sizehist"></div>
    </div>
  </div>
</div>

</div>"""

_INSTANCE_JS = """
(function(){
  function esc(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g,function(char){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  function bars(id, rows, opts){
    opts = opts || {};
    var max = opts.max || Math.max.apply(null, rows.map(function(r){return r[1]})) || 1;
    document.getElementById(id).innerHTML = rows.map(function(r){
      var pct = Math.max(1, Math.round(r[1]/max*100));
      return '<div class="bar"><div class="nm"></div>'+
        '<div class="track"><div class="fill'+(r[2]?" pt":"")+'" style="width:'+pct+'%">'+
        '</div></div>'+
        '<div class="vl"><span class="num">'+r[1]+'</span>'+(r[3]||"")+'</div></div>';
    }).join("");
    // names via textContent so an id from the data can never inject markup
    var nms = document.getElementById(id).querySelectorAll(".nm");
    rows.forEach(function(r,i){ nms[i].textContent = r[0]; });
  }
  function hist(id, buckets){
    var max = Math.max.apply(null, buckets.map(function(b){return b[1]})) || 1;
    document.getElementById(id).innerHTML = buckets.map(function(b){
      var h = Math.max(2, Math.round(b[1]/max*112));
      return '<div class="col"><div class="hv">'+(b[1]||"")+'</div>'+
        '<div class="hb" style="height:'+h+'px"></div><div class="hl">'+b[0]+'</div></div>';
    }).join("");
  }

  DATA.stats.forEach(function(s){
    var d=document.createElement("div"); d.className="stat "+(s[2]||"");
    d.innerHTML='<div class="n"></div><div class="l"></div>';
    d.querySelector(".n").textContent=s[0]; d.querySelector(".l").textContent=s[1];
    document.getElementById("stats").appendChild(d);
  });

  bars("supply", [
    ["Faculty capacity", DATA.supply.capacity, false, " teachings"],
    ["Sections to cover", DATA.supply.demand, false, " sections"],
    ["Part-time gap", DATA.supply.gap, true, " sections"]
  ], {max: Math.max(DATA.supply.capacity, DATA.supply.demand)});

  bars("bysem", DATA.bysem.map(function(x){return [x[0], x[1], false, " sections"]}));
  bars("bytod", DATA.bytod.map(function(x){return [x[0], x[1], false, " sections"]}));
  bars("perms", DATA.perms.map(function(x){return [x[0], x[1], false, " of "+DATA.nprof]}));
  hist("loadhist", DATA.loadhist);
  hist("sizehist", DATA.sizehist);

  document.getElementById("slothead").innerHTML='<td style="width:118px"></td>'+
    DATA.days.map(function(d){return '<th scope="col">'+esc(d)+'</th>'}).join("");
  document.getElementById("slotbody").innerHTML=DATA.tods.map(function(tod){
    return '<tr><th scope="row" class="rowhead">'+esc(tod)+'</th>'+DATA.days.map(function(d){
      var here=DATA.slots.filter(function(s){return s[2].indexOf(d)>=0 && s[1]===tod});
      if(!here.length) return '<td class="cell empty"></td>';
      return '<td class="cell"><div class="cellinner">'+here.map(function(s){
        return '<span class="slot'+(s[3]==="double"?" dbl":"")+'">'+
          '<span class="id">'+esc(s[0])+'</span>'+
          '<span class="meta">'+esc(s[2].join("+")+' \\u00b7 '+s[3])+'</span></span>';
      }).join("")+'</div></td>';
    }).join("")+'</tr>';
  }).join("");

  document.getElementById("roomtable").innerHTML=
    '<tr><th>Room</th><th style="text-align:right">Seats</th>'+
    '<th style="text-align:right">Sections that fit</th></tr>'+
    DATA.rooms.map(function(r){
      return '<tr><td>'+esc(r[0])+'</td><td class="n">'+esc(r[1])+
        '</td><td class="n">'+esc(r[2])+'</td></tr>';
    }).join("");
})();
"""


def instance_page(payload: Any, *, title: str = "Scheduling Instance") -> str:
    """The inputs: the week on offer, who can teach, what must be covered."""
    days_of = _slot_days(payload)
    len_of = _slot_len(payload)
    tod_of = _slot_tod(payload)
    loads = {str(k): int(v) for k, v in _pairs(payload.get("professor_teaching"))}
    rooms = sorted(((str(k), int(v)) for k, v in _pairs(payload.get("classroom_cap"))),
                   key=lambda kv: -kv[1])
    sections = [tuple(str(x) for x in s) for s in payload.get("section_subset") or []]
    sizes = [int(v) for _, v in _pairs(payload.get("section_attendance"))]

    n_prof = len(loads)
    capacity = sum(loads.values())
    demand = len(sections)
    night = sum(1 for _, v in _pairs(payload.get("professor_can_teach_night")) if v)
    offc = sum(1 for _, v in _pairs(payload.get("professor_can_teach_out_DMS")) if v)
    packed = sum(1 for _, v in _pairs(payload.get("professor_pack_day_pref")) if v)
    courses = [str(c) for c in payload.get("course_set") or []]

    by_sem = Counter(s[2] for s in sections)
    by_tod = Counter(s[3] for s in sections)
    load_hist = Counter(loads.values())

    bands = [(0, 40), (41, 80), (81, 120), (121, 200), (201, 10**9)]
    labels = ["≤40", "41-80", "81-120", "121-200", "200+"]
    size_hist = [
        [labels[i], sum(1 for s in sizes if lo <= s <= hi)]
        for i, (lo, hi) in enumerate(bands)
    ]

    sem_order = [str(s) for s in payload.get("semester_set") or []]
    data = {
        "stats": [
            [n_prof, "professors", ""],
            [len(courses), "courses", ""],
            [demand, "sections to cover", ""],
            [len(days_of), "timeslots", ""],
            [len(rooms), "rooms", ""],
            [max(0, demand - capacity), "part-time gap", "pt"],
        ],
        "supply": {"capacity": capacity, "demand": demand, "gap": max(0, demand - capacity)},
        "bysem": (
            [[s, by_sem.get(s, 0)] for s in sem_order]
            or [[s, n] for s, n in sorted(by_sem.items())]
        ),
        "bytod": [[t, by_tod.get(t, 0)] for t in _order(payload, "time_of_day_set", _TODS)],
        "perms": [
            ["Can teach night", night],
            ["Can go off campus", offc],
            ["Prefer packed days", packed],
        ],
        "nprof": n_prof,
        "loadhist": [[str(k), load_hist[k]] for k in sorted(load_hist)],
        "sizehist": size_hist,
        "days": _order(payload, "day_of_week_set", _DAYS),
        "tods": _order(payload, "time_of_day_set", _TODS),
        "slots": sorted(
            ([s, tod_of.get(s, ""), days_of.get(s, []), len_of.get(s, "single")]
             for s in days_of),
            key=lambda r: str(r[0]),
        ),
        "rooms": [[r, cap, sum(1 for s in sizes if s <= cap)] for r, cap in rooms],
    }
    body = _INSTANCE_BODY.format(
        eyebrow=html.escape(
            f"{n_prof} professors · {len(courses)} courses · {demand} sections "
            f"· {len(rooms)} rooms"
        ),
        heading=html.escape(title),
    )
    return _doc(title, body, data, _INSTANCE_JS)
