import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);

// ---------- three.js scene ----------
const holder = $('canvas-holder');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
holder.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14161a);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.position.set(120, -160, 110);
camera.up.set(0, 0, 1); // Z-up, like the printer

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(150, -220, 260);
scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.5);
fill.position.set(-180, 160, 80);
scene.add(fill);

const grid = new THREE.GridHelper(256, 16, 0x333944, 0x232830);
grid.rotation.x = Math.PI / 2; // into XY plane (Z-up)
scene.add(grid);

function resize() {
  const w = holder.clientWidth, h = holder.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });

// ---------- state ----------
let model = null;            // { parts: [...], length, width, height }
let meshes = [];             // THREE.Mesh per part
let edgeLines = [];          // THREE.LineSegments per part
let baseOffsets = [];        // explode directions
let selectedPart = -1;
const group = new THREE.Group();
scene.add(group);

const raycaster = new THREE.Raycaster();

function clearModel() {
  group.clear();
  meshes = []; edgeLines = []; baseOffsets = []; selectedPart = -1;
}

function faceDirection(normal) {
  const ax = Math.abs(normal.x), ay = Math.abs(normal.y), az = Math.abs(normal.z);
  if (az >= ax && az >= ay) return normal.z > 0 ? 'top (up)' : 'bottom (plate)';
  if (ay >= ax) return normal.y > 0 ? 'left side' : 'right side';
  return normal.x > 0 ? 'back end' : 'front end';
}

function buildModel(data) {
  clearModel();
  model = data;
  const center = new THREE.Vector3(0, 0, data.height / 2);
  data.parts.forEach((part, i) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(part.vertices, 3));
    geo.setIndex(part.faces);
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(part.color), roughness: 0.55, metalness: 0.05,
      flatShading: true,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.userData.partIndex = i;
    group.add(mesh);
    meshes.push(mesh);

    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo, 20),
      new THREE.LineBasicMaterial({ color: 0x0b0d10, transparent: true, opacity: 0.55 })
    );
    mesh.add(edges);
    edgeLines.push(edges);

    geo.computeBoundingBox();
    const c = geo.boundingBox.getCenter(new THREE.Vector3());
    const dir = c.clone().sub(center);
    if (dir.length() < 1e-6) dir.set(0, 0, 1);
    baseOffsets.push(dir.normalize());
  });
  applyEdgeVisibility();
  applyExplode();

  const size = Math.max(data.length, data.width, data.height);
  controls.target.copy(center);
  camera.position.set(size * 1.2, -size * 1.6, size * 1.1).add(center);
  $('dims').textContent =
    `L ${data.length.toFixed(1)} x W ${data.width.toFixed(1)} x H ${data.height.toFixed(1)} mm`;
}

function applyExplode() {
  const f = parseFloat($('explode').value);
  if (!model) return;
  const scale = f * Math.max(model.length, model.width, model.height) * 0.35;
  meshes.forEach((mesh, i) => mesh.position.copy(baseOffsets[i]).multiplyScalar(scale));
}
$('explode').addEventListener('input', applyExplode);

function applyEdgeVisibility() {
  const on = $('show-edges').checked;
  edgeLines.forEach((l) => (l.visible = on));
}
$('show-edges').addEventListener('change', applyEdgeVisibility);

function selectPart(i) {
  selectedPart = i;
  meshes.forEach((m, j) => m.material.emissive.setHex(j === i ? 0x2a4d75 : 0x000000));
  document.querySelectorAll('#parts .part').forEach((el, j) =>
    el.classList.toggle('selected', j === i));
}

