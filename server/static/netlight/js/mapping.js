const board = document.getElementById("board");
const ctx = board.getContext("2d");

const pxldNameEl = document.getElementById("pxldName");
const slaveSelect = document.getElementById("slaveSelect");
const pickedInfo = document.getElementById("pickedInfo");
const pxldIdEl = document.getElementById("pxldId");
const mcuIdEl = document.getElementById("mcuId");
const msgEl = document.getElementById("msg");

let st = {
  cell: 16,
  grid_w: 120,
  grid_h: 60,

  slaves: [],          // from pxld
  layout: {},          // slave_id -> {ox,oy}
  maps: {},            // slave_id -> mapKey -> {pxld_id,mcu_id}
  wh: {},              // slave_id -> {w,h} (A auto, later editable)
  picked: null,
};

function keyXY(x,y){ return `${x},${y}`; }

async function jget(url){ return (await fetch(url)).json(); }
async function jpost(url, obj){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(obj)});
  return await r.json();
}

function autoWH(pixelCount){
  const w = Math.min(40, Math.max(1, pixelCount));
  const h = Math.ceil(pixelCount / w);
  return {w,h};
}

function resizeCanvas(){
  board.width = st.grid_w * st.cell;
  board.height = st.grid_h * st.cell;
}

function draw(){
  resizeCanvas();
  ctx.fillStyle = "#0f1419";
  ctx.fillRect(0,0,board.width,board.height);

  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  for (let x=0;x<=st.grid_w;x++){
    ctx.beginPath(); ctx.moveTo(x*st.cell,0); ctx.lineTo(x*st.cell,board.height); ctx.stroke();
  }
  for (let y=0;y<=st.grid_h;y++){
    ctx.beginPath(); ctx.moveTo(0,y*st.cell); ctx.lineTo(board.width,y*st.cell); ctx.stroke();
  }

  // draw slaves as blit rectangles
  for (const s of st.slaves){
    const sid = s.slave_id;
    const wh = st.wh[sid];
    const lay = st.layout[sid] || {ox:0, oy:0};

    const x = lay.ox * st.cell;
    const y = lay.oy * st.cell;
    const w = wh.w * st.cell;
    const h = wh.h * st.cell;

    ctx.fillStyle = "rgba(99,179,237,0.14)";
    ctx.fillRect(x,y,w,h);
    ctx.strokeStyle = "rgba(99,179,237,0.9)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x,y,w,h);

    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.font = "12px monospace";
    ctx.fillText(`S${sid} ${wh.w}x${wh.h}`, x+4, y+14);

    const m = st.maps[sid] || {};
    for (const k in m){
      const [lx,ly] = k.split(",").map(n=>parseInt(n,10));
      const gx = (lay.ox + lx) * st.cell;
      const gy = (lay.oy + ly) * st.cell;
      ctx.fillStyle = "rgba(16,185,129,0.9)";
      ctx.fillRect(gx+st.cell*0.25, gy+st.cell*0.25, st.cell*0.5, st.cell*0.5);
    }
  }

  if (st.picked){
    ctx.strokeStyle = "rgba(245,158,11,0.95)";
    ctx.lineWidth = 3;
    ctx.strokeRect(st.picked.gx*st.cell, st.picked.gy*st.cell, st.cell, st.cell);
  }
}

function hitTest(gx,gy){
  for (const s of st.slaves){
    const sid = s.slave_id;
    const wh = st.wh[sid];
    const lay = st.layout[sid] || {ox:0, oy:0};
    const inside = (gx>=lay.ox && gy>=lay.oy && gx<lay.ox+wh.w && gy<lay.oy+wh.h);
    if (!inside) continue;
    return {sid, lx: gx-lay.ox, ly: gy-lay.oy};
  }
  return null;
}

board.addEventListener("click", (ev)=>{
  const r = board.getBoundingClientRect();
  const gx = Math.floor((ev.clientX - r.left) / st.cell);
  const gy = Math.floor((ev.clientY - r.top) / st.cell);

  const hit = hitTest(gx,gy);
  if (!hit){
    st.picked = null;
    pickedInfo.textContent = `未命中任何 slave：(${gx},${gy})`;
    draw();
    return;
  }

  st.picked = {gx,gy, ...hit};
  const sid = hit.sid;
  const m = st.maps[sid] || {};
  const cur = m[keyXY(hit.lx, hit.ly)];
  pickedInfo.textContent = `slave=${sid} global=(${gx},${gy}) local=(${hit.lx},${hit.ly})` + (cur ? ` pxld=${cur.pxld_id} mcu=${cur.mcu_id}` : "");

  if (cur){
    pxldIdEl.value = cur.pxld_id;
    mcuIdEl.value = cur.mcu_id;
  }
  slaveSelect.value = String(sid);
  draw();
});

