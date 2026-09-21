import { spawn, spawnSync } from 'node:child_process';

const args = ['astro', 'dev', '--host', '127.0.0.1', '--port', '4321', '--ignore-lock'];
const npmCommand = process.platform === 'win32' ? 'npx.cmd' : 'npx';
const child = spawn(npmCommand, args, { stdio: 'inherit', shell: process.platform === 'win32' });
let stopping = false;

async function waitForServer() {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    try {
      const response = await fetch('http://127.0.0.1:4321/');
      if (response.status >= 200 && response.status < 500) return;
    } catch { /* Astro is still starting. */ }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Astro no respondió en http://127.0.0.1:4321/');
}

function stop() {
  if (stopping) return;
  stopping = true;
  if (!child.killed) child.kill();
  spawnSync(npmCommand, ['astro', 'dev', 'stop'], { stdio: 'inherit', shell: process.platform === 'win32' });
}

process.on('SIGINT', () => { stop(); process.exit(130); });
process.on('SIGTERM', () => { stop(); process.exit(143); });
process.on('exit', stop);

try {
  await waitForServer();
  child.on('exit', (code) => {
    if (!stopping && code && code !== 0) console.error(`Astro terminó con código ${code}.`);
  });
  await new Promise(() => {});
} catch (error) {
  stop();
  console.error(error);
  process.exitCode = 1;
}
