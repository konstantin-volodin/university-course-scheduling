(function(){
  function esc(value){
    return String(value == null ? "" : value).replace(/[&<>"']/g,function(char){
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }
  var R=DATA.assignments, DAYS=DATA.days, TODS=DATA.timesOfDay;
  var SEMS=DATA.semesters, ROOMS=DATA.rooms;
  var state={sem:SEMS[0],staff:"all",room:"all",scheduled:"all",pick:null};
  var CAP=6;  // chips shown per slot group before it has to be opened

  function pct(value){return Number(value||0).toFixed(1)+"%";}
  [["",DATA.summary.total,"total sections"],
   ["",pct(DATA.summary.namedPct),"named faculty"],
   ["pt",pct(100-DATA.summary.namedPct),"part-time"],
   ["",pct(DATA.summary.onCampusPct),"on campus"],
   ["",DATA.summary.patternCount===null?pct(DATA.summary.roomUtilizationPct):DATA.summary.patternCount,
    DATA.summary.patternCount===null?"room-slot utilization":"candidate patterns"],
   ["",DATA.summary.unscheduled,"unscheduled"]
  ].forEach(function(s){
    var d=document.createElement("div"); d.className="stat "+s[0];
    d.innerHTML='<div class="n"></div><div class="l"></div>';
    d.querySelector(".n").textContent=s[1]; d.querySelector(".l").textContent=s[2];
    document.getElementById("stats").appendChild(d);
  });

  document.getElementById("stagetable").innerHTML='<thead><tr><th>Stage</th><th>Value</th><th>Time</th><th>Optimality</th><th>Bound</th><th>Gap</th></tr></thead><tbody>'+DATA.stages.map(function(s){
    var early=!s.proven;
    var bounded=s.optimality_source==="lower_bound";
    var explanation=bounded?"The feasible incumbent attained the objective lower bound; no backend search was needed.":"Backend optimality uses configured gap and numerical tolerances; it is not necessarily exact.";
    return '<tr><td>'+esc(s.name.replace(/^./,function(c){return c.toUpperCase()}))+'</td>'+
      '<td class="v">'+s.value.toFixed(2)+'</td>'+
      '<td class="v">'+Math.round(s.seconds)+'s</td>'+
      '<td class="st '+(early?"early":"ok")+'" title="'+explanation+'">'+(bounded?"bound certified":early?"stopped early":"backend optimal")+'</td>'+
      '<td class="v" title="Full-stage objective bound under earlier stage caps">'+(s.best_bound==null?'—':s.best_bound.toFixed(2))+'</td>'+
      '<td class="v">'+(s.relative_gap==null?'—':pct(100*s.relative_gap))+'</td></tr>';
  }).join("")+'</tbody>';
  var ITEMCAP=50;  // items listed per goal; result.json always has all of them
  document.getElementById("scoring").innerHTML=DATA.stages.map(function(s){
    var score=s.final==null?s.value:s.final;
    var status=s.optimality_source==="lower_bound"?"best possible: nothing left to improve":
      s.proven?"best possible":"best found within the time limit, not proven best";
    var items=s.items||[];
    var list=items.slice(0,ITEMCAP).map(function(item){
      return '<li><span class="amt">'+(+item.amount.toFixed(2))+'</span> '+esc(item.description)+'</li>';
    }).join("");
    var more=items.length>ITEMCAP?'<li class="more">and '+(items.length-ITEMCAP)+
      ' more; result.json lists all of them</li>':'';
    return '<li class="goal"><h3>'+esc(s.name)+'</h3>'+
      '<p class="meaning">'+(s.maximise?'Higher is better. ':'One point: ')+esc(s.meaning)+'</p>'+
      '<p class="score"><b>'+(+score.toFixed(2))+'</b> · '+status+'</p>'+
      (items.length?'<details><summary>What added to this score ('+items.length+')</summary>'+
        '<ul class="items">'+list+more+'</ul></details>':'<p class="none">Nothing added to this score.</p>')+
      '</li>';
  }).join("");
  document.getElementById("semesterstats").innerHTML=DATA.summary.bySemester.map(function(s){
    return '<div class="semesterstat"><span>'+esc(s.semester)+'</span><b>'+s.total+
      '</b> sections · <b>'+s.named+'</b> named faculty · <b>'+s.onCampus+'</b> on campus</div>';
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
    if(state.room==="off" && r.room!==null) return false;
    if(state.scheduled==="yes" && !r.slot) return false;
    if(state.scheduled==="no" && r.slot) return false;
    return true;
  }
  var palette=[['#315d9a','#edf3fc'],['#7b4590','#f6eff9'],
    ['#237466','#edf7f3'],['#a05b23','#fff5e8'],['#a14363','#fceff3'],['#4d6590','#eff2f8']];
  var courseNames=Array.from(new Set(R.map(function(r){return r.course}))).sort();
  function courseCard(r,meeting,index){
    var colors=palette[courseNames.indexOf(r.course)%palette.length];
    return '<button class="chip course-card'+(r.professor===null?' pt':'')+
      (index>=CAP?' over':'')+'" data-row="'+r.id+'" style="--course-color:'+colors[0]+
      ';--course-wash:'+colors[1]+'" aria-label="'+esc(r.label+', '+meeting.time+', '+
      (r.room||'No listed room'))+'">'+
      '<span class="card-course">'+esc(r.course)+'</span>'+
      '<span class="card-time">'+esc(meeting.time)+'</span>'+
      '<span class="card-room">'+esc(r.room||'Off campus')+' · Section '+esc(r.section)+'</span>'+
      '<span class="card-professor">'+esc(r.professor||'Unstaffed / part-time')+'</span></button>';
  }
  function clockGrid(rows){
    var starts=new Set(), cells={};
    rows.forEach(function(r){(r.meetings||[]).forEach(function(m){
      var start=m.time.slice(0,5), key=m.day+'|'+start;
      starts.add(start); (cells[key]=cells[key]||[]).push({row:r,meeting:m});
    });});
    return Array.from(starts).sort().map(function(start){
      return '<tr class="clock-row"><th scope="row" class="rowhead clock-label">'+
        esc(start)+'</th>'+DAYS.map(function(day){
          var entries=(cells[day+'|'+start]||[]).sort(function(a,b){
            return a.row.course.localeCompare(b.row.course)||String(a.row.section).localeCompare(String(b.row.section));
          });
          if(!entries.length) return '<td class="cell clock-empty"></td>';
          return '<td class="cell"><div class="grp"><div class="course-stack">'+
            entries.map(function(e,i){return courseCard(e.row,e.meeting,i)}).join('')+'</div>'+
            (entries.length>CAP?'<button class="more" data-n="'+(entries.length-CAP)+'">+'+
              (entries.length-CAP)+' more</button>':'')+'</div></td>';
        }).join('')+'</tr>';
    }).join('');
  }
  function render(){
    var rows=R.filter(visible), byCell={};
    var unscheduled=rows.filter(function(r){return !r.slot});
    document.getElementById("emptyresults").hidden=rows.length!==0;
    document.getElementById("gridwrap").hidden=!rows.some(function(r){return r.slot});
    document.getElementById("unscheduled").hidden=unscheduled.length===0;
    document.getElementById("unscheduledrows").innerHTML=unscheduled.map(function(r){
      return '<button class="chip'+(r.professor===null?' pt':'')+'" data-row="'+r.id+
        '">'+esc(r.label)+'</button>';
    }).join("");
    rows.forEach(function(r){ r.days.forEach(function(d){
      var k=d+"|"+r.timeOfDay; (byCell[k]=byCell[k]||[]).push(r);
    }); });
    var scheduled=rows.filter(function(r){return r.slot});
    var hasClocks=scheduled.length && scheduled.every(function(r){return (r.meetings||[]).length});
    document.getElementById("body").innerHTML=hasClocks?clockGrid(scheduled):TODS.map(function(tod){
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
              var clock=(f.meetings||[]).filter(function(m){return m.day===d})
                .map(function(m){return m.time}).join(', ');
              var heading=clock?(slot.indexOf('generated-')===0?clock:slot+' · '+clock):slot;
              return '<div class="grp"><div class="grp-h'+
                (f.length==="double"?' dbl':'')+'">'+esc(heading)+'</div>'+
                '<div class="grp-c">'+g.map(function(r,gi){
                  var pt=r.professor===null;
                  return '<button class="chip'+(pt?' pt':'')+(gi>=CAP?' over':'')+
                    '" data-row="'+r.id+'" title="'+
                    esc((pt?'Part-timer':'Prof '+r.professor)+' \u00b7 course '+r.course+
                      ' \u00b7 '+r.slot)+'">'+
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
    document.getElementById("count").innerHTML='<b>'+rows.length+'</b> sections shown \u00b7 <b>'+
      (rows.length-pt)+'</b> faculty \u00b7 <b>'+pt+'</b> part-time \u00b7 <b>'+
      unscheduled.length+'</b> unscheduled';
    if(state.pick && !rows.some(function(r){return String(r.id)===state.pick})) hideDetail();
    else if(state.pick) markPick();
  }
  function markPick(){
    Array.prototype.forEach.call(document.querySelectorAll(".chip"),function(c){
      var mine=c.dataset.row===state.pick;
      c.classList.toggle("dim", state.pick!==null && !mine);
      c.classList.toggle("sel", state.pick!==null && mine);
      c.setAttribute("aria-pressed",String(state.pick!==null && mine));
    });
  }
  function hideDetail(){
    state.pick=null;
    document.getElementById("detail").hidden=true;
    Array.prototype.forEach.call(document.querySelectorAll(".chip"),function(c){
      c.classList.remove("dim"); c.classList.remove("sel");
      c.setAttribute("aria-pressed","false");
    });
  }
  function showDetail(rowId){
    var r=R.filter(function(x){return String(x.id)===rowId})[0];
    if(!r) return;
    state.pick=rowId;
    var f=[["Course",r.course],["Section",r.section],
      ["Professor",r.professor===null?"part-timer":r.professor],
      ["Meets",r.slot?((r.meetings||[]).length?r.meetings.map(function(m){return m.day+" "+m.time}).join(" + "):r.days.join(" + ")+" \u00b7 "+r.timeOfDay):"Unscheduled"],
      ["Slot",r.slot?r.slot+" ("+r.length+")":"Not assigned"],
      ["Room",r.room?r.room+" \u00b7 "+ROOMS[r.room]+" seats":"off campus"],
      ["Students",r.students===null?"\u2014":r.students]];
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
    var b=e.target.closest?e.target.closest("#semseg button,#staffseg button,#roomseg button,#scheduledseg button"):null;
    if(!b) return;
    Array.prototype.forEach.call(b.parentNode.children,function(x){
      x.setAttribute("aria-pressed",String(x===b));
    });
    if(b.dataset.sem) state.sem=b.dataset.sem;
    if(b.dataset.staff) state.staff=b.dataset.staff;
    if(b.dataset.room) state.room=b.dataset.room;
    if(b.dataset.scheduled) state.scheduled=b.dataset.scheduled;
    render();
  });
  document.addEventListener("keydown",function(e){ if(e.key==="Escape") hideDetail(); });
  render();
})();
