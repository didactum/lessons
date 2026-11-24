// Lesson preview.
//   node scripts/preview.mjs                       -> http://localhost:4173 (pick a lesson, read it aloud)
//   node scripts/preview.mjs --render out.html [files...]   -> one static HTML page (CI attaches it to the PR)
// A rough sketch of each beat's board (lines + drawing) and what the teacher says. The site's chalkboard is the
// real player; this is for reading your lesson before you open a pull request. Every lesson string is escaped.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : e.name.endsWith(".json") ? [path.join(d, e.name)] : []));
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const pts = (a) => (Array.isArray(a) ? a.map((p) => `${num(p[0])},${num(p[1])}`).join(" ") : "");

function opSvg(o) {
  const s = 'stroke="#eef" fill="none" stroke-width="0.6"';
  switch (o.op) {
    case "line": case "brace": case "callout_arrow": return `<line x1="${num(o.from?.[0])}" y1="${num(o.from?.[1])}" x2="${num(o.to?.[0])}" y2="${num(o.to?.[1])}" ${s}/>`;
    case "arrow": return `<line x1="${num(o.from?.[0])}" y1="${num(o.from?.[1])}" x2="${num(o.to?.[0])}" y2="${num(o.to?.[1])}" ${s} marker-end="url(#a)"/>`;
    case "polyline": case "curve": return `<polyline points="${pts(o.pts)}" ${s}/>`;
    case "polygon": return `<polygon points="${pts(o.pts)}" ${s}/>`;
    case "circle": return `<circle cx="${num(o.c?.[0])}" cy="${num(o.c?.[1])}" r="${num(o.r)}" ${s}/>`;
    case "arc": {
      const [cx, cy, r] = [num(o.c?.[0]), num(o.c?.[1]), num(o.r)], rad = (a) => (num(a) * Math.PI) / 180;
      const x0 = cx + r * Math.cos(rad(o.a0)), y0 = cy - r * Math.sin(rad(o.a0)), x1 = cx + r * Math.cos(rad(o.a1)), y1 = cy - r * Math.sin(rad(o.a1));
      return `<path d="M${x0},${y0} A${r},${r} 0 0 0 ${x1},${y1}" ${s}/>`;
    }
    case "label": case "math": {
      const anchor = o.align === "left" ? "start" : o.align === "right" ? "end" : "middle";
      return `<text x="${num(o.at?.[0])}" y="${num(o.at?.[1])}" font-size="${num(o.size) || 4}" fill="#ffd" text-anchor="${anchor}">${esc(o.text ?? o.tex)}</text>`;
    }
    case "numberline": {
      const [x, y, len, lo, hi] = [num(o.at?.[0]), num(o.at?.[1]), num(o.len), num(o.lo), num(o.hi)];
      const at = (v) => x + ((v - lo) / (hi - lo || 1)) * len;
      return `<line x1="${x}" y1="${y}" x2="${x + len}" y2="${y}" ${s}/>` + (o.marks || []).map((m) => `<circle cx="${at(num(m.v))}" cy="${y}" r="0.9" fill="#ffd"/><text x="${at(num(m.v))}" y="${y - 2}" font-size="3.5" fill="#ffd" text-anchor="middle">${esc(m.text ?? m.v)}</text>`).join("");
    }
    case "group": return (o.children || []).map(opSvg).join("");
    default: return "";
  }
}

function beatHtml(b) {
  const board = b.board || {};
  const says = (board.draw || []).filter((o) => o.say).map((o) => o.say);
  return `<div class=beat><div class=board><b>${esc(board.title)}</b>${(board.lines || []).map((l) => `<div class=line>${esc(l)}</div>`).join("")}
<svg viewBox="0 0 100 70"><defs><marker id=a viewBox="0 0 6 6" refX=5 refY=3 markerWidth=4 markerHeight=4 orient=auto><path d="M0,0L6,3L0,6z" fill="#eef"/></marker></defs>${(board.draw || []).map(opSvg).join("")}</svg></div>
<p class=say>${esc(says.length ? says.join(" / ") : b.narration?.text)}</p>${b.checkin ? `<p><b>Ask:</b> ${esc(b.checkin.prompt)} — ${(b.checkin.choices || []).map(esc).join(" · ")}</p>` : ""}</div>`;
}

