import { atom } from 'nanostores';
import { z } from 'zod';
import type { ProjectDraft } from '../types';
import { emptyProjectDraft } from '../types';

const DOSSIER_KEY = 'invest-lavalleja:dossier:v1';
const MOVEMENT_KEY = 'invest-lavalleja:movement:v1';
const PROJECT_KEY = 'invest-lavalleja:project:v1';
const VALID_ZONE_IDS = new Set(['minas', 'solis-aguas-blancas', 'villa-serrana-penitente', 'mariscala-piraraja', 'jose-pedro-varela', 'batlle-zapican', 'arequita-polanco-barriga-negra']);
const storedZonesSchema = z.array(z.string().refine((id) => VALID_ZONE_IDS.has(id))).max(3);
const storedProjectSchema = z.object({
  activity: z.string().max(80),
  stage: z.string().max(80),
  needs: z.array(z.string().max(80)).max(6),
});

export const $savedZones = atom<string[]>([]);
export const $movementPaused = atom(false);
export const $projectDraft = atom<ProjectDraft>(emptyProjectDraft);

let initialized = false;
let abortController: AbortController | undefined;

function safeRead<T>(storage: Storage | undefined, key: string, fallback: T, parse: (value: string) => T): T {
  if (!storage) return fallback;
  try {
    const raw = storage.getItem(key);
    return raw === null ? fallback : parse(raw);
  } catch {
    return fallback;
  }
}

function readZones(): string[] {
  return safeRead(typeof window === 'undefined' ? undefined : window.localStorage, DOSSIER_KEY, [], (raw) => {
    const result = storedZonesSchema.safeParse(JSON.parse(raw));
    return result.success ? result.data : [];
  });
}

function readProject(): ProjectDraft {
  return safeRead(typeof window === 'undefined' ? undefined : window.sessionStorage, PROJECT_KEY, emptyProjectDraft, (raw) => {
    const result = storedProjectSchema.safeParse(JSON.parse(raw));
    return result.success ? result.data : emptyProjectDraft;
  });
}

function readMovement(): boolean {
  return safeRead(typeof window === 'undefined' ? undefined : window.localStorage, MOVEMENT_KEY, false, (raw) => raw === 'true');
}

function announceState(): void {
  window.dispatchEvent(new CustomEvent('invest:state-change'));
}

export function initializeClientState(): void {
  if (typeof window === 'undefined' || initialized) return;
  initialized = true;
  $savedZones.set(readZones());
  $projectDraft.set(readProject());
  $movementPaused.set(readMovement());
  abortController = new AbortController();

  window.addEventListener('storage', (event) => {
    if (event.key === DOSSIER_KEY) $savedZones.set(readZones());
    if (event.key === PROJECT_KEY) $projectDraft.set(readProject());
    if (event.key === MOVEMENT_KEY) $movementPaused.set(readMovement());
  }, { signal: abortController.signal });

  window.addEventListener('invest:state-change', () => {
    $savedZones.set(readZones());
    $projectDraft.set(readProject());
    $movementPaused.set(readMovement());
  }, { signal: abortController.signal });
}

export function toggleZone(zoneId: string): boolean {
  if (!VALID_ZONE_IDS.has(zoneId)) return false;
  const current = $savedZones.get();
  if (current.includes(zoneId)) {
    const next = current.filter((id) => id !== zoneId);
    $savedZones.set(next);
    try { window.localStorage.setItem(DOSSIER_KEY, JSON.stringify(next)); } catch { /* storage is optional */ }
    announceState();
    return false;
  }
  if (current.length >= 3) return false;
  const next = [...current, zoneId];
  $savedZones.set(next);
  try { window.localStorage.setItem(DOSSIER_KEY, JSON.stringify(next)); } catch { /* storage is optional */ }
  announceState();
  return true;
}

export function removeZone(zoneId: string): void {
  if (!$savedZones.get().includes(zoneId)) return;
  toggleZone(zoneId);
}

export function clearZones(): void {
  $savedZones.set([]);
  try { window.localStorage.removeItem(DOSSIER_KEY); } catch { /* storage is optional */ }
  announceState();
}

export function updateProjectDraft(patch: Partial<ProjectDraft>): void {
  const next = { ...$projectDraft.get(), ...patch };
  $projectDraft.set(next);
  try { window.sessionStorage.setItem(PROJECT_KEY, JSON.stringify(next)); } catch { /* storage is optional */ }
  announceState();
}

export function resetProjectDraft(): void {
  $projectDraft.set(emptyProjectDraft);
  try { window.sessionStorage.removeItem(PROJECT_KEY); } catch { /* storage is optional */ }
  announceState();
}

export function setMovementPaused(paused: boolean): void {
  $movementPaused.set(paused);
  try { window.localStorage.setItem(MOVEMENT_KEY, String(paused)); } catch { /* storage is optional */ }
  document.documentElement.dataset.motionPaused = paused ? 'true' : 'false';
  announceState();
}

export function disposeClientStateForTests(): void {
  abortController?.abort();
  abortController = undefined;
  initialized = false;
}
