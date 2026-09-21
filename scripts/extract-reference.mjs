import fs from 'node:fs';
import path from 'node:path';

const projectRoot = process.cwd();
const sourcePath = path.resolve(projectRoot, 'Invest_Lavalleja_Vista_Previa.html');
const html = fs.readFileSync(sourcePath, 'utf8');

function readJsonScript(id) {
  const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp(`<script[^>]*id=["']${escaped}["'][^>]*>([\\s\\S]*?)</script>`, 'i'));
  if (!match) throw new Error(`No se encontró el bloque ${id}`);
  return JSON.parse(match[1]);
}

function writeJson(relativePath, value) {
  const target = path.resolve(projectRoot, relativePath);
  if (!target.startsWith(projectRoot + path.sep)) throw new Error(`Destino inválido: ${relativePath}`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

const catalog = readJsonScript('catalog-data');
const pages = readJsonScript('pages-data');
const assets = readJsonScript('asset-data');

writeJson('src/data/catalog.json', catalog);
writeJson('src/data/pages.json', pages);

const extracted = [];
for (const [publicPath, dataUrl] of Object.entries(assets)) {
  const match = /^data:([^;]+);base64,(.+)$/s.exec(dataUrl);
  if (!match) throw new Error(`Asset no base64: ${publicPath}`);
  const target = path.resolve(projectRoot, `public${publicPath}`);
  if (!target.startsWith(path.resolve(projectRoot, 'public') + path.sep)) {
    throw new Error(`Asset fuera de public/: ${publicPath}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, Buffer.from(match[2], 'base64'));
  extracted.push({ publicPath, mime: match[1], bytes: fs.statSync(target).size });
}

const routeManifest = pages.map(({ path: routePath, title }) => ({ path: routePath, title }));
writeJson('src/data/route-manifest.json', routeManifest);
writeJson('docs/extracted-assets.json', extracted);

const styleMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/i);
if (styleMatch) {
  const styleTarget = path.resolve(projectRoot, 'src/styles/reference.css');
  fs.mkdirSync(path.dirname(styleTarget), { recursive: true });
  fs.writeFileSync(styleTarget, `${styleMatch[1].trim()}\n`, 'utf8');
}

console.log(`Extraídos ${pages.length} páginas, ${Object.keys(assets).length} assets y ${catalog.sectors.length} sectores.`);
for (const asset of extracted) console.log(`${asset.publicPath} (${asset.bytes} bytes)`);
