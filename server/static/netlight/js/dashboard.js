async function jget(url) {
  const r = await fetch(url);
  return await r.json();
}

async function main() {
  const info = await jget("/light/api/pxld/info/?name=show.pxld");
  const slaves = await jget("/light/api/pxld/slaves/?name=show.pxld");

  const infoEl = document.getElementById("pxldInfo");
  if (!info.ok) {
    infoEl.textContent = `PXLD info error: ${info.err}`;
    return;
  }

  const i = info.info;
  infoEl.innerHTML = `
    <div><b>magic</b>: <code>${i.magic}</code>  <b>ver</b>: <code>${i.version}</code>  <b>fps</b>: <code>${i.fps}</code></div>
    <div><b>frames</b>: <code>${i.total_frames}</code>  <b>slaves</b>: <code>${i.total_slaves}</code>  <b>pixels</b>: <code>${i.total_pixels}</code></div>
    <div><b>udp</b>: <code>${i.udp_port}</code>  <b>crc32</b>: <code>${i.crc32_ok ? "PASS" : "FAIL/NA"}</code></div>
  `;

  const tb = document.querySelector("#slaveTable tbody");
  tb.innerHTML = "";
  if (!slaves.ok) return;
  for (const s of slaves.slaves) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td style="padding:10px;border:1px solid #e5e7eb;"><code>${s.slave_id}</code></td>
      <td style="padding:10px;border:1px solid #e5e7eb;">${s.pixel_count}</td>
      <td style="padding:10px;border:1px solid #e5e7eb;">${s.data_length}</td>
      <td style="padding:10px;border:1px solid #e5e7eb;">${s.valid_bounds ? "OK" : "BAD"}</td>
    `;
    tb.appendChild(tr);
  }
}

main().catch(console.error);