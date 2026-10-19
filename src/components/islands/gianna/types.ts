export type Source = { id: string; title: string; url: string };
export type Citation = {
  id: string;
  title: string;
  record_id?: string;
  excerpt: string;
  cutoff_date: string | null;
  evidence_type?: string;
  locator?: string;
  sources: Source[];
};
export type Reply = {
  id: string;
  answer: string;
  citations: Citation[];
  opportunity_ids?: string[];
  follow_up?: string | null;
  status: string;
  notice: string;
};
export type Exchange = { question: string; reply: Reply };
export type Config = { name: string; greeting: string; notice: string; enabled: boolean; available: boolean; test_mode?: boolean };
