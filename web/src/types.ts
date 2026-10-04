// Shape of web/public/graph.json as the site reads it. Mirrors pipeline/schema.py and
// transfer.card(); every field the site is not sure of is optional and rendered honestly
// when absent. The adapter in data.ts is the one place that bridges pipeline naming.

export type Direction = "gain" | "loss" | "mixed" | "unknown" | "not_applicable";
export type MechanismFamily = "ion_channel" | "non_channel";
export type TransferStatus = "viable" | "needs_expert_check" | "not_shared" | "already_open";
export type StationKey =
  | "diagnosis"
  | "registry"
  | "natural_history"
  | "mechanism"
  | "model"
  | "outcome_measure"
  | "trial";

export interface Source {
  label: string;
  url: string;
  retrieved?: string | null;
}

export interface HpoTerm {
  id: string;
  label: string;
  pmid: string;
  annotation?: string;
}

export interface DirectionEvidence {
  pmid: string;
  variant?: string | null;
  quote?: string | null;
  claim_id?: string | null;
  evidence_level?: string | null;
  level?: string | null;
}

export interface Line {
  key: string;
  gene: string;
  mechanism: string;
  mechanism_family: MechanismFamily;
  direction: Direction;
  label: string;
  gloss: string;
  mechanism_label?: string | null;
  xrefs?: Record<string, string>;
  sources: Source[];
  hpo_terms?: HpoTerm[];
  organisations?: string[];
  direction_known?: Direction;
  direction_step?: boolean;
  cluster_group?: string;
  coverage?: {
    esearch_term?: string;
    papers_mentioning_gene?: number;
    papers_extracted?: number;
    pmids_searched?: string[];
    retrieved?: string;
  };
  direction_evidence?: DirectionEvidence[] | DirectionEvidence | null;
}

export interface Organisation {
  key: string;
  name: string;
  lines: string[];
  url: string;
  contact_page?: string | null;
  last_verified?: string | null;
}

export interface Study {
  nct: string;
  name: string;
  kind: string;
  stopped?: boolean;
  genes_named?: string[];
  source?: Source;
  last_verified?: string | null;
  // StudyRecord fields on the strip-list
  overall_status?: string;
  start_date?: string | null;
  last_update_date?: string | null;
  why_stopped?: string | null;
  conditions?: string[];
  lead_sponsor?: string | null;
  minimum_age?: string | null;
  maximum_age?: string | null;
  retrieved?: string | null;
  human_check?: string[];
  researcher?: Record<string, unknown>; // never rendered on the family path
}

export interface Asset {
  id: string;
  type: string;
  station: StationKey;
  scope: "gene" | "line";
  label: string;
  owner_gene: string;
  owner_line?: string | null;
  direction?: Direction;
  direction_basis?: string | null;
  open_to_all?: boolean;
  source: Source;
  last_verified?: string | null;
}

export interface Paper {
  pmid: string;
  title?: string | null;
  year?: number | string | null;
  journal?: string | null;
  doi?: string | null;
  retrieved?: string | null;
  genes_mentioned?: string[];
}

export interface Claim {
  pmid: string;
  gene: string;
  claim_level: "variant" | "gene";
  variant?: string | null;
  direction: Direction;
  stance: "supports" | "contradicts" | "unclear";
  basis: string;
  evidence_quote: string;
  claim_id: string;
  extractor_run_id?: string;
  agent?: string;
  model?: string;
  flags?: string[];
}

export interface ConflictSide {
  says: string;
  source: Source;
}

export interface Conflict {
  id: string;
  gene: string;
  variant?: string | null;
  line?: string | null;
  sides: ConflictSide[];
  note?: string | null;
}

export interface Alias {
  term: string;
  kind: string; // disease | gene | variant | organisation | mechanism | id | group | symptom
  line?: string | null;
  gene?: string | null;
  direction_step?: boolean;
  genes?: string[];
  orpha?: string | null;
  group_size?: number | null;
  mechanism?: string | null;
  direction?: Direction | null;
  pmid?: string | null;
  hpo?: string | null;
  hpo_id?: string | null;
  variant_direction?: Direction | null; // "mixed": the lab studies of this variant disagree
  note?: string | null;
}

export interface CoListing {
  line: string;
  gene: string;
  nct: string;
  matched_field: string;
  window?: string;
  tier?: number;
  human_check: boolean;
  caveat?: string;
  kind?: string;
  retrieved?: string | null;
}

export interface Edge {
  subject: string;
  predicate: string;
  object: string;
  source: Source;
  tier?: number;
  knowledge_level?: string;
  agent_type?: string;
  direction_qualifier?: Direction | null;
  note?: string | null;
  retrieved?: string | null;
}

export interface StationState {
  state: "have" | "missing" | "unknown";
  why: string;
}

export interface Transfer {
  target: string;
  asset_id: string;
  asset_type: string;
  station: StationKey;
  owner_gene: string;
  owner_line?: string | null;
  status: TransferStatus;
  crosses_gene: boolean;
  crosses_direction: boolean;
  fills_missing_station: boolean;
  evidence_level: string;
  cited_pmid?: string | null;
  reason: string;
  check_first: string[];
  evidence_claim_ids: string[];
  rank: number;
  card_type?: string;
  blocked?: boolean;
  banner?: string | Banner | null;
  basis_note?: string | null;
  owner_org?: string | null;
  nct?: string | null;
  study_status?: string | null;
  start_date?: string | null;
  last_update_date?: string | null;
  direction_basis?: string | null;
  study_population?: string | null; // the record's own words, shown in quotes
  co_owner_genes?: string[];
  open_to_all?: boolean;
  what_differs: string[];
}

