import { sleep, throwIfAborted } from './cancel.js';
export async function withRetry(fn, {
  maxAttempts=3,baseDelayMs=2000,maxDelayMs=30000,
  retryableError=()=>true,onRetry=()=>{},signal,wait=sleep,
}={}) {
  if(!Number.isInteger(maxAttempts)||maxAttempts<1)throw new RangeError('maxAttempts must be a positive integer');
  for(let attempt=1;attempt<=maxAttempts;attempt++){
    throwIfAborted(signal);
    try{return await fn(attempt);}
    catch(error){
      throwIfAborted(signal);
      if(attempt===maxAttempts||!retryableError(error))throw error;
      const delay=Math.min(maxDelayMs,baseDelayMs*2**(attempt-1)*(.5+Math.random()*.5));
      await onRetry({attempt,delay,error});await wait(delay,signal);
    }
  }
}
