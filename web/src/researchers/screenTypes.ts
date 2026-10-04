// Shape of web/public/screen.json as the researcher page reads it
// Optional fields render honestly when absent.

interface ScreenMeta {
  source?: string;
  open_targets_release?: string;
  retrieved?: string;
  evidence_retrieved?: string;
  rule_version?: string;
  family_label?: string;
  direction_source?: string;
  ordering_rule?: string;
  pubmed_query_form?: string;
  badge?: string;
  approved_total_method?: string;
  chembl_version?: string;
  interstitial?: string;
  interstitial_continue?: string;
  interstitial_back?: string;
  medication_warning?: string;
  hypothesis_label?: string;
  already_studied_caption?: string;
  target_caption?: string;
  direction_filter_note?: string;
  family_direction_note?: string;
  family_coverage_note?: string;
  family_genes?: string[];
  family_effects?: { reduces?: number; increases?: number; unclear?: number };
  removed_counts_note?: string;
  pubmed_query_note?: string;
  sanity_check_note?: string;
  new_candidates_note?: string;
  evidence_read?: string;
  studies_found?: number;
  next_test_labels?: Record<string, string>;
  doubt_kind_labels?: Record<string, string>;
  sources?: string[];
  [k: string]: unknown;
}

interface Funnel {
  approved: number;
  family: number;
  direction_pass: number;
  with_pair_paper?: number;
  with_mechanism_reference_only?: number;
  without_paper?: number;
  on_line_gene?: number;
}

interface ScreenStudy {
  nct: string;
  status?: string | null;
  why_stopped?: string | null;
  why_stopped_withheld?: boolean;
  start_date?: string | null;
  last_update?: string | null;
}

interface Cited {
  text: string;
  pmid?: string | null;
  kind?: string | null; // doubts: a code from meta.doubt_kind_labels
}

interface Critique {
  status: "checked_by_code" | "not_available";
  reason?: string | null;
  why?: Cited[];
  doubts?: Cited[];
  unchecked_reasoning?: string[];
  next_test?: string | null;
  evidence_read?: string | null;
  provenance?: {
    agent?: string;
    model?: string;
    tool_version?: string;
    run_at?: string;
    prompt_sha256?: string;
    evidence_read?: string;
    [k: string]: unknown;
  } | null;
}

export interface ScreenCard {
  drug_id: string;
  name: string;
  action_type?: string;
  effect?: string;
  targets?: string[];
  target_level?: string;
  on_line_gene?: boolean;
  max_stage?: string;
  state: "already_studied" | "paper_found" | "no_paper_found" | string;
  evidence: {
    pmids?: string[];
    pubmed_count?: number;
    opentargets_pmids?: string[];
    studies?: ScreenStudy[];
  };
  critique: Critique;
}

export interface ScreenLine {
  key: string;
  label: string;
  gene: string;
  direction: string;
  gloss?: string;
  status: "screened" | "refused";
  refusal_reason?: string | null;
  direction_evidence?: { level?: string; pmid?: string; variant?: string } | null;
  funnel?: Funnel;
  removed_by_reason?: Record<string, number>;
  sanity_check?: { applicable?: boolean; surfaced: number; already_tried_total: number } | null;
  new_candidates?: number;
  new_candidates_on_line_gene?: number;
  cards: ScreenCard[];
  cards_not_shown?: number;
  cards_not_shown_by_state?: Record<string, number>;
  cards_not_shown_reason?: string | null;
}

export interface Screen {
  meta: ScreenMeta;
  lines: ScreenLine[];
}
