import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
const scene=new THREE.Scene();scene.background=new THREE.Color('#070c0b');
const camera=new THREE.PerspectiveCamera(32,1,.05,50);
const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.1;document.body.prepend(renderer.domElement);
renderer.domElement.setAttribute('role','img');renderer.domElement.setAttribute('aria-label','Tre cubi originali Meshy su podi metallici con luce verde menta, ciano e lilla');
const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),env=pmrem.fromScene(room,.05);scene.environment=env.texture;scene.environmentIntensity=.7;pmrem.dispose();room.dispose();
scene.add(new THREE.HemisphereLight(0xc9fff0,0x0c1814,1));
const key=new THREE.DirectionalLight(0xd8fff1,3);key.position.set(2,4,5);scene.add(key);
const fill=new THREE.DirectionalLight(0x92b8ff,1);fill.position.set(-3,2,0);scene.add(fill);
const composer=new EffectComposer(renderer);composer.addPass(new RenderPass(scene,camera));composer.addPass(new UnrealBloomPass(new THREE.Vector2(1,1),.36,.4,1.1));composer.addPass(new OutputPass());
const colors=['#63d5e9','#2de2b0','#b9a2f5'];const groups=[],models=[],rings=[];let raf=0,start=performance.now(),ready=false,intersecting=true;
const reduced=matchMedia('(prefers-reduced-motion: reduce)'),status=document.querySelector('#status'),replay=document.querySelector('#replay');
function resize(){const w=innerWidth,h=innerHeight;renderer.setSize(w,h);composer.setSize(w,h);camera.aspect=w/h;const d=Math.max(7.4,7.4/camera.aspect);camera.position.set(0,2.9,d);camera.lookAt(0,.25,0);camera.updateProjectionMatrix();render(performance.now(),false)}
function ease(t){t=THREE.MathUtils.clamp(t,0,1);return 1-Math.pow(1-t,3)}
function render(now,schedule=true){if(!ready){composer.render();return}const elapsed=(now-start)/1000;groups.forEach((group,i)=>{const p=reduced.matches?1:ease((elapsed-[.18,0,.32][i])/.9);group.position.y=-.28*(1-p);group.scale.setScalar(Math.max(.001,p));const model=models[i];model.rotation.y=.57+(reduced.matches?0:Math.sin(elapsed*.55+i)*.035);model.position.y=[.29,.49,.19][i]+(reduced.matches?0:Math.sin(elapsed*1.2+i)*.018);rings[i].material.opacity=.35+(reduced.matches?0:.12*Math.sin(elapsed*1.2+i))});composer.render();if(schedule&&!reduced.matches&&!document.hidden&&intersecting)raf=requestAnimationFrame(render)}
function resume(){cancelAnimationFrame(raf);render(performance.now())}
document.addEventListener('visibilitychange',()=>{if(document.hidden)cancelAnimationFrame(raf);else resume()});reduced.addEventListener('change',resume);
new IntersectionObserver(([e])=>{intersecting=e.isIntersecting;if(intersecting)resume();else cancelAnimationFrame(raf)}).observe(renderer.domElement);
replay.addEventListener('click',()=>{start=performance.now();resume()});addEventListener('resize',resize);resize();
try{
const gltf=await new GLTFLoader().loadAsync('./neon-cube-assembly-3s.glb');
// Put the shared original geometry at the assembled pose before cloning.
const mixer=new THREE.AnimationMixer(gltf.scene);const action=mixer.clipAction(gltf.animations[0]);action.play();mixer.setTime(2.2);
for(let i=0;i<3;i++){
const group=new THREE.Group();group.position.x=(i-1)*1.52;scene.add(group);groups.push(group);
const model=gltf.scene.clone(true);model.scale.setScalar(i===1?.86:.71);model.rotation.y=.57;group.add(model);models.push(model);
model.traverse(o=>{if(!o.isMesh)return;const mat=o.material.clone();if(mat.map){mat.roughness=.6;mat.onBeforeCompile=shader=>{shader.uniforms.brandColor={value:new THREE.Color(colors[i])};shader.fragmentShader='uniform vec3 brandColor;\n'+shader.fragmentShader;shader.fragmentShader=shader.fragmentShader.replace('#include <emissivemap_fragment>',`#include <emissivemap_fragment>
#ifdef USE_MAP
vec3 tex=texture2D(map,vMapUv).rgb;float sat=max(max(tex.r,tex.g),tex.b)-min(min(tex.r,tex.g),tex.b);float neon=smoothstep(.18,.5,sat);totalEmissiveRadiance+=brandColor*neon*1.9;
#endif`)};mat.customProgramCacheKey=()=>`engn-${i}`}o.material=mat});
const height=[.20,.35,.15][i];const plinth=new THREE.Mesh(new THREE.CylinderGeometry(.68,.73,height,4,1),new THREE.MeshStandardMaterial({color:0x14231e,metalness:.8,roughness:.35}));plinth.rotation.y=Math.PI/4;plinth.position.y=-.39-height/2;group.add(plinth);
const wire=new THREE.LineSegments(new THREE.EdgesGeometry(plinth.geometry),new THREE.LineBasicMaterial({color:colors[i],transparent:true,opacity:.4}));wire.rotation.copy(plinth.rotation);wire.position.copy(plinth.position);group.add(wire);rings.push(wire);
const disc=new THREE.Mesh(new THREE.RingGeometry(.57,.575,80),new THREE.MeshBasicMaterial({color:colors[i],transparent:true,opacity:.18,side:THREE.DoubleSide}));disc.rotation.x=-Math.PI/2;disc.position.y=-.64;group.add(disc);
}
ready=true;status.textContent='ORIGINAL MESHY MODEL · PODIUM';replay.disabled=false;await renderer.compileAsync(scene,camera);start=performance.now();resume();
}catch(error){status.textContent='Modello non caricato · controlla connessione e file';console.error(error)}