// ---------- picking ----------
renderer.domElement.addEventListener('pointerdown', (e) => {
  renderer.domElement.dataset.moved = '0';
});
renderer.domElement.addEventListener('pointermove', () => {
  renderer.domElement.dataset.moved = '1';
});
renderer.domElement.addEventListener('click', (e) => {
  if (renderer.domElement.dataset.moved === '1') return; // it was a drag
  if (!model) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(
    ((e.clientX - rect.left) / rect.width) * 2 - 1,
    -((e.clientY - rect.top) / rect.height) * 2 + 1
  );
  raycaster.setFromCamera(ndc, camera);

  // edges first, with a tight threshold so faces stay easy to hit
  const sizeRef = Math.max(model.length, model.width, model.height);
  raycaster.params.Line = { threshold: sizeRef * 0.004 };
  const visibleEdges = edgeLines.filter((l) => l.visible);
  const edgeHits = raycaster.intersectObjects(visibleEdges, false);
  const meshHits = raycaster.intersectObjects(meshes, false);

  if (edgeHits.length &&
      (!meshHits.length || edgeHits[0].distance < meshHits[0].distance + sizeRef * 0.01)) {
    const hit = edgeHits[0];
    const line = hit.object;
    const pos = line.geometry.getAttribute('position');
    const i = hit.index; // first vertex of the segment
    const a = new THREE.Vector3().fromBufferAttribute(pos, i);
    const b = new THREE.Vector3().fromBufferAttribute(pos, i + 1);
    line.parent.localToWorld(a); line.parent.localToWorld(b);
    const len = a.distanceTo(b);
    const part = model.parts[line.parent.userData.partIndex];
    selectPart(line.parent.userData.partIndex);
    $('info').textContent =
      `Edge  ${len.toFixed(2)} mm\n` +
      `from (${a.x.toFixed(1)}, ${a.y.toFixed(1)}, ${a.z.toFixed(1)})\n` +
      `to   (${b.x.toFixed(1)}, ${b.y.toFixed(1)}, ${b.z.toFixed(1)})\n` +
      `part: ${part.name} (filament ${part.extruder})`;
    return;
  }
  if (meshHits.length) {
    const hit = meshHits[0];
    const idx = hit.object.userData.partIndex;
    const part = model.parts[idx];
    selectPart(idx);
    const n = hit.face.normal.clone().transformDirection(hit.object.matrixWorld);
    const p = hit.point;
    const box = new THREE.Box3().setFromObject(hit.object);
    const s = box.getSize(new THREE.Vector3());
    $('info').textContent =
      `Face on ${faceDirection(n)}\n` +
      `at (${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)}) mm\n` +
      `part: ${part.name}  filament ${part.extruder}\n` +
      `part volume ${(part.volume / 1000).toFixed(2)} cm3  ` +
      `bbox ${s.x.toFixed(1)} x ${s.y.toFixed(1)} x ${s.z.toFixed(1)} mm\n` +
      `source: ${part.provenance}`;
    return;
  }
  selectPart(-1);
  $('info').textContent = 'Click a face or an edge in the 3D view.';
});

// ---------- API plumbing ----------
async function api(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `${res.status} ${res.statusText}`);
  return body;
}

$('file').addEventListener('change', async () => {
  const file = $('file').files[0];
  if (!file) return;
  const form = new FormData();
  form.append('svg', file);
  try {
    const data = await api('/api/svg', { method: 'POST', body: form });
    const sel = $('layer');
    sel.innerHTML = '';
    data.layers.forEach((l) => {
      const opt = document.createElement('option');
      opt.value = l.name;
      opt.textContent = l.name + (l.visible ? ' (visible)' : '');
      if (l.visible) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.disabled = false;
    $('convert').disabled = false;
    $('warnings').textContent = '';
  } catch (err) {
    $('warnings').textContent = err.message;
  }
});

$('color-mode').addEventListener('change', () => {
  $('shell-row').style.display =
    $('color-mode').value === 'projection' ? 'block' : 'none';
});

$('convert').addEventListener('click', async () => {
  const btn = $('convert');
  btn.disabled = true; btn.textContent = 'Converting…';
  $('warnings').textContent = '';
  try {
    const params = {
      layer: $('layer').value,
      color_mode: $('color-mode').value,
      shell_depth: parseFloat($('shell-depth').value),
    };
    params[$('size-by').value] = parseFloat($('size-mm').value);
    const data = await api('/api/convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    buildModel(data);
    const partsEl = $('parts');
    partsEl.innerHTML = '';
    data.parts.forEach((p, i) => {
      const el = document.createElement('div');
      el.className = 'part';
      el.innerHTML =
        `<span class="swatch" style="background:${p.color}"></span>` +
        `<span>slot ${p.extruder} - ${p.name}</span>` +
        `<span style="margin-left:auto;color:#9aa1ab">${(p.volume / 1000).toFixed(1)} cm3</span>`;
      el.addEventListener('click', () => selectPart(i));
      partsEl.appendChild(el);
    });
    $('warnings').textContent = (data.warnings || []).join('\n');
    $('download').disabled = false;
    document.body.dataset.converted = '1';
  } catch (err) {
    $('warnings').textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = 'Convert';
  }
});

$('download').addEventListener('click', () => {
  window.location.href = '/api/download';
});
