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
  function pct(value){return Number(value||0).toFixed(1)+"%";}
  [["",DATA.summary.total,"total sections"],
   ["",pct(DATA.summary.namedPct),"named faculty"],
   ["pt",pct(100-DATA.summary.namedPct),"part-time"],
   ["",pct(DATA.summary.onCampusPct),"on campus"],
   ["",pct(DATA.summary.roomUtilizationPct),"room-slot utilization"],
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
      (rows.length-pt)+'</b> faculty \u00b7 <b>'+pt+'</b> part-time';
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
      ["Meets",r.days.join(" + ")+" \u00b7 "+r.timeOfDay],
      ["Slot",r.slot+" ("+r.length+")"],
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
