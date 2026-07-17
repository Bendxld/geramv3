# ============================================================
# GERAM OS v2 · plantillas_codigo.py
# Plantillas base FUNCIONALES que code_agent.py inyecta en el prompt de
# Gemini antes de pedirle código visual/interactivo. La idea: el error
# más común al pedirle a un LLM "hazme un X en 3D" es que reinventa TODO
# el boilerplate (escena, cámara, luces, renderer, loop de animación)
# desde cero y ahí es donde mete errores tontos (cámara mal posicionada,
# luces faltantes, geometría genérica en vez de la pedida = "blob" en
# vez de la forma real). Dándole una base ya probada y pidiéndole que
# SOLO adapte la parte específica (geometría/dibujo/lógica), el
# resultado es mucho más confiable.
#
# Cada plantilla es HTML/JS (o Python, para automatización) COMPLETO y
# ejecutable tal cual — no son snippets sueltos.
# ============================================================

PLANTILLA_THREEJS = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Escena 3D</title>
<style>
  html, body { margin: 0; padding: 0; overflow: hidden; background: #111; }
  canvas { display: block; }
</style>
</head>
<body>
<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// --- Escena, cámara y renderer: NO reescribir salvo que el jefe pida
// explícitamente cambiar el fondo, el campo de visión o desactivar
// sombras/controles. ---
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);

const camera = new THREE.PerspectiveCamera(
  50, window.innerWidth / window.innerHeight, 0.1, 100
);
camera.position.set(0, 1.5, 6);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);

// --- Luces: base razonable para que cualquier geometría se vea con
// volumen (luz ambiental para que nada quede totalmente negro + luz
// direccional con sombra para dar relieve). Ajustar intensidad/color
// si el jefe lo pide, pero mantener AMBAS luces. ---
const luzAmbiental = new THREE.AmbientLight(0xffffff, 0.5);
scene.add(luzAmbiental);

const luzDireccional = new THREE.DirectionalLight(0xffffff, 1.2);
luzDireccional.position.set(3, 5, 4);
luzDireccional.castShadow = true;
scene.add(luzDireccional);

// --- Controles de mouse (orbit): ya cableados. Si el jefe NO pidió
// interactividad, se puede dejar igual (no estorba) o quitar este
// bloque completo. ---
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

// ============================================================
// TODO: reemplazar este placeholder por la geometría/objeto REAL que
// pidió el jefe. Si pidió una forma compleja (ej. un corazón, una
// estrella, un logo), usa THREE.Shape() + ExtrudeGeometry para tener
// volumen real en vez de una geometría primitiva genérica — NO se vale
// aproximar una forma pedida con una esfera/cubo/cono si la forma real
// es reconocible (ej. un corazón NO es una esfera aplastada).
// ============================================================
const geometria = new THREE.BoxGeometry(1.5, 1.5, 1.5);
const material = new THREE.MeshStandardMaterial({ color: 0x4f8ef7 });
const objeto = new THREE.Mesh(geometria, material);
objeto.castShadow = true;
objeto.receiveShadow = true;
scene.add(objeto);

// --- Resize: NO quitar, evita que la escena se vea deformada si la
// ventana cambia de tamaño. ---
window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

// --- Loop de animación: si el jefe pidió rotación/animación, agrégala
// aquí (ej. objeto.rotation.y += 0.01). controls.update() es
// obligatorio si enableDamping está activo. ---
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();
</script>
</body>
</html>
"""

PLANTILLA_CANVAS_2D = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Gráfico 2D</title>
<style>
  html, body { margin: 0; padding: 0; overflow: hidden; background: #111; }
  canvas { display: block; }
</style>
</head>
<body>
<canvas id="lienzo"></canvas>
<script>
// --- Setup del canvas: NO reescribir. Usa devicePixelRatio para que
// se vea nítido en pantallas de alta densidad, y se reajusta solo si
// la ventana cambia de tamaño. ---
const lienzo = document.getElementById("lienzo");
const ctx = lienzo.getContext("2d");
let ancho, alto, dpr;

function redimensionar() {
  dpr = window.devicePixelRatio || 1;
  ancho = window.innerWidth;
  alto = window.innerHeight;
  lienzo.width = ancho * dpr;
  lienzo.height = alto * dpr;
  lienzo.style.width = ancho + "px";
  lienzo.style.height = alto + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
redimensionar();
window.addEventListener("resize", redimensionar);

// ============================================================
// TODO: reemplazar este placeholder por el dibujo/animación REAL que
// pidió el jefe. `dibujar(tiempoMs)` se llama una vez por frame — usa
// `tiempoMs` para animar (ej. Math.sin(tiempoMs / 1000) para algo que
// oscile), y ctx.clearRect ya limpia el frame anterior antes de cada
// llamada.
// ============================================================
function dibujar(tiempoMs) {
  ctx.clearRect(0, 0, ancho, alto);
  ctx.fillStyle = "#4f8ef7";
  const radio = 60;
  ctx.beginPath();
  ctx.arc(ancho / 2, alto / 2, radio, 0, Math.PI * 2);
  ctx.fill();
}

function loop(tiempoMs) {
  dibujar(tiempoMs);
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
</script>
</body>
</html>
"""

PLANTILLA_AUTOMATIZACION = '''#!/usr/bin/env python3
"""Plantilla base para un script de automatización simple."""

import sys


def main():
    # TODO: reemplazar por la lógica real que pidió el jefe.
    pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
'''
