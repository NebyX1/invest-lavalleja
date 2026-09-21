import { spawn } from 'node:child_process';

const command = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const child = spawn(command, ['astro', 'preview', '--host', '127.0.0.1', '--port', '4321'], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

const deadline = Date.now() + 120_000;
while (Date.now() < deadline) {
  try {
    const response = await fetch('http://127.0.0.1:4321/');
    if (response.ok) break;
  } catch {
    // Preview is still starting.
  }
  await new Promise((resolve) => setTimeout(resolve, 250));
}

if (Date.now() >= deadline) {
  child.kill('SIGTERM');
  throw new Error('Preview server did not start within 120 seconds.');
}

const stop = () => child.kill('SIGTERM');
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
process.on('exit', stop);
await new Promise((resolve) => child.once('exit', resolve));
