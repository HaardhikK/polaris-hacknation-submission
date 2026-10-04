// Funding evidence (brief Module 1 edge): live NIH RePORTER projects whose title names the
// gene. Titles and organisations only, never investigators. Grant titles may name a
// medicine, so this list only ever renders inside a "For researchers" disclosure.
import type { Graph } from "../types";
import { fundingForGene } from "../data";
import { Ext } from "../shared/Layout";

export function FundingList({ graph, gene }: { graph: Graph; gene: string }) {
  const rows = fundingForGene(graph, gene);
  return (
    <div style={{ marginBottom: 8 }}>
      <p style={{ margin: "4px 0" }}>
        <strong>{gene}</strong>: {rows.length} live project{rows.length === 1 ? "" : "s"} whose
        title names the gene
        {rows.length === 0 ? " in the data file." : " (project number, title, organisation)."}{" "}
        Matched by the gene name in the title; the direction (gain or loss) is not checked, so a
        project may study the opposite direction.
      </p>
      {rows.length > 0 && (
        <ul className="list small">
          {rows.map((f) => (
            <li key={f.project_num}>
              <span className="sign">–</span>
              <span>
                <Ext href={f.url}>{f.project_num}</Ext> · {f.title}
                {f.organisation ? ` · ${f.organisation}` : ""}
                {f.fiscal_year ? ` · FY ${f.fiscal_year}` : ""}
                {f.end_date ? ` · ends ${f.end_date}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
