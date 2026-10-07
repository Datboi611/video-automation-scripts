// ---------- Esfera holográfica ----------
const canvas = document.getElementById("orb");
const ctx = canvas.getContext("2d");
const COLORES = {
  reposo:     [30, 150, 255],
  escuchando: [80, 230, 255],
  pensando:   [120, 110, 255],
  hablando:   [60, 190, 255],
  dormido:    [20, 70, 140],
};
const TEXTOS = { reposo: "EN ESPERA", escuchando: "ESCUCHANDO", pensando: "PROCESANDO", hablando: "RESPONDIENDO", dormido: "EN REPOSO" };

let estado = "reposo", nivel = 0, nivelObj = 0, color = [...COLORES.reposo], giro = 0, velGiro = 0.004;
const N = 900, puntos = [];
for (let i = 0; i < N; i++) {           // esfera de Fibonacci
  const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
  puntos.push([Math.cos(th) * r, y, Math.sin(th) * r, Math.random()]);
}

function ajustar() {
  const d = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * d;
  canvas.height = canvas.clientHeight * d;
}
window.addEventListener("resize", ajustar);
ajustar();

const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

function anillo(cx, cy, r, ancho, alpha, desde, hasta, dash) {
  ctx.beginPath();
  ctx.setLineDash(dash || []);
  ctx.lineWidth = ancho;
  ctx.strokeStyle = rgba(color, alpha);
  ctx.arc(cx, cy, r, desde, hasta);
  ctx.stroke();
  ctx.setLineDash([]);
}

