export type ColorTone = 'mint' | 'gold' | 'violet';

export interface Sector {
  id: string;
  name: string;
  short: string;
  tagline: string;
  icon: string;
  color: ColorTone;
  description: string;
  fact: string;
  factLabel: string;
  sources: string[];
  angles: [string, string][];
  customers: string;
  checks: string[];
}

export interface Zone {
  id: string;
  name: string;
  short: string;
  eyebrow: string;
  summary: string;
  sectors: string[];
  sources: string[];
  position: [number, number];
  strengths: string[];
  opportunity: string;
  checks: string[];
}

export interface Fact {
  id: string;
  value: string;
  label: string;
  period: string;
  source: string;
  scope: string;
}

export interface CaseStudy {
  id: string;
  name: string;
  location: string;
  title: string;
  metric: string;
  label: string;
  source: string;
  text: string;
  lesson: string;
  limit: string;
}

export interface ProjectStep {
  id: string;
  title: string;
  text: string;
  result: string;
  source: string;
}

export interface FAQ {
  q: string;
  a: string;
  sources: string[];
}

export interface Source {
  id: string;
  title: string;
  url: string;
  scope: string;
  type: string;
  consulted: string;
}

export interface Catalog {
  edition: string;
  slogan: string;
  sectors: Sector[];
  zones: Zone[];
  facts: Fact[];
  cases: CaseStudy[];
  steps: ProjectStep[];
  faqs: FAQ[];
  sources: Source[];
}

export type EditorialPart =
  | { type: 'html'; content: string }
  | { type: 'explorer' }
  | { type: 'save'; id: string }
  | { type: 'wizard' }
  | { type: 'dossier' }
  | { type: 'inline-search' };

export interface EditorialPage {
  path: string;
  title: string;
  description: string;
  parts: EditorialPart[];
}

export interface SearchEntry {
  id: string;
  title: string;
  type: 'Página' | 'Sector' | 'Zona' | 'Historia' | 'Fuente';
  excerpt: string;
  path: string;
}

export type ProjectDraft = {
  activity: string;
  stage: string;
  needs: string[];
};

export const emptyProjectDraft: ProjectDraft = { activity: '', stage: '', needs: [] };
