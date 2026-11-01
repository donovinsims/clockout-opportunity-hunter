#!/usr/bin/env node
import { buildProgram } from './program.js';
import { redact } from '../core/redact.js';
buildProgram().parseAsync(process.argv).catch(error => {
  if (error.code === 'commander.helpDisplayed' || error.code === 'commander.version') return;
  console.error(`Error: ${redact(error.message)}`);
  process.exitCode = error.exitCode === 64 || error.code?.startsWith('commander.') ? 64 : (error.exitCode ?? 1);
});
