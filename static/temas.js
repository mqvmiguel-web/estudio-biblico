/* ===========================================================
   TEMAS_V1 — selector de temas con persistencia
   Temas: verde, azul, violeta, ambar, monocromo, sepia, oscuro, contraste
=========================================================== */
const TEMAS = {
  verde:    {nombre:'🌿 Verde Bosque',    icono:'🌿', desc:'Natural y tranquilo',    acento:'#176b49', acento2:'#e2f2ea', fondo:'#eef2f0', panel:'#fff', soft:'#f5f8f6', texto:'#18231d', muted:'#6b7871', line:'#dce4df', textoInv:'#fff', sombra:'rgba(23,107,73,.25)', green:'#176b49', green2:'#e2f2ea'},
  azul:     {nombre:'🌊 Azul Océano',     icono:'🌊', desc:'Profundo y sereno',      acento:'#0d6efd', acento2:'#d6e9ff', fondo:'#f0f5ff', panel:'#fff', soft:'#e8f0fe', texto:'#0a1d3a', muted:'#5a7ab8', line:'#c9dfff', textoInv:'#fff', sombra:'rgba(13,110,253,.25)', green:'#0d6efd', green2:'#d6e9ff'},
  violeta:  {nombre:'🌅 Violeta Crepúsculo',icono:'🌅', desc:'Místico y cálido',       acento:'#7c3aed', acento2:'#f0e7ff', fondo:'#faf5ff', panel:'#fff', soft:'#f3ebff', texto:'#2e1065', muted:'#8b70c8', line:'#e2d5ff', textoInv:'#fff', sombra:'rgba(124,58,237,.25)', green:'#7c3aed', green2:'#f0e7ff'},
  ambar:    {nombre:'🍂 Ámbar Cálido',    icono:'🍂', desc:'Acogedor y nostálgico',   acento:'#d97706', acento2:'#fff8e1', fondo:'#fffef7', panel:'#fffdf5', soft:'#fff8e1', texto:'#451a03', muted:'#b8860b', line:'#ffe08a', textoInv:'#fff', sombra:'rgba(217,119,6,.25)', green:'#d97706', green2:'#fff8e1'},
  monocromo:{nombre:'⚫ Monocromo Elegante',icono:'⚫', desc:'Limpio y técnico',        acento:'#1a1a2e', acento2:'#e8e8ee', fondo:'#f5f5f7', panel:'#fff', soft:'#eef0f2', texto:'#111', muted:'#6b6b6b', line:'#d1d1d1', textoInv:'#fff', sombra:'rgba(0,0,0,.15)', green:'#1a1a2e', green2:'#e8e8ee'},
  sepia:    {nombre:'📜 Sepia Lectura',   icono:'📜', desc:'Como papel envejecido',   acento:'#8b6914', acento2:'#fdf6e3', fondo:'#fdf6e3', panel:'#fefae0', soft:'#f5f0d8', texto:'#3c2f0f', muted:'#a68b4c', line:'#e8dcc8', textoInv:'#3c2f0f', sombra:'rgba(139,105,20,.2)', green:'#8b6914', green2:'#fdf6e3'},
  oscuro:   {nombre:'🌙 Noche Oscura',    icono:'🌙', desc:'Para leer de noche',      acento:'#22c55e', acento2:'#14532d', fondo:'#0f1712', panel:'#1a2416', soft:'#1f2d1b', texto:'#e8f5e9', muted:'#7fb07a', line:'#2d4a26', textoInv:'#0f1712', sombra:'rgba(0,0,0,.4)', green:'#22c55e', green2:'#14532d'},
  contraste:{nombre:'🌈 Alto Contraste',  icono:'🌈', desc:'Accesibilidad total',     acento:'#00ff00', acento2:'#003300', fondo:'#000', panel:'#111', soft:'#222', texto:'#fff', muted:'#0f0', line:'#0f0', textoInv:'#000', sombra:'rgba(0,255,0,.4)', green:'#00ff00', green2:'#003300'},
};

const TEMA_KEY = 'estudioBiblicoTemaActual';
const TEMA_DEFECTO = 'verde';

function getTemaActual(){
  try{
    const t = localStorage.getItem(TEMA_KEY);
    return TEMAS[t] ? t : TEMA_DEFECTO;
  }catch(e){ return TEMA_DEFECTO; }
}

function aplicarTema(temaId){
  const tema = TEMAS[temaId] || TEMAS[TEMA_DEFECTO];
  const root = document.documentElement;
  root.setAttribute('data-tema', temaId);
  // Actualizar variables CSS del tema + mantener compatibilidad con --green/--green2
  root.style.setProperty('--tema-acento', tema.acento);
  root.style.setProperty('--tema-acento2', tema.acento2);
  root.style.setProperty('--tema-fondo', tema.fondo);
  root.style.setProperty('--tema-panel', tema.panel);
  root.style.setProperty('--tema-soft', tema.soft);
  root.style.setProperty('--tema-texto', tema.texto);
  root.style.setProperty('--tema-muted', tema.muted);
  root.style.setProperty('--tema-line', tema.line);
  root.style.setProperty('--tema-texto-inv', tema.textoInv);
  root.style.setProperty('--tema-sombra', tema.sombra);
  // Compatibilidad: actualizar --green y --green2 para que el CSS original funcione
  root.style.setProperty('--green', tema.green || tema.acento);
  root.style.setProperty('--green2', tema.green2 || tema.acento2);
  try{ localStorage.setItem(TEMA_KEY, temaId); }catch(e){}
  const sel = document.getElementById('temaSelector');
  if(sel) sel.value = temaId;
  window.dispatchEvent(new CustomEvent('temaCambiado', {detail:{tema:temaId, datos:tema}}));
  return tema;
}

