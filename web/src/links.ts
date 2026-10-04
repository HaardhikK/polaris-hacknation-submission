// Every outbound link is built from an ID on an allow-listed host: the same list as
// pipeline/schema.py ALLOWED_HOSTS (seed organisation domains per the Safety set; the
// NORD, scn8a.net and RePORTER hosts). User-typed text
// never reaches a URL. A URL from the data file is used only if it passes the same check.

export const ALLOWED_HOSTS = new Set([
  "pubmed.ncbi.nlm.nih.gov",
  "pmc.ncbi.nlm.nih.gov",
  "clinicaltrials.gov",
  "www.orpha.net",
  "hpo.jax.org",
  "monarchinitiative.org",
  "zenodo.org",
  "doi.org",
  "www.uniprot.org",
  "www.findmice.org",
  "www.mmrrc.org",
  "www.jax.org",
  "www.scn2a.org",
  "curesyngap1.org",
  "bridgesyngap.org",
  "www.ebi.ac.uk",
  "www.citizen.health",
  "globalgenes.org",
  "rarediseases.org",
  "scn8aalliance.org",
  "thecutesyndrome.com",
  "scn8a.net",
  "dravetfoundation.org",
  "dravet.eu",
  "www.stxbp1disorders.org",
  "www.louloufoundation.org",
  "cdkl5.com",
  "reporter.nih.gov",
]);

const ALLOWED_QUERIES: Record<string, RegExp> = { "www.mmrrc.org": /^mmrrc_id=\d+$/ };

/** The URL itself when it is https, on an allow-listed host, ID-shaped; otherwise null. */
export function safeUrl(
  url: string | null | undefined,
  extraHosts?: ReadonlySet<string>,
): string | null {
  if (!url) return null;
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.protocol !== "https:") return null;
  if (!ALLOWED_HOSTS.has(u.hostname) && !extraHosts?.has(u.hostname)) return null;
  if (u.username || u.password || u.port || u.hash) return null;
  const q = u.search.replace(/^\?/, "");
  if (q && !ALLOWED_QUERIES[u.hostname]?.test(q)) return null;
  return u.toString();
}

export const pubmedUrl = (pmid: string) =>
  /^\d{1,9}$/.test(pmid) ? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/` : null;

export const nctUrl = (nct: string) =>
  /^NCT\d{8}$/.test(nct) ? `https://clinicaltrials.gov/study/${nct}` : null;

export const orphaUrl = (id: string) => {
  const m = /^ORPHA:(\d+)$/.exec(id);
  return m ? `https://www.orpha.net/en/disease/detail/${m[1]}` : null;
};

// Static directory pages for the honest-gap state (home pages only, never the query).
export const DIRECTORIES = [
  { name: "NORD Rare Disease Database", url: "https://rarediseases.org" },
  { name: "Orphanet patient organisations", url: "https://www.orpha.net" },
  { name: "Global Genes", url: "https://globalgenes.org" },
];
