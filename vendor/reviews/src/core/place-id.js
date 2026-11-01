export function extractPlaceId(value) {
  let text=String(value??'');for(let i=0;i<2;i++){try{text=decodeURIComponent(text);}catch{break;}}
  return /!1s(0x[0-9a-f]+:0x[0-9a-f]+)(?=[!/?&#\s]|$)/i.exec(text)?.[1] ?? null;
}