function dibujar(t) {
  const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.28;
  t /= 1000;
  const obj = COLORES[estado] || COLORES.reposo;
  color = color.map((c, i) => c + (obj[i] - c) * 0.06);
  nivel += (nivelObj - nivel) * 0.25;
  const respira = estado === "reposo" || estado === "dormido" ? 0.04 * Math.sin(t * (estado === "dormido" ? 0.8 : 1.6)) : 0;
  const objGiro = { reposo: 0.004, escuchando: 0.008, pensando: 0.03, hablando: 0.012, dormido: 0.0015 }[estado];
  velGiro += (objGiro - velGiro) * 0.05;
  giro += velGiro;
  const k = 1 + respira + nivel * 0.18;

  ctx.clearRect(0, 0, W, H);
  ctx.globalCompositeOperation = "lighter";

  // halo exterior
  let g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.9);
  g.addColorStop(0, rgba(color, 0.22 + nivel * 0.25));
  g.addColorStop(0.5, rgba(color, 0.06 + nivel * 0.08));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // anillos HUD
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(giro * 0.6);
  anillo(0, 0, R * 1.42, 1.2, 0.35, 0, Math.PI * 2, [2, 10]);
  for (let i = 0; i < 3; i++) anillo(0, 0, R * 1.5, 3, 0.55, i * 2.09, i * 2.09 + 1.1);
  ctx.restore();
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(-giro * 1.1);
  for (let i = 0; i < 4; i++) anillo(0, 0, R * 1.3, 1.5, 0.45, i * 1.57 + 0.2, i * 1.57 + 1.2);
  ctx.restore();
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(giro * 0.25);
  for (let i = 0; i < 72; i++) {           // marcas tipo reloj
    const a = (i / 72) * Math.PI * 2, largo = i % 6 === 0 ? 10 : 4;
    ctx.beginPath();
    ctx.strokeStyle = rgba(color, i % 6 === 0 ? 0.6 : 0.25);
    ctx.lineWidth = 1;
    ctx.moveTo(Math.cos(a) * R * 1.62, Math.sin(a) * R * 1.62);
    ctx.lineTo(Math.cos(a) * (R * 1.62 + largo), Math.sin(a) * (R * 1.62 + largo));
    ctx.stroke();
  }
  ctx.restore();
  if (estado === "pensando") {           // arco de carga
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(t * 4);
    anillo(0, 0, R * 1.18, 3, 0.9, 0, 1.3);
    ctx.restore();
  }

  // onda de voz alrededor de la esfera
  for (let capa = 0; capa < 3; capa++) {
    ctx.beginPath();
    for (let i = 0; i <= 160; i++) {
      const a = (i / 160) * Math.PI * 2;
      const onda = Math.sin(a * (6 + capa * 3) + t * (3 + capa)) * Math.sin(a * 3 - t * 2);
      const r = R * 1.08 * k + onda * R * (0.02 + nivel * 0.16);
      const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.strokeStyle = rgba(color, 0.35 - capa * 0.08);
    ctx.lineWidth = 1.4;
    ctx.stroke();
  }

  // esfera de partículas 3D
  const cg = Math.cos(giro), sg = Math.sin(giro), ct = Math.cos(0.4), st = Math.sin(0.4);
  for (const [x0, y0, z0, s] of puntos) {
    const ruido = 1 + nivel * 0.12 * Math.sin(s * 40 + t * 8);
    let x = x0 * cg - z0 * sg, z = x0 * sg + z0 * cg;
    let y = y0 * ct - z * st; z = y0 * st + z * ct;
    const p = 2.6 / (2.6 + z), rr = R * k * ruido;
    const px = cx + x * rr * p, py = cy + y * rr * p, prof = (1 - z) / 2;
    ctx.fillStyle = rgba(color, 0.15 + prof * 0.75);
    ctx.fillRect(px, py, 1 + prof * 1.8, 1 + prof * 1.8);
  }

  // núcleo
  g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * (0.55 + nivel * 0.25));
  g.addColorStop(0, `rgba(235,250,255,${0.85 + nivel * 0.15})`);
  g.addColorStop(0.25, rgba(color, 0.7));
  g.addColorStop(1, rgba(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(cx, cy, R * 0.9, 0, Math.PI * 2); ctx.fill();

  ctx.globalCompositeOperation = "source-over";
  requestAnimationFrame(dibujar);
}
requestAnimationFrame(dibujar);

// ---------- API para Python ----------
const $ = (id) => document.getElementById(id);
const log = $("log");
window.J = {
  setState(s) {
    estado = s;
    const a = document.getElementById("audio");
    if (a) a.volume = s === "hablando" ? volMusica * 0.2 : volMusica;  // baja la música mientras habla
    $("estado").textContent = TEXTOS[s] || s.toUpperCase();
    if (s !== "hablando" && s !== "escuchando") nivelObj = 0;
  },
  setLevel(v) { nivelObj = Math.max(0, Math.min(1, v)); },
  setStatus(txt) { $("estado").textContent = txt.toUpperCase(); },
  setHint(txt) { $("hint").textContent = txt; },
  mostrarChat() {},
  pedirTexto(motivo) {  // la caja de texto solo aparece cuando JARVIS necesita que escribas algo
    $("entrada").placeholder = motivo || "Escribe aquí…";
    $("chat").hidden = false;
    $("entrada").focus();
  },
  proceso(id, texto, paso) {
    const ul = $("procesos");
    ul.querySelector(".vacio")?.remove();
    let li = document.getElementById("pr-" + id);
    if (!li) {
      li = document.createElement("li");
      li.id = "pr-" + id;
      li.innerHTML = '<span class="dot"></span><span><span class="t"></span><small></small></span>';
      ul.prepend(li);
      while (ul.children.length > 6) ul.lastChild.remove();
    }
    li.querySelector(".t").textContent = texto.length > 70 ? texto.slice(0, 68) + "…" : texto;
    li.querySelector("small").textContent = paso === "hecho" ? "completado" : paso === "error" ? "error" : paso;
    li.className = paso === "hecho" ? "hecho" : paso === "error" ? "error" : "";
  },
  panel(titulo, texto) {
    const cont = $("paneles");
    const id = "pn-" + titulo.toLowerCase().replace(/[^a-z0-9]/g, "");
    document.getElementById(id)?.remove();
    const c = document.createElement("section");
    c.className = "card"; c.id = id;
    const h = document.createElement("h4");
    h.textContent = titulo.toUpperCase();
    const x = document.createElement("button"); x.textContent = "✕"; x.onclick = () => c.remove();
    h.append(x);
    const pre = document.createElement("pre");
    // títulos de sección en MAYÚSCULAS seguidos de ":" se resaltan
    texto.split("\n").forEach((l, i) => {
      if (i) pre.append("\n");
      if (/^[A-ZÁÉÍÓÚÑ ]{4,}( \(\d+\))?:/.test(l)) { const b = document.createElement("b"); b.textContent = l; pre.append(b); }
      else pre.append(l);
    });
    c.append(h, pre);
    cont.prepend(c);
    while (cont.children.length > 3) cont.lastChild.remove();
  },
  musica(p) {
    const a = $("audio");
    a.src = p.url; a.volume = volMusica; a.play().catch(() => {});
    $("pista-t").textContent = p.titulo; $("pista-c").textContent = p.canal || "";
    $("player").hidden = false; $("player").classList.remove("pausa"); $("p-play").textContent = "❚❚";
  },
  musicaControl(accion, nivel) {
    const a = $("audio");
    if (/paus|stop|para/.test(accion) && !/detener/.test(accion)) { a.pause(); $("player").classList.add("pausa"); $("p-play").textContent = "▶"; }
    else if (/reanud|play|contin|resum/.test(accion)) { a.play(); $("player").classList.remove("pausa"); $("p-play").textContent = "❚❚"; }
    else if (/deten|quita|apaga/.test(accion)) { a.pause(); a.removeAttribute("src"); $("player").hidden = true; }
    else if (/vol/.test(accion) && nivel != null) { volMusica = Math.max(0, Math.min(1, nivel / 100)); a.volume = volMusica; }
  },
  addMsg(rol, texto) {
    const d = document.createElement("div");
    d.className = "msg " + rol;
    const e = document.createElement("em");
    e.textContent = rol === "usuario" ? "TÚ" : rol === "sistema" ? "SISTEMA" : "JARVIS";
    d.append(e, document.createTextNode(texto));
    log.append(d);
    while (log.children.length > 60) log.firstChild.remove();
    log.scrollTop = log.scrollHeight;
  },
};

const api = () => window.pywebview && window.pywebview.api;
let volMusica = 0.6;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("chat").hidden = true; });
$("p-play").addEventListener("click", () => J.musicaControl($("audio").paused ? "reanudar" : "pausar"));
$("p-stop").addEventListener("click", () => J.musicaControl("detener"));
$("p-next").addEventListener("click", () => api() && api().musica("siguiente"));
$("audio").addEventListener("ended", () => api() && api().musica("siguiente"));

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("entrada").value.trim();
  if (!t) return;
  $("entrada").value = "";
  $("chat").hidden = true;
  api() ? api().enviar(t) : J.addMsg("usuario", t);
});
canvas.addEventListener("click", () => api() && api().activar());
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && api()) api().detener(); });

