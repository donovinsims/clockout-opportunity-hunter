export function classifyPage(url, snippet='') {
  let parsed;try{parsed=new URL(url);}catch{return 'structure-unknown';}
  const state=typeof snippet==='string'?{text:snippet}:snippet;
  if(/\/sorry(?:\/|$)/i.test(parsed.pathname))return 'blocked';
  if(state.recaptchaIframe||/recaptcha|captcha challenge/i.test(state.text??''))return 'captcha';
  if(/unusual traffic|ungewöhnlichen Datenverkehr/i.test(state.text??''))return 'blocked';
  if(parsed.hostname==='accounts.google.com')return 'sign-in-wall';
  if(parsed.hostname==='consent.google.com'||state.consentForm)return 'consent-wall';
  return 'ok';
}