export interface Banner {
  heading: string;
  body: string;
}

export interface Card {
  line: string;
  direction: Direction;
  banner?: string | Banner | null;
  banner_parts?: Banner | null;
  named_in_same_study?: string[];
  top_cards?: (string | { asset_id: string; card_type?: string })[];
  top_cards_typed?: { asset_id: string; card_type?: string }[];
  card_type?: string;
  stations: Record<string, StationState>;
  steps: {
    total: number;
    missing: string[];
    borrowable: string[];
    held?: number;
    unknown?: number;
    mode?: string;
    sentence?: string;
  };
  transfers: Transfer[];
}

export interface TextProvenance {
  model?: string;
  run_at?: string;
  prompt_sha256?: string;
  checker?: string;
  tool_version?: string;
}

export interface CardText {
  card_key?: string;
  text?: string; // the pipeline's name for the explanation
  explanation?: string;
  check_first?: string[];
  proposal?: string | null;
  provenance?: TextProvenance | null;
  provenance_line?: string;
  source?: string; // "codex" | "template"
}

export interface TriedBefore {
  nct: string;
  name?: string;
  overall_status?: string;
  state?: "stopped" | "paused"; // SUSPENDED records are paused, not stopped
  why_stopped?: string | null;
  last_update_date?: string | null;
}

/** One cluster (mechanism × direction) as the pipeline ranks it: meta.cluster_groups keys. */
export interface MechanismCluster {
  key: string;
  label: string;
  lines: string[];
  genes: string[];
  shared_assets: number;
  funding_projects: number;
  organisations: { key: string; name: string; url: string; contact_page?: string | null }[];
  studies: Record<string, ClusterStudy[]>; // active · finished_or_unknown · stopped (incl. paused)
  models: {
    id: string;
    label: string;
    owner_gene: string;
    repository_id?: string | null;
    url: string;
  }[];
  outcome_measures: { id: string; label: string; owner_gene: string; pmid?: string | null }[];
  institutions: { name: string; roles: string[]; lines: string[] }[];
}

export interface ClusterStudy {
  nct: string;
  name: string;
  kind?: string;
  lines: string[];
  overall_status?: string | null;
  state?: "active" | "finished_or_unknown" | "stopped" | "paused";
  why_stopped?: string | null;
  caveat?: string | null;
}

/** An NIH RePORTER project whose title names the gene: title and organisation only. */
export interface Funding {
  gene: string;
  project_num: string;
  title: string;
  organisation?: string | null;
  fiscal_year?: number | null;
  start_date?: string | null;
  end_date?: string | null;
  url?: string | null;
}

export interface ConsistencyCheck {
  title: string;
  question?: string;
  held_out?: { name?: string; nct?: string; genes_named?: string[]; start_date?: string };
  prediction?: { genes?: string[]; lines?: string[] };
  agreement?: { hits?: number; k?: number; matched_genes?: string[]; sentence?: string };
  pool?: {
    size?: number;
    random_baseline?: number;
    channel_lines_considered?: string[];
    other_genes_on_the_map?: string[];
  };
  inputs?: {
    claims_used?: number;
    papers_cutoff?: string;
    papers_used?: string[];
    static_background?: string[];
    studies_before_start?: string[];
    studies_before_start_note?: string;
  };
  co_listings_note?: string;
  caveat?: string;
}

export interface HowItGrows {
  orphanet_entries?: number;
  orphanet_entries_with_a_gene?: number;
  orphanet_direction_labels?: {
    links?: number;
    gain_of_function?: number;
    loss_of_function?: number;
  };
  studies_fetched?: number;
  studies_naming_two_or_more_seeded_genes?: { nct: string; genes: string[] }[];
  lines_covered?: number;
  genes_covered?: number;
  free_resources?: { id: string; label: string; nct?: string | null; url?: string | null }[];
  out_of_scope?: string;
  burden_of_care?: string;
  retrieved?: Record<string, string>;
}

export interface DataSource {
  key: string;
  name: string;
  release?: string;
  licence?: string;
  retrieved?: string;
  url?: string;
}

export interface Meta {
  source?: string;
  built?: string;
  pre_computed?: string;
  model?: string;
  tool_version?: string;
  generator?: string;
  schema_version?: number;
  badge?: string;
  footer?: string;
  medication_warning?: string;
  hpo_annotation_label?: string;
  steps_total?: number;
  esearch_term?: string;
  sources?: DataSource[];
  cluster_groups?: { key: string; label: string; caption?: string; line_keys: string[] }[];
  counts?: Record<string, number>;
  consistency_check?: ConsistencyCheck;
  how_it_grows?: HowItGrows;
}

/** An edge as the pipeline writes it: typed ids plus the PMID / NCT that backs it. */
export interface RawEdge {
  kind: string;
  source_id: string;
  target_id: string;
  pmid?: string | null;
  nct?: string | null;
  claim_id?: string | null;
  asset_id?: string | null;
  source_url?: string | null;
  retrieved?: string | null;
}

export interface Graph {
  meta: Meta;
  lines: Line[];
  organisations: Organisation[];
  studies: Study[];
  assets: Asset[];
  papers: Paper[];
  claims: Claim[];
  conflicts: Conflict[];
  aliases: Alias[];
  co_listings: CoListing[];
  edges: Edge[];
  cards: Record<string, Card>;
  texts: Record<string, Record<string, CardText>>;
  tried_before: Record<string, TriedBefore[]>;
  mechanism_view: MechanismCluster[];
  funding: Funding[];
}
