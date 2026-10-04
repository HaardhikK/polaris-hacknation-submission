// The researcher entry's own ID-built links (the Open Targets host). Never
// imported by the family bundle.
export const RESEARCHER_HOSTS: ReadonlySet<string> = new Set(["platform.opentargets.org"]);

export const openTargetsDrugUrl = (chemblId: string) =>
  /^CHEMBL\d{1,9}$/.test(chemblId) ? `https://platform.opentargets.org/drug/${chemblId}` : null;
