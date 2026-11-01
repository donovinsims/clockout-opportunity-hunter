// Keep credentials out of persisted metadata, diagnostics, and console output.
export function redact(value,secrets=[]) {
  if(typeof value==='string'){
    let text=value;
    for(const secret of secrets.filter(s=>typeof s==='string'&&s.length))for(const representation of new Set([secret,encodeURIComponent(secret)]))text=text.split(representation).join('[REDACTED]');
    return text
      .replace(/(https?|socks5):\/\/[^\s/@]+(?::[^\s/@]*)?@/gi,'$1://[REDACTED]@')
      .replace(/(["']?(?:authorization|proxy-authorization|cookie|set-cookie)["']?\s*[:=]\s*)["']?[^\r\n<]*/gi,'$1[REDACTED]')
      .replace(/(["']?(?:password|passwd|token|secret|api[_-]?key)["']?\s*[:=]\s*)["']?[^\s"'<>,;]+["']?/gi,'$1[REDACTED]');
  }
  if(Array.isArray(value))return value.map(v=>redact(v,secrets));
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value)
    .filter(([,v])=>typeof v!=='function'&&v!==undefined)
    .map(([k,v])=>[k,/^(password|passwd|username|authorization|cookie|cookies|proxyConfig|proxyPool|token|secret|api[_-]?key)$/i.test(k)?'[REDACTED]':redact(v,secrets)]));
  return value;
}