function initTema(){
  const t = getTemaActual();
  aplicarTema(t);
}

// Crear selector de temas (modal)
function abrirSelectorTema(){
  if(document.getElementById('temaModal')) return;
  const actual = getTemaActual();
  const modal = document.createElement('div');
  modal.id = 'temaModal';
  modal.innerHTML = `
    <div class="tema-modal-overlay" onclick="cerrarTemaModal(event)">
      <div class="tema-modal" onclick="event.stopPropagation()">
        <button class="tema-cerrar" onclick="cerrarTemaModal()" aria-label="Cerrar">✕</button>
        <h2>🎨 Elige tu tema</h2>
        <p class="tema-sub">Tu preferencia se guarda y sincroniza entre dispositivos</p>
        <div class="tema-grid" id="temaGrid"></div>
        <p class="tema-nota">Los cambios se aplican al instante. Tu tema actual se marca con ✓</p>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const grid = modal.querySelector('#temaGrid');
  Object.entries(TEMAS).forEach(([id, tema])=>{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `tema-opcion ${id===getTemaActual()?'activa':''}`;
    btn.dataset.tema = id;
    btn.innerHTML = `<span class="tema-icono">${tema.icono}</span><div><strong>${tema.nombre}</strong><br><small>${tema.desc}</small></div>`;
    btn.onclick = () => { aplicarTema(id); renderGrid(); };
    grid.appendChild(btn);
  });
  // animación entrada: la clase "abierto" va en el overlay
  const overlay = modal.querySelector('.tema-modal-overlay');
  requestAnimationFrame(()=> overlay.classList.add('abierto'));
}

function renderGrid(){
  const actual = getTemaActual();
  document.querySelectorAll('#temaGrid .tema-opcion').forEach(b=>{
    b.classList.toggle('activa', b.dataset.tema === actual);
  });
}

function cerrarTemaModal(e){
  const modal = document.getElementById('temaModal');
  if(e && e.target !== e.currentTarget) return;
  if(!modal) return;
  const overlay = modal.querySelector('.tema-modal-overlay');
  overlay.classList.remove('abierto');
  setTimeout(()=> modal.remove(), 200);
}

// Botón flotante para abrir selector (se inyecta en ajustes o se usa standalone)
function crearBotonTema(){
  const btn = document.createElement('button');
  btn.id = 'btnTemaFlotante';
  btn.type = 'button';
  btn.className = 'tema-boton-flotante';
  btn.title = 'Cambiar tema';
  btn.innerHTML = '🎨';
  btn.onclick = abrirSelectorTema;
  return btn;
}

// Inicialización automática
if(typeof window !== 'undefined'){
  initTema();
  // Exponer globalmente
  window.Temas = {TEMAS, aplicarTema, getTemaActual, abrirSelectorTema, cerrarTemaModal, crearBotonTema};
}

// Estilos del modal (inyectados dinámicamente)
const estilosModal = `
.tema-modal-overlay{
  position:fixed;inset:0;background:#000a;z-index:1000;
  display:grid;place-items:center;padding:16px;
  opacity:0;transform:scale(.95);transition:opacity .2s,transform .2s;
}
.tema-modal-overlay.abierto{opacity:1;transform:scale(1)}
.tema-modal{
  background:var(--panel);border-radius:16px;padding:20px;
  width:100%;max-width:420px;box-shadow:0 20px 60px #0004;
  position:relative;
}
.tema-cerrar{
  position:absolute;top:8px;right:10px;border:0;background:transparent;
  font-size:22px;color:var(--muted);cursor:pointer;padding:4px;line-height:1;
}
.tema-cerrar:hover{color:var(--text)}
.tema-modal h2{margin:0 0 4px;font-size:20px}
.tema-sub{margin:0 0 16px;color:var(--muted);font-size:13px}
.tema-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;max-height:50vh;overflow:auto}
.tema-opcion{
  border:2px solid var(--line);background:var(--panel);border-radius:12px;
  padding:14px 12px;cursor:pointer;text-align:left;transition:.15s;
}
.tema-opcion:hover{border-color:var(--green);background:var(--green2)}
.tema-opcion.activa{
  border-color:var(--green);background:var(--green2);box-shadow:0 0 0 2px var(--green2)
}
.tema-icono{font-size:20px;display:block;margin-bottom:6px}
.tema-opcion strong{display:block;font-size:14px}
.tema-opcion small{color:var(--muted);font-size:12px}
.tema-nota{margin:12px 0 0;font-size:12px;color:var(--muted);text-align:center}
@media(max-width:520px){
  .tema-grid{grid-template-columns:1fr}
}
`;

// Inyectar estilos al cargar
if(typeof document !== 'undefined'){
  const style = document.createElement('style');
  style.textContent = estilosModal;
  document.head.appendChild(style);
}