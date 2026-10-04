// Protein-variant spellings: p.Arg853Gln / p.R853Q / R853Q / Arg853Gln -> "r853q".
const AA3: Record<string, string> = {
  ala: "A",
  arg: "R",
  asn: "N",
  asp: "D",
  cys: "C",
  gln: "Q",
  glu: "E",
  gly: "G",
  his: "H",
  ile: "I",
  leu: "L",
  lys: "K",
  met: "M",
  phe: "F",
  pro: "P",
  ser: "S",
  thr: "T",
  trp: "W",
  tyr: "Y",
  val: "V",
  ter: "*",
};

/** The lowercase one-letter form of a variant token, or null when it is not one. */
export function canonicalVariant(token: string): string | null {
  const t = token.replace(/^p\./i, "");
  let m = /^([A-Za-z]{3})(\d{1,5})([A-Za-z]{3}|\*)$/.exec(t);
  if (m) {
    const a = AA3[m[1].toLowerCase()];
    const b = m[3] === "*" ? "*" : AA3[m[3].toLowerCase()];
    if (a && b) return `${a}${m[2]}${b}`.toLowerCase();
  }
  m = /^([A-Za-z])(\d{1,5})([A-Za-z*])$/.exec(t);
  if (m) return `${m[1]}${m[2]}${m[3]}`.toLowerCase();
  return null;
}

export const VARIANT_TOKEN =
  /(?:p\.)?(?:[A-Za-z]{3}\d{1,5}(?:[A-Za-z]{3}|\*)|[A-Za-z]\d{1,5}[A-Za-z*])/g;
