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
          '<span class="meta">'+esc((s[4]||[]).length?s[4].filter(function(m){return m.day===d}).map(function(m){return m.time}).join(', '):s[2].join("+")+' \u00b7 '+s[3])+'</span></span>';
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