document.getElementById("applyBtn").addEventListener("click", ()=>{
  if (!st.picked) return;
  const sid = st.picked.sid;
  st.maps[sid] = st.maps[sid] || {};
  st.maps[sid][keyXY(st.picked.lx, st.picked.ly)] = {
    pxld_id: parseInt(pxldIdEl.value,10) || 0,
    mcu_id: parseInt(mcuIdEl.value,10) || 0,
  };
  msgEl.textContent = `已套用：S${sid} (${st.picked.lx},${st.picked.ly})`;
  draw();
});

document.getElementById("saveBtn").addEventListener("click", async ()=>{
  const sid = parseInt(slaveSelect.value, 10);
  const wh = st.wh[sid];
  const mapObj = st.maps[sid] || {};
  const arr = [];
  for (const k in mapObj){
    const [x,y] = k.split(",").map(n=>parseInt(n,10));
    arr.push({x,y, pxld_id: mapObj[k].pxld_id, mcu_id: mapObj[k].mcu_id});
  }
  const body = {version:1, slave_id:sid, w:wh.w, h:wh.h, map: arr};
  const res = await jpost("/light/api/mapping/set/", body);
  msgEl.textContent = res.ok ? `保存成功：mapping_slave_${sid}.json` : `保存失敗：${res.err||"unknown"}`;
});

slaveSelect.addEventListener("change", async ()=>{
  const sid = parseInt(slaveSelect.value,10);
  await loadMappingFor(sid);
  draw();
});

async function loadMappingFor(slaveId){
  const res = await jget(`/light/api/mapping/get/?slave_id=${slaveId}`);
  st.maps[slaveId] = {};
  if (res.ok && res.data && res.data.map){
    for (const it of res.data.map){
      st.maps[slaveId][keyXY(it.x,it.y)] = {pxld_id: it.pxld_id, mcu_id: it.mcu_id};
    }
    // 若檔案內帶 w/h，優先使用（B 階段）
    if (res.data.w && res.data.h){
      st.wh[slaveId] = {w: res.data.w|0, h: res.data.h|0};
    }
  }
}

async function bootstrap(){
  msgEl.textContent = "載入 PXLD slaves...";

  const name = pxldNameEl.value;
  const sres = await jget(`/light/api/pxld/slaves/?name=${encodeURIComponent(name)}`);
  if (!sres.ok){
    msgEl.textContent = `PXLD 讀取失敗：${sres.err}`;
    return;
  }
  st.slaves = sres.slaves;

  // auto w/h (A)
  for (const s of st.slaves){
    st.wh[s.slave_id] = autoWH(s.pixel_count);
  }

  // layout：先讀 layout.json，沒有就自動排
  const lres = await jget("/light/api/config/layout/get/");
  st.layout = {};
  if (lres.ok && lres.data && lres.data.layout){
    for (const it of lres.data.layout){
      st.layout[it.slave_id] = {ox: it.ox|0, oy: it.oy|0};
    }
  }

  // auto layout if missing
  let curx = 0, cury = 0, rowh = 0;
  for (const s of st.slaves){
    const sid = s.slave_id;
    if (!st.layout[sid]){
      const wh = st.wh[sid];
      st.layout[sid] = {ox: curx, oy: cury};
      curx += wh.w + 2;
      rowh = Math.max(rowh, wh.h);
      if (curx > st.grid_w - 45){
        curx = 0;
        cury += rowh + 2;
        rowh = 0;
      }
    }
  }

  // slaveSelect
  slaveSelect.innerHTML = "";
  for (const s of st.slaves){
    const opt = document.createElement("option");
    opt.value = String(s.slave_id);
    opt.textContent = `Slave ${s.slave_id} (${s.pixel_count} LED)`;
    slaveSelect.appendChild(opt);
  }

  // load mapping for first slave
  if (st.slaves.length){
    await loadMappingFor(st.slaves[0].slave_id);
    slaveSelect.value = String(st.slaves[0].slave_id);
  }

  msgEl.textContent = "完成";
  draw();
}

bootstrap().catch(console.error);