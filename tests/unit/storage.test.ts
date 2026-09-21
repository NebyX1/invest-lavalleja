import { describe, expect, it } from 'vitest';
import { $projectDraft, $savedZones, initializeClientState } from '../../src/stores/state';

describe('estado compartido', () => {
  it('no accede a APIs del navegador al renderizar en servidor', () => {
    expect(() => initializeClientState()).not.toThrow();
    expect($savedZones.get()).toEqual([]);
    expect($projectDraft.get()).toEqual({ activity: '', stage: '', needs: [] });
  });
});
