import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {AfterimagePass} from 'three/addons/postprocessing/AfterimagePass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';

const params=new URLSearchParams(location.search);
if(params.has('embed'))document.body.classList.add('embed');
const status=document.querySelector('#status'),play=document.querySelector('#play'),reset=document.querySelector('#reset'),seek=document.querySelector('#seek'),time=document.querySelector('#time');
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const scene=new THREE.Scene();scene.background=new THREE.Color('#05070c');
const camera=new THREE.PerspectiveCamera(32,1,.05,60);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;document.body.prepend(renderer.domElement);
renderer.domElement.setAttribute('aria-label','Animazione 3D del cubo Meshy: 27 moduli, assemblaggio e impulso neon');renderer.domElement.setAttribute('role','img');
const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.65;room.dispose();pmrem.dispose();
scene.add(new THREE.HemisphereLight(0xaeefff,0x090715,.7));
function light(color,power,pos){const l=new THREE.DirectionalLight(color,power);l.position.set(...pos);scene.add(l)}
light(0xc4eeff,3,[2,4,3]);light(0x725bff,2,[-3,1,-2]);light(0x63d5e9,.7,[3,-1,-2]);
const composer=new EffectComposer(renderer);composer.addPass(new RenderPass(scene,camera));
const bloom=new UnrealBloomPass(new THREE.Vector2(1,1),.45,.4,1.05);composer.addPass(bloom);
const trails=new AfterimagePass(.10);composer.addPass(trails);composer.addPass(new OutputPass());

let mixer,model,action,parts=[],running=false,startTime=0,current=0,raf=0;
const energy={value:.7},cyan=new THREE.Color('#2de2b0'),magenta=new THREE.Color('#63d5e9');
const coreMaterial=new THREE.MeshStandardMaterial({color:0x071e28,metalness:.5,roughness:.25,emissive:0x2de2b0,emissiveIntensity:2});
const core=new THREE.Mesh(new THREE.IcosahedronGeometry(.13,2),coreMaterial);
const coreLight=new THREE.PointLight(0x2de2b0,1,3,2);scene.add(coreLight);
const beamMaterial=new THREE.MeshBasicMaterial({color:0x65dfff,transparent:true,opacity:0,blending:THREE.AdditiveBlending,depthWrite:false,side:THREE.DoubleSide});
const rays=new THREE.Group();
for(let i=0;i<6;i++){const mesh=new THREE.Mesh(new THREE.ConeGeometry(.075,1.35,12,1,true),beamMaterial);const axis=new THREE.Vector3(...[[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]][i]);mesh.position.copy(axis).multiplyScalar(.95);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,-1,0),axis);rays.add(mesh)}

