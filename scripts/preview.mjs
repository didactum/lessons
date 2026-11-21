// Tiny local previewer: node scripts/preview.mjs  ->  http://localhost:4173
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(d, e.name)) : e.name.endsWith(".json") ? [path.join(d, e.name)] : []));

const PAGE = `<!doctype html><meta charset=utf-8><title>Lesson preview</title>
<style>body{font:16px system-ui;max-width:760px;margin:2rem auto;padding:0 1rem;background:#1d2b25;color:#eef}
h2{margin-top:2rem}.beat{border-left:3px solid #8fd;padding:.5rem 1rem;margin:1rem 0}.vis{display:inline-block;border:1px dashed #8fd;border-radius:6px;padding:.2rem .5rem;margin:.2rem;font-size:.85rem}
select,button{font:inherit}</style>
<select id=s></select> <button id=speak>Read aloud</button><div id=o></div>
<script>
const o=document.getElementById('o'),s=document.getElementById('s');let lesson;
const esc=t=>String(t).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
fetch('/api/lessons').then(r=>r.json()).then(l=>{s.innerHTML=l.map(x=>'<option>'+esc(x)+'</option>').join('');load()});
s.onchange=load;
async function load(){lesson=await (await fetch('/'+s.value)).json();
 o.innerHTML='<h1>'+esc(lesson.metadata.topic)+'</h1><p>'+esc(lesson.problem.statement)+'</p>'+(lesson.chapters||lesson.acts).map(c=>'<h2>'+esc(c.title)+'</h2>'+c.beats.map(b=>
 '<div class=beat><p>'+esc(b.narration.text)+'</p>'+(b.visuals||[]).map(v=>'<span class=vis>'+esc(v.type)+' · '+esc((v.layout||{}).region||'auto')+'</span>').join('')+(b.checkin?'<p><b>Ask:</b> '+esc(b.checkin.prompt)+'</p>':'')+'</div>').join('')).join('')}
document.getElementById('speak').onclick=()=>{speechSynthesis.cancel();for(const c of (lesson.chapters||lesson.acts))for(const b of c.beats)speechSynthesis.speak(new SpeechSynthesisUtterance(b.narration.text))};
</script>`;

http.createServer((req, res) => {
  const url = decodeURIComponent(req.url.split("?")[0]);
  if (url === "/") { res.setHeader("content-type", "text/html"); return res.end(PAGE); }
  if (url === "/api/lessons") return res.end(JSON.stringify(walk(path.join(root, "lessons")).map((f) => path.relative(root, f)).sort()));
  const f = path.resolve(root, "." + url);
  if (!f.startsWith(path.join(root, "lessons") + path.sep) || !fs.existsSync(f)) { res.statusCode = 404; return res.end("not found"); }
  res.setHeader("content-type", "application/json"); res.end(fs.readFileSync(f));
}).listen(4173, "127.0.0.1", () => console.log("Preview: http://localhost:4173"));
