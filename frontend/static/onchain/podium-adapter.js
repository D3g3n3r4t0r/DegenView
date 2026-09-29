/** Integration candidate for frontend/static/onchain/podium.js.
 * Preserves renderPodium(container, items, {still}), rank-order .pc-slot,
 * data-open, and the trusted format.tile() logoHtml contract.
 * From design/engn-motion-kit (PR #383), wired in by podium.js.
 */
import "@onchain/motion.js";
function element(tag,className,text){const el=document.createElement(tag);el.className=className;if(text!=null)el.textContent=text;return el}
export function renderPodium(container,items,{still=false}={}){
 if(!document.querySelector('link[data-engn-podium]')){const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('./podium-adapter.css'+new URL(import.meta.url).search,import.meta.url).href;link.dataset.engnPodium='';document.head.append(link)}
 const root=element('div','engn-pod'+(still?' is-still':''));const list=element('ol','pc-list');list.setAttribute('aria-label','Top 3');
 items.slice(0,3).forEach((item,index)=>{const rank=index+1;const slot=element('li',`pc-slot pc-r${rank}`);const button=element('button','pc-place');button.type='button';button.dataset.open=item.id;button.setAttribute('aria-label',`Number ${rank}: ${item.symbol} ${item.value}`);
 const rankLabel=element('span','engn-rank',`0${rank}`);rankLabel.setAttribute('aria-hidden','true');
 const motion=document.createElement('engn-motion');motion.className='engn-model';motion.setAttribute('state',still?'idle':'assemble');motion.setAttribute('decorative','');if(still)motion.setAttribute('paused','');
 const logo=element('span','engn-token-logo');logo.setAttribute('aria-hidden','true');logo.innerHTML=item.logoHtml||'';
 const symbol=element('span','engn-symbol',item.symbol),value=element('span','engn-value',item.value);if(/^[-−]/.test(String(item.value).trim()))value.dataset.sign='down';
 button.append(rankLabel,motion,logo,symbol,value);slot.append(button);list.append(slot)});
 root.append(list);container.replaceChildren(root);
}
