/* Independent, testable geometry. These functions never access location APIs. */
(function(root) {
 'use strict';
 function validPosition(p) {
  return p && typeof p.latitude==='number' && typeof p.longitude==='number' &&
    Number.isFinite(p.latitude) && Number.isFinite(p.longitude) &&
    Math.abs(p.latitude)<=90 && Math.abs(p.longitude)<=180;
 }
 function metres(a,b) {
  if(!validPosition(a)||!validPosition(b)) throw new Error('Invalid position');
  const rad=Math.PI/180, dlat=(b.latitude-a.latitude)*rad, dlon=(b.longitude-a.longitude)*rad;
  const h=Math.sin(dlat/2)**2 + Math.cos(a.latitude*rad)*Math.cos(b.latitude*rad)*Math.sin(dlon/2)**2;
  return 6371008.8 * 2 * Math.asin(Math.sqrt(Math.min(1,Math.max(0,h))));
 }
 function rank(stops,p,linkedOnly=false,radius=5000) {
  if(!validPosition(p)) throw new Error('Invalid position');
  const found=[];
  for(const s of stops||[]) {
   if(!s||!Number.isFinite(s.lat)||!Number.isFinite(s.lon)||s.lat<39.78||s.lat>40.13||s.lon<3.76||s.lon>4.35) continue;
   if(linkedOnly && !s.matches?.length) continue;
   const distance=metres(p,{latitude:s.lat,longitude:s.lon});
   if(distance<=radius)found.push({...s,distance});
  }
  return found.sort((a,b)=>a.distance-b.distance||String(a.id).localeCompare(String(b.id)));
 }
 const functions={metres,rank,validPosition};
 if(typeof module==='object'&&module.exports)module.exports=functions;
 if(root)root.NearbyMath=functions;
})(typeof window!=='undefined'?window:null);
