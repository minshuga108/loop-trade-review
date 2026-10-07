const E=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const both=(a,b)=>`<span data-l="en">${E(a)}</span><span data-l="zh">${E(b)}</span>`;
let sid="default";try{sid=localStorage.getItem("sid")||sid}catch(e){}
const H={"X-Session":sid},id=decodeURIComponent(location.pathname.split("/").pop());
const setL=z=>{document.documentElement.lang=z?"zh-CN":"en";document.getElementById("lb").textContent=z?"English":"中文"};
try{setL(localStorage.getItem("lang")==="zh")}catch(e){}
document.getElementById("lb").onclick=()=>{const z=document.documentElement.lang!=="zh-CN";setL(z);try{localStorage.setItem("lang",z?"zh":"en")}catch(e){}};
document.getElementById("who").textContent="· "+id;
fetch("/api/thesis/"+encodeURIComponent(id),{headers:H}).then(r=>r.ok?r.json():Promise.reject(r.status)).then(t=>{
  document.getElementById("body").innerHTML=`<ol>${t.text.en.map((e,i)=>`<li>${both(e,t.text.zh[i])}</li>`).join("")}</ol>`+
   (t.diff.length?`<ul>${t.diff.map(d=>`<li class="d">${both(d.en,d.zh)}</li>`).join("")}</ul>`:"")+
   `<p class="tag">${both("Thesis hash","论点哈希")} <code>${E(t.hash)}</code> · ${E(t.date)}</p>`+
   (t.frozen.length?`<p class="tag">${both("Frozen versions in the public record","公开记录中的冻结版本")}: ${t.frozen.map(f=>`v${f.version} <code>${E(f.hash.slice(0,16))}</code> (#${f.seq}, ${E(f.date)})`).join(" · ")}</p>`:"")+
   `<p class="tag">${both(t.label,t.label_zh||t.label)}</p>`;
}).catch(e=>{document.getElementById("body").textContent="Not available ("+e+")"});
fetch("/api/thesis/"+encodeURIComponent(id)+"/score",{headers:H}).then(r=>r.ok?r.json():Promise.reject(r.status)).then(j=>{
  document.getElementById("sc").innerHTML=`<p>${both(j.summary.en,j.summary.zh)}</p>`+(j.note?`<p class="tag">${both(j.note,j.note_zh||j.note)}</p>`:"");
}).catch(()=>{});