function lessonHtml(lesson) {
  const chapters = lesson.chapters || lesson.acts || [];
  return `<h1>${esc(lesson.metadata?.topic)}</h1><p class=meta>${esc((lesson.metadata?.authors || []).join(", "))} · ${esc(lesson.metadata?.license)}</p><p><b>Problem:</b> ${esc(lesson.problem?.statement)}</p>` +
    chapters.map((c) => `<h2>${esc(c.title)}${c.role ? ` <small>(${esc(c.role)})</small>` : ""}</h2>` + (c.beats || []).map(beatHtml).join("")).join("");
}

const STYLE = `<style>body{font:16px system-ui;max-width:820px;margin:2rem auto;padding:0 1rem;background:#1d2b25;color:#eef}
.board{background:#15251f;border:1px solid #3a5;border-radius:8px;padding:.5rem}.line{font-family:ui-monospace,monospace;color:#7ac8f8}
svg{width:100%;background:#0f1b17;border-radius:6px}.beat{margin:1rem 0}.say{font-style:italic;color:#b8c4bc}.meta{color:#9ab}</style>`;

const args = process.argv.slice(2);
if (args[0] === "--render") {
  const out = args[1] || "preview.html";
  const files = args.slice(2).length ? args.slice(2) : walk(path.join(root, "lessons"));
  const body = files.map((f) => { try { return lessonHtml(JSON.parse(fs.readFileSync(f, "utf8"))); } catch (e) { return `<p>${esc(f)}: ${esc(e.message)}</p>`; } }).join("<hr>");
  fs.writeFileSync(out, `<!doctype html><meta charset=utf-8><title>Lesson preview</title>${STYLE}${body}`);
  console.log(`wrote ${out}`);
} else {
  const PAGE = `<!doctype html><meta charset=utf-8><title>Lesson preview</title>${STYLE}
<select id=s></select> <button id=speak>Read aloud</button><div id=o></div>
<script>const s=document.getElementById('s'),o=document.getElementById('o');let lesson;
fetch('/api/lessons').then(r=>r.json()).then(l=>{l.forEach(x=>{const e=document.createElement('option');e.textContent=x;s.append(e)});load()});
s.onchange=load;async function load(){o.innerHTML=await (await fetch('/render/'+s.value)).text();lesson=await (await fetch('/'+s.value)).json()}
document.getElementById('speak').onclick=()=>{speechSynthesis.cancel();for(const c of (lesson.chapters||lesson.acts))for(const b of c.beats)speechSynthesis.speak(new SpeechSynthesisUtterance(b.narration.text))};</script>`;
  http.createServer((req, res) => {
    const url = decodeURIComponent(req.url.split("?")[0]);
    if (url === "/") { res.setHeader("content-type", "text/html"); return res.end(PAGE); }
    if (url === "/api/lessons") return res.end(JSON.stringify(walk(path.join(root, "lessons")).map((f) => path.relative(root, f)).sort()));
    const rendered = url.startsWith("/render/");
    const f = path.resolve(root, "." + (rendered ? url.slice(7) : url));
    if (!f.startsWith(path.join(root, "lessons") + path.sep) || !fs.existsSync(f)) { res.statusCode = 404; return res.end("not found"); }
    if (rendered) { res.setHeader("content-type", "text/html"); try { return res.end(lessonHtml(JSON.parse(fs.readFileSync(f, "utf8")))); } catch (e) { return res.end(esc(e.message)); } }
    res.setHeader("content-type", "application/json"); res.end(fs.readFileSync(f));
  }).listen(4173, "127.0.0.1", () => console.log("Preview: http://localhost:4173"));
}
