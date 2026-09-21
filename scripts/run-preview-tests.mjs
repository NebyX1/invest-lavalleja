import { spawn } from 'node:child_process';

const command = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const child = spawn(command, ['playwright', 'test'], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env: { ...process.env, PLAYWRIGHT_PREVIEW: 'true' },
});

child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