// ---------- Reloj y estado del sistema ----------
const DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
function reloj() {
  const d = new Date();
  $("hora").textContent = d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  $("fecha").textContent = `${DIAS[d.getDay()]} ${d.toLocaleDateString("es")}`;
}
setInterval(reloj, 1000); reloj();

function barra(id, v) { $(id).style.width = v + "%"; $(id + "-v").textContent = Math.round(v) + "%"; }
async function stats() {
  if (!api()) return;
  try {
    const s = await api().info();
    barra("cpu", s.cpu); barra("ram", s.ram);
    s.bat == null ? ($("bat-box").style.display = "none") : barra("bat", s.bat);
  } catch (e) {}
}
setInterval(stats, 2500);
window.addEventListener("pywebviewready", stats);

// Modo demo si se abre en un navegador normal (sin Python)
setTimeout(() => {
  if (api()) return;
  J.setHint("Vista previa — ejecuta main.py para activar a JARVIS");
  J.proceso(1, "¿Qué tengo pendiente hoy?", "resumen del dia");
  J.proceso(2, "Pon música lo-fi para estudiar", "hecho");
  J.panel("Tu día", "CALENDARIO:\nhoy 11:00: Física 2210\nhoy 15:10: Examen licencia Utah\n\nTODOIST:\nVENCIDA ayer: Quiz 4\nhoy: Writing: Implicit Bias Test (prioridad alta)\n\nPENDIENTES PERSONALES:\n[Pill&Go] Probar el actor Carlos (alta)");
  $("player").hidden = false; $("pista-t").textContent = "lofi hip hop radio – beats to study"; $("pista-c").textContent = "Lofi Girl";
  const ciclo = ["escuchando", "pensando", "hablando", "dormido"];
  let i = 0;
  setInterval(() => { J.setState(ciclo[++i % 4]); }, 3000);
  setInterval(() => { if (estado === "hablando" || estado === "escuchando") J.setLevel(Math.random()); }, 90);
}, 1500);