function resize(){const w=innerWidth,h=innerHeight;renderer.setSize(w,h);composer.setSize(w,h);camera.aspect=w/h;const d=Math.max(6.7,5.1/camera.aspect);camera.position.set(d*.67,d*.46,d*.82);camera.lookAt(0,.02,0);camera.updateProjectionMatrix();draw()}
function smooth(x){x=THREE.MathUtils.clamp(x,0,1);return x*x*x*(x*(x*6-15)+10)}
function pose(t){
 current=THREE.MathUtils.clamp(t,0,3);
 if(mixer){action.paused=false;mixer.setTime(current);action.paused=true;}
 const pulse=current>=1.8&&current<=2.3?Math.sin(Math.PI*(current-1.8)/.5):0;
 const assembled=smooth((current-1.5)/.3);
 energy.value=.55+assembled*.6+pulse*1.9;
 for(const {edge,index} of parts){const wave=Math.max(0,1-Math.abs((current-1.84)*8-index/26*1.7));edge.material.opacity=.1+assembled*.37+wave*.33;edge.material.color.copy(index%5===0?magenta:cyan).multiplyScalar(1.2+pulse*1.8)}
 coreMaterial.emissiveIntensity=2+pulse*2;coreLight.intensity=(1-assembled)*.8+pulse*1.2;
 bloom.strength=.34+pulse*.24;beamMaterial.opacity=pulse*.045;
 trails.uniforms.damp.value=running&&current>.3&&current<1.8?.12:0;
 time.value=`${current.toFixed(2)} / 3.00 s`;seek.value=current;
}
function draw(){composer.render()}
function frame(now){if(!running)return;pose((now-startTime)/1000);draw();if(current>=3){running=false;play.textContent='Riproduci 3 s';status.textContent='Completata · 3.00 s';return}raf=requestAnimationFrame(frame)}
function stop(){running=false;cancelAnimationFrame(raf);play.textContent='Riproduci 3 s'}
function begin(){stop();pose(0);running=true;startTime=performance.now();play.textContent='Pausa';status.textContent='Assemblaggio · 27 moduli';raf=requestAnimationFrame(frame)}
play.addEventListener('click',()=>{if(running){stop();status.textContent='In pausa';pose(current);draw()}else begin()});
reset.addEventListener('click',()=>{stop();pose(0);draw();status.textContent='Posa iniziale · 27 moduli'});
seek.addEventListener('input',()=>{stop();pose(Number(seek.value));draw();status.textContent=current===3?'Posa finale · 3.00 s':'Anteprima fotogramma'});
reduced.addEventListener('change',()=>{if(reduced.matches){stop();pose(3);draw()}});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&running){stop();pose(current);draw()}});
addEventListener('resize',resize);resize();

try{
 const gltf=await new GLTFLoader().loadAsync('./neon-cube-assembly-3s.glb');model=gltf.scene;scene.add(model);
 // External faces are the original Meshy mesh and UV texture, not replacement cubes.
 model.traverse(o=>{if(o.isMesh&&o.material.map){const mat=o.material.clone();mat.roughness=.62;mat.metalness=.8;mat.onBeforeCompile=shader=>{shader.uniforms.assemblyEnergy=energy;shader.fragmentShader='uniform float assemblyEnergy;\n'+shader.fragmentShader;shader.fragmentShader=shader.fragmentShader.replace('#include <emissivemap_fragment>',`#include <emissivemap_fragment>
 #ifdef USE_MAP
 vec3 neonSample=texture2D(map,vMapUv).rgb;
 float saturation=max(max(neonSample.r,neonSample.g),neonSample.b)-min(min(neonSample.r,neonSample.g),neonSample.b);
 totalEmissiveRadiance+=neonSample*smoothstep(.18,.5,saturation)*assemblyEnergy*2.4;
 #endif`)};o.material=mat}});
 const root=model.getObjectByName('Assembly_presentation')||model.children[0];root.add(core,rays);
 const cells=gltf.parser.json.extras.cellSize;
 const edgeGeometry=new THREE.EdgesGeometry(new THREE.BoxGeometry(cells[0]*.988,cells[1]*.988,cells[2]*.988));
 let index=0;model.traverse(o=>{if(o.userData.grid){const edge=new THREE.LineSegments(edgeGeometry,new THREE.LineBasicMaterial({color:cyan,transparent:true,opacity:.1,blending:THREE.AdditiveBlending,depthWrite:false}));o.add(edge);parts.push({edge,index:index++});if(o.userData.grid.every(v=>v===1)){o.traverse(child=>{if(child.isMesh){child.material=coreMaterial}})}}});
 mixer=new THREE.AnimationMixer(model);action=mixer.clipAction(gltf.animations[0]);action.setLoop(THREE.LoopOnce,1);action.clampWhenFinished=true;action.play();
 play.disabled=reset.disabled=seek.disabled=false;status.textContent='Pronta · modello originale / 27 moduli';
 // Warm shaders before starting the three-second timeline.
 pose(0);draw();await renderer.compileAsync(scene,camera);
 if(params.has('t')){pose(Number(params.get('t')));draw();status.textContent='Anteprima fotogramma'}
 else if(reduced.matches){pose(3);draw();status.textContent='Movimento ridotto · posa finale'}
 else begin();
}catch(error){status.textContent='Caricamento non riuscito. Verifica connessione e file GLB.';console.error(error)}


